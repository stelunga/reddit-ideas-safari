import json
import time
import os
import re
from datetime import datetime
import threading
import click
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

CONFIG_FILE = 'config.json'
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Config file {CONFIG_FILE} not found.")
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def construct_query(industry, config):
    # Collect all keywords from each category
    all_keywords = []
    for cat in config['pain_keywords'].values():
        all_keywords.extend(cat)  # Use all keywords from each category

    # Simple OR group
    keywords_str = " OR ".join([f'"{k}"' for k in all_keywords])
    return f'site:reddit.com "{industry}" ({keywords_str})'

def construct_query_for_category(industry, category_keywords):
    keywords_str = " OR ".join([f'"{k}"' for k in category_keywords])
    return f'site:reddit.com "{industry}" ({keywords_str})'

def search_reddit(industry, config, limit=10):
    # Parallel search: one thread per pain keyword category
    results = []
    threads = []
    results_lock = threading.Lock()

    def search_category(category, keywords):
        query = construct_query_for_category(industry, keywords)
        click.echo(f"Searching [{category}]: {query}")
        try:
            ddgs = DDGS()
            search_gen = ddgs.text(query, max_results=limit)
            with results_lock:
                for r in search_gen:
                    results.append(r)
        except Exception as e:
            click.echo(f"Search failed for {category}: {e}")

    for category, keywords in config['pain_keywords'].items():
        t = threading.Thread(target=search_category, args=(category, keywords))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Deduplicate results by URL (href)
    seen = set()
    deduped = []
    for r in results:
        url = r.get('href')
        if url and url not in seen:
            deduped.append(r)
            seen.add(url)
    return deduped

def scrape_thread(url):
    # Convert to old.reddit.com for easier parsing
    if "www.reddit.com" in url:
        url = url.replace("www.reddit.com", "old.reddit.com")
    elif "reddit.com" in url and "old.reddit.com" not in url:
        url = url.replace("reddit.com", "old.reddit.com")
        
    click.echo(f"Scraping: {url}")
    try:
        resp = requests.get(url, headers={'User-Agent': USER_AGENT})
        if resp.status_code != 200:
            click.echo(f"Failed to fetch {url}: {resp.status_code}")
            return None
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        title = soup.find('a', class_='title')
        title_text = title.text.strip() if title else "No Title"
        
        post_body = soup.find('div', class_='usertext-body')
        body_text = post_body.text.strip() if post_body else ""
        
        comments = []
        comment_area = soup.find('div', class_='commentarea')
        if comment_area:
            entries = comment_area.find_all('div', class_='entry', limit=10) # Top 10 comments
            for entry in entries:
                text_div = entry.find('div', class_='usertext-body')
                if text_div:
                    comments.append(text_div.text.strip())

        return {
            'url': url,
            'title': title_text,
            'body': body_text,
            'comments': comments
        }
    except Exception as e:
        click.echo(f"Scraping error {url}: {e}")
        return None

def analyze_content(scraped_data, config):
    text_content = (scraped_data['title'] + " " + scraped_data['body'] + " ".join(scraped_data['comments'])).lower()
    
    hits = {}
    total_score = 0
    
    for category, keywords in config['pain_keywords'].items():
        cat_hits = []
        for kw in keywords:
            if kw in text_content:
                cat_hits.append(kw)
                total_score += 1
        if cat_hits:
            hits[category] = cat_hits
            
    scraped_data['analysis'] = hits
    scraped_data['score'] = total_score
    return scraped_data

def generate_markdown_report(industry, findings):
    # Ensure reports directory exists
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
    # Use full datetime for uniqueness
    dt_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(reports_dir, f"report_{industry.replace(' ', '_')}_{dt_str}.md")

    with open(filename, 'w') as f:
        f.write(f"# Reddit Pain Safari Report: {industry}\n\n")
        f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Executive Summary\n")
        f.write(f"Found {len(findings)} relevant threads.\n\n")
        
        sorted_findings = sorted(findings, key=lambda x: x['score'], reverse=True)
        
        f.write("## Detailed Findings\n\n")
        
        for item in sorted_findings:
            if item['score'] > 0:
                f.write(f"### {item['title']}\n")
                f.write(f"**Score**: {item['score']} | [Source Link]({item['url']})\n\n")
                
                for cat, kws in item['analysis'].items():
                    f.write(f"- **{cat.capitalize()}**: {', '.join(kws)}\n")
                
                f.write("\n---\n\n")
                
    click.echo(f"Report generated: {filename}")

@click.command()
@click.option('--industry', prompt='Target Industry', help='The industry to scan (e.g., "plumbers", "accountants").')
@click.option('--limit', default=10, help='Number of search results to process.')
def main(industry, limit):
    """Automates the 'Safari' technique for validating business ideas on Reddit."""
    
    # 1. Load Config
    try:
        config = load_config()
    except Exception as e:
        click.echo(f"Error loading config: {e}")
        return

    # 2. Search (initial run with higher limit)
    initial_limit = max(limit, 30)  # Ensure at least 30 per category
    click.echo("Starting search...")
    search_results = search_reddit(industry, config, initial_limit)

    if not search_results:
        click.echo("No results found.")
        return

    # 3. Scrape & Analyze
    click.echo("Processing results...")
    analyzed_findings = []
    for res in search_results:
        url = res.get('href')
        if not url:
            continue
        data = scrape_thread(url)
        if data:
            analyzed = analyze_content(data, config)
            analyzed_findings.append(analyzed)
        time.sleep(1)  # Be polite to Reddit

    # Filter for relevant results (score >= 3)
    relevant = [item for item in analyzed_findings if item['score'] >= 3]

    # Fallback: if not enough relevant results, do one more run with pairwise combos
    min_relevant = 10
    if len(relevant) < min_relevant:
        click.echo(f"Not enough relevant results (found {len(relevant)} with score >= 3). Running fallback pairwise search...")
        from itertools import combinations
        extra_results = []
        threads = []
        results_lock = threading.Lock()

        def search_pair(category, pair):
            query = construct_query_for_category(industry, pair)
            click.echo(f"[Fallback] Searching [{category} pair]: {query}")
            try:
                ddgs = DDGS()
                search_gen = ddgs.text(query, max_results=initial_limit)
                with results_lock:
                    for r in search_gen:
                        extra_results.append(r)
            except Exception as e:
                click.echo(f"Fallback search failed for {category} pair: {e}")

        for category, keywords in config['pain_keywords'].items():
            for pair in combinations(keywords, 2):
                t = threading.Thread(target=search_pair, args=(category, pair))
                threads.append(t)
                t.start()

        for t in threads:
            t.join()

        # Deduplicate extra results
        seen = set(r.get('href') for r in search_results)
        deduped = []
        for r in extra_results:
            url = r.get('href')
            if url and url not in seen:
                deduped.append(r)
                seen.add(url)

        # Scrape & analyze fallback results
        for res in deduped:
            url = res.get('href')
            if not url:
                continue
            data = scrape_thread(url)
            if data:
                analyzed = analyze_content(data, config)
                analyzed_findings.append(analyzed)
            time.sleep(1)

        # Re-filter for relevant results
        relevant = [item for item in analyzed_findings if item['score'] >= 3]

    # 4. Output
    if relevant:
        generate_markdown_report(industry, relevant)
    else:
        click.echo("No valid data extracted.")

if __name__ == '__main__':
    main()
