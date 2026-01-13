"""
Pain Aspect Extraction Module for Reddit Safari.

Uses sentence-level analysis to detect structured pain signals:
- Tool complaints (software/app + negative sentiment)
- Manual processes (spreadsheets, pen and paper)
- Seeking alternatives ("is there a tool for...")
- Cost issues (expensive, overkill)
- UX frustrations (slow, crashes, clunky)
"""

import re
from textblob import TextBlob

# Pain aspect definitions with patterns and sentiment thresholds
PAIN_ASPECTS = {
    "tool_complaint": {
        "patterns": [
            r"\b(software|app|tool|system|platform|program)\b",
        ],
        "negative_patterns": [
            r"\b(crash|slow|broken|terrible|awful|horrible|worst|sucks|useless|buggy|unreliable)\b",
        ],
        "sentiment_threshold": -0.15,
        "weight": 2.0,
        "description": "Complaint about existing software/tool"
    },
    "manual_process": {
        "patterns": [
            r"\b(spreadsheet|excel|manual|pen and paper|paper and pencil|copy.?paste|by hand|handwritten)\b",
            r"\b(keep.{0,15}(track|record|log)|use.{0,10}paper)\b",  # "keep track", "keep records"
        ],
        "negative_patterns": [],
        "sentiment_threshold": None,  # No sentiment required - descriptive
        "weight": 1.5,
        "description": "Using manual methods for a task"
    },
    "seeking_alternative": {
        "patterns": [
            r"\b(is there|any (tool|app|software|application)|alternative|looking for)\b",
            r"\b(how do you|does anyone|what do you use|what software|what (tool|app))\b",
            r"\b(anyone know|suggestion|recommend|best way to)\b",
            r"\bwhat.{0,20}(use|track|manage|record)\b",  # "What do you use to track..."
            r"\bany.{0,30}(app|software|tool|application)\b",  # "Any beekeeping application"
        ],
        "negative_patterns": [],
        "sentiment_threshold": None,
        "weight": 2.5,
        "description": "Actively seeking a solution"
    },
    "cost_issue": {
        "patterns": [
            r"\b(expensive|cost|price|afford|budget|overkill|overpriced|too much)\b",
        ],
        "negative_patterns": [],
        "sentiment_threshold": -0.1,
        "weight": 1.0,
        "description": "Complaint about pricing/value"
    },
    "ux_frustration": {
        "patterns": [
            r"\b(clunky|slow|crash|crashes|ugly|confusing|frustrating|nightmare|annoying|hate|terrible|horrible)\b",
        ],
        "negative_patterns": [],
        "sentiment_threshold": -0.2,
        "weight": 1.5,
        "description": "Frustration with user experience"
    }
}

# Blacklist patterns to filter out noise
NOISE_PATTERNS = [
    r"\b(salary|resume|interview|student|intern|degree|homework|job hunt|career)\b",
    r"\b(my boss|coworker|burnout|quit|fired|laid off)\b",
    r"\b(regret|depressing|depression|hate my job|toxic workplace)\b",  # Career complaints
    r"\b(bee sting|back pain|physical pain)\b",  # Literal pain, not software pain
]


def extract_sentences(text: str) -> list[str]:
    """
    Split text into sentences using TextBlob's tokenizer.
    Handles abbreviations (e.g., U.S., Inc.) better than regex.
    """
    if not text:
        return []
    
    # Use TextBlob's sentence tokenizer for robust splitting
    blob = TextBlob(text.strip())
    return [str(s).strip() for s in blob.sentences if str(s).strip()]


def analyze_sentence_sentiment(sentence: str) -> float:
    """
    Analyze sentiment of a single sentence using TextBlob.
    Returns polarity from -1.0 (negative) to 1.0 (positive).
    """
    try:
        blob = TextBlob(sentence)
        return blob.sentiment.polarity
    except Exception:
        return 0.0


def matches_patterns(text: str, patterns: list[str]) -> list[str]:
    """
    Check if text matches any of the given regex patterns.
    Returns list of matched pattern strings.
    """
    text_lower = text.lower()
    matches = []
    for pattern in patterns:
        found = re.findall(pattern, text_lower, re.IGNORECASE)
        matches.extend(found)
    return matches


