import unittest
from unittest.mock import patch, MagicMock
import pain_aspects
import llm_classifier

class TestPainAspects(unittest.TestCase):
    """
    Test the Aspect-Based Extraction logic (pain_aspects.py)
    """

    def test_detect_tool_complaint(self):
        """Should detect 'tool_complaint' when app + negative sentiment are present"""
        text = "This app is absolutely terrible and crashes constantly."
        aspects = pain_aspects.detect_aspects(text)
        
        self.assertTrue(any(a['aspect'] == 'tool_complaint' for a in aspects))
        # Ensure sentiment is negative
        complaint = next(a for a in aspects if a['aspect'] == 'tool_complaint')
        self.assertLess(complaint['sentiment'], 0)

    def test_detect_manual_process(self):
        """Should detect 'manual_process' for spreadsheet keywords (no sentiment needed)"""
        text = "I am currently using a spreadsheet to manage all my client data."
        aspects = pain_aspects.detect_aspects(text)
        
        self.assertTrue(any(a['aspect'] == 'manual_process' for a in aspects))

    def test_detect_seeking_alternative(self):
        """Should detect 'seeking_alternative' for explicit questions"""
        text = "Is there an app for tracking beehive health?"
        aspects = pain_aspects.detect_aspects(text)
        
        self.assertTrue(any(a['aspect'] == 'seeking_alternative' for a in aspects))

    def test_ignore_noise(self):
        """Should ignore noise like student/career posts"""
        text = "I need help with my homework assignment for my degree."
        aspects = pain_aspects.detect_aspects(text)
        self.assertEqual(len(aspects), 0)


class TestLLMClassifier(unittest.TestCase):
    """
    Test the LLM Classification logic (llm_classifier.py)
    """

    @patch('ollama.chat')
    def test_classify_strong_opportunity(self, mock_chat):
        """Should return STRONG_OPPORTUNITY when LLM says so"""
        
        # Mock LLM response
        mock_response = {
            'message': {
                'content': '{"classification": "STRONG_OPPORTUNITY", "confidence": 0.9, "reasoning": "Clear need"}'
            }
        }
        mock_chat.return_value = mock_response

        post_data = {'title': 'Need software', 'body': 'I hate Excel'}
        aspects = [{'aspect': 'tool_complaint', 'sentence': 'I hate Excel', 'sentiment': -0.8}]
        
        result = llm_classifier.classify_opportunity(post_data, aspects, "testing")
        
        self.assertTrue(result['is_opportunity'])
        self.assertEqual(result['classification'], 'STRONG_OPPORTUNITY')
        self.assertEqual(result['confidence'], 0.9)

    @patch('ollama.chat')
    def test_classify_rejection(self, mock_chat):
        """Should return NOT_OPPORTUNITY when LLM says so"""
        
        mock_response = {
            'message': {
                'content': '{"classification": "NOT_OPPORTUNITY", "confidence": 0.1, "reasoning": "Just venting"}'
            }
        }
        mock_chat.return_value = mock_response

        post_data = {'title': 'My boss', 'body': 'is mean'}
        aspects = [] # No aspects
        
        result = llm_classifier.classify_opportunity(post_data, aspects, "testing")
        
        self.assertFalse(result['is_opportunity'])
        self.assertEqual(result['classification'], 'NOT_OPPORTUNITY')

    @patch('ollama.chat')
    def test_llm_failure_fallback(self, mock_chat):
        """Should fall back to 'WEAK_OPPORTUNITY' if LLM fails but signals exist"""
        
        # Simulate exception (e.g. Ollama offline)
        mock_chat.side_effect = Exception("Connection refused")

        post_data = {'title': 'Help', 'body': 'Is there an app?'}
        # Strong signal present
        aspects = [{'aspect': 'seeking_alternative', 'sentence': 'Is there an app?', 'sentiment': 0}]
        
        result = llm_classifier.classify_opportunity(post_data, aspects, "testing")
        
        # Should be TRUE because we have 'seeking_alternative' signal
        self.assertTrue(result['is_opportunity'])
        self.assertEqual(result['classification'], 'WEAK_OPPORTUNITY')
        self.assertIn('fallback', result['reasoning'])

if __name__ == '__main__':
    unittest.main()
