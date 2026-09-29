#!/usr/bin/env python3
"""Tách một PDF thành nhiều phần theo cấu hình env_split.py."""

from __future__ import annotations

import argparse
import os
import runpy
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

try:
    from PyPDF2 import PdfReader, PdfWriter
except ImportError as exc:
    PdfReader = None
    PdfWriter = None
    dep_err: Exception | None = exc
else:
    dep_err = None


class SplitError(RuntimeError):
    """Lỗi cấu hình hoặc tách PDF không an toàn."""


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def getRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = getRoot()
    parser = argparse.ArgumentParser(
        description="Tách PDF theo khoảng trang trong config/env_split.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "pdf_arg",
        nargs="?",
        type=Path,
        help="File PDF đầu vào (cách viết rút gọn thay cho -i).",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        help="File PDF cần tách.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="out_dir",
        type=Path,
        help="Thư mục output; mặc định là data/<nhóm>/<tên sách>/part/.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        default=root / "config" / "env_split.py",
        help="File chứa pdf_splits và classification.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè các file PDF phần đã tồn tại.",
    )
    return parser.parse_args(argv)


def getInput(args: argparse.Namespace) -> Path:
    if args.input_path and args.pdf_arg:
        raise SplitError("Chỉ truyền input một lần: dùng -i hoặc positional.")
    in_path = args.input_path or args.pdf_arg
    if in_path is None:
        raise SplitError("Thiếu file PDF đầu vào. Hãy dùng -i <file.pdf>.")
    in_path = in_path.expanduser().resolve()
    if not in_path.is_file():
        raise SplitError(f"Không tìm thấy file PDF: {in_path}")
    if in_path.suffix.lower() != ".pdf":
        raise SplitError(f"Input không phải file PDF: {in_path}")
    return in_path