def is_noise(text: str) -> bool:
    """
    Check if text matches noise patterns (career, student, literal pain, etc.)
    """
    text_lower = text.lower()
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False


def detect_aspects(text: str, industry: str = "") -> list[dict]:
    """
    Main function: Detect pain aspects in text at sentence level.
    
    Args:
        text: The post text (title + body)
        industry: The target industry (for context, currently unused)
    
    Returns:
        List of detected aspects, each with:
        - aspect: str (aspect type name)
        - sentence: str (the sentence that matched)
        - confidence: float (0.0-1.0)
        - sentiment: float (-1.0 to 1.0)
        - matches: list[str] (matched keywords)
    """
    if not text:
        return []
    
    # Quick noise check on full text
    if is_noise(text):
        return []
    
    sentences = extract_sentences(text)
    detected_aspects = []
    
    for sentence in sentences:
        sentiment = analyze_sentence_sentiment(sentence)
        
        for aspect_name, aspect_config in PAIN_ASPECTS.items():
            # Check if sentence matches the aspect patterns
            pattern_matches = matches_patterns(sentence, aspect_config["patterns"])
            
            if not pattern_matches:
                continue
            
            # Check negative patterns if defined (for tool_complaint)
            negative_matches = []
            if aspect_config.get("negative_patterns"):
                negative_matches = matches_patterns(sentence, aspect_config["negative_patterns"])
            
            # Check sentiment threshold if required
            threshold = aspect_config.get("sentiment_threshold")
            sentiment_ok = True
            if threshold is not None:
                # For negative thresholds, sentiment must be <= threshold
                # OR we found explicit negative patterns
                sentiment_ok = sentiment <= threshold or bool(negative_matches)
            
            if not sentiment_ok:
                continue
            
            # Calculate confidence based on matches and sentiment strength
            confidence = min(1.0, 0.5 + (len(pattern_matches) * 0.15) + (len(negative_matches) * 0.2))
            if threshold is not None and sentiment < threshold:
                confidence += 0.1  # Boost for strong negative sentiment
            
            detected_aspects.append({
                "aspect": aspect_name,
                "sentence": sentence[:150],  # Truncate long sentences
                "confidence": round(confidence, 2),
                "sentiment": round(sentiment, 2),
                "matches": list(set(pattern_matches + negative_matches))[:5],  # Dedupe and limit
            })
    
    # Deduplicate aspects (keep highest confidence per type)
    unique_aspects = {}
    for aspect in detected_aspects:
        key = aspect["aspect"]
        if key not in unique_aspects or aspect["confidence"] > unique_aspects[key]["confidence"]:
            unique_aspects[key] = aspect
    
    return list(unique_aspects.values())


def calculate_aspect_score(aspects: list[dict]) -> float:
    """
    Calculate weighted score from detected aspects.
    
    Args:
        aspects: List of detected aspects from detect_aspects()
    
    Returns:
        Weighted score (higher = more likely opportunity)
    """
    if not aspects:
        return 0.0
    
    score = 0.0
    for aspect in aspects:
        aspect_name = aspect["aspect"]
        confidence = aspect.get("confidence", 0.5)
        weight = PAIN_ASPECTS.get(aspect_name, {}).get("weight", 1.0)
        score += weight * confidence
    
    return round(score, 2)


def format_aspects_for_llm(aspects: list[dict]) -> str:
    """
    Format detected aspects as text for LLM prompt.
    
    Args:
        aspects: List of detected aspects
    
    Returns:
        Formatted string for LLM context
    """
    if not aspects:
        return "No clear pain signals detected."
    
    lines = []
    for aspect in aspects:
        desc = PAIN_ASPECTS.get(aspect["aspect"], {}).get("description", aspect["aspect"])
        sentiment_str = f"sentiment: {aspect['sentiment']:.1f}"
        lines.append(f"- [{desc}]: \"{aspect['sentence']}\" ({sentiment_str})")
    
    return "\n".join(lines)
