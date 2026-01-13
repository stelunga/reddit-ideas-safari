import json
import time
import os
import re
from datetime import datetime
import threading
import click
import requests
import ollama
from bs4 import BeautifulSoup
from ddgs import DDGS
from sentence_transformers import SentenceTransformer, util
import collections
from itertools import combinations

# New aspect-based detection modules
import pain_aspects
import llm_classifier

CONFIG_FILE = 'config.json'
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'

# Global model variable for lazy loading
semantic_model = None

def load_config():
    """Loads validation criteria, creating a default config if none exists."""
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "pain_keywords": {
                "Time Wasted": ["manual", "copy paste", "spreadsheet", "hours", "slow", "data entry"],
                "Money Lost": ["fined", "cost", "lost money", "expensive", "compliance", "audit"],
                "Bad Tools": ["clunky", "legacy", "old software", "crashes", "paper", "fax"]
            }
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_model():
    """Lazy loads the SBERT model to avoid startup lag if not needed."""
    global semantic_model
    if semantic_model is None:
        click.echo("Loading semantic model (all-MiniLM-L6-v2)...")
        semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
    return semantic_model

def llm_verify_local(post_data, industry):
    """
    Uses local Llama 3 via Ollama to perform the final validation logic.
    This acts as the 'Judge' to decide if a post is a genuine business opportunity.
    """
    prompt = f"""
    You are a Venture Capital Analyst. Analyze this Reddit post from the {industry} industry.
    
    Title: {post_data['title']}
    Body Snippet: {post_data['body'][:600]}...
    
    Task: Is this a VALID 'Micro-SaaS' software opportunity?
    
    CRITERIA TO REJECT (Output 'false'):
    - It is about salary, careers, burnout, or boss complaints.
    - It is a student asking for homework help or certification advice.
    - It is a consumer complaining about high prices.
    
    CRITERIA TO ACCEPT (Output 'true'):
    - Mention of using spreadsheets, manual work, or "paper and pencil".
    - Complaints about specific software being broken, slow, or ugly.
    - Questions like "Is there an app for X?"
    
    Respond in JSON format only:
    {{
        "is_opportunity": true/false,
        "reason": "short explanation"
    }}
    """
    
    try:
        response = ollama.chat(model='llama3', messages=[
            {'role': 'user', 'content': prompt},
        ], format='json')
        
        result = json.loads(response['message']['content'])
        return result.get('is_opportunity', False), result.get('reason', "No reason provided")
    except Exception as e:
        click.echo(f"Local LLM Error (ensure 'ollama serve' is running): {e}")
        # Default to True so we don't lose data if LLM is down, but note the error
        return True, "LLM Check Skipped (Error)"

def discover_subreddits(industry):
    """
    Hybrid Discovery Method:
    1. Uses DuckDuckGo with MULTIPLE queries for better coverage.
    2. Uses Llama 3 to filter out consumer/hobbyist subs (High precision).
    """
    click.echo(f"🔍 Searching for '{industry}' subreddits via DuckDuckGo...")
    
    # Use multiple query strategies for better coverage
    queries = [
        f'site:reddit.com/r/ {industry}',  # Direct subreddit search
        f'reddit {industry} subreddit',     # General search
        f'"{industry}" site:reddit.com',    # Industry in quotes
    ]
    
    candidates = []
    subreddit_pattern = re.compile(r'r/([a-zA-Z0-9_]+)')
    
    try:
        ddgs = DDGS()
        
        for query in queries:
            try:
                results = ddgs.text(query, max_results=8)
                
                for res in results:
                    # PRIORITY 1: Extract from URL (most reliable)
                    url = res.get('href', '')
                    if 'reddit.com/r/' in url:
                        parts = url.split('/r/')
                        if len(parts) > 1:
                            sub_name = parts[1].split('/')[0].split('?')[0]
                            # Skip generic subs
                            if sub_name and len(sub_name) > 2 and sub_name.lower() not in ['popular', 'all', 'home']:
                                candidates.append(sub_name)
                                continue
                    
                    # PRIORITY 2: Fallback to text parsing
                    text = (res.get('title', '') + " " + res.get('body', '')).lower()
                    found = subreddit_pattern.findall(text)
                    for s in found:
                        if len(s) > 2 and s.lower() not in ['popular', 'all', 'home']:
                            candidates.append(s)
            except Exception:
                continue  # Try next query if one fails

    except Exception as e:
        click.echo(f"Search failed: {e}")
        return []

    # Count frequency and get top candidates
    counts = collections.Counter([c for c in candidates if len(c) > 2])
    top_candidates = [s for s, c in counts.most_common(8)]
    
    if not top_candidates:
        click.echo("No candidates found via search.")
        return []

    click.echo(f"🧠 Asking Llama 3 to filter candidates: {top_candidates}")
    
    # 2. LLM Verification Loop
    verified_subs = []
    for sub in top_candidates:
        prompt = f"""
        Analyze 'r/{sub}' for the '{industry}' industry.
        
        Criteria for Relevance:
        - It IS relevant if it discusses the topic, work, tools, or hobby related to {industry}.
        - ACCEPT mixed communities (Professionals AND Enthusiasts).
        - REJECT only unrelated, meme, or purely off-topic subs.
        
        Is this subreddit relevant?
        Reply JSON only:
        {{
            "is_relevant": true/false,
            "reason": "short reason"
        }}
        """
        try:
            response = ollama.chat(model='llama3', messages=[
                {'role': 'user', 'content': prompt},
            ], format='json')
            data = json.loads(response['message']['content'])
            
            if data.get('is_relevant'):
                verified_subs.append(sub)
                click.echo(f"  ✅ r/{sub}: {data.get('reason')}")
            else:
                click.echo(f"  ❌ r/{sub}: {data.get('reason')}")
        except:
            continue
            
    return verified_subs[:5]

