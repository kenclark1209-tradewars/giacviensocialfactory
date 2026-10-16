# fk-remix-link — Remix a Video from a Link

Turn a YouTube / TikTok / Reels / web link into an original rewritten video:
extract public metadata (oEmbed / OpenGraph / captions), get a script (yours or
AI-drafted), split it into scenes, generate clips, then build the final MP4 with
AI voiceover, music and burned-in subtitles.

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

## Step 2: Script — the user's own words come first

The user writes the script with **their own ChatGPT, in their own style**.
Two paths:

**A. User pastes their script** (preferred) — save it verbatim and go to step 3.
The AI will only *split* it into scenes; it never rewrites the user's voice.

**B. AI drafts the script** — when the user has no script yet:

```bash
curl -s -X POST http://127.0.0.1:8100/api/remix/rewrite \
  -H "Content-Type: application/json" \
  -d '{"url":"<URL>","tone":"storytelling","language":"vi"}'
# Returns: {"script": "...", ...}
```

Show the draft to the user for editing before continuing.

## Step 3: Scene breakdown + queue generation (plan)

```bash
curl -s -X POST http://127.0.0.1:8100/api/remix/plan \
  -H "Content-Type: application/json" \
  -d '{"url":"<URL>","script":"<USER SCRIPT OR AI DRAFT>","tone":"storytelling","language":"vi","material":"ghibli","scene_count":4,"orientation":"VERTICAL","voice_template":"<name-or-null>"}'
# Returns: {"project_id": "...", "video_id": "...", "plan": {"title": "...", "scenes": [...], "script_source": "user|ai"}, ...}
```

- With `script`: the AI only structures it into scenes (action + image/video prompts),
  keeping the user's narrator wording; `script_source` is `"user"`.
- Without `script`: one-shot AI rewrite + structuring (`script_source` is `"ai"`).

This creates the project (unless `--project` given), the video, and the scenes with
`narrator_text` already filled, then queues `GENERATE_IMAGE` + `GENERATE_VIDEO_OMNI`
for every scene. Requires the Flow extension connected (`GET /health` →
`extension_connected: true`).

Show the user the scene breakdown (per-scene action + narrator text) and ask for
approval before generation burns credits if anything looks off — scenes can be
edited with `PATCH /api/scenes/{sid}` (see AGENTS.md rule 13) before generation.

## Step 4: Wait for generation

```bash
curl -s "http://127.0.0.1:8100/api/requests/batch-status?video_id=<VID>&type=GENERATE_VIDEO_OMNI"
# Poll until "done": true. Videos take 2-5 min each.
```

Optionally review: `/fk-review-video` (light mode) before finishing, same as the
standard pipeline.

## Step 5: Build the final MP4 (voiceover + music + subtitles)

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
  steps 1–3 in the UI (paste link → script box → scene breakdown); step 5 runs
  from here or Post-production.
