import argparse
import io
import sys
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image
from tqdm import tqdm


OCR_SCALE = 2
OCR_LANG = "eng"


def parseArgs():
    """Đọc tham số dòng lệnh."""
    p = argparse.ArgumentParser(
        description="Convert one PDF file or a directory of PDFs to text"
    )
    p.add_argument("pdf_arg", nargs="?", help="Path to a PDF file or directory")
    p.add_argument("-i", "--input", dest="input_path", help="Input path")
    p.add_argument(
        "-c", "--columns", type=int, default=1,
        help="Number of text columns (default: 1)"
    )
    p.add_argument(
        "-t", "--ocr", action="store_true",
        help="Use OCR mode (default: extract with pymupdf)"
    )
    p.add_argument(
        "-o", "--output", dest="output_path",
        help="Output file or directory"
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing output files"
    )
    return p.parse_args()


def checkArgs(args):
    """Kiểm tra tham số hợp lệ."""
    if args.input_path and args.pdf_arg:
        print("Error: Specify the input once, using -i or positional form")
        sys.exit(1)
    raw_path = args.input_path or args.pdf_arg
    if not raw_path:
        print("Error: An input PDF file or directory is required")
        sys.exit(1)
    in_path = Path(raw_path)
    if not in_path.exists():
        print(f"Error: Input not found: {in_path}")
        sys.exit(1)
    if in_path.is_file() and in_path.suffix.lower() != ".pdf":
        print("Error: Input file must be a .pdf file")
        sys.exit(1)
    if args.columns < 1:
        print("Error: Number of columns must be greater than zero")
        sys.exit(1)
    return in_path


def findPdfs(in_path):
    """Tìm PDF trong input file hoặc thư mục."""
    if in_path.is_file():
        return [in_path]
    pdfs = []
    for path in in_path.rglob("*.pdf"):
        if "out" not in path.relative_to(in_path).parts:
            pdfs.append(path)
    return sorted(pdfs)


def getOutPath(pdf_path, in_path, out_arg):
    """Tạo output theo -o hoặc quy tắc mặc định."""
    if not out_arg:
        return pdf_path.parent / "text" / f"{pdf_path.stem}_text.txt"

    out_path = Path(out_arg)
    if in_path.is_file():
        if out_path.suffix.lower() == ".txt":
            return out_path
        return out_path / f"{pdf_path.stem}_text.txt"

    rel_dir = pdf_path.parent.relative_to(in_path)
    return out_path / rel_dir / f"{pdf_path.stem}_text.txt"


def extractPage(page, num_col, use_ocr):
    """Trích xuất một trang theo chế độ."""
    if use_ocr:
        return ocrPage(page)
    return extractBlocks(page, num_col)


def ocrPage(page):
    """Nhận dạng trang bằng OCR."""
    mat = pymupdf.Matrix(OCR_SCALE, OCR_SCALE)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang=OCR_LANG).strip()


def extractBlocks(page, num_col):
    """Trích xuất theo block và thứ tự cột."""
    blocks = page.get_text("blocks")
    texts = sortBlocks(blocks, num_col, page.rect.width)
    return "\n".join(texts).strip()


def sortBlocks(blocks, num_col, width):
    """Sắp xếp block theo thứ tự đọc."""
    cols = [[] for _ in range(num_col)]
    col_w = width / num_col
    for block in blocks:
        x0, y0, _, _, text = block[:5]
        if not text.strip():
            continue
        col = min(int(x0 / col_w), num_col - 1)
        cols[col].append((x0, y0, text))
    ordered = []
    for col in cols:
        col.sort(key=lambda x: (x[1], x[0]))
        ordered.extend(item[2] for item in col)
    return ordered


def processPdf(pdf_path, in_path, out_arg, use_ocr, num_col, overwrite):
    """Xử lý một file PDF và ghi output."""
    out_path = getOutPath(pdf_path, in_path, out_arg)
    if out_path.exists() and not overwrite:
        return None, out_path
    text_parts = []
    with pymupdf.open(pdf_path) as doc:
        for page in tqdm(doc, desc=pdf_path.name, unit="page", leave=False):
            text_parts.append(extractPage(page, num_col, use_ocr))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(text_parts), encoding="utf-8")
    return out_path, out_path


def main():
    """Điều phối xử lý file hoặc thư mục PDF."""
    args = parseArgs()
    in_path = checkArgs(args)
    pdfs = findPdfs(in_path)
    if not pdfs:
        print(f"No PDF files found in: {in_path}")
        return 1

    mode = "OCR" if args.ocr else "pymupdf"
    print(f"Input: {in_path}")
    print(f"PDF files: {len(pdfs)}")
    print(f"Number of columns: {args.columns}")
    print(f"Extraction mode: {mode}")
    print("Output: default or -o path")
    print(f"Overwrite: {'yes' if args.overwrite else 'no'}")

    failed = []
    skipped = 0
    for pdf_path in tqdm(pdfs, desc="PDF files", unit="file"):
        try:
            out_path, target = processPdf(
                pdf_path, in_path, args.output_path,
                args.ocr, args.columns, args.overwrite
            )
            if out_path is None:
                skipped += 1
                tqdm.write(f"Skipped (output exists): {target}")
            else:
                tqdm.write(f"Saved: {out_path}")
        except Exception as err:
            failed.append((pdf_path, err))
            tqdm.write(f"Error: {pdf_path} - {err}")

    if skipped:
        print(f"Skipped: {skipped} file(s)")
    if failed:
        print(f"Completed with errors: {len(failed)}/{len(pdfs)} files failed")
        return 1
    print(f"Completed: {len(pdfs)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
