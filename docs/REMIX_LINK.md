# Remix từ link (Remix Link)

Dán một link video (YouTube / TikTok / Reels) hoặc bài viết web → FrameWeaver
tự động bóc tách nội dung gốc, viết lại thành kịch bản mới theo giọng điệu bạn
chọn, dựng 4 cảnh hoạt hình, lồng giọng đọc AI, ghép nhạc và in phụ đề → file
MP4 hoàn chỉnh.

> Không tải video gốc về: pipeline chỉ đọc metadata công khai (tiêu đề, mô tả,
> phụ đề/captions) rồi **viết lại** thành nội dung mới của bạn.

## 3 bước tự động

```
[Dán link] ──► [1. Bóc tách] oEmbed + OpenGraph + phụ đề video
                    │
                    ▼
             [2. Viết lại] chọn giọng điệu (6) + phong cách hoạt hình (8 gợi ý) + giọng đọc AI
                    │         → AI dựng kịch bản 4 cảnh: action + prompt ảnh/video + lời dẫn
                    │         → tự tạo project/video, xếp hàng tạo ảnh + clip
                    ▼
             [3. Dựng MP4] voiceover TTS từng cảnh + ghép nhạc + in phụ đề + nối thành MP4
```

## Dùng trên dashboard

Trang chủ → thẻ **"Remix từ link"**:

1. Dán link → **Lấy nội dung** → xem trước tiêu đề/tác giả/thumbnail.
2. Chọn giọng điệu viết lại (tài liệu, kể chuyện, hài hước, truyền cảm hứng, tin tức, giáo dục),
   phong cách hoạt hình (8 phong cách gợi ý đánh dấu ★), giọng đọc AI, số cảnh, project, tỷ lệ khung hình.
3. **Viết lại & tạo video** → chuyển sang màn hình pipeline theo dõi tiến độ tạo ảnh/clip.
4. Khi các clip xong, chạy bước dựng MP4 (qua skill `/fk-remix-link` bước 4 hoặc Hậu kỳ).

## Dùng qua API / skill

Xem `skills/fk-remix-link.md`:

- `POST /api/remix/extract` — bóc tách link → metadata + captions.
- `POST /api/remix/plan` — viết lại AI → tạo project/video/cảnh → xếp hàng tạo ảnh + video.
- `POST /api/remix/build` — TTS voiceover → ghép nhạc + phụ đề → dựng MP4.
- `GET /api/remix/tones` — danh sách 6 giọng điệu.

## Giới hạn

- Link ở chế độ riêng tư/đã xóa/trang chặn bot sẽ báo lỗi rõ ràng thay vì đoán nội dung.
- Phụ đề YouTube ưu tiên tiếng Việt, rồi tiếng Anh; video không có phụ đề vẫn viết lại được từ tiêu đề + mô tả.
- Lời dẫn mỗi cảnh bị giới hạn số từ để vừa ~6,5 giây audio (tiếng Việt: tối đa 22 từ).
- Tạo ảnh/clip vẫn dùng tín dụng Google Flow như pipeline thường.
