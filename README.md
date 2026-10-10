# READBOOK

Bộ công cụ tách, trích xuất, dịch và chuyển đổi sách PDF/EPUB.

## Cấu trúc source

```text
main/
├── readbook/
│   ├── pipeline.py          # Pipeline dùng chung cho các PDF part
│   ├── pipeline_pdf.py      # Pipeline đầy đủ cho một sách PDF
│   ├── pipeline_epub.py     # Pipeline đầy đủ cho một sách EPUB
│   ├── en2vi.py             # Dịch TXT tiếng Anh sang Markdown tiếng Việt
│   ├── md2docx.py           # Chuyển Markdown sang DOCX
│   ├── pdf/
│   │   ├── pdf_split.py
│   │   └── book_pdf2text.py
│   ├── epub/
│   │   ├── epub_split.py
│   │   └── book_epub2text.py
│   └── utils/
│       ├── docx2pdf.py
│       └── merge_pdf.py
├── code/                    # Notebook/code minh họa
└── slide_create/            # Cấu hình tạo slide
```

## Chạy pipeline

Chạy các lệnh từ thư mục gốc của dự án:

```powershell
# Toàn bộ pipeline PDF
python main/readbook/pipeline_pdf.py -i data/ROOT/Ten_Sach.pdf

# Toàn bộ pipeline EPUB
python main/readbook/pipeline_epub.py -i data/ROOT/Ten_Sach.epub

# Xử lý một PDF hoặc thư mục PDF đã tách
python main/readbook/pipeline.py -i data/NHOM/Ten_Sach/part
```

Xem đầy đủ tham số của một lệnh bằng `--help`, ví dụ:

```powershell
python main/readbook/pipeline_pdf.py --help
```

## Quy ước đường dẫn

Các script xác định thư mục gốc dự án dựa trên vị trí của chính file Python, không
phụ thuộc thư mục hiện hành. Các tài nguyên mặc định vẫn ở vị trí cũ:

- `config/env.py`: cấu hình model Gemini.
- `config/env_split.py`: cấu hình tách PDF/EPUB và phân loại sách.
- `instruction/en2vi_prompt.md`: prompt dịch.
- `sample/sample.docx`: Word template.
- `data/`: dữ liệu nguồn và kết quả xử lý.
