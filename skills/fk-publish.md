# fk-publish — Post a Finished Video to Social Platforms

After a video is built and the user is happy with it, publish it to YouTube,
Facebook (Page), TikTok, and Instagram (Reels) from the Gallery page
("Đăng lên ↑" button on each finished video card) or via the API below.

Usage: `/fk-publish <video-id> --platforms youtube,tiktok --caption "..." [--public-url https://…]`

## Prerequisites (one-time per platform)

Each platform needs a developer app created by the user, with credentials in
env (`YOUTUBE_CLIENT_ID/SECRET`, `FACEBOOK_APP_ID/SECRET`,
`TIKTOK_CLIENT_KEY/SECRET`) and the redirect URI
`{PUBLISH_REDIRECT_BASE}/api/publish/callback/{platform}` registered.
Full setup guide: `docs/PUBLISH.md`.

If `GET /api/publish/platforms` shows `app_ready: false` for a platform,
stop and tell the user which env vars / app steps are missing (the
`setup_hint` field explains it) — do not attempt to publish there.

## Step 1: Check connections

```bash
curl -s http://127.0.0.1:8100/api/publish/platforms
```

For every platform the user wants: `connected` must be true. If not, tell the
user to open the dashboard Gallery → "Đăng lên ↑" → "Kết nối" (OAuth in a new
tab), then re-check. Never invent or paste tokens yourself.

## Step 2: Publish

```bash
curl -s -X POST http://127.0.0.1:8100/api/publish \
  -H "Content-Type: application/json" \
  -d '{"video_id":"<VID>","platforms":["youtube","tiktok"],
       "caption":"<caption>","title":"<youtube title>",
       "youtube_privacy":"unlisted","tiktok_privacy":"PUBLIC_TO_EVERYONE",
       "public_url":"https://… (only needed for Instagram)"}'
```

Notes:
- The video file is resolved from the assembled MP4 (`output/quick_videos/<vid>.mp4`,
  fallback: imported source). If the video has no MP4 yet, the API returns 400 —
  build it first.
- Instagram needs a **public** video URL (`public_url`); localhost files won't work.
- YouTube defaults to `unlisted`; TikTok to `PUBLIC_TO_EVERYONE`.

## Step 3: Watch the jobs

```bash
curl -s "http://127.0.0.1:8100/api/publish/jobs?video_id=<VID>"
```

Poll until every job is `DONE` or `FAILED`. On `DONE`, report the
`external_url` ("Xem bài đăng"). On `FAILED`, show the `error` and suggest the
fix (reconnect if the token expired, check `setup_hint` if the app isn't
configured). Jobs: `QUEUED → UPLOADING → PROCESSING → DONE/FAILED`.
