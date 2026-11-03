# EPUB Architecture — Kiến trúc file EPUB

Tài liệu tham khảo nội bộ cho pipeline `readbook/epub/`.

---

## 1. EPUB bản chất là gì?

**EPUB = file ZIP** chứa các tài nguyên web (XHTML, CSS, hình ảnh, font) + metadata (OPF, NCX/NAV).

```bash
$ unzip -l book.epub
mimetype
META-INF/container.xml
EPUB/content.opf          # Package document (metadata, manifest, spine)
EPUB/toc.ncx              # EPUB 2 TOC (tùy chọn)
EPUB/toc01.html           # EPUB 3 Navigation Document (properties="nav")
EPUB/ch01.html            # Content documents (XHTML)
EPUB/ch02.html
EPUB/epub.css
EPUB/assets/cover.png
...
```

---

## 2. Các file cốt lõi

### 2.1 `mimetype` (bắt buộc, không nén, offset 0)
```
application/epub+zip
```

### 2.2 `META-INF/container.xml`
Trỏ đến OPF rootfile:
```xml
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

### 2.3 `EPUB/content.opf` — **Package Document** (trái tim EPUB)

```xml
<package version="3.0" unique-identifier="pub-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">ISBN...</dc:identifier>
    <dc:title>Book Title</dc:title>
    <dc:language>en</dc:language>
    <dc:creator>Author</dc:creator>
    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>
  </metadata>

  <manifest>
    <!-- Mỗi item = một file trong zip -->
    <item id="nav" href="toc01.html" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="ch01.html" media-type="application/xhtml+xml"/>
    <item id="css" href="epub.css" media-type="text/css"/>
    <item id="cover-img" href="assets/cover.png" media-type="image/png"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>

  <spine toc="ncx">  <!-- toc = id của NCX item (EPUB 2) -->
    <itemref idref="cover" linear="no"/>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>

  <guide>  <!-- EPUB 2 landmarks, tùy chọn -->
    <reference href="cover.html" type="cover" title="Cover"/>
  </guide>
</package>
```

**3 thành phần quan trọng:**

| Section | Vai trò |
|---------|---------|
| `metadata` | Thông tin sách (title, author, language, identifier...) |
| `manifest` | **Danh sách tất cả file** trong EPUB — mỗi item có `id`, `href`, `media-type`, `properties` |
| `spine` | **Thứ tự đọc** — danh sách `itemref` trỏ đến `id` trong manifest |

---

## 3. Spine — Thứ tự đọc (Reading Order)

```xml
<spine toc="ncx" page-progression-direction="ltr">
  <itemref idref="cover" linear="no"/>
  <itemref idref="titlepage" linear="yes"/>
  <itemref idref="ch01" linear="yes"/>
  <itemref idref="ch02" linear="yes"/>
</spine>
```

* `idref` → trỏ đến `id` trong `<manifest>`
* `linear="yes"` = phần nội dung chính (chapter); `linear="no"` = phụ lục, bìa, copyright...
* **Spine index** (1-based) = vị trí trong danh sách `itemref` có `linear="yes"` — **đây là số dùng trong `epub_splits` config**.

---

## 4. Mục lục (TOC) — 2 chuẩn song hành

### 4.1 EPUB 2: `toc.ncx` (Navigation Control XML)
```xml
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="book-id"/></head>
  <docTitle><text>Book Title</text></docTitle>
  <navMap>
    <navPoint id="ch1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="ch01.html"/>
    </navPoint>
  </navMap>
</ncx>
```
* Media-type: `application/x-dtbncx+xml`
* Khai báo trong manifest như item bình thường
* Spine tham chiếu qua `toc="ncx-id"`

### 4.2 EPUB 3: Navigation Document (XHTML với `properties="nav"`)
```xml
<!-- toc01.html / toc1.html / nav.xhtml / bất kỳ tên gì -->
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Table of Contents</title></head>
  <body>
    <nav epub:type="toc">
      <ol>
        <li><a href="ch01.html">Chapter 1</a></li>
        <li><a href="ch02.html">Chapter 2</a></li>
      </ol>
    </nav>
    <nav epub:type="landmarks">
      <ol>
        <li><a href="cover.html" epub:type="cover">Cover</a></li>
      </ol>
    </nav>
  </body>
</html>
```
* Media-type: `application/xhtml+xml` (giống content document)
* **Quan trọng**: `properties="nav"` trong manifest → **EPUB reader biết đây là TOC**
* Có thể chứa nhiều `<nav>`: `toc`, `landmarks`, `page-list`, `loi` (list of illustrations)...

---

## 5. Tại sao tên file TOC khác nhau (`toc01.html` vs `toc1.html` vs `nav.xhtml`)?

**EPUB spec không quy định tên file** — chỉ yêu cầu:
1. File là XHTML hợp lệ
2. Manifest item có `properties="nav"`
3. Nội dung có `<nav epub:type="toc">`

Nhà xuất bản / công cụ xuất EPUB đặt tên tùy ý:
| Publisher / Tool | Tên file thường thấy |
|------------------|---------------------|
| O'Reilly | `toc01.html`, `toc02.html`... |
| KindleGen / Calibre | `toc.ncx` + `nav.xhtml` |
| Sigil | `toc.xhtml` |
| Pandoc | `toc.html` |
| Tự viết | `toc1.html`, `navigation.html`... |

**Code không nên hardcode tên file** — phải đọc từ manifest:

```python
# Đúng: tìm item có properties="nav"
for item in manifest_items.values():
    if "nav" in item.get("props", "").split():
        nav_href = item["href"]   # "toc01.html" HOẶC "toc1.html" HOẶC "nav.xhtml"
        break
```

---

## 6. Manifest item — Các thuộc tính quan trọng

| Thuộc tính | Ví dụ | Ý nghĩa |
|------------|-------|---------|
| `id` | `ch1` | ID nội bộ, dùng trong spine |
| `href` | `ch01.html` | Đường dẫn tương đối từ OPF |
| `media-type` | `application/xhtml+xml` | MIME type |
| `properties` | `nav` \| `cover-image` \| `svg` \| `mathml`... | Đặc tính đặc biệt |

`properties` có thể có nhiều giá trị cách nhau bởi dấu cách:
```xml
<item id="ch1" href="ch01.html" media-type="application/xhtml+xml" properties="mathml svg"/>
```

---

## 7. Content Documents (XHTML)

Mỗi chapter = một file XHTML:
```xml
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">
  <head>
    <title>Chapter 1</title>
    <link rel="stylesheet" href="epub.css" type="text/css"/>
  </head>
  <body epub:type="chapter">
    <h1>Chapter 1. Introduction</h1>
    <p>Content...</p>
  </body>
</html>
```

* Namespace XHTML bắt buộc
* `epub:type` trên `<body>` hoặc các element: `chapter`, `preface`, `appendix`, `bibliography`, `cover`, `titlepage`...
* CSS liên kết tương đối từ vị trí file XHTML

---

## 8. Luồng xử lý trong `epub_split.py`

```
1. Mở ZIP → đọc mimetype → kiểm tra "application/epub+zip"
2. Đọc META-INF/container.xml → lấy OPF path (EPUB/content.opf)
3. Parse OPF:
   - Metadata (title, creator, language, identifier)
   - Manifest → dict[id] = {id, href, path, media-type, props}
   - Spine → danh sách itemref (linear=yes/no, idref)
   - TOC id từ spine.toc
4. Xây dựng nav_map (TOC title cho từng spine item):
   a) Tìm manifest item có properties="nav" → đọc file đó (toc01.html/toc1.html/nav.xhtml)
      - Parse <nav epub:type="toc"> → map href -> title
      - NẾU LỖI (file thiếu, XML hỏng) → fallback
   b) Fallback: đọc NCX (toc.ncx) từ toc_id hoặc media-type
5. Ghép spine + nav_map → BookInfo(spine=[SpineItem(index, idref, href, media-type, props, linear, toc_title)])
6. epub_splits config: map key -> spine index (1-based) hoặc range (start, end)
7. Với mỗi part: merge các spine item XHTML thành một file XHTML output
8. Ghi manifest.json track tiến trình
```

---

## 9. `epub_splits` config — Ví dụ thực tế

Với spine output từ `--list-spine`:

```
[001] linear=yes  EPUB/cover.html              (no TOC title)
[002] linear=yes  EPUB/dedication01.html       (no TOC title)
[003] linear=yes  EPUB/titlepage01.html        (no TOC title)
[004] linear=yes  EPUB/copyright-page01.html   (no TOC title)
[005] linear=yes  EPUB/preface01.html          Preface
[006] linear=yes  EPUB/ch01.html               1. Introduction to Context Engineering
[007] linear=yes  EPUB/ch02.html               2. Introduction to DSPy
...
[016] linear=yes  EPUB/ch11.html               11. Optimizing Coding Agents
[017] linear=yes  EPUB/ix01.html               Index
[018] linear=yes  EPUB/colophon01.html         (no TOC title)
[019] linear=yes  EPUB/colophon02.html         (no TOC title)
```

Config:
```python
epub_splits = {
    "Context_Engineering_with_DSPy": {
        "preface": 5,              # spine item 5
        "01": 6,                   # spine item 6
        "02": 7,
        "03": 8,
        "04": 9,
        "05": 10,
        "06": 11,
        "07": 12,
        "08": 13,
        "09": 14,
        "10": 15,
        "11": 16,
        "backmatter": (17, 19),    # spine 17-19 (index, colophon)
    },
}
```

* Key = hậu tố output (`_preface.xhtml`, `_01.xhtml`, `_backmatter.xhtml`)
* Value = `int` (một spine item) hoặc `tuple(int, int)` (khoảng)

---

## 10. Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| `Không tìm thấy EPUB nav: EPUB/toc01.html` | Manifest khai báo `properties="nav"` trỏ file không có trong zip | Code đã fallback NCX; kiểm tra EPUB có bị corrupt |
| `Spine tham chiếu manifest id không tồn tại` | OPF spine `idref` không khớp manifest `id` | EPUB invalid; sửa OPF hoặc bỏ qua item |
| `XHTML không có body` | File content không phải XHTML chuẩn | Bỏ qua item (linear=no) |
| `EPUB mimetype không hợp lệ` | File zip không có mimetype hoặc sai nội dung | Không phải EPUB chuẩn |

---

## 11. Tham khảo spec

* [EPUB 3.3 Spec](https://www.w3.org/TR/epub-33/)
* [EPUB Publications 3.0](https://www.w3.org/TR/epub-publications-30/)
* [EPUB Content Documents 3.0](https://www.w3.org/TR/epub-contentdocs-30/)
* [EPUB OCF (Open Container Format)](https://www.w3.org/TR/epub-ocf3/)

---

## 12. Debug nhanh

```bash
# Xem cấu trúc ZIP
unzip -l book.epub

# Xem OPF
unzip -p book.epub EPUB/content.opf | xmllint --format -

# Xem NCX
unzip -p book.epub EPUB/toc.ncx | xmllint --format -

# Xem NAV document
unzip -p book.epub EPUB/toc01.html | xmllint --format -

# Chạy list-spine (pipeline readbook)
python main/readbook/epub/epub_split.py --list-spine -i data/ROOT/book.epub
```

---

*Tài liệu này mô tả kiến trúc EPUB liên quan đến pipeline `readbook/epub/`. Cập nhật khi gặp trường hợp mới.*