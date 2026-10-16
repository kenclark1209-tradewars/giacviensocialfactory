"""Unit tests for agent/services/remix_plan.py.

The AI provider call is stubbed; these tests cover tone validation, prompt
construction and the defensive narrator-length clamp.
"""
import json
from unittest.mock import AsyncMock

import pytest

from agent.services import remix_plan
from agent.services.link_extract import LinkContent
from agent.services.remix_plan import TONES, plan_remix_script


def _content(**kwargs):
    base = dict(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                platform="youtube", title="Original title",
                description="A short description of the source video.",
                captions="First line. Second line.", captions_lang="en")
    base.update(kwargs)
    return LinkContent(**base)


def _plan_json(narrator="Short narration text here."):
    return json.dumps({
        "title": "Rewritten title",
        "scenes": [
            {"action": f"Action for scene {i}",
             "image_prompt": f"Image prompt {i}",
             "video_prompt": f"0-3s: Move. 3-6s: Continue. 6-8s: Settle. {i}",
             "narrator_text": narrator}
            for i in range(4)
        ],
    })


async def test_plan_calls_provider_with_schema(monkeypatch):
    caller = AsyncMock(return_value=_plan_json())
    monkeypatch.setattr(remix_plan.ai_tasks, "complete", caller)

    plan = await plan_remix_script(_content(), tone="documentary", language="vi", scene_count=4)

    assert plan["title"] == "Rewritten title"
    assert len(plan["scenes"]) == 4
    assert plan["tone"] == "documentary"
    assert plan["language"] == "vi"
    assert plan["source_url"].startswith("https://www.youtube.com")
    # Schema was passed so the provider returns structured JSON.
    assert caller.call_args.kwargs["schema"] == remix_plan.PLAN_SCHEMA
    prompt = caller.call_args.args[1]
    assert "Original title" in prompt
    assert "First line." in prompt  # captions feed the rewrite


async def test_plan_rejects_unknown_tone():
    with pytest.raises(ValueError, match="Giọng điệu"):
        await plan_remix_script(_content(), tone="nope")


async def test_plan_rejects_bad_scene_count():
    with pytest.raises(ValueError):
        await plan_remix_script(_content(), scene_count=0)
    with pytest.raises(ValueError):
        await plan_remix_script(_content(), scene_count=9)


async def test_plan_clamps_long_narrator_text(monkeypatch):
    long_text = " ".join(f"word{i}" for i in range(60))  # 60 words, over the vi limit of 22
    caller = AsyncMock(return_value=_plan_json(narrator=long_text))
    monkeypatch.setattr(remix_plan.ai_tasks, "complete", caller)

    plan = await plan_remix_script(_content(), language="vi", scene_count=4)
    for scene in plan["scenes"]:
        assert len(scene["narrator_text"].split()) <= 22


async def test_plan_trims_scenes_to_requested_count(monkeypatch):
    caller = AsyncMock(return_value=_plan_json())
    monkeypatch.setattr(remix_plan.ai_tasks, "complete", caller)

    plan = await plan_remix_script(_content(), scene_count=2)
    assert len(plan["scenes"]) == 2


async def test_plan_raises_on_bad_json(monkeypatch):
    caller = AsyncMock(return_value="not json {{{")
    monkeypatch.setattr(remix_plan.ai_tasks, "complete", caller)
    with pytest.raises(ValueError, match="không đúng định dạng"):
        await plan_remix_script(_content())


async def test_plan_raises_when_no_scenes(monkeypatch):
    caller = AsyncMock(return_value=json.dumps({"title": "x", "scenes": []}))
    monkeypatch.setattr(remix_plan.ai_tasks, "complete", caller)
    with pytest.raises(ValueError, match="không tạo được cảnh"):
        await plan_remix_script(_content())


def test_tones_have_vi_and_en_labels():
    assert set(TONES) == {"documentary", "storytelling", "humorous", "motivational", "news", "educational"}
    for meta in TONES.values():
        assert meta["vi"] and meta["en"] and meta["guidance"]


def test_recommended_materials_exist():
    from agent.materials import get_material
    for material_id in remix_plan.RECOMMENDED_MATERIALS:
        assert get_material(material_id), f"missing material: {material_id}"
    assert len(remix_plan.RECOMMENDED_MATERIALS) == 8
