# Reddit Pain Safari

## Overview

This tool automates the "Safari" technique for discovering business ideas. It scans Reddit for professionals in specific industries complaining about their daily workflows, identifying "pain markers" that indicate potential for software solutions (SaaS, Micro-SaaS).

## Architecture

### 1. Hybrid Discovery (`reddit_safari.py`)
- **Discovery**: Uses DuckDuckGo to find relevant subreddits.
  - *Strategy*: Searches `site:reddit.com/r/{industry}` and `reddit {industry} subreddit`.
  - *Filtering*: Uses local **Llama 3** (via Ollama) to accept professional/mixed communities and reject consumer/meme subreddits.

### 2. Search & Scrape
- **Engine**: DuckDuckGo (via `ddgs`) generates targeted queries (e.g., `site:reddit.com/r/farming "spreadsheet"`).
- **Scraper**: Fetches `old.reddit.com` for static HTML parsing (Title, Body, Comments, Date).

### 3. Aspect-Based Analysis (`pain_aspects.py`)
- **NLP**: Uses `TextBlob` to split posts into sentences.
- **Pain Detection**: Scans each sentence for "Pain Aspects":
  - `visual_struggle`: "It looks terrible"
  - `seeking_alternative`: "Is there an app for..."
  - `tool_complaint`: "Excel is crashing"
- **Scoring**: Calculates an `aspect_score` based on the density and intensity of pain signals.

### 4. LLM Classification (`llm_classifier.py`)
- **The Judge**: If aspect score > threshold, the post is sent to Llama 3.
- **Prompt**: Uses extracted pain aspects as context to classify the post:
  - `STRONG_OPPORTUNITY`: Clear B2B software need or deep frustration.
  - `WEAK_OPPORTUNITY`: Ambiguous.
  - `NOT_OPPORTUNITY`: Consumer complaint, career advice, etc.

### 5. Config (`config.json`)
- Use `aspect_score_threshold` (default 0.5) to tune sensitivity.
- Use `min_comments` (default 2) and `max_age_years` (default 10) to adjust scope.

## Tech Stack
- **Language**: Python 3.x
- **Core Libraries**:
  - `click` (CLI Interface)
  - `ollama` (Local LLM verification)
  - `duckduckgo-search` (Search automation via `ddgs`)
  - `textblob` (NLP Aspect Extraction)
  - `sentence-transformers` (Semantic scoring)
  - `beautifulsoup4` (Web scraping)

## Usage

### 1. Run Online (No Installation)

❗**NOTE** - this is currently **NOT** working

[![Launch Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/stelunga/reddit-ideas-safari/HEAD)

- **Binder**: Click the "Launch Binder" badge above. This service is **free** and runs in your browser.
  1. Wait for the environment to load (this may take a minute).
  2. When the terminal appears, type:
     ```bash
     python reddit_safari.py
     ```

### 2. Local Installation

It is recommended to use a virtual environment.

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Running the Tool

You can run the tool directly from the command line.

**Interactive Mode:**

```bash
python reddit_safari.py
```

You will be prompted to enter the target industry.

**Command Line Arguments:**

```bash
python reddit_safari.py --industry "accountants" --limit 20
```

**Test Mode:**

To quickly verify the tool works without running a full search, use the `--test-mode` flag. This limits the number of searches per category (default: 2) and disables fallback searches for speed.

```bash
python reddit_safari.py --industry "test" --test-mode
```

- Only a small number of results will be processed.
- Fallback (pairwise) search is skipped in test mode.
- Useful for debugging or checking installation.

### 4. Running Tests

To run the test suite:

```bash
python -m unittest test_reddit_safari.py
```
