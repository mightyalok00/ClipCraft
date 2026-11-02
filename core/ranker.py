"""Universal AI Highlight Ranking and Virality Scoring Engine."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from config import load_config

# Criteria prompts tuned per content category
PROMPT_CRITERIA = {
    "gaming": """You are evaluating raw gameplay / live stream footage.
CRITICAL RULES:
- HARD REQUIREMENT: Every clip MUST feature the streamer's own reaction/voice, not pure game dialogue.
- THE PAYOFF MUST BE VISIBLE: A clutch play, sudden death, hilarious physics fail, or jump scare.
- COLD OPEN: Cut straight to the action or reaction. No waiting in menus or dead silence.""",

    "podcast": """You are evaluating podcast / interview conversation.
CRITICAL RULES:
- Focus on OPINION BOMBS, counter-intuitive perspectives, or vulnerable confessions.
- Both speakers must be clear. Capture complete, self-contained thoughts without mid-sentence cutoffs.
- COLD OPEN: Start on the boldest, most thought-provoking statement.""",

    "educational": """You are evaluating tutorial / tech / educational video.
CRITICAL RULES:
- Focus on practical, actionable tips, "aha" moments, and surprising hacks.
- The viewer should learn one clear thing in under 60 seconds.
- COLD OPEN: Open with the promise ("Here's why your code breaks...", "Never do this...").""",

    "vlog": """You are evaluating vlog / story / IRL video.
CRITICAL RULES:
- Focus on emotional peaks, hilarious moments, unexpected twists, and relatable experiences.
- COLD OPEN: Start right when the unexpected happens or the punchline lands.""",

    "general": """You are an elite short-form video editor for TikTok, YouTube Shorts, and Reels.
CRITICAL RULES:
- Prioritize: 1. Instant hook, 2. Emotional peak/reaction, 3. Strong payoff.
- Standalone: A stranger with zero context must understand and enjoy it in 3 seconds.""",
}

SYSTEM_TEMPLATE = """{criteria}

Content Type: {content_type}
Target Duration: 30-60 seconds per clip.

TASK: Identify the top {num_clips} most viral, scroll-stopping moments from the transcript below.

Return a STRICT JSON response with the following format:
{{
  "highlights": [
    {{
      "title": "Punchy 3-6 word title",
      "start_time": 12.5,
      "end_time": 45.2,
      "score": 92,
      "hook_score": 95,
      "first_line": "Exact first sentence the clip opens with",
      "hook_sentence": "Same opening hook sentence",
      "virality_reason": "One sentence explaining why viewers will share this",
      "on_screen": "What is visually happening at the payoff"
    }}
  ]
}}

Transcript:
{transcript_text}
"""


def get_llm_client(config: dict[str, Any]):
    """Instantiate the active LLM client based on configuration."""
    provider = config.get("llm_provider", "gemini").lower()

    if provider == "gemini":
        from google import genai  # type: ignore
        key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("GEMINI_API_KEY is not set.")
        client = genai.Client(api_key=key)
        model_name = config.get("gemini_model", "gemini-2.5-flash")

        def _call_gemini(prompt: str) -> str:
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            return res.text or ""
        return _call_gemini

    elif provider in ("groq", "openai", "ollama"):
        from openai import OpenAI  # type: ignore

        if provider == "groq":
            key = config.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")
            if not key:
                raise ValueError("GROQ_API_KEY is not set.")
            client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
            model_name = config.get("groq_model", "llama-3.3-70b-versatile")

        elif provider == "ollama":
            client = OpenAI(
                api_key="ollama",
                base_url=config.get("ollama_base_url", "http://localhost:11434/v1")
            )
            model_name = config.get("ollama_model", "llama3.2")

        else:  # openai
            key = config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            if not key:
                raise ValueError("OPENAI_API_KEY is not set.")
            client = OpenAI(api_key=key)
            model_name = config.get("openai_model", "gpt-4o-mini")

        def _call_openai_compat(prompt: str) -> str:
            res = client.chat.completions.create(
                model=model_name,
                temperature=0.3,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            return res.choices[0].message.content or ""
        return _call_openai_compat

    raise ValueError(f"Unknown LLM provider: {provider}")


def _extract_json(raw_text: str) -> Any:
    """Robustly extract JSON structure from LLM markdown response."""
    cleaned = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    return json.loads(cleaned)


def build_prompt_for_category(
    category: str,
    transcript_text: str,
    num_clips: int = 3,
    energy_summary: str = "",
    custom_prompt: str = "",
) -> str:
    """Build the LLM system prompt tailored to a content category."""
    cat_key = category.lower()
    if cat_key == "education":
        cat_key = "educational"
    criteria = PROMPT_CRITERIA.get(cat_key, PROMPT_CRITERIA["general"])
    if energy_summary:
        criteria += f"\nAUDIO ENERGY / REACTION NOTES: {energy_summary}"
    if custom_prompt:
        criteria += f"\nADDITIONAL USER DIRECTION: {custom_prompt}"

    return SYSTEM_TEMPLATE.format(
        criteria=criteria,
        content_type=category,
        num_clips=num_clips,
        transcript_text=transcript_text[:120000],
    )


def rank_highlights(
    transcript: dict[str, Any],
    num_clips: int = 5,
    content_type: str = "general",
    prompt_override: str = "",
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank transcript segments to extract top viral highlights."""
    conf = config or load_config()
    call_llm = get_llm_client(conf)

    segments = transcript.get("segments", [])
    if not segments:
        return []

    # Format transcript text
    lines = []
    for s in segments:
        lines.append(f"[{s['start']:.1f}s - {s['end']:.1f}s]: {s['text']}")
    transcript_text = "\n".join(lines)

    criteria = PROMPT_CRITERIA.get(content_type.lower(), PROMPT_CRITERIA["general"])
    if prompt_override:
        criteria += f"\nADDITIONAL USER DIRECTION: {prompt_override}"

    prompt = SYSTEM_TEMPLATE.format(
        criteria=criteria,
        content_type=content_type,
        num_clips=num_clips,
        transcript_text=transcript_text[:120000],  # generous context window
    )

    print(f"[ranker] Querying {conf.get('llm_provider', 'LLM').upper()} for {num_clips} highlights...")
    raw_response = call_llm(prompt)

    # Parse JSON
    try:
        data = _extract_json(raw_response)
        highlights = data if isinstance(data, list) else data.get("highlights", [])
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        print(f"[ranker] Failed parsing LLM response: {e}\nRaw was:\n{raw_response[:500]}")
        return []

    # Sanitize and deduplicate
    duration = transcript.get("duration", 0.0)
    cleaned = []
    for h in highlights:
        start = float(h.get("start_time", 0.0))
        end = float(h.get("end_time", 0.0))
        if end <= start or (duration and start > duration):
            continue
        # Clamp duration to 15s - 90s
        if (end - start) < 15.0:
            end = min(start + 30.0, duration or start + 30.0)

        cleaned.append({
            "title": str(h.get("title") or "Viral Highlight").strip(),
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "duration": round(end - start, 2),
            "score": int(h.get("score") or 80),
            "hook_score": int(h.get("hook_score") or 85),
            "first_line": str(h.get("first_line") or "").strip(),
            "hook_sentence": str(h.get("hook_sentence") or h.get("first_line") or "").strip(),
            "virality_reason": str(h.get("virality_reason") or "").strip(),
            "on_screen": str(h.get("on_screen") or "").strip(),
        })

    # Sort by score descending
    cleaned.sort(key=lambda x: (x["score"] + x["hook_score"]), reverse=True)
    return cleaned[:num_clips]
