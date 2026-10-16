"""Remix-link API: paste a video/page link -> extract -> AI rewrite -> build MP4.

Three endpoints mirror the three pipeline steps, reusing the existing
generation queue (requests/batch), TTS narration, audio mix and assembly
services — no parallel pipeline, just a new automated entry point.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional

from agent.db import crud as db_crud
from agent.materials import get_material
from agent.services.flow_client import get_flow_client
from agent.services.link_extract import LinkContent, extract_link
from agent.services.remix_plan import TONES, plan_remix_script, rewrite_script, structure_script
from agent.api.requests import BatchRequestCreate, create_batch
from agent.models.request import RequestCreate
from agent.api.tts import narrate_video
from agent.models.tts import NarrateVideoRequest
from agent.services.audio_mix import AudioMixError, finish_audio_mix
from agent.services.video_assembly import assemble_video as assemble_video_service

router = APIRouter(prefix="/remix", tags=["remix"])
logger = logging.getLogger(__name__)


class ExtractRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class RewriteRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    tone: str = "storytelling"
    language: str = Field(default="vi", max_length=8)


class PlanRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    project_id: Optional[str] = None
    tone: str = "storytelling"
    language: str = Field(default="vi", max_length=8)
    material: str = "realistic"
    scene_count: int = Field(default=4, ge=1, le=8)
    orientation: Literal["VERTICAL", "HORIZONTAL"] = "VERTICAL"
    voice_template: Optional[str] = Field(default=None, max_length=64)
    script: Optional[str] = Field(default=None, max_length=8000,
        description="User-written script (e.g. from their own ChatGPT). When provided, "
                    "the AI only splits it into scenes without rewriting the voice.")


class BuildRequest(BaseModel):
    video_id: str
    project_id: str
    engine: Literal["omnivoice", "vieneu", "kokoro", "qwen3"] = "omnivoice"
    template: Optional[str] = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    preset_id: Optional[str] = None
    speed: float = Field(default=1.0, ge=0.5, le=3.0)
    music_filename: Optional[str] = None
    music_volume: float = Field(default=0.3, ge=0.0, le=1.0)
    burn_subtitles: bool = True


@router.get("/tones")
async def list_tones():
    """Rewrite tones for the UI picker."""
    return {
        tone_id: {"vi": meta["vi"], "en": meta["en"]}
        for tone_id, meta in TONES.items()
    }


@router.post("/extract")
async def extract(body: ExtractRequest):
    """Step 1 — pull public metadata (oEmbed / OpenGraph / captions) from a link."""
    try:
        content: LinkContent = await extract_link(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return content.to_dict()


@router.post("/rewrite")
async def rewrite(body: RewriteRequest):
    """Step 2a — AI rewrites the extracted content into a full script for the user to review/edit.

    Skip this entirely when the user pastes their own script (e.g. written with their own ChatGPT).
    """
    if body.tone not in TONES:
        raise HTTPException(400, f"Unknown tone: {body.tone}")
    try:
        content = await extract_link(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        script = await rewrite_script(content, tone=body.tone, language=body.language)
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"script": script, "tone": body.tone, "language": body.language,
            "source_title": content.title, "source_url": content.url}


@router.post("/plan", status_code=201)
async def plan(body: PlanRequest):
    """Step 2b/3 — split the script into scenes, create project/video and queue generation.

    Uses the user's own script when `script` is provided (only structured, never rewritten);
    otherwise AI-rewrites the source first (legacy one-shot behaviour).
    """
    if body.tone not in TONES:
        raise HTTPException(400, f"Unknown tone: {body.tone}")
    material = get_material(body.material)
    if not material:
        raise HTTPException(400, "Unknown visual style")
    if not get_flow_client().connected:
        raise HTTPException(503, "Flow extension is disconnected")

    try:
        content = await extract_link(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        if body.script and body.script.strip():
            plan = await structure_script(
                body.script,
                scene_count=body.scene_count,
                language=body.language,
                tone=body.tone,
                source_url=content.url,
                source_title=content.title,
            )
        else:
            plan = await plan_remix_script(
                content, tone=body.tone, language=body.language, scene_count=body.scene_count
            )
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc

    if body.project_id:
        project = await db_crud.get_project(body.project_id)
        if not project or project.get("status") != "ACTIVE":
            raise HTTPException(404, "Active project not found")
    else:
        project = await db_crud.create_project(
            name=(plan.get("title") or content.title or "Remix")[:72],
            description=f"Nguồn: {content.url}",
            language=body.language,
            material=body.material,
            allow_music=True,
            allow_voice=True,
        )

    existing = await db_crud.list_videos(project["id"])
    video = await db_crud.create_video(
        project_id=project["id"],
        title=(plan.get("title") or content.title or "Remix")[:72],
        description=f"Nguồn: {content.url}",
        display_order=max((v["display_order"] for v in existing), default=-1) + 1,
        orientation=body.orientation,
    )
    try:
        prefix = material.get("scene_prefix") or material["style_instruction"]
        total = len(plan["scenes"])
        for index, item in enumerate(plan["scenes"]):
            scene = await db_crud.create_scene(
                video_id=video["id"],
                display_order=index,
                prompt=item.get("action", "")[:1000],
                image_prompt=f"{prefix} {item.get('image_prompt', '')}"[:2000],
                video_prompt=item.get("video_prompt", "")[:2000],
                chain_type="ROOT",
                source="remix",
            )
            narrator = (item.get("narrator_text") or "").strip()
            if narrator:
                await db_crud.update_scene(scene["id"], narrator_text=narrator)

        queued = await create_batch(BatchRequestCreate(requests=[
            RequestCreate(
                type=req_type, project_id=project["id"], video_id=video["id"],
                scene_id=scene_id, orientation=body.orientation,
            )
            for req_type in ("GENERATE_IMAGE", "GENERATE_VIDEO_OMNI")
            for scene_id in [s["id"] for s in await db_crud.list_scenes(video["id"])]
        ]))
        await db_crud.update_video(video["id"], status="PROCESSING")
    except Exception:
        await db_crud.delete_video(video["id"])
        raise

    return {
        "project_id": project["id"],
        "video_id": video["id"],
        "plan": plan,
        "scene_count": total,
        "request_count": len(queued),
        "voice_template": body.voice_template,
    }


@router.post("/build")
async def build(body: BuildRequest):
    """Step 3 — TTS voiceover for every scene, mix narration + music + subtitles, assemble MP4."""
    video = await db_crud.get_video(body.video_id)
    if not video or video.get("project_id") != body.project_id:
        raise HTTPException(404, "Video not found in this project")
    scenes = await db_crud.list_scenes(body.video_id)
    if not scenes:
        raise HTTPException(404, "No scenes found for video")
    missing = [s["display_order"] for s in scenes if not (s.get("narrator_text") or "").strip()]
    if missing:
        raise HTTPException(409, f"Scenes {missing} have no narrator_text — run /api/remix/plan first")

    narration = await narrate_video(
        body.video_id,
        NarrateVideoRequest(
            project_id=body.project_id,
            engine=body.engine,
            template=body.template,
            preset_id=body.preset_id,
            orientation="VERTICAL" if (video.get("orientation") or "VERTICAL") == "VERTICAL" else "HORIZONTAL",
            speed=body.speed,
            mix=True,
        ),
    )
    if narration.scenes_narrated == 0:
        raise HTTPException(502, "TTS narration failed for every scene")

    mix_update: dict = {
        "narration": {
            "narration_volume": 1.0,
            "source_volume": 0.4,
            "burn_subtitles": body.burn_subtitles,
        }
    }
    if body.music_filename:
        mix_update["music"] = {"filename": body.music_filename, "volume": body.music_volume}
    try:
        mix_result = await finish_audio_mix(body.video_id, video.get("orientation"), mix_update)
    except AudioMixError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    try:
        assembled = await assemble_video_service(body.video_id, video.get("orientation"))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Video assembly failed: {exc}") from exc

    return {
        "video_id": body.video_id,
        "scenes_narrated": narration.scenes_narrated,
        "scenes_failed": narration.scenes_failed,
        "mix": mix_result,
        "assembled": assembled,
    }
