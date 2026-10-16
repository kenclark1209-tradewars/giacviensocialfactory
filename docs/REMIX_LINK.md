# Remix từ link (Remix Link)

Dán một link video (YouTube / TikTok / Reels) hoặc bài viết web → FrameWeaver
tự động bóc tách nội dung gốc, viết lại thành kịch bản mới theo giọng điệu bạn
chọn, dựng 4 cảnh hoạt hình, lồng giọng đọc AI, ghép nhạc và in phụ đề → file
MP4 hoàn chỉnh.

> Không tải video gốc về: pipeline chỉ đọc metadata công khai (tiêu đề, mô tả,
> phụ đề/captions) rồi **viết lại** thành nội dung mới của bạn.

## 3 bước tự động (+ kịch bản của bạn)

```
[Dán link] ──► [1. Bóc tách] oEmbed + OpenGraph + phụ đề video
                    │
                    ▼
             [2. Kịch bản] DÁN kịch bản bạn viết bằng ChatGPT của mình
                    │      (theo phong cách của bạn — AI chỉ chia cảnh, KHÔNG viết lại)
                    │      …hoặc bấm "Nhờ AI soạn hộ" rồi sửa
                    ▼
             [3. Phân cảnh] chia kịch bản thành 4 cảnh: action + prompt ảnh/video + lời dẫn
                    │         → tự tạo project/video, xếp hàng tạo ảnh + clip
                    ▼
             [4. Dựng MP4] voiceover TTS từng cảnh + ghép nhạc + in phụ đề + nối thành MP4
```

## Dùng trên dashboard

Trang chủ → thẻ **"Remix từ link"**:

1. Dán link → **Lấy nội dung** → xem trước tiêu đề/tác giả/thumbnail.
2. **Kịch bản**: dán kịch bản bạn đã viết bằng ChatGPT (giữ nguyên phong cách của bạn),
   hoặc bấm **Nhờ AI soạn hộ** để có bản nháp rồi sửa.
3. Chọn phong cách hoạt hình (8 phong cách gợi ý đánh dấu ★), giọng đọc AI, số cảnh, project, tỷ lệ khung hình.
4. **Phân cảnh & tạo video** → xem phân cảnh ngay trong thẻ → **Mở pipeline** theo dõi tiến độ tạo ảnh/clip.
5. Khi các clip xong, chạy bước dựng MP4 (qua skill `/fk-remix-link` bước 5 hoặc Hậu kỳ).

## Dùng qua API / skill

Xem `skills/fk-remix-link.md`:

- `POST /api/remix/extract` — bóc tách link → metadata + captions.
- `POST /api/remix/rewrite` — AI soạn kịch bản đầy đủ để bạn sửa (bỏ qua nếu bạn đã có kịch bản riêng).
- `POST /api/remix/plan` — nhận `script` của bạn (chỉ chia cảnh, không viết lại) → tạo project/video/cảnh → xếp hàng tạo ảnh + video.
- `POST /api/remix/build` — TTS voiceover → ghép nhạc + phụ đề → dựng MP4.
- `GET /api/remix/tones` — danh sách 6 giọng điệu.

## Giới hạn

- Link ở chế độ riêng tư/đã xóa/trang chặn bot sẽ báo lỗi rõ ràng thay vì đoán nội dung.
- Phụ đề YouTube ưu tiên tiếng Việt, rồi tiếng Anh; video không có phụ đề vẫn viết lại được từ tiêu đề + mô tả.
- Lời dẫn mỗi cảnh bị giới hạn số từ để vừa ~6,5 giây audio (tiếng Việt: tối đa 22 từ).
- Tạo ảnh/clip vẫn dùng tín dụng Google Flow như pipeline thường.
