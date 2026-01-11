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
from sentence_transformers import SentenceTransformer, util
import collections
from itertools import combinations

CONFIG_FILE = 'config.json'
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'

# Global model variable (lazy loaded)
semantic_model = None

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Config file {CONFIG_FILE} not found.")
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_model():
    global semantic_model
    if semantic_model is None:
        click.echo("Loading semantic model (this may take a moment)...")
        # Use a lightweight model
        semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
    return semantic_model

def discover_subreddits(industry):
    """
    Searches for relevant subreddits for the given industry.
    Returns a list of top subreddit names (e.g., ['Truckers', 'FreightBrokers']).
    """
    click.echo(f"Discovering top subreddits for '{industry}'...")
    query = f"best subreddits for {industry} site:reddit.com"
    
    subreddits = []
    try:
        ddgs = DDGS()
        # Search for discussions about subreddits
        results = ddgs.text(query, max_results=20)
        
        subreddit_pattern = re.compile(r'r/([a-zA-Z0-9_]+)')
        
        for res in results:
            # Check title and body snippet
            text = (res.get('title', '') + " " + res.get('body', '')).lower()
            found = subreddit_pattern.findall(text)
            subreddits.extend(found)
            
            # Also check URL if it points to a subreddit
            url = res.get('href', '')
            if 'reddit.com/r/' in url:
                parts = url.split('/r/')
                if len(parts) > 1:
                    sub_name = parts[1].split('/')[0]
                    subreddits.append(sub_name)

    except Exception as e:
        click.echo(f"Subreddit discovery failed: {e}")
        return []

    # Filter out common false positives or generic ones if needed
    blacklist = {'all', 'popular', 'askreddit', 'iama', 'funny', 'pics', 'videos', 'todayilearned', 'reddit'}
    filtered = [s for s in subreddits if s.lower() not in blacklist and len(s) > 2]
    
    # Count frequency
    counts = collections.Counter(filtered)
    top_subs = [s for s, c in counts.most_common(5)]
    
    click.echo(f"Discovered subreddits: {top_subs}")
    return top_subs

def construct_query_for_category(industry, category_keywords, subreddits=None):
    keywords_str = " OR ".join([f'"{k}"' for k in category_keywords])
    
    # We return just the keyword part, the caller handles site restriction
    # But for the query text itself, we include industry + keywords
    return f'"{industry}" ({keywords_str})'

def search_reddit(industry, config, subreddits, limit=10):
    results = []
    threads = []
    results_lock = threading.Lock()
    
    # If we have subreddits, we search specifically within them
    # If not, we fall back to global search
    search_targets = subreddits if subreddits else [None]

    def search_worker(category, keywords, subreddit):
        query_base = construct_query_for_category(industry, keywords, subreddits)
        
        if subreddit:
            query = f'site:reddit.com/r/{subreddit} {query_base}'
        else:
            query = f'site:reddit.com {query_base}'
            
        try:
            ddgs = DDGS()
            # We reduce limit per subreddit to avoid exploding result count
            sub_limit = max(5, int(limit / len(search_targets))) if subreddits else limit
            
            search_gen = ddgs.text(query, max_results=sub_limit)
            with results_lock:
                for r in search_gen:
                    r['source_subreddit'] = subreddit
                    results.append(r)
        except Exception as e:
            pass

    for category, keywords in config['pain_keywords'].items():
        for sub in search_targets:
            t = threading.Thread(target=search_worker, args=(category, keywords, sub))
            threads.append(t)
            t.start()

    for t in threads:
        t.join()

    # Deduplicate results by URL (href)
    seen = set()
    deduped = []
    for r in results:
        url = r.get('href')
        if url and url not in seen and 'reddit.com' in url:
            deduped.append(r)
            seen.add(url)
    return deduped

