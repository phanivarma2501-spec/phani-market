import requests
import re
from typing import Dict, Optional, Tuple
from settings import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, REASONING_MODEL


def estimate_probability(market: Dict) -> Tuple[Optional[float], str]:
    """
    Use DeepSeek R1 to estimate probability for a market.
    Returns (probability, full_reasoning) tuple.
    probability is None if R1 cannot estimate confidently.
    """
    question = market["question"]
    yes_price = market.get("yes_price", 0.5)
    no_price = market.get("no_price", 0.5)
    research_summary = market.get("research_summary", "")
    metaculus_prob = market.get("metaculus_probability")
    end_date = market.get("end_date", "Unknown")

    metaculus_str = f"{metaculus_prob:.1%}" if metaculus_prob is not None else "Not available"

    prompt = f"""You are an expert prediction market analyst. Estimate the probability that the following market resolves YES.

Market Question: {question}
Resolution Date: {end_date}

Current Market Prices:
- YES: {yes_price:.3f} (market implies {yes_price:.1%} probability)
- NO: {no_price:.3f} (market implies {no_price:.1%} probability)

Metaculus Expert Forecast: {metaculus_str}

Research Summary:
{research_summary}

Instructions:
1. Think step by step through the evidence
2. Consider base rates, current evidence, and expert forecasts
3. Identify the key uncertainties
4. Give your final probability estimate as a number between 0.01 and 0.99

You MUST end your response with exactly this format on the last line:
PROBABILITY: 0.XX

Where 0.XX is your probability estimate (e.g. PROBABILITY: 0.67)"""

    if not DEEPSEEK_API_KEY:
        print("  [Reasoning] DEEPSEEK_API_KEY is empty — cannot call R1", flush=True)
        return None, "DEEPSEEK_API_KEY not set"

    print(f"  [Reasoning] Calling R1 for: {question[:60]}...", flush=True)
    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": REASONING_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8000,
                "temperature": 0.1,
            },
            timeout=180,
        )
        if resp.status_code != 200:
            print(f"  [Reasoning] R1 HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
            return None, f"HTTP {resp.status_code}"

        choice = resp.json()["choices"][0]
        message = choice.get("message", {})
        content = (message.get("content") or "").strip()
        reasoning = (message.get("reasoning_content") or "").strip()
        finish_reason = choice.get("finish_reason")

        # Try final answer first, then chain-of-thought as fallback
        probability = _extract_probability(content) if content else None
        if probability is None and reasoning:
            probability = _extract_probability(reasoning)

        if probability is None:
            print(
                f"  [Reasoning] R1 returned no parseable PROBABILITY. "
                f"finish_reason={finish_reason!r} content_len={len(content)} "
                f"reasoning_len={len(reasoning)} content_tail={content[-120:]!r} "
                f"reasoning_tail={reasoning[-120:]!r}",
                flush=True,
            )
        else:
            print(f"  [Reasoning] R1 → {probability:.1%}", flush=True)

        return probability, content or reasoning

    except Exception as e:
        print(f"  [Reasoning] Error: {e}", flush=True)
        return None, str(e)


def _extract_probability(text: str) -> Optional[float]:
    """Extract probability from R1 response."""
    # Look for PROBABILITY: 0.XX pattern
    pattern = r"PROBABILITY:\s*(0\.\d+|1\.0+|0)"
    matches = re.findall(pattern, text, re.IGNORECASE)

    if matches:
        try:
            prob = float(matches[-1])  # Take last occurrence
            # Clamp to valid range
            prob = max(0.01, min(0.99, prob))
            return prob
        except ValueError:
            pass

    # Fallback: look for any decimal probability in last 3 lines
    lines = text.strip().split("\n")[-3:]
    for line in reversed(lines):
        numbers = re.findall(r"0\.\d{2,}", line)
        if numbers:
            try:
                prob = float(numbers[-1])
                if 0.01 <= prob <= 0.99:
                    return prob
            except ValueError:
                continue

    return None