def loadConfig(cfg_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg_path = cfg_path.expanduser().resolve()
    if not cfg_path.is_file():
        raise SplitError(f"Không tìm thấy config: {cfg_path}")
    try:
        cfg_data = runpy.run_path(str(cfg_path))
    except Exception as exc:
        raise SplitError(f"Không thể đọc config {cfg_path}: {exc}") from exc
    plans = cfg_data.get("pdf_splits")
    if not isinstance(plans, dict):
        raise SplitError("Config phải khai báo dictionary tên pdf_splits.")
    class_map = cfg_data.get("classification")
    if not isinstance(class_map, dict):
        raise SplitError("Config phải khai báo dictionary tên classification.")
    return plans, class_map


def checkName(raw_text: Any, label: str) -> str:
    if not isinstance(raw_text, str) or not raw_text:
        raise SplitError(f"{label} phải là chuỗi không rỗng.")
    if raw_text in {".", ".."} or any(char in '<>:"/\\|?*' for char in raw_text):
        raise SplitError(f"{label} không hợp lệ: {raw_text!r}")
    if raw_text.endswith((".", " ")):
        raise SplitError(f"{label} không được kết thúc bằng dấu chấm/cách.")
    return raw_text


def findClass(class_map: dict[str, Any], book_name: str) -> str:
    matches: list[str] = []
    near_names: list[str] = []
    for raw_key, names in class_map.items():
        class_key = checkName(raw_key, "Khóa classification")
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise SplitError(f"classification[{class_key!r}] phải là list tên sách.")
        if book_name in names:
            matches.append(class_key)
        near_names.extend(name for name in names if name.casefold() == book_name.casefold())
    if len(matches) > 1:
        keys = ", ".join(matches)
        raise SplitError(f"Tên sách {book_name!r} thuộc nhiều nhóm: {keys}")
    if matches:
        return matches[0]
    if near_names:
        expected = ", ".join(repr(name) for name in near_names)
        raise SplitError(
            f"Không khớp chính xác {book_name!r}; phép so sánh phân biệt hoa/thường. "
            f"Tên gần giống trong classification: {expected}"
        )
    raise SplitError(f"Không tìm thấy {book_name!r} trong classification.")


def getOutDir(
    out_arg: Path | None,
    in_path: Path,
    class_map: dict[str, Any],
    root: Path,
) -> Path:
    if out_arg is not None:
        return out_arg.expanduser().resolve()
    class_key = findClass(class_map, in_path.stem)
    return (root / "data" / class_key / in_path.stem / "part").resolve()


def pickPlan(
    plans: dict[str, Any], in_path: Path
) -> tuple[str, dict[str, tuple[int, int]]]:
    keys = (in_path.stem, in_path.name)
    for key in keys:
        plan = plans.get(key)
        if plan is not None:
            if not isinstance(plan, dict):
                raise SplitError(f"Cấu hình của {key!r} phải là dictionary.")
            return key, plan

    low_keys = {key.casefold() for key in keys}
    near_keys = [str(key) for key in plans if str(key).casefold() in low_keys]
    if near_keys:
        expected = ", ".join(repr(key) for key in near_keys)
        raise SplitError(
            f"Không khớp chính xác {in_path.stem!r} trong pdf_splits; "
            f"phép so sánh phân biệt hoa/thường. Tên gần giống: {expected}"
        )

    names = ", ".join(map(str, plans)) or "(trống)"
    raise SplitError(
        f"Không có cấu hình cho {in_path.stem!r}. Các tên hiện có: {names}"
    )


def cleanSuffix(raw_text: Any) -> str:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SplitError("Hậu tố phải là chuỗi không rỗng.")
    suffix = raw_text.strip()
    if any(char in '<>:"/\\|?*' for char in suffix):
        raise SplitError(f"Hậu tố chứa ký tự không hợp lệ: {suffix!r}")
    if suffix.endswith((".", " ")):
        raise SplitError(f"Hậu tố không được kết thúc bằng dấu chấm/cách: {suffix!r}")
    return suffix if suffix.startswith("_") else f"_{suffix}"


def checkPlans(
    plan: dict[str, Any], in_path: Path, out_dir: Path, page_total: int
) -> list[tuple[int, int, Path]]:
    if not plan:
        raise SplitError(f"Cấu hình tách của {in_path.stem!r} đang trống.")
    jobs: list[tuple[int, int, Path]] = []
    seen_paths: set[Path] = set()
    for raw_text, page_range in plan.items():
        suffix = cleanSuffix(raw_text)
        if (
            not isinstance(page_range, (tuple, list))
            or len(page_range) != 2
            or any(isinstance(val, bool) or not isinstance(val, int) for val in page_range)
        ):
            raise SplitError(f"Khoảng trang của {raw_text!r} phải là (start, end).")
        start_page, end_page = page_range
        if start_page < 1 or end_page < start_page or end_page > page_total:
            raise SplitError(
                f"Khoảng {raw_text!r}=({start_page}, {end_page}) không hợp lệ; "
                f"PDF có {page_total} trang."
            )
        out_path = (out_dir / f"{in_path.stem}{suffix}.pdf").resolve()
        if out_path == in_path:
            raise SplitError("Output không được trùng với PDF đầu vào.")
        if out_path in seen_paths:
            raise SplitError(f"Hai hậu tố tạo cùng output: {out_path.name}")
        seen_paths.add(out_path)
        jobs.append((start_page, end_page, out_path))
    return jobs


def writePart(
    reader: Any, start_page: int, end_page: int, out_path: Path
) -> None:
    writer = PdfWriter()
    for idx in range(start_page - 1, end_page):
        writer.add_page(reader.pages[idx])
    meta = reader.metadata
    if meta:
        clean_meta = {str(key): str(val) for key, val in meta.items() if val is not None}
        if clean_meta:
            writer.add_metadata(clean_meta)

    file_id, temp_raw = tempfile.mkstemp(
        prefix=f".{out_path.stem}_", suffix=".pdf", dir=str(out_path.parent)
    )
    os.close(file_id)
    temp_path = Path(temp_raw)
    try:
        with temp_path.open("wb") as out_file:
            writer.write(out_file)
        test_pdf = PdfReader(str(temp_path))
        if len(test_pdf.pages) != end_page - start_page + 1:
            raise SplitError(f"Kiểm tra output thất bại: {out_path.name}")
        temp_path.replace(out_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def runSplit(args: argparse.Namespace) -> list[Path]:
    if dep_err is not None or PdfReader is None:
        raise SplitError("Thiếu PyPDF2. Cài bằng: python -m pip install PyPDF2")
    in_path = getInput(args)
    plans, class_map = loadConfig(args.config_path)
    book_key, plan = pickPlan(plans, in_path)
    out_dir = getOutDir(args.out_dir, in_path, class_map, getRoot())
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        reader = PdfReader(str(in_path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise SplitError("PDF được bảo vệ bằng mật khẩu.")
        page_total = len(reader.pages)
    except SplitError:
        raise
    except Exception as exc:
        raise SplitError(f"Không thể đọc PDF {in_path}: {exc}") from exc

    jobs = checkPlans(plan, in_path, out_dir, page_total)
    old_files = [out_path for _, _, out_path in jobs if out_path.exists()]
    if old_files and not args.overwrite:
        names = ", ".join(path.name for path in old_files)
        raise SplitError(f"Output đã tồn tại: {names}. Dùng --overwrite để ghi đè.")

    print(f"Book: {book_key} | pages: {page_total} | parts: {len(jobs)}")
    outputs: list[Path] = []
    for idx, (start_page, end_page, out_path) in enumerate(jobs, start=1):
        print(
            f"[{idx}/{len(jobs)}] {start_page}-{end_page} "
            f"-> {out_path.name}"
        )
        try:
            writePart(reader, start_page, end_page, out_path)
        except Exception as exc:
            if isinstance(exc, SplitError):
                raise
            raise SplitError(f"Không thể tạo {out_path}: {exc}") from exc
        outputs.append(out_path)
    return outputs


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    try:
        args = parseArgs(argv)
        outputs = runSplit(args)
    except SplitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Completed: {len(outputs)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
