"""
LLM Classifier Module for Reddit Safari.

Uses structured prompts with pre-extracted pain aspects to guide
LLM classification decisions. Makes a single call per post.
"""

import json
import ollama


def classify_opportunity(post_data: dict, aspects: list[dict], industry: str) -> dict:
    """
    Uses LLM to classify a post based on pre-extracted pain aspects.
    
    Args:
        post_data: Dict with 'title' and 'body' keys
        aspects: List of detected aspects from pain_aspects.detect_aspects()
        industry: Target industry string
    
    Returns:
        Dict with:
        - is_opportunity: bool
        - classification: str ("STRONG_OPPORTUNITY", "WEAK_OPPORTUNITY", "NOT_OPPORTUNITY")
        - confidence: float (0.0-1.0)
        - reasoning: str
        - pain_type: str (primary pain category if opportunity)
    """
    title = post_data.get('title', 'No Title')
    body = post_data.get('body', '')[:1000]  # Bumped from 500 for better context
    
    # Format aspects for the prompt
    if aspects:
        aspects_text = "\n".join([
            f"- [{a['aspect'].replace('_', ' ').title()}]: \"{a['sentence'][:100]}...\" (sentiment: {a['sentiment']})"
            for a in aspects
        ])
    else:
        aspects_text = "No clear pain signals detected."
    
    prompt = f"""You are analyzing a Reddit post from the {industry} industry to identify Micro-SaaS software opportunities.

TITLE: {title}
BODY: {body}

DETECTED PAIN SIGNALS:
{aspects_text}

CLASSIFICATION TASK:
Based on the detected signals above, classify this post:

1. STRONG_OPPORTUNITY: Professional clearly needs software (tool complaint + seeking alternative, OR explicit "is there an app" question)
2. WEAK_OPPORTUNITY: Possible need, but unclear context (mentions manual process but no frustration expressed)
3. NOT_OPPORTUNITY: Off-topic (consumer, student, career advice, hobby discussion, literal physical pain)

REJECT if:
- No pain signals detected
- About salary/career/burnout
- Student/homework help
- Consumer price complaints (not B2B)

ACCEPT if:
- Professionals discussing workflow problems
- Explicit questions about tools/software
- Frustration with existing software + industry relevance

Respond ONLY with valid JSON:
{{"classification": "STRONG_OPPORTUNITY|WEAK_OPPORTUNITY|NOT_OPPORTUNITY", "confidence": 0.0-1.0, "reasoning": "1 sentence", "pain_type": "tool|process|cost|ux|none"}}"""

    try:
        response = ollama.chat(
            model='llama3',
            messages=[{'role': 'user', 'content': prompt}],
            format='json'
        )
        
        result = json.loads(response['message']['content'])
        
        classification = result.get('classification', 'NOT_OPPORTUNITY')
        is_opportunity = classification in ['STRONG_OPPORTUNITY', 'WEAK_OPPORTUNITY']
        
        return {
            'is_opportunity': is_opportunity,
            'classification': classification,
            'confidence': float(result.get('confidence', 0.5)),
            'reasoning': result.get('reasoning', 'No reason provided'),
            'pain_type': result.get('pain_type', 'none')
        }
        
    except Exception as e:
        # Fallback: If LLM fails, use aspect score as heuristic
        has_strong_signal = any(
            a['aspect'] in ['seeking_alternative', 'tool_complaint'] 
            for a in aspects
        )
        
        return {
            'is_opportunity': has_strong_signal,
            'classification': 'WEAK_OPPORTUNITY' if has_strong_signal else 'NOT_OPPORTUNITY',
            'confidence': 0.5,
            'reasoning': f'LLM unavailable (fallback): {str(e)[:50]}',
            'pain_type': 'unknown'
        }


def batch_classify(posts: list[dict], industry: str) -> list[dict]:
    """
    Classify multiple posts. Adds classification results to each post dict.
    
    Args:
        posts: List of post dicts, each with 'title', 'body', and 'aspects' keys
        industry: Target industry
    
    Returns:
        Same list with 'llm_result' key added to each post
    """
    results = []
    for post in posts:
        aspects = post.get('aspects', [])
        llm_result = classify_opportunity(post, aspects, industry)
        post['llm_result'] = llm_result
        results.append(post)
    return results