def search_fallback(industry, config, subreddits, limit=10):
    """
    Fallback search using pairwise combinations of keywords.
    Searches within discovered subreddits if available.
    """
    click.echo("Running fallback pairwise search...")
    results = []
    threads = []
    results_lock = threading.Lock()
    
    search_targets = subreddits if subreddits else [None]

    def search_pair(category, pair, subreddit):
        # Construct query: "industry" ("kw1" AND "kw2")
        # We use AND implicitly by just listing them or explicit OR? 
        # Original logic implies looking for specific combos. Let's use simple space (AND)
        query_text = f'"{industry}" "{pair[0]}" "{pair[1]}"'
        
        if subreddit:
            query = f'site:reddit.com/r/{subreddit} {query_text}'
        else:
            query = f'site:reddit.com {query_text}'

        try:
            ddgs = DDGS()
            search_gen = ddgs.text(query, max_results=limit)
            with results_lock:
                for r in search_gen:
                    r['source_subreddit'] = subreddit
                    results.append(r)
        except Exception as e:
            pass

    for category, keywords in config['pain_keywords'].items():
        # Limit combinations to avoid spamming
        pairs = list(combinations(keywords, 2))
        # Take a subset of pairs if too many
        if len(pairs) > 5:
            pairs = pairs[:5]
            
        for pair in pairs:
            for sub in search_targets:
                t = threading.Thread(target=search_pair, args=(category, pair, sub))
                threads.append(t)
                t.start()
                # Throttle threads slightly
                time.sleep(0.1)

    for t in threads:
        t.join()

    seen = set()
    deduped = []
    for r in results:
        url = r.get('href')
        if url and url not in seen and 'reddit.com' in url:
            deduped.append(r)
            seen.add(url)
    return deduped

def scrape_thread(url):
    # Convert to old.reddit.com for easier parsing
    if "www.reddit.com" in url:
        url = url.replace("www.reddit.com", "old.reddit.com")
    elif "reddit.com" in url and "old.reddit.com" not in url:
        url = url.replace("reddit.com", "old.reddit.com")
    
    # Retry Loop
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={'User-Agent': USER_AGENT})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                title = soup.find('a', class_='title')
                title_text = title.text.strip() if title else "No Title"
                
                # Find the main post content. In old.reddit, it's inside the siteTable div
                site_table = soup.find('div', id='siteTable')
                if site_table:
                    entry = site_table.find('div', class_='entry')
                    if entry:
                        post_body = entry.find('div', class_='usertext-body')
                        body_text = post_body.text.strip() if post_body else ""
                    else:
                        body_text = ""
                else:
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
            elif resp.status_code == 429: # Rate limited
                time.sleep(5 * (attempt + 1)) # Wait 5s, 10s, 15s
                continue
            else:
                return None
        except Exception as e:
            return None
            
    return None

def calculate_semantic_score(post_text, industry):
    model = load_model()
    
    # 1. Positive Anchors (Business Opportunities)
    positive_anchors = {
        "Time Wasted (Automation Opp)": f"I spend hours doing manual work, repetitive data entry, and slow administrative workflows in {industry}.",
        "Money Lost (Compliance/Fin Opp)": f"I lost money, got fined, underpaid, or had financial errors due to mistakes in {industry}.",
        "Bad Tools (Disruption Opp)": f"The specific software, SaaS, applications, and digital tools used in {industry} are broken, slow, expensive, or missing features."
    }

    # 2. Negative Anchors (Noise to Filter Out)
    negative_anchors = {
        "Career_Noise": f"I hate my boss, I want to quit, salary negotiation, interview tips, resume help, career advice, society doesn't respect us, is this career worth it, I am bored, underpaid, and undervalued in {industry}.",
        "Student_Noise": f"How to get certified, exam study tips, which school to pick, beginner questions for {industry}.",
        "Joy_Noise": f"I love my job in {industry}, everything is perfect, great success, high salary, happy."
    }
    
    post_embedding = model.encode(post_text)
    
    # Calculate best positive match
    pos_scores = {}
    for cat, text in positive_anchors.items():
        anchor_embedding = model.encode(text)
        pos_scores[cat] = float(util.cos_sim(post_embedding, anchor_embedding)[0][0])
    
    best_cat = max(pos_scores, key=pos_scores.get)
    best_pos_score = pos_scores[best_cat]

    # Calculate "Noise Level"
    noise_scores = []
    for text in negative_anchors.values():
        anchor_embedding = model.encode(text)
        noise_scores.append(float(util.cos_sim(post_embedding, anchor_embedding)[0][0]))
    
    max_noise = max(noise_scores)

    # 3. The "Signal-to-Noise" Adjustment
    # If the post is more about Career/School/Joy than Business, punish the score.
    final_score = best_pos_score
    if max_noise > 0.40 and max_noise >= best_pos_score:
        final_score = best_pos_score - 0.35  # Severe penalty for ambiguity
    
    return final_score, best_cat

