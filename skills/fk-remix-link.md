# fk-remix-link — Remix a Video from a Link

Turn a YouTube / TikTok / Reels / web link into an original rewritten video:
extract public metadata (oEmbed / OpenGraph / captions), AI-rewrite it into
scenes in your chosen tone and animation style, generate clips, then build the
final MP4 with AI voiceover, music and burned-in subtitles.

Usage: `/fk-remix-link <url> [--tone storytelling] [--style realistic] [--voice template-name] [--scenes 4] [--project <id>] [--orientation VERTICAL]`

Tones: `documentary` · `storytelling` · `humorous` · `motivational` · `news` · `educational`
Styles: any material id from `GET /api/materials` — the dashboard highlights 8 recommended ones (realistic, 3d_pixar, anime, ghibli, comic_book, watercolor, stickman_light, claymation).

The pipeline never downloads the source video — it rewrites the *ideas* into
original scenes, so the output is yours.

---

## Step 1: Extract

```bash
curl -s -X POST http://127.0.0.1:8100/api/remix/extract \
  -H "Content-Type: application/json" \
  -d '{"url":"<URL>"}'
```

Check the result: `title`, `author`, `description`, `captions` (preferred vi, then en).
If extraction fails (private/deleted/blocked page), stop and tell the user why —
do not guess the content.

## Step 2: Plan (extract → AI rewrite → queue generation)

```bash
curl -s -X POST http://127.0.0.1:8100/api/remix/plan \
  -H "Content-Type: application/json" \
  -d '{"url":"<URL>","tone":"storytelling","language":"vi","material":"ghibli","scene_count":4,"orientation":"VERTICAL","voice_template":"<name-or-null>"}'
# Returns: {"project_id": "...", "video_id": "...", "plan": {"title": "...", "scenes": [...]}, "request_count": N, "voice_template": "..."}
```

This creates the project (unless `--project` given), the video, and 4 scenes with
`narrator_text` already filled, then queues `GENERATE_IMAGE` + `GENERATE_VIDEO_OMNI`
for every scene. Requires the Flow extension connected (`GET /health` →
`extension_connected: true`).

Show the user the rewritten plan (title + per-scene action + narrator text) and
ask for approval before generation burns credits if the plan looks off — the
scenes can be edited with `PATCH /api/scenes/{sid}` before generation.

## Step 3: Wait for generation

```bash
curl -s "http://127.0.0.1:8100/api/requests/batch-status?video_id=<VID>&type=GENERATE_VIDEO_OMNI"
# Poll until "done": true. Videos take 2-5 min each.
```

Optionally review: `/fk-review-video` (light mode) before finishing, same as the
standard pipeline.

## Step 4: Build the final MP4 (voiceover + music + subtitles)

```bash
curl -s -X POST http://127.0.0.1:8100/api/remix/build \
  -H "Content-Type: application/json" \
  -d '{"video_id":"<VID>","project_id":"<PID>","template":"<voice-template>","music_filename":"<file-in-music-library>","music_volume":0.3,"burn_subtitles":true}'
# Returns: {"scenes_narrated": 4, "scenes_failed": 0, "mix": {...}, "assembled": {...}}
```

This runs TTS narration for every scene (using each scene's `narrator_text`),
mixes narration + optional background music, burns in subtitles, and assembles
the final MP4. `music_filename` must exist in the project's music library
(`GET /api/music`); omit it for voiceover-only.

## Notes

- Narrator text is clamped to fit ~6.5s of scene audio (vi: max 22 words).
- `voice_template` comes from `GET /api/tts/templates`; omit for the default voice.
- Every step is idempotent-safe: re-running plan creates a *new* video; build
  requires `narrator_text` on all scenes or it returns 409.
- Dashboard: the "Remix từ link / Remix from a link" card on the home page runs
  steps 1–2 in the UI; step 4 runs from here or Post-production.
