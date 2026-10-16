# Đăng video lên mạng xã hội (Social Publish)

Sau khi dựng xong video và xem ưng ý, bấm **"Đăng lên ↑"** trên thẻ video ở
trang Gallery để đăng tự động lên YouTube, Facebook, TikTok, Instagram.

## Cách hoạt động

1. Mỗi nền tảng cần một **developer app** do bạn tự tạo (một lần duy nhất).
   Điền client ID/secret vào env rồi restart backend (xem bên dưới).
2. Trong modal "Đăng video", bấm **Kết nối** ở từng nền tảng → đăng nhập và
   cấp quyền trong tab mới → quay lại bấm **Tải lại kết nối**.
3. Tick chọn nền tảng, viết caption, chọn chế độ riêng tư (YouTube/TikTok),
   bấm **Đăng lên**. Trạng thái từng nền tảng hiện ngay trong modal, kèm link
   bài đăng khi xong.

Token được lưu trong DB local (`publish_account`) và tự gia hạn khi hết hạn
(nếu nền tảng hỗ trợ refresh token).

## Setup từng nền tảng

Đặt các biến env trước khi chạy backend, ví dụ trong `~/.zshrc` hoặc file `.env`:

```bash
export PUBLISH_REDIRECT_BASE="http://127.0.0.1:8100"  # phải khớp redirect URI đã đăng ký
export YOUTUBE_CLIENT_ID="..."
export YOUTUBE_CLIENT_SECRET="..."
export FACEBOOK_APP_ID="..."
export FACEBOOK_APP_SECRET="..."
export TIKTOK_CLIENT_KEY="..."
export TIKTOK_CLIENT_SECRET="..."
```

Redirect URI cho từng nền tảng (đăng ký trong cấu hình app):

| Nền tảng  | Redirect URI |
|-----------|--------------|
| YouTube   | `{PUBLISH_REDIRECT_BASE}/api/publish/callback/youtube` |
| Facebook / Instagram | `{PUBLISH_REDIRECT_BASE}/api/publish/callback/facebook` |
| TikTok    | `{PUBLISH_REDIRECT_BASE}/api/publish/callback/tiktok` |

### YouTube

1. Google Cloud Console → tạo project → bật **YouTube Data API v3**.
2. Credentials → Create Credentials → OAuth client ID (Web application).
3. Thêm redirect URI ở bảng trên. Điền `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`.
4. Scope xin: `youtube.upload`. Video mặc định đăng ở chế độ **Unlisted**.

### Facebook (Page)

1. developers.facebook.com → tạo app → thêm quyền `pages_manage_posts`,
   `pages_read_engagement`.
2. Thêm redirect URI ở bảng trên. Điền `FACEBOOK_APP_ID` / `FACEBOOK_APP_SECRET`.
3. Khi kết nối, chọn **Page** muốn đăng. Lưu ý: API chỉ đăng được lên Page,
   không đăng lên trang cá nhân.

### Instagram (Reels)

1. Dùng chung app Facebook ở trên, thêm quyền `instagram_basic`,
   `instagram_content_publish` (cần duyệt app).
2. Tài khoản Instagram phải là **Business/Creator** và đã liên kết với Page.
3. **Quan trọng:** Meta tải video từ **URL công khai** — backend chạy localhost
   không đủ. Hãy upload file MP4 lên nơi công khai (Drive mở public, S3, …)
   rồi dán link vào ô "URL công khai của video" trong modal.

### TikTok

1. developers.tiktok.com → tạo app → xin duyệt **Content Posting API**
   (scope `video.upload`, `video.publish`; quá trình duyệt mất vài ngày).
2. Thêm redirect URI ở bảng trên. Điền `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`.
3. Video được upload trực tiếp từ file (FILE_UPLOAD) rồi TikTok xử lý ngầm —
   modal sẽ hiện "Đang xử lý…" cho tới khi xong.

## API

- `GET /api/publish/platforms` — danh sách nền tảng + trạng thái kết nối.
- `GET /api/publish/connect/{platform}` — lấy URL OAuth (mở tab mới).
- `GET /api/publish/callback/{platform}` — OAuth redirect (tự động).
- `DELETE /api/publish/accounts/{platform}` — ngắt kết nối.
- `POST /api/publish` — `{video_id, platforms[], caption, title?, youtube_privacy?, tiktok_privacy?, public_url?}`.
- `GET /api/publish/jobs?video_id=` — trạng thái các job đăng bài.

## Lưu ý

- Chưa cấu hình app (thiếu client ID/secret): modal hiện nút **Cách setup**
  với hướng dẫn ngay trong đó — kết nối sẽ báo lỗi cho tới khi bạn điền env.
- Token hết hạn không refresh được: modal báo "hãy kết nối lại".
- Mỗi lần đăng tạo một `publish_job`; xem lại lịch sử qua `GET /api/publish/jobs`.
