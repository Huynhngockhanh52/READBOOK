# READBOOK

Bộ công cụ tách, trích xuất, dịch và chuyển đổi sách PDF/EPUB sang DOCX, kèm pipeline tạo slide PowerPoint.

## 1. Cài đặt

```bash
# Python 3.10+
python -m venv interpreter
.\interpreter\Scripts\activate
pip install -r interpreter/requirements.txt
```

### Dependencies chính
| Gói | Dùng cho |
|-----|----------|
| `PyPDF2`, `pymupdf`, `pdfplumber` | Trích xuất PDF |
| `lxml` | Parse EPUB/XHTML |
| `mistune`, `python-docx` | Markdown → DOCX |
| `google-genai` | Backend Gemini |
| `pytesseract`, `Pillow` | OCR (cần Tesseract cài hệ thống) |

### Cấu hình API (Gemini)
Tạo file `config/env.py`:
```python
API_GEMINI_KEY = "your-gemini-api-key"
MODEL_31_PRE = "gemini-1.5-pro"
# hoặc
MODEL_35 = "gemini-1.5-flash"
```

---

## 2. Cấu trúc thư mục

```
E:\NKT01_PhD\workspace\SP\READBOOK
├── config/
│   ├── env.py              # API key, model Gemini
│   └── env_split.py        # pdf_splits, epub_splits, classification
├── instruction/
│   ├── en2vi_prompt.md     # Prompt dịch Anh → Việt
│   ├── summary_chapter.md  # Prompt tóm tắt chương
│   └── sum2slide.md        # Prompt tạo slide
├── sample/
│   ├── sample.docx         # Word template (style: Heading 1, KC H2, KC H3, KC H4, KC NORMAL, KC DEF, Command)
│   ├── base_book.pptx      # Template PowerPoint
│   ├── base_book2.pptx
│   └── base_book3.pptx
├── data/
│   ├── ROOT/               # Đặt sách gốc (.pdf/.epub) ở đây
│   └── <NHÓM>/             # Tự động tạo theo classification
│       └── <TÊN_SÁCH>/
│           ├── part/       # PDF/XHTML đã tách theo chương
│           ├── text/       # TXT có cấu trúc Markdown (có separator =========)
│           ├── tran/       # Markdown tiếng Việt đã dịch
│           ├── docx/       # DOCX cuối cùng
│           ├── done/       # DOCX đã duyệt (cho pipeline slide)
│           ├── slide/
│           │   ├── md/     # Markdown từ DOCX
│           │   ├── sum/    # Tóm tắt chương
│           │   ├── section/# Slide markdown
│           │   └── pptx/   # PowerPoint output
│           └── manifest.json
├── main/
│   ├── readbook/
│   │   ├── pipeline.py         # PDF part → TXT → VI MD → DOCX
│   │   ├── pipeline_pdf.py     # PDF gốc → đầy đủ pipeline
│   │   ├── pipeline_epub.py    # EPUB gốc → đầy đủ pipeline
│   │   ├── en2vi.py            # Dịch TXT → VI Markdown (5 backend)
│   │   ├── md2docx.py          # Markdown → DOCX (theo template)
│   │   ├── pdf/
│   │   │   ├── pdf_split.py    # Tách PDF theo trang
│   │   │   └── book_pdf2text.py# PDF → TXT (1/2 cột, OCR)
│   │   ├── epub/
│   │   │   ├── epub_split.py   # Tách EPUB theo spine item
│   │   │   └── book_epub2text.py# XHTML → TXT
│   │   └── utils/
│   │       ├── docx2pdf.py     # DOCX → PDF (giữ thứ tự chapter)
│   │       └── merge_pdf.py    # Ghép PDF chapter
│   ├── slide_create/
│   │   ├── pipeline.py         # DOCX → MD → Summary → Slide MD → PPTX
│   │   ├── summary.py          # Tóm tắt chương
│   │   ├── sum2slide.py        # Tóm tắt → Slide markdown
│   │   ├── slide_create.py     # Slide markdown → PPTX
│   │   └── utils/docx2md.py    # DOCX → Markdown
│   └── book_task.py            # Điều phối tự động (tự hẹn chạy lại khi quota hết)
└── interpreter/                # Virtualenv
```

---

## 3. Cấu hình `config/env_split.py`

### 3.1 `pdf_splits` — tách PDF theo trang
```python
pdf_splits = {
    "Ten_Sach": {
        "_preface": (1, 10),
        "_ch01": (11, 35),
        "_ch02": (36, 60),
    },
}
```
* Key = hậu tố file output (`Ten_Sach_ch01.pdf`)
* Value = tuple `(start_page, end_page)` 1-based, inclusive

### 3.2 `epub_splits` — tách EPUB theo spine item
```python
epub_splits = {
    "Ten_Sach": {
        "01": 5,    # spine item 5
        "02": 6,    # spine item 6
        "03": (7, 9), # spine item 7-9
    },
}
```
* Spine item = vị trí trong OPF spine, không phải số trang hiển thị
* Chạy `--list-spine` để xem mapping

### 3.3 `classification` — nhóm thư mục (hỗ trợ lồng nhau)
```python
classification = {
    "LLM": {
        "PROMPT": ["Prompt_Engineering_for_LLM"],
        "CONTEXT": ["Context_Engineering_v1", "Context_Engineering_with_DSPy"],
    },
    "AI_AGENT": ["Agentic_Engineering"],
    "PROGRAMMING": ["Full-Stack_Web_Development_ASP.NET", "TryHackMe"],
}
```
* `dict` = nhóm trung gian (tạo thư mục con)
* `list[str]` = lá (tên sách)
* Kết quả: `data/LLM/PROMPT/Prompt_Engineering_for_LLM/part/...`