def scrape_thread_safe(url):
    """Scrapes a Reddit thread with retry logic and User-Agent protection.
    
    Now extracts:
    - Title
    - Body
    - Comment count
    - Post date
    """
    time.sleep(1.5) # Polite delay
    
    # Force old.reddit for easier HTML parsing
    if "www.reddit.com" in url:
        url = url.replace("www.reddit.com", "old.reddit.com")
    elif "reddit.com" in url and "old.reddit.com" not in url:
        url = url.replace("reddit.com", "old.reddit.com")
    
    headers = {'User-Agent': USER_AGENT}
    
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Extract Title
                title_tag = soup.find('a', class_='title')
                title = title_tag.text.strip() if title_tag else "No Title"
                
                # Extract Body
                body_div = soup.find('div', class_='usertext-body')
                body = body_div.text.strip() if body_div else ""
                
                # Extract Comment Count
                comment_count = 0
                comments_link = soup.find('a', class_='comments')
                if comments_link:
                    comment_text = comments_link.text.strip()
                    # Parse "42 comments" or "1 comment"
                    match = re.search(r'(\d+)\s*comment', comment_text)
                    if match:
                        comment_count = int(match.group(1))
                
                # Extract Post Date
                post_date = None
                time_tag = soup.find('time')
                if time_tag and time_tag.get('datetime'):
                    try:
                        # Parse ISO format: 2024-01-15T12:30:00+00:00
                        date_str = time_tag['datetime']
                        post_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    except:
                        pass
                
                return {
                    'url': url, 
                    'title': title, 
                    'body': body,
                    'comment_count': comment_count,
                    'post_date': post_date
                }
            elif resp.status_code == 429:
                time.sleep(5) # Backoff if rate limited
        except:
            pass
    return None

def calculate_semantic_score(post_text, industry):
    """
    Calculates a relevance score using SBERT (Sentence-BERT).
    Compares the post against a "Golden Opportunity" anchor and a "Noise" anchor.
    """
    model = load_model()
    
    # Positive Signal (The Opportunity)
    opp_text = f"I hate this software. I use spreadsheets to track data manually. I waste hours copying data. Is there an app for this problem in {industry}?"
    
    # Negative Signal (The Noise)
    noise_text = f"I hate my boss. My salary is too low. I am burning out. How do I get a job? Student looking for internship in {industry}."
    
    embeddings = model.encode([post_text, opp_text, noise_text])
    
    # Cosine Similarity
    opp_score = float(util.cos_sim(embeddings[0], embeddings[1])[0][0])
    noise_score = float(util.cos_sim(embeddings[0], embeddings[2])[0][0])
    
    # Penalize if the post is closer to "Noise" than "Opportunity"
    final_score = opp_score
    if noise_score > 0.45 and noise_score > opp_score:
        final_score = opp_score - 0.5 
        
    return final_score

def analyze_batch(results, config, industry, global_seen_urls):
    """
    Filters raw search results using Aspect-Based Pain Detection.
    
    Pipeline:
    1. URL deduplication
    2. Hard keyword blocks (title-based)
    3. Aspect extraction (sentence-level pain signals)
    4. Aspect score threshold filtering
    """
    analyzed_data = []
    
    # Fast blacklist for immediate rejection
    blacklist = ["hiring", "salary", "resume", "interview", "degree", "student", "intern", "pay"]
    
    # Get threshold from config, default to 1.5
    aspect_threshold = config.get('aspect_score_threshold', 1.5)
    
    for res in results:
        url = res.get('href')
        if not url or url in global_seen_urls:
            continue
            
        global_seen_urls.add(url)
        
        # Scrape
        data = scrape_thread_safe(url)
        if not data:
            continue
        
        # Engagement Filter: Skip posts with < 5 comments
        min_comments = config.get('min_comments', 5)
        if data.get('comment_count', 0) < min_comments:
            continue
        
        # Date Filter: Skip posts older than 2 years
        max_age_years = config.get('max_age_years', 2)
        if data.get('post_date'):
            from datetime import timezone
            now = datetime.now(timezone.utc)
            age = now - data['post_date'].replace(tzinfo=timezone.utc)
            if age.days > (max_age_years * 365):
                continue
            
        # Hard Filter on title
        title_lower = data['title'].lower()
        if any(w in title_lower for w in blacklist):
            continue
        
        # Aspect-Based Detection (New)
        # Analyze title + more body content for better signal
        full_text = f"{data['title']} {data['body'][:600]}"
        aspects = pain_aspects.detect_aspects(full_text, industry)
        aspect_score = pain_aspects.calculate_aspect_score(aspects)
        
        data['aspects'] = aspects
        data['aspect_score'] = aspect_score
        
        # Also keep legacy semantic score for comparison/fallback
        semantic_score = calculate_semantic_score(f"{data['title']} {data['body'][:300]}", industry)
        data['semantic_score'] = semantic_score
        
        # Pass candidates with sufficient aspect signals
        if aspect_score >= aspect_threshold or (aspect_score > 0 and semantic_score > 0.40):
            analyzed_data.append(data)
            
    return analyzed_data

def generate_markdown_report(industry, findings):
    """
    Writes verified opportunities to a formatted Markdown file in the /reports directory.
    Updated to show detected pain aspects.
    """
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
    
    dt_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(reports_dir, f"report_{industry.replace(' ', '_')}_{dt_str}.md")

    with open(filename, 'w') as f:
        f.write(f"# Verified Opportunities: {industry}\n\n")
        f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Total Verified**: {len(findings)}\n\n")
        f.write("---\n\n")
        
        # Sort by aspect score (primary) then semantic score (secondary)
        sorted_items = sorted(findings, key=lambda x: (x.get('aspect_score', 0), x.get('semantic_score', 0)), reverse=True)
        
        for opp in sorted_items:
            f.write(f"### {opp['title']}\n")
            
            # Show both scores
            aspect_score = opp.get('aspect_score', 0)
            semantic_score = opp.get('semantic_score', 0)
            f.write(f"**Aspect Score**: {aspect_score:.2f} | **Semantic Score**: {semantic_score:.2f}\n\n")
            
            # Show detected aspects
            aspects = opp.get('aspects', [])
            if aspects:
                f.write("**Pain Signals Detected**:\n")
                for aspect in aspects:
                    aspect_name = aspect['aspect'].replace('_', ' ').title()
                    f.write(f"- 🔍 [{aspect_name}]: \"{aspect['sentence'][:80]}..\"\n")
                f.write("\n")
            
            # Show LLM analysis
            llm_result = opp.get('llm_result', {})
            classification = llm_result.get('classification', 'N/A')
            reasoning = llm_result.get('reasoning', opp.get('llm_reason', 'N/A'))
            f.write(f"**🤖 Classification**: {classification}\n")
            f.write(f"**Reasoning**: {reasoning}\n\n")
            
            f.write(f"[View Thread]({opp['url']})\n")
            
            # Add a small snippet for context
            if opp.get('body'):
                snippet = opp['body'][:300].replace('\n', ' ') + "..."
                f.write(f"> {snippet}\n")
            
            f.write("\n---\n\n")
            
    click.echo(f"📝 Report saved to: {filename}")
    return filename

