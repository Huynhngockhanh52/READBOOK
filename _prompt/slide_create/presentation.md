# BUILD POWERPOINT SLIDE CREATOR

## ROLE

Bạn là Senior Python Developer. Hãy xây dựng chương trình Python tạo file PowerPoint hoàn chỉnh từ file Markdown đã chứa cấu trúc từng slide.

File cần xây dựng:

`READBOOK/main/slide_create/slide_create.py`

Chương trình sử dụng:

- File PowerPoint mẫu: `READBOOK/sample/base_book.pptx`
- Cấu hình layout: `slide_create/conf/base_book.yaml`
- Nội dung bài thuyết trình: file Markdown được chỉ định qua input.

Không hard-code layout, placeholder hoặc cấu trúc slide vào source code.

## OBJECTIVE

Chương trình cần đọc file Markdown đã được chuẩn hóa theo cấu trúc:

```markdown
## SLIDE 1. Background

**Script:** Nội dung thuyết trình...

### TITLE

Tiêu đề

### TXT_CHAPTER

Nội dung
```

Sau đó:

- Copy `READBOOK/sample/base_book.pptx` thành file PowerPoint output được chỉ định.
- Dựa trên `layouts` trong `base_book.yaml` để xác định layout và placeholder hợp lệ.
- Tạo từng slide theo đúng layout được ghi trong Markdown.
- Đưa nội dung của từng `### PLACEHOLDER` vào đúng shape tương ứng.
- Đưa `**Script:**` vào Notes / Speaker Notes của đúng slide.
- Giữ nguyên thiết kế, theme, master, vị trí và style có sẵn trong file PowerPoint mẫu.

## CLI

Hỗ trợ:

```text
-i, --input       File Markdown chứa nội dung slide.
-o, --output      File hoặc thư mục PowerPoint output tùy chọn.
--overwrite       Cho phép ghi đè output đã tồn tại.
```

Nếu không có `-o`, output mặc định được tạo trong thư mục `pptx` cùng cấp với thư mục `section`.

Ví dụ:

```text
book/
├── section/
│   ├── chapter01_slide.md
│   └── chapter02_slide.md
└── pptx/
    ├── chapter01.pptx
    └── chapter02.pptx
```

Quy tắc tên mặc định:

`chapter01_slide.md → chapter01.pptx`

Nếu có `-o`, sử dụng đường dẫn output được chỉ định.

## RULES

### Rule 1 — Template và Output

Luôn sử dụng `READBOOK/sample/base_book.pptx` làm file PowerPoint gốc.

Không chỉnh sửa trực tiếp file mẫu. Trước khi tạo slide, phải copy file mẫu sang đường dẫn output rồi thực hiện các thay đổi trên bản copy.

Nếu không chỉ định `-o`, xác định thư mục `pptx` cùng cấp với `section` chứa file input và tự tạo thư mục nếu chưa tồn tại.

Nếu output đã tồn tại và không có `--overwrite`, không được ghi đè.

### Rule 2 — Layouts

Đọc `slide_create/conf/base_book.yaml` và sử dụng phần `layouts` làm quy định chính cho tên layout và placeholder.

Tên layout trong:

`## SLIDE N. <layout>`

phải tồn tại trong YAML và trong PowerPoint template.

Không tự đổi tên, suy đoán hoặc thay layout khác nếu layout được chỉ định không tồn tại.

### Rule 3 — Parse Markdown

Mỗi slide gồm:

- `## SLIDE N. <layout>`: số slide và layout.
- `**Script:**`: nội dung Speaker Notes.
- `### PLACEHOLDER`: nội dung cần đưa vào placeholder tương ứng.

Giữ đúng thứ tự slide trong Markdown.

`Script` phải được xử lý riêng, không xem là placeholder.

### Rule 4 — Placeholder Mapping

Mỗi placeholder được sử dụng trong Markdown phải có trong danh sách placeholder của layout tương ứng trong YAML và có shape tương ứng trong PowerPoint template.

Map nội dung theo đúng tên placeholder.

Không tự đưa nội dung sang placeholder khác nếu không tìm thấy tên tương ứng. Nếu có lỗi, báo rõ slide, layout và placeholder gây lỗi.

Không bắt buộc tất cả placeholder của layout phải có nội dung.

### Rule 5 — Nội dung và Formatting

Chỉ thay nội dung tại các placeholder được chỉ định; giữ nguyên thiết kế có sẵn của template.

Không tự thay đổi theme, font, màu sắc, kích thước hoặc vị trí shape nếu không cần thiết.

Với nội dung Markdown thông thường:

- Giữ paragraph và bullet cơ bản.
- Loại bỏ các ký hiệu Markdown chỉ dùng cho cấu trúc.
- Không tự tóm tắt, viết lại hoặc bổ sung nội dung.

Ưu tiên giữ formatting mặc định của placeholder trong PowerPoint.

### Rule 6 — Speaker Notes

Nội dung sau `**Script:**` phải được đưa vào Notes / Speaker Notes của đúng slide tương ứng.

Script không được hiển thị trên canvas của slide.

Nếu thư viện PowerPoint được sử dụng không hỗ trợ đầy đủ Speaker Notes trực tiếp, có thể xử lý phần cần thiết bằng OOXML nhưng phải bảo đảm file `.pptx` cuối cùng hợp lệ và mở bình thường trong Microsoft PowerPoint.

### Rule 7 — Validation

Trước khi lưu file cuối cùng, kiểm tra:

- Số slide và thứ tự slide hợp lệ.
- Layout tồn tại trong YAML và template.
- Placeholder thuộc đúng layout.
- Placeholder tương ứng tồn tại trong PowerPoint.
- Script được gắn đúng slide.

Không âm thầm bỏ qua lỗi và không tự sửa tên layout hoặc placeholder do Markdown cung cấp.

### Rule 8 — Code

Sử dụng `pathlib.Path`, `argparse`, YAML parser và thư viện PowerPoint phù hợp.

Ưu tiên `python-pptx`; có thể sử dụng OOXML khi cần cho Speaker Notes hoặc các tính năng `python-pptx` không hỗ trợ trực tiếp.

Function dùng camelCase, biến dùng snake_case.

Code phải chạy thực tế, rõ ràng và không viết pseudo-code.

## DELIVERABLE

Tạo hoàn chỉnh:

`READBOOK/main/slide_create/slide_create.py`

Luồng xử lý chính:

```text
section/chapter01_slide.md
          +
base_book.yaml
          +
READBOOK/sample/base_book.pptx
          ↓
Copy template
          ↓
Create slides by layout
          ↓
Placeholder → Slide content
Script → Speaker Notes
          ↓
pptx/chapter01.pptx
```

Mục tiêu cuối cùng là tạo file `.pptx` hoàn chỉnh trong thư mục `pptx` cùng cấp với `section`, không làm thay đổi thiết kế gốc ngoài việc thêm slide và điền nội dung vào đúng các vị trí đã quy định.