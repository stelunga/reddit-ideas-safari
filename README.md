# Reddit Pain Safari

## Overview

This tool automates the "Safari" technique for discovering business ideas. It scans Reddit for professionals in specific industries complaining about their daily workflows, identifying "pain markers" that indicate potential for software solutions (SaaS, Micro-SaaS).

## Architecture

### 1. Configuration (`config.json`)

- Stores the "Pain Keywords" categorized by type:
  - **Struggle**: "hate", "nightmare", "annoying"
  - **Workaround**: "spreadsheet", "manual", "excel"
  - **Big Fail**: "too expensive", "too complex"
  - **Question**: "is there a tool", "how do I"

### 2. Search Module

**This and the Scraper Module are temporary workarounds until we have Reddit API (praw) access**

- **Engine**: DuckDuckGo (via `ddgs`) to avoid Google CAPTCHA/API limits.
- **Strategy**: Generates composite queries.
  - _Format_: `site:reddit.com "[Industry]" ("keyword1" OR "keyword2" ...)`
- **Filtering**: Limits results to the last ~2 years to ensure relevance.

### 3. Scraper Module

- **Target**: `old.reddit.com`
  - Why: Returns static HTML (faster, easier to parse, no React hydration issues).
- **Process**:
  - Converts standard reddit links to `old.reddit.com`.
  - Fetches page content using `requests` with proper User-Agent headers.
  - Parses HTML with `BeautifulSoup`.
- **Extraction**:
  - Thread Title
  - Post Body
  - Top-level Comments
  - Metadata: Date, Comment Count.

### 4. Analyzer Module

- **Relevance Check**: Discards threads with low engagement (< 5 comments) or old dates (> 2 years).
- **Keyword Matching**: Scans the extracted text for the pain keywords defined in `config.json`.
- **Semantic Analysis**: Uses `sentence-transformers` to score relevance against business opportunity anchors (e.g., "Time Wasted", "Money Lost") and filter out noise.

### 5. Output

- Generates a Markdown report (`report_[industry]_[date].md`).
- Sections:
  - **Executive Summary**: Top pain points identified.
  - **Detailed Findings**: Grouped by category (Struggle, Workaround, etc.).
  - **Source Links**: URLs to the original discussions.

## Tech Stack

- **Language**: Python 3.x
- **Libraries**:
  - `requests` (HTTP requests)
  - `beautifulsoup4` (HTML parsing)
  - `ddgs` (Search automation)
  - `sentence-transformers` (Semantic analysis)
  - `click` (CLI interface)

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