@click.command()
@click.option('--industry', prompt='Target Industry', help='Industry to scan (e.g., Plumbing, Legal)')
@click.option('--limit', default=10, help='Max search results per query')
@click.option('--test-mode', is_flag=True, default=False, help='Run fast test (fewer searches)')
def main(industry, limit, test_mode):
    """
    The Local-First Sales Safari Tool.
    Automates discovering B2B Micro-SaaS ideas using Hybrid Discovery + Semantic Search + Local Llama 3.
    """
    config = load_config()
    load_model() # Preload SBERT model
    
    # Adjust limits for Test Mode to ensure quick debugging
    if test_mode:
        click.echo("⚠️ TEST MODE ENABLED: Limits restricted to 3 results.")
        limit = 3

    # 1. Discovery Phase
    subreddits = discover_subreddits(industry)
    click.echo(f"🎯 Target Subreddits: {subreddits}")
    
    # 2. Search Phase
    ddgs = DDGS()
    global_seen = set()
    
    click.echo("Searching and filtering candidates...")
    
    # Construct search queries - RESTRICTED to discovered subreddits
    search_queries = []
    
    if subreddits:
        # Build subreddit site restriction (e.g., "site:reddit.com/r/Beekeeping OR site:reddit.com/r/bee")
        # DuckDuckGo doesn't support multiple site: in one query, so we search each sub
        for sub in subreddits[:5]:  # Limit to top 5 subs for better coverage
            sub_site = f"site:reddit.com/r/{sub}"
            search_queries.extend([
                f'{sub_site} (manual OR spreadsheet OR problem)',
                f'{sub_site} (software OR tool OR app)',
                f'{sub_site} (frustrat OR hate OR help)',
            ])
    else:
        # Fallback: no subreddits found, search general Reddit (less precise)
        click.echo("⚠️ No subreddits found, using broad Reddit search...")
        search_queries = [
            f'site:reddit.com "{industry}" (manual OR spreadsheet OR "paper and pencil")',
            f'site:reddit.com "{industry}" (software OR tool OR app)',
            f'site:reddit.com "{industry}" problem',
        ]
    
    raw_results = []
    for q in search_queries:
        try:
            click.echo(f"  > Searching: {q}...")
            # Execute DDG Search
            raw_results.extend([r for r in ddgs.text(f"site:reddit.com {q}", max_results=limit)])
        except Exception as e:
            click.echo(f"  Search error: {e}")
            continue
            
    # 3. Aspect-Based Analysis Phase (replaces old semantic-only filter)
    # Uses sentence-level pain detection + semantic scoring
    candidates = analyze_batch(raw_results, config, industry, global_seen)
    click.echo(f"Aspect Filter found {len(candidates)} potential leads.")
    
    # 4. LLM Classification Phase (uses structured prompt with aspects)
    final_opportunities = []
    use_llm = config.get('use_llm_classification', True)
    
    if candidates:
        if use_llm:
            click.echo("Classifying with Llama 3 (using detected aspects)...")
            with click.progressbar(candidates) as bar:
                for item in bar:
                    aspects = item.get('aspects', [])
                    result = llm_classifier.classify_opportunity(item, aspects, industry)
                    item['llm_result'] = result
                    
                    if result['is_opportunity']:
                        item['llm_reason'] = result['reasoning']
                        final_opportunities.append(item)
        else:
            # Skip LLM, use aspect score directly
            click.echo("LLM disabled. Using aspect scores only...")
            for item in candidates:
                if item.get('aspect_score', 0) >= 2.0:
                    item['llm_result'] = {'classification': 'ASPECT_ONLY', 'reasoning': 'LLM disabled'}
                    item['llm_reason'] = 'Aspect-based (LLM skipped)'
                    final_opportunities.append(item)
    
    # 5. Reporting Phase
    if final_opportunities:
        generate_markdown_report(industry, final_opportunities)
    else:
        click.echo("No high-quality opportunities found after analysis.")

if __name__ == '__main__':
    main()