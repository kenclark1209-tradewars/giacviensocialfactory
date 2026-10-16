"""Step 2 of the "remix link" pipeline: rewrite extracted content into a new script.

Takes the LinkContent from step 1 plus the user's tone / language choices and
asks the configured AI provider for a fresh 4-scene (default) script: action,
image prompt, video prompt (sub-clip timing) and narrator text per scene.
The output is original writing based on the source's *ideas* — never a copy.
"""
from __future__ import annotations

import json
import logging

from agent.services import ai_tasks, cli_providers
from agent.services.link_extract import LinkContent

logger = logging.getLogger(__name__)

# Six rewrite tones shown in the UI (id -> guidance for the scriptwriter).
TONES: dict[str, dict[str, str]] = {
    "documentary": {
        "vi": "Phim tài liệu",
        "en": "Documentary",
        "guidance": "Authoritative, fact-driven narration. Add context the viewer cannot see; short punchy sentences; build setup -> rising -> climax -> resolution.",
    },
    "storytelling": {
        "vi": "Kể chuyện",
        "en": "Storytelling",
        "guidance": "Warm narrative voice with emotion and a clear arc. Make the viewer feel something in every scene.",
    },
    "humorous": {
        "vi": "Hài hước",
        "en": "Humorous",
        "guidance": "Playful, witty narration with light jokes. Keep it family-friendly and never mean-spirited.",
    },
    "motivational": {
        "vi": "Truyền cảm hứng",
        "en": "Motivational",
        "guidance": "Uplifting, energetic voice. End scenes with a forward-looking punch; speak directly to the viewer.",
    },
    "news": {
        "vi": "Tin tức",
        "en": "News",
        "guidance": "Neutral news-anchor tone. Who/what/where first, then why it matters. No invented facts.",
    },
    "educational": {
        "vi": "Giáo dục",
        "en": "Educational",
        "guidance": "Clear explainer tone. One key idea per scene; define terms simply; build understanding step by step.",
    },
}

# Eight recommended animation styles (material ids must exist in agent/materials.py).
RECOMMENDED_MATERIALS = [
    "realistic",
    "3d_pixar",
    "anime",
    "ghibli",
    "comic_book",
    "watercolor",
    "stickman_light",
    "claymation",
]

# Max narrator words per language so the voiceover fits the ~6.5s usable scene audio.
NARRATOR_MAX_WORDS = {
    "vi": 22, "en": 22, "ja": 33, "ko": 22, "th": 24,
    "zh": 28, "es": 24, "fr": 24, "ar": 20, "hi": 22, "id": 22,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short rewritten video title"},
        "scenes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "One-line scene action (ACTION only, no character appearance)"},
                    "image_prompt": {"type": "string", "description": "Still-image prompt for frame 0"},
                    "video_prompt": {"type": "string", "description": "8s video prompt with sub-clip timing like '0-3s: ... 3-6s: ... 6-8s: ...'"},
                    "narrator_text": {"type": "string", "description": "Voiceover script for this scene"},
                },
            },
        },
    },
}


def _source_brief(content: LinkContent) -> str:
    parts = []
    if content.title:
        parts.append(f"Title: {content.title}")
    if content.author:
        parts.append(f"Author: {content.author}")
    if content.description:
        parts.append(f"Description: {content.description[:1200]}")
    if content.captions:
        parts.append(f"Captions ({content.captions_lang}): {content.captions[:2500]}")
    elif content.page_text:
        parts.append(f"Page text: {content.page_text[:2500]}")
    return "\n".join(parts) or "(no extractable text; invent nothing, write a generic intro scene)"


async def plan_remix_script(
    content: LinkContent,
    *,
    tone: str = "storytelling",
    language: str = "vi",
    scene_count: int = 4,
) -> dict:
    """Ask the AI provider to rewrite the source into an original scene plan."""
    if tone not in TONES:
        raise ValueError(f"Giọng điệu không hợp lệ: {tone}")
    if not 1 <= scene_count <= 8:
        raise ValueError("Số cảnh phải từ 1 đến 8.")
    language = (language or "vi").lower()
    max_words = NARRATOR_MAX_WORDS.get(language, 22)
    tone_guidance = TONES[tone]["guidance"]

    prompt = f"""Rewrite the following source material into an ORIGINAL {scene_count}-scene short video script.
Write in {language}. Do NOT copy sentences from the source; keep only the core ideas and facts, retold in your own words.
Tone: {tone_guidance}

SOURCE MATERIAL:
{_source_brief(content)}

RULES:
- Exactly {scene_count} scenes forming one arc (hook -> development -> climax -> payoff).
- Each scene: one clear ACTION for `action` (never describe character appearance there).
- `video_prompt` must use 8-second sub-clip timing: "0-3s: [action]. 3-6s: [action]. 6-8s: [action]."
- `narrator_text`: {max_words} words MAX (hard limit so it fits the scene audio), 2-3 punchy sentences, no filler like "In this scene...".
- Never invent dates, names, or statistics not present in the source.
- Never use real public-figure names for depicted characters.
- Return ONLY the JSON object matching the schema."""

    role = cli_providers.resolve_role("scriptwriter")
    raw = await ai_tasks.complete(role, prompt, schema=PLAN_SCHEMA)
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AI trả về kịch bản không đúng định dạng. Hãy thử lại.") from exc
    scenes = plan.get("scenes") or []
    if not scenes:
        raise ValueError("AI không tạo được cảnh nào. Hãy thử lại với link khác.")
    # Clamp narrator length defensively; the model sometimes overshoots.
    for scene in scenes:
        text = (scene.get("narrator_text") or "").strip()
        words = text.split()
        if len(words) > max_words:
            scene["narrator_text"] = " ".join(words[:max_words])
    plan["scenes"] = scenes[:scene_count]
    plan["tone"] = tone
    plan["language"] = language
    plan["source_url"] = content.url
    plan["source_title"] = content.title
    return plan
