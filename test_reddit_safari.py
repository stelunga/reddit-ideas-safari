import unittest
import reddit_safari

class TestRedditSafari(unittest.TestCase):
    def test_main_fallback_logic(self):
        # Patch DDGS and scraping to avoid real network calls
        import sys
        import types
        called = {'fallback': False}

        class DummyDDGS:
            def text(self, query, max_results=10):
                # Simulate initial search returns low-score results, fallback returns high-score
                import re
                or_group = re.search(r'\((.*?)\)', query)
                if or_group:
                    keywords = [k.strip() for k in or_group.group(1).split('OR')]
                    if len(keywords) == 2:
                        called['fallback'] = True
                        return iter([{ 'href': f'https://example.com/fallback_{hash(query)}' }])
                # Initial search returns a dummy result (will be filtered out by score)
                return iter([{ 'href': f'https://example.com/initial_{hash(query)}' }])
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass

        def dummy_scrape_thread(url):
            # Simulate a scraped thread with a high score for fallback
            return {
                'url': url,
                'title': 'Pain',
                'body': 'hate spreadsheet manual',
                'comments': [],
                'analysis': {'struggle': ['hate'], 'workaround': ['spreadsheet', 'manual']},
                'score': 3
            }

        # Patch
        original_ddgs = reddit_safari.DDGS
        original_scrape = reddit_safari.scrape_thread
        reddit_safari.DDGS = DummyDDGS
        reddit_safari.scrape_thread = dummy_scrape_thread

        # Patch generate_markdown_report to capture output
        captured = {}
        def dummy_report(industry, findings):
            captured['findings'] = findings
        original_report = reddit_safari.generate_markdown_report
        reddit_safari.generate_markdown_report = dummy_report

        # Patch click.echo to suppress output
        original_echo = reddit_safari.click.echo
        reddit_safari.click.echo = lambda *a, **k: None

        try:
            reddit_safari.main.callback('plumbers', 2)
            self.assertTrue(called['fallback'])
            self.assertIn('findings', captured)
            self.assertGreaterEqual(len(captured['findings']), 1)
            self.assertGreaterEqual(captured['findings'][0]['score'], 3)
        finally:
            reddit_safari.DDGS = original_ddgs
            reddit_safari.scrape_thread = original_scrape
            reddit_safari.generate_markdown_report = original_report
            reddit_safari.click.echo = original_echo
    def test_construct_query_for_category(self):
        industry = "plumbers"
        keywords = ["hate", "nightmare"]
        query = reddit_safari.construct_query_for_category(industry, keywords)
        self.assertIn('site:reddit.com "plumbers"', query)
        self.assertIn('"hate"', query)
        self.assertIn('"nightmare"', query)

    def test_parallel_search_reddit(self):
        # Patch DDGS to avoid real network calls
        class DummyDDGS:
            def text(self, query, max_results=10):
                # Return a fake result with the query in the href for traceability
                return iter([{ 'href': f'https://example.com/{hash(query)}' }])
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass

        original_ddgs = reddit_safari.DDGS
        reddit_safari.DDGS = DummyDDGS
        try:
            results = reddit_safari.search_reddit("plumbers", self.mock_config, limit=2)
            self.assertTrue(isinstance(results, list))
            self.assertGreaterEqual(len(results), 2)  # One per category
            # Ensure deduplication works (simulate duplicate)
            self.mock_config['pain_keywords']['extra'] = ["hate"]
            results2 = reddit_safari.search_reddit("plumbers", self.mock_config, limit=2)
            hrefs = [r['href'] for r in results2]
            self.assertEqual(len(hrefs), len(set(hrefs)))
        finally:
            reddit_safari.DDGS = original_ddgs

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
