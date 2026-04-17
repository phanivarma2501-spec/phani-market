import requests
from typing import Optional
from settings import METACULUS_BASE_URL


def search_metaculus(question: str) -> Optional[float]:
    """
    Search Metaculus for a matching question and return community probability.
    Returns None if no match found.
    """
    try:
        # Extract key terms from question
        keywords = _extract_keywords(question)
        if not keywords:
            return None

        params = {
            "search": keywords,
            "status": "open",
            "type": "forecast",
            "limit": 5,
        }
        resp = requests.get(
            f"{METACULUS_BASE_URL}/questions/",
            params=params,
            headers={"User-Agent": "phani-market-bot/2.0 (https://github.com/phanivarma2501-spec/phani-market)"},
            timeout=10,
        )
        if resp.status_code == 403:
            return None
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        if not results:
            return None

        # Find best matching question
        best_match = _find_best_match(question, results)
        if not best_match:
            return None

        # Get community prediction
        cp = best_match.get("community_prediction", {})
        if not cp:
            return None

        # For binary questions
        q2 = cp.get("full", {})
        if q2:
            p = q2.get("q2")  # median prediction
            if p is not None:
                return float(p)

        return None

    except Exception as e:
        print(f"[Metaculus] Search error: {e}")
        return None


def _extract_keywords(question: str) -> str:
    """Extract key search terms from a question."""
    # Remove common filler words
    stop_words = {"will", "the", "a", "an", "be", "in", "by", "to", "of",
                  "and", "or", "is", "are", "was", "were", "has", "have",
                  "had", "that", "this", "for", "with", "at", "from"}
    words = question.lower().replace("?", "").split()
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    return " ".join(keywords[:6])  # Top 6 keywords


def _find_best_match(original: str, results: list) -> Optional[dict]:
    """Find the most similar question from Metaculus results."""
    if not results:
        return None

    original_lower = original.lower()
    best_score = 0
    best_result = None

    for r in results:
        title = r.get("title", "").lower()
        score = _similarity_score(original_lower, title)
        if score > best_score:
            best_score = score
            best_result = r

    # Only return if reasonably similar (>20% word overlap)
    if best_score > 0.2:
        return best_result
    return None


def _similarity_score(a: str, b: str) -> float:
    """Simple word overlap similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
