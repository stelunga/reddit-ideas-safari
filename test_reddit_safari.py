import unittest
import reddit_safari

class TestRedditSafari(unittest.TestCase):

    def setUp(self):
        self.mock_config = {
            "pain_keywords": {
                "struggle": ["hate", "nightmare"],
                "workaround": ["spreadsheet", "manual"]
            }
        }

    def test_construct_query(self):
        industry = "plumbers"
        query = reddit_safari.construct_query(industry, self.mock_config)
        self.assertIn('site:reddit.com "plumbers"', query)
        self.assertIn('"hate"', query)
        self.assertIn('"spreadsheet"', query)

    def test_analyze_content(self):
        scraped_data = {
            'title': "I hate using spreadsheets",
            'body': "It is a nightmare.",
            'comments': ["Just do it manual"]
        }
        
        result = reddit_safari.analyze_content(scraped_data, self.mock_config)
        
        # Check specific keyword hits
        self.assertIn('struggle', result['analysis'])
        self.assertIn('hate', result['analysis']['struggle'])
        self.assertIn('nightmare', result['analysis']['struggle'])
        
        self.assertIn('workaround', result['analysis'])
        self.assertIn('spreadsheet', result['analysis']['workaround'])
        self.assertIn('manual', result['analysis']['workaround'])
        
        # Calculate expected score: hate(1) + nightmare(1) + spreadsheet(1) + manual(1) = 4
        self.assertEqual(result['score'], 4)

    def test_analyze_content_no_hits(self):
        scraped_data = {
            'title': "I love my job",
            'body': "Everything is great.",
            'comments': ["Good for you"]
        }
        
        result = reddit_safari.analyze_content(scraped_data, self.mock_config)
        
        self.assertEqual(result['score'], 0)
        self.assertEqual(result['analysis'], {})

if __name__ == '__main__':
    unittest.main()