def analyze_content(scraped_data, config, industry):
    # Hard Filter: Quick Reject List
    blacklist = ["salary", "wage", "pay", "bonus", "raise", "interview", "resume", "hiring", "recruiter", 
                 "job offer", "student", "college", "degree", "exam", "certification", "study", 
                 "love", "happy", "fun", "great", "best", "excited"]
    
    title_lower = scraped_data['title'].lower()
    if any(word in title_lower for word in blacklist):
        return None

    # Prepare text for keyword analysis (lower case)
    title_body = (scraped_data['title'] + " " + scraped_data['body']).lower()
    full_text = (title_body + " " + " ".join(scraped_data['comments'])).lower()
    
    # 1. Keyword Analysis
    hits = {}
    keyword_score = 0
    
    for category, keywords in config['pain_keywords'].items():
        cat_hits = []
        for kw in keywords:
            if kw in full_text:
                cat_hits.append(kw)
                keyword_score += 1
        if cat_hits:
            hits[category] = cat_hits
            
    # 2. Semantic Analysis
    # We use Title + Body (limited length) for semantic check to keep it focused
    # Limit body to first 500 chars to avoid noise from long rants about unrelated stuff
    semantic_text = f"{scraped_data['title']}. {scraped_data['body'][:500]}"
    semantic_score, pain_category = calculate_semantic_score(semantic_text, industry)
    
    scraped_data['analysis'] = hits
    scraped_data['keyword_score'] = keyword_score
    scraped_data['semantic_score'] = semantic_score
    scraped_data['pain_category'] = pain_category
    
    return scraped_data

def process_results(results, config, industry, start_time):
    """Helper to scrape, analyze, and print progress for a list of results."""
    analyzed_findings = []
    total = len(results)
    
    for idx, res in enumerate(results, 1):
        url = res.get('href')
        if not url:
            continue
        
        # UI Update
        elapsed = time.time() - start_time
        mins, secs = divmod(int(elapsed), 60)
        click.echo(f"[{idx}/{total}] Elapsed: {mins:02d}:{secs:02d} - {url}")
        
        data = scrape_thread(url)
        if data:
            analyzed = analyze_content(data, config, industry)
            if analyzed: # Might be None due to hard filter
                analyzed_findings.append(analyzed)
        time.sleep(1)  # Be polite
        
    return analyzed_findings

