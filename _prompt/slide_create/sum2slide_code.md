# BUILD SUMMARY TO SLIDE CLI

## ROLE

Bạn là Senior Python Developer. Hãy xây dựng chương trình Python chuyển các file Markdown đã được tóm tắt thành nội dung từng slide bằng Codex CLI hoặc Claude CLI ở chế độ non-interactive.

File cần xây dựng:

`READBOOK/main/slide_create/sum2slide.py`

Chương trình sử dụng cố định:

- Rule/layout: `slide_create/conf/base_book.yaml`
- Prompt chung: `READBOOK/instruction/sum2slide.md`

Không hard-code nội dung rule, layout hoặc prompt vào source code và không tạo đối số CLI để thay đổi hai đường dẫn này.

## OBJECTIVE

Chương trình nhận một file summary Markdown hoặc thư mục chứa các file summary, đọc danh sách layout từ `base_book.yaml`, kết hợp với `sum2slide.md`, sau đó gửi tới model để xây dựng nội dung từng slide.

Output của model có dạng:

```markdown
## SLIDE 1. Background

**Script:** Nội dung thuyết trình...

### TITLE

Tiêu đề

### TXT_CHAPTER

Nội dung
```

Trong đó:

- `SLIDE N` xác định thứ tự slide.
- Phần sau `SLIDE N.` là tên layout.
- `### ...` là các placeholder của layout.
- `**Script:**` là lời thuyết trình và được xem là Speaker Notes, không phải placeholder.

Trước khi lưu, chương trình phải parse và validate toàn bộ cấu trúc slide với `base_book.yaml`.

## CLI

Chỉ hỗ trợ các đối số:

```text
-i, --input       File summary .md hoặc thư mục chứa các file summary.
-o, --output      Đường dẫn output tùy chọn.
-m, --model       Backend sử dụng: codex hoặc claude.
--overwrite       Cho phép ghi đè output đã tồn tại.
```

Mặc định:

```text
-i       ./sum
-m       codex
```

Nếu không có `-o`, output mặc định là thư mục `section` cùng cấp với `sum`.

Ví dụ:

```text
book/
├── sum/
│   ├── chapter01_sum.md
│   └── chapter02_sum.md
└── section/
    ├── chapter01_slide.md
    └── chapter02_slide.md
```

## RULES

### Rule 1 — Input và Output

- Nếu input là file `.md`, chỉ xử lý file đó; nếu là thư mục, xử lý recursive toàn bộ file `.md`.
- Giữ cấu trúc thư mục tương đối khi xử lý batch.
- `chapter01_sum.md → chapter01_slide.md`; nếu input không có `_sum`, thêm `_slide` trước extension.
- Nếu output đã tồn tại và không có `--overwrite`, bỏ qua file.
- Nếu có `-o`, sử dụng đường dẫn output được chỉ định.

### Rule 2 — Rule, Prompt và Request

Luôn đọc cấu hình từ:

`slide_create/conf/base_book.yaml`

và prompt từ:

`READBOOK/instruction/sum2slide.md`

Đọc YAML bằng `PyYAML`, tối thiểu lấy phần `layouts`.

Request gửi tới model gồm:

```text
sum2slide prompt
+ layouts/rules cần thiết
+ summary Markdown
```

Không yêu cầu model tự truy cập các file cấu hình trên filesystem.

### Rule 3 — Layouts

Từ `base_book.yaml`, lấy danh sách các layout và placeholder tương ứng.

Ví dụ:

```yaml
layouts:
    Background:
        - TITLE
        - TXT_CHAPTER

    01.tbcontent:
        - TITLE
        - TXT1
        - TXT2

    02.h1:
        - TITLE
        - TXT
```

Danh sách này được dùng cho cả hai mục đích:

- Cung cấp cho model để lựa chọn layout phù hợp.
- Kiểm tra output của model trước khi lưu.

### Rule 4 — Parse cấu trúc slide

Parse output của model thành các slide riêng biệt.

Mỗi slide cần xác định được:

- Số thứ tự slide.
- Tên layout.
- Nội dung `Script`.
- Các placeholder và nội dung tương ứng.

Quy ước:

- `## SLIDE N. <layout>` bắt đầu một slide mới.
- `**Script:**` chứa Speaker Notes.
- `### PLACEHOLDER` bắt đầu nội dung của một placeholder.
- `Script` phải được lưu riêng, không đưa vào danh sách placeholder.
- Số slide phải liên tục và giữ đúng thứ tự.

### Rule 5 — Validate layout và placeholder

Trước khi lưu output, kiểm tra từng slide:

- Layout phải tồn tại trong `layouts`.
- Mọi `### PLACEHOLDER` phải thuộc layout tương ứng.
- Không cho phép model tự tạo layout hoặc placeholder mới.
- Không cho phép một placeholder xuất hiện nhiều lần trong cùng một slide.
- `Script` không được validate như placeholder.
- Không bắt buộc sử dụng toàn bộ placeholder của layout nếu rule không yêu cầu.

Ví dụ, nếu YAML có:

```yaml
02.h1:
    - TITLE
    - TXT
```

thì slide có thể sử dụng:

```markdown
## SLIDE 3. 02.h1

**Script:** ...

### TITLE

...

### TXT

...
```

Không hợp lệ nếu xuất hiện `TXT1`, `IMAGE1` hoặc placeholder khác không có trong `02.h1`.

Không tự sửa tên layout hoặc placeholder sai do model sinh ra; phải báo lỗi rõ ràng.

### Rule 6 — Script và Speaker Notes

`**Script:**` là lời thuyết trình tương ứng với từng slide.

Khi parse:

- Lưu riêng nội dung script dưới trường `script` hoặc `notes`.
- Không xem `Script` là placeholder.
- Không đưa Script vào nội dung hiển thị trên canvas của slide.
- Phải giữ đúng liên kết giữa Script và slide tương ứng.
- Nội dung Script sẽ được sử dụng ở bước tạo PowerPoint để đưa vào Notes / Speaker Notes của slide.

### Rule 7 — Non-interactive

Việc gọi Codex hoặc Claude phải:

- Sử dụng `subprocess`.
- Chạy ở chế độ non-interactive.
- Truyền toàn bộ request qua `stdin`.
- Với Codex, sử dụng cơ chế `codex exec ... -` để đọc prompt từ `stdin`.
- Không đưa prompt dài vào command-line argument.
- Nhận kết quả từ `stdout`.
- Sử dụng `stderr` cho lỗi hoặc diagnostic.
- Kiểm tra return code trước khi xử lý kết quả.

### Rule 8 — Giới hạn request

Mỗi request hoàn chỉnh bao gồm:

```text
prompt + layouts/rules + summary content
```

không được vượt quá 50.000 token.

Sử dụng ngưỡng an toàn khoảng 45.000 token hoặc khoảng 120.000 ký tự khi cần ước lượng bảo thủ.

Nếu vượt giới hạn:

- Ưu tiên chia summary theo Heading 2 (`##`).
- Giữ nguyên thứ tự nội dung.
- Xử lý từng phần lần lượt.
- Ghép output thành một file slide hoàn chỉnh.
- Đảm bảo số thứ tự `SLIDE N` liên tục sau khi ghép.

### Rule 9 — Validation và lỗi

Chỉ lưu file output khi toàn bộ slide đã parse và validate thành công.

Nếu không hợp lệ, phải báo rõ:

- File đang xử lý.
- Số slide.
- Layout.
- Placeholder hoặc cấu trúc gây lỗi.

Không lưu output chưa hoàn chỉnh nếu model hoặc một phần xử lý thất bại.

Khi chạy batch, lỗi của một file không nên làm dừng toàn bộ các file còn lại nếu có thể tiếp tục.

### Rule 10 — Code

- Sử dụng `pathlib.Path`, `argparse`, `subprocess`, `yaml`, UTF-8 và exception handling phù hợp.
- Function dùng camelCase, biến dùng snake_case.
- Tách riêng logic đọc config, xây dựng request, gọi model, parse output, validate và ghi file.
- Hai đường dẫn `base_book.yaml` và `sum2slide.md` được xác định từ cấu trúc project, không lấy từ CLI.
- Không đặt toàn bộ logic trong `main()`.
- Code phải chạy thực tế, không viết pseudo-code.

## DELIVERABLE

Tạo hoàn chỉnh:

`READBOOK/main/slide_create/sum2slide.py`

Bảo đảm luồng xử lý:

```text
Summary Markdown
      ↓
Prompt + layouts
      ↓
Codex / Claude
      ↓
Parse slide
      ↓
Validate layout + placeholders
      ↓
Slide content + Script/Notes
```

Mọi `Script` phải được giữ đúng theo slide tương ứng để sử dụng làm Speaker Notes khi tạo PowerPoint.