#!/usr/bin/env python3
"""Merge chapter PDFs in natural chapter order."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

try:
    from PyPDF2 import PdfMerger, PdfReader
except ImportError as exc:
    PdfMerger = None
    PdfReader = None
    DEPENDENCY_ERROR: Exception | None = exc
else:
    DEPENDENCY_ERROR = None


class MergeError(RuntimeError):
    """Raised when chapter PDFs cannot be merged safely."""


FRONT_MATTER = {
    "cover": 0,
    "title": 1,
    "copyright": 2,
    "dedication": 3,
    "foreword": 4,
    "preface": 5,
    "introduction": 6,
    "intro": 6,
}


def set_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def chapter_token(path: Path) -> str:
    """Extract ``chapter`` from ``<file_name>_<chapter>.pdf``."""
    if "_" not in path.stem:
        raise MergeError(
            f"Tên file không đúng dạng <file_name>_<chapter>.pdf: {path.name}"
        )
    token = path.stem.rsplit("_", 1)[1].strip().casefold()
    if not token:
        raise MergeError(f"Thiếu chapter trong tên file: {path.name}")
    return token


def chapter_id(path: Path, allow_front_matter: bool) -> tuple[int, int]:
    token = chapter_token(path)
    if allow_front_matter and token in FRONT_MATTER:
        return 0, FRONT_MATTER[token]
    if token.isdecimal():
        return 1, int(token)
    hint = " hoặc dùng --front-matter" if not allow_front_matter else ""
    raise MergeError(
        f"Chapter phải là số (ví dụ 00, 01, 02){hint}: {path.name}"
    )


def chapter_sort_key(path: Path, allow_front_matter: bool) -> tuple[int, int, str]:
    category, order = chapter_id(path, allow_front_matter)
    return category, order, path.name.casefold()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ghép các PDF theo hậu tố <chapter> ở cuối tên file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help=(
            "Thư mục chứa các file <file_name>_<chapter>.pdf "
            "(cách viết rút gọn thay cho -i)."
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        help="Thư mục PDF đầu vào; nếu bỏ trống thì dùng ./pdf_vi.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        help=(
            "File PDF kết quả; mặc định là <tên thư mục cha>_vi.pdf "
            "nằm cạnh thư mục input."
        ),
    )
    parser.add_argument(
        "--front-matter",
        action="store_true",
        help="Cho phép các hậu tố như cover, foreword, preface, intro trước chương số.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè file PDF kết quả nếu đã tồn tại.",
    )
    return parser.parse_args(argv)


def default_output(input_dir: Path) -> Path:
    book_name = input_dir.parent.name or "merged"
    return input_dir.parent / f"{book_name}_vi.pdf"


def collect_files(
    input_arg: Path,
    output_arg: Path | None,
    overwrite: bool,
    allow_front_matter: bool = False,
) -> tuple[list[Path], Path]:
    input_dir = input_arg.expanduser().resolve()
    if not input_dir.is_dir():
        raise MergeError(f"Không tìm thấy thư mục PDF: {input_dir}")

    output_path = (
        output_arg.expanduser().resolve()
        if output_arg is not None
        else default_output(input_dir)
    )
    if output_path.suffix.casefold() != ".pdf":
        raise MergeError(f"Output phải có đuôi .pdf: {output_path}")
    if output_path.exists() and output_path.is_dir():
        raise MergeError(f"Output đang là một thư mục: {output_path}")

    files = [
        path.resolve()
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.casefold() == ".pdf"
        and path.resolve() != output_path
    ]
    if not files:
        raise MergeError(f"Không có file .pdf trong: {input_dir}")

    chapters: dict[tuple[int, int], Path] = {}
    for path in files:
        chapter = chapter_id(path, allow_front_matter)
        if chapter in chapters:
            raise MergeError(
                f"Vị trí chapter bị trùng: {chapters[chapter].name}, {path.name}"
            )
        chapters[chapter] = path
    files.sort(key=lambda path: chapter_sort_key(path, allow_front_matter))

    if output_path in files:
        raise MergeError("File output không được đồng thời là một file đầu vào.")
    if output_path.exists() and not overwrite:
        raise MergeError(
            f"Output đã tồn tại: {output_path}. Dùng --overwrite để ghi đè."
        )
    return files, output_path


def check_readable_pdf(path: Path) -> int:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise MergeError(f"PDF có mật khẩu: {path}")
        return len(reader.pages)
    except MergeError:
        raise
    except Exception as exc:
        raise MergeError(f"Không thể đọc PDF {path}: {exc}") from exc


def merge_files(files: list[Path], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page_total = 0
    for path in files:
        page_total += check_readable_pdf(path)

    file_id, temp_raw = tempfile.mkstemp(
        prefix=f".{output_path.stem}_", suffix=".pdf", dir=str(output_path.parent)
    )
    os.close(file_id)
    temp_path = Path(temp_raw)
    merger = PdfMerger()
    try:
        for path in files:
            merger.append(str(path))
        with temp_path.open("wb") as output_file:
            merger.write(output_file)
        merger.close()

        merged_pages = check_readable_pdf(temp_path)
        if merged_pages != page_total:
            raise MergeError(
                f"Kiểm tra thất bại: cần {page_total} trang, nhận {merged_pages} trang."
            )
        temp_path.replace(output_path)
    except Exception:
        try:
            merger.close()
        finally:
            temp_path.unlink(missing_ok=True)
        raise
    return page_total


def run(args: argparse.Namespace) -> tuple[Path, int, int]:
    if DEPENDENCY_ERROR is not None or PdfMerger is None or PdfReader is None:
        raise MergeError("Thiếu PyPDF2. Cài bằng: python -m pip install PyPDF2")

    if args.input_dir is not None and args.input_path is not None:
        raise MergeError("Chỉ truyền input một lần: dùng -i hoặc positional.")
    input_dir = args.input_path or args.input_dir or Path("pdf_vi")
    files, output_path = collect_files(
        input_dir,
        args.output_path,
        args.overwrite,
        args.front_matter,
    )
    print(f"Input:  {files[0].parent}")
    print(f"Output: {output_path}")
    for index, path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] chapter={chapter_token(path)} | {path.name}")

    try:
        page_total = merge_files(files, output_path)
    except MergeError:
        raise
    except Exception as exc:
        raise MergeError(f"Không thể tạo {output_path}: {exc}") from exc
    return output_path, len(files), page_total


def main(argv: Sequence[str] | None = None) -> int:
    set_utf8()
    try:
        output_path, file_count, page_total = run(parse_args(argv))
    except MergeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Đã hủy.", file=sys.stderr)
        return 130
    print(f"Hoàn tất: {file_count} file, {page_total} trang -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