def generate_markdown_report(industry, findings):
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
    dt_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(reports_dir, f"report_{industry.replace(' ', '_')}_{dt_str}.md")

    with open(filename, 'w') as f:
        f.write(f"# Reddit Pain Safari Report: {industry}\n\n")
        f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Executive Summary\n")
        f.write(f"Found {len(findings)} relevant threads.\n")
        f.write("Organized by Commercial Opportunity Type.\n\n")
        
        # Group by Pain Category
        grouped = {}
        for item in findings:
            cat = item.get('pain_category', 'Uncategorized')
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(item)
            
        # Order categories specifically
        cat_order = ["Bad Tools (Disruption Opp)", "Time Wasted (Automation Opp)", "Money Lost (Compliance/Fin Opp)"]
        
        for category in cat_order:
            items = grouped.get(category, [])
            if not items:
                continue
                
            f.write(f"## 🚨 {category}\n\n")
            # Sort by score
            sorted_items = sorted(items, key=lambda x: x['semantic_score'], reverse=True)
            
            for item in sorted_items:
                f.write(f"### {item['title']}\n")
                f.write(f"**Relevance**: {item['semantic_score']:.2f} | **Pain Points**: {item['keyword_score']} | [Source]({item['url']})\n\n")
                
                if item['body']:
                    # Show a snippet of body
                    snippet = item['body'][:200] + "..." if len(item['body']) > 200 else item['body']
                    f.write(f"> {snippet.replace(chr(10), ' ')}\n\n")
                
                for cat, kws in item['analysis'].items():
                    f.write(f"- **{cat.capitalize()}**: {', '.join(kws)}\n")
                
                f.write("\n---\n\n")
                
    click.echo(f"Report generated: {filename}")

@click.command()
@click.option('--industry', prompt='Target Industry', help='The industry to scan (e.g., "plumbers", "accountants").')
@click.option('--limit', default=10, help='Number of search results to process.')
@click.option('--test-mode', is_flag=True, default=False, help='Run in test mode (limit to 5 searches total).')
def main(industry, limit, test_mode):
    """Automates the 'Safari' technique for validating business ideas on Reddit."""
    
    # 1. Load Config
    try:
        config = load_config()
    except Exception as e:
        click.echo(f"Error loading config: {e}")
        return

    # 2. Discover Subreddits
    subreddits = discover_subreddits(industry)
    if not subreddits:
        click.echo("No specific subreddits found. Falling back to broad search.")
    
    # 3. Search
    click.echo("Starting targeted search...")
    search_limit = max(limit, 20)
    if test_mode:
        click.echo("[TEST MODE] Limiting search depth.")
        search_limit = 2
        
    search_results = search_reddit(industry, config, subreddits, search_limit)

    if not search_results:
        click.echo("No results found.")
        return

    # 4. Scrape & Analyze
    click.echo(f"Processing {len(search_results)} results with Semantic Analysis...")
    
    # Pre-load model
    load_model()
    
    start_time = time.time()
    analyzed_findings = process_results(search_results, config, industry, start_time)

    # 5. Filter & Fallback
    # Updated Thresholds:
    # 1. Hard Filter already applied in analyze_content (returns None)
    # 2. Semantic Score > 0.42 (Pure Semantic) OR (Semantic > 0.35 AND Keywords >= 2)
    relevant = []
    def is_relevant(item):
        return item['semantic_score'] > 0.42 or (item['semantic_score'] > 0.35 and item['keyword_score'] >= 2)

    for item in analyzed_findings:
        if is_relevant(item):
            relevant.append(item)
            
    # Fallback Logic
    if len(relevant) < 10 and not test_mode:
        click.echo(f"Found only {len(relevant)} high-quality results. Triggering fallback search...")
        
        fallback_results = search_fallback(industry, config, subreddits, limit=5)
        
        # Dedup against existing
        existing_urls = set(r['url'] for r in analyzed_findings)
        new_urls = [r for r in fallback_results if r.get('href') not in existing_urls]
        
        if new_urls:
            click.echo(f"Processing {len(new_urls)} fallback results...")
            fallback_analyzed = process_results(new_urls, config, industry, start_time)
            
            for item in fallback_analyzed:
                analyzed_findings.append(item)
                if is_relevant(item):
                    relevant.append(item)
        else:
            click.echo("Fallback search found no new unique results.")

    # 6. Output
    if relevant:
        generate_markdown_report(industry, relevant)
    else:
        click.echo("No valid data extracted.")

if __name__ == '__main__':
    main()