---

## 4. Chạy pipeline

### 4.1 PDF sách gốc → DOCX
```bash
# Toàn bộ pipeline tự động
python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf

# Chỉ định model dịch (mặc định: codex)
python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf -m gemini

# Ghi đè output đã có
python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf --overwrite

# Tùy chỉnh số cột / OCR
python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf -c 2 --ocr
```

### 4.2 EPUB sách gốc → DOCX
```bash
python main/readbook/pipeline_epub.py -i data/ROOT/Ten_Sach.epub
python main/readbook/pipeline_epub.py -i data/ROOT/Ten_Sach.epub -m claude
python main/readbook/pipeline_epub.py -i data/ROOT/Ten_Sach.epub --overwrite

# Chỉ xem spine (không ghi file)
python main/readbook/epub/epub_split.py --list-spine -i data/ROOT/Ten_Sach.epub
```

### 4.3 Chạy từng giai đoạn (PDF đã tách sẵn)
```bash
# part/ → text/ → tran/ → docx/
python main/readbook/pipeline.py -i data/NHOM/Ten_Sach/part -m gemini
```

### 4.4 Tạo slide từ DOCX đã duyệt
```bash
# Yêu cầu: copy DOCX hoàn chỉnh vào <work_dir>/done/
python main/slide_create/pipeline.py -i data/NHOM/Ten_Sach/done -m codex
```

### 4.5 Điều phối tự động (book_task.py)
Tự chạy PDF/EPUB → DOCX → chờ duyệt → slide, tự hẹn Task Scheduler khi quota hết.

```bash
python main/book_task.py -i data/ROOT/Ten_Sach.pdf -t pdf -m codex
python main/book_task.py -i data/ROOT/Ten_Sach.epub -t epub -m claude

# Bỏ qua bước duyệt thủ công (tự copy docx/ → done/)
python main/book_task.py -i data/ROOT/Ten_Sach.pdf -t pdf --non-check
```

---

## 5. Backend dịch (`en2vi.py`)

| Model | Mô tả |
|-------|-------|
| `gemini` | Google Gemini chat (stateful, cần `config/env.py`) |
| `codex` | Codex CLI hội thoại (stateful) |
| `claude` | Claude Code hội thoại (stateful) |
| `non-codex` | Codex `exec` stateless |
| `non-claude` | Claude `-p` stateless |

Mặc định: `codex`. Đổi bằng `-m`.

---

## 6. Quy trình làm việc khuyến nghị

```
1. Đặt sách gốc vào data/ROOT/
2. Cập nhật config/env_split.py (pdf_splits hoặc epub_splits, classification)
3. Chạy pipeline đầy đủ:
   python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf
4. Kiểm tra DOCX ở data/NHOM/Ten_Sach/docx/
5. Sửa lỗi dịch thuật nếu cần → copy file hoàn chỉnh vào data/NHOM/Ten_Sach/done/
6. Tạo slide:
   python main/slide_create/pipeline.py -i data/NHOM/Ten_Sach/done
7. Kết quả PPTX ở data/NHOM/Ten_Sach/slide/pptx/
```

---

## 7. Tham số thường dùng

| Script | Tham số hay dùng |
|--------|------------------|
| `pipeline_pdf.py` | `-i`, `-o`, `-m`, `-c`, `--ocr`, `--overwrite`, `--limit`, `--template` |
| `pipeline_epub.py` | `-i`, `-o`, `-m`, `--overwrite`, `--split-config` |
| `pipeline.py` | `-i`, `-o`, `-m`, `--overwrite`, `--limit`, `--template` |
| `en2vi.py` | `-i` (file/dir), `-o`, `-m`, `--overwrite`, `--limit`, `--dry-run`, `-v` |
| `pdf_split.py` | `-i`, `-o`, `--config`, `--overwrite`, `--list-spine` (chỉ EPUB) |
| `book_pdf2text.py` | `-i`, `-o`, `-c`, `--ocr`, `--overwrite` |
| `slide_create/pipeline.py` | `-i` (done/ dir), `-m`, `--overwrite` |
| `book_task.py` | `-i`, `-t pdf|epub`, `-m`, `-o`, `--non-check`, `--overwrite` |

Xem đầy đủ: `<script> --help`

---

## 8. Xử lý sự cố

| Vấn đề | Giải pháp |
|--------|-----------|
| `Thiếu PyPDF2` | `pip install PyPDF2` |
| `Thiếu lxml` | `pip install lxml` |
| `Không tìm thấy classification` | Thêm sách vào `config/env_split.py` |
| `Output đã tồn tại` | Dùng `--overwrite` hoặc xóa thư mục output cũ |
| `Gemini quota exceeded` | Chạy `book_task.py` (tự hẹn chạy lại) hoặc đổi model `-m codex` |
| `OCR không chạy` | Cài Tesseract hệ thống, `pip install pytesseract pillow` |
| `Style DOCX bị lỗi` | Đảm bảo `sample/sample.docx` có style: Heading 1, KC H2, KC H3, KC H4, KC NORMAL, KC DEF, Command |

---

## 9. Tích hợp Notion (MCP)

Dự án cấu hình MCP server `notionApi` trong `.claude/mcp.json` / `config/mcp.json`. Dùng để ghi log tiến độ, note nghiên cứu.

---

## 10. License

Nghiên cứu nội bộ — không phân phối.