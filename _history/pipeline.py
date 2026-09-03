#!/usr/bin/env python3
"""Run the PDF -> TXT -> Vietnamese Markdown -> DOCX pipeline."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


block_sep = "=========="
block_re = re.compile(r"(?m)^\s*={10,}\s*$")
para_re = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)+")
model_opts = ("gemini", "codex", "claude", "non-codex", "non-claude")
char_limit = 50_000


class PipeError(RuntimeError):
    """Raised when a pipeline step cannot finish safely."""


def getRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = getRoot()
    parser = argparse.ArgumentParser(
        description="Pipeline: PDF -> TXT -> chia block -> dịch VI -> DOCX.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        required=True,
        help="Một file PDF hoặc thư mục chứa PDF.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="work_dir",
        type=Path,
        help="Thư mục gốc chứa text/, tran/ và docx/.",
    )
    parser.add_argument(
        "-m",
        "--model",
        choices=model_opts,
        default="codex",
        help="Backend dịch thuật của en2vi.py.",
    )
    parser.add_argument(
        "-c",
        "--columns",
        type=int,
        default=1,
        help="Số cột văn bản trong PDF.",
    )
    parser.add_argument(
        "-t",
        "--ocr",
        action="store_true",
        help="Dùng OCR khi chuyển PDF sang TXT.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Tạo lại output đã tồn tại ở cả ba công đoạn.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=char_limit,
        help="Giới hạn ký tự cho block và translation session.",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=root / "instruction" / "en2vi_prompt.md",
        help="Prompt dùng cho bước dịch.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "env.py",
        help="Cấu hình Gemini.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=root / "sample" / "sample.docx",
        help="Word template dùng cho DOCX.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=5,
        help="Số request tối đa trước khi reset Gemini chat.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Số giây chờ trước Gemini request.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1_800,
        help="Timeout cho mỗi request dịch.",
    )
    return parser.parse_args(argv)


def getInput(path: Path) -> Path:
    in_path = path.expanduser().resolve()
    if not in_path.exists():
        raise PipeError(f"Input không tồn tại: {in_path}")
    if in_path.is_file() and in_path.suffix.lower() != ".pdf":
        raise PipeError(f"Input phải là file PDF hoặc thư mục: {in_path}")
    if not in_path.is_file() and not in_path.is_dir():
        raise PipeError(f"Input không hợp lệ: {in_path}")
    return in_path


def getWorkDir(in_path: Path, out_arg: Path | None) -> Path:
    if out_arg is not None:
        work_dir = out_arg.expanduser().resolve()
    elif in_path.is_file():
        work_dir = in_path.parent
    else:
        work_dir = in_path
    if work_dir.exists() and not work_dir.is_dir():
        raise PipeError(f"Output root phải là thư mục: {work_dir}")
    return work_dir


def runCmd(args: list[str], label: str, root: Path) -> None:
    print(f"\n=== {label} ===", flush=True)
    try:
        result = subprocess.run(args, cwd=str(root), check=False)
    except OSError as exc:
        raise PipeError(f"Không thể chạy {args[0]}: {exc}") from exc
    if result.returncode != 0:
        raise PipeError(f"{label} thất bại, exit code={result.returncode}")


def getTxts(text_dir: Path) -> list[Path]:
    files = sorted(
        (p for p in text_dir.rglob("*.txt") if p.is_file()),
        key=lambda p: str(p).lower(),
    )
    if not files:
        raise PipeError(f"Không tìm thấy TXT sau bước 1: {text_dir}")
    return files


def getParas(text: str) -> list[str]:
    clean = block_re.sub("\n\n", text)
    return [p.strip() for p in para_re.split(clean) if p.strip()]


def packParas(paras: list[str], limit: int) -> tuple[list[str], int]:
    blocks: list[str] = []
    current: list[str] = []
    cur_len = 0
    over_count = 0

    for para in paras:
        para_len = len(para)
        if para_len > limit:
            over_count += 1
        extra = para_len if not current else 2 + para_len
        if current and cur_len + extra > limit:
            blocks.append("\n\n".join(current))
            current = [para]
            cur_len = para_len
        else:
            current.append(para)
            cur_len += extra
    if current:
        blocks.append("\n\n".join(current))
    return blocks, over_count


def splitFile(path: Path, limit: int) -> tuple[int, int, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PipeError(f"Không thể đọc TXT {path}: {exc}") from exc

    paras = getParas(text)
    blocks, over_num = packParas(paras, limit)
    new_text = f"\n\n{block_sep}\n\n".join(blocks)
    if new_text:
        new_text += "\n"
    if text != new_text:
        try:
            path.write_text(new_text, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise PipeError(f"Không thể ghi TXT {path}: {exc}") from exc
    return len(paras), len(blocks), over_num


def splitTexts(text_dir: Path, limit: int) -> list[Path]:
    files = getTxts(text_dir)
    print("\n=== Step 2/4: Split TXT into session-sized blocks ===")
    for i, path in enumerate(files, start=1):
        para_num, block_num, over_num = splitFile(path, limit)
        rel_path = path.relative_to(text_dir)
        print(
            f"[{i}/{len(files)}] {rel_path}: paragraphs={para_num}, "
            f"blocks={block_num}, oversized={over_num}"
        )
    return files


def getMdFiles(tran_dir: Path) -> list[Path]:
    files = sorted(
        (p for p in tran_dir.rglob("*.md") if p.is_file()),
        key=lambda p: str(p).lower(),
    )
    if not files:
        raise PipeError(f"Không tìm thấy Markdown sau bước dịch: {tran_dir}")
    return files


def runPdf(
    args: argparse.Namespace,
    in_path: Path,
    text_dir: Path,
    root: Path,
) -> None:
    script = root / "main" / "book_pdf2text.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(in_path),
        "-o",
        str(text_dir),
        "-c",
        str(args.columns),
    ]
    if args.ocr:
        cmd.append("--ocr")
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Step 1/4: PDF to TXT", root)


def runTrans(
    args: argparse.Namespace,
    text_dir: Path,
    tran_dir: Path,
    root: Path,
) -> None:
    script = root / "main" / "en2vi.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(text_dir),
        "-o",
        str(tran_dir),
        "-m",
        args.model,
        "--prompt",
        str(args.prompt.expanduser().resolve()),
        "--config",
        str(args.config.expanduser().resolve()),
        "--limit",
        str(args.limit),
        "--max-requests",
        str(args.max_requests),
        "--delay",
        str(args.delay),
        "--timeout",
        str(args.timeout),
    ]
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Step 3/4: Translate TXT to Vietnamese Markdown", root)


def runDocx(
    args: argparse.Namespace,
    tran_dir: Path,
    docx_dir: Path,
    root: Path,
) -> None:
    files = getMdFiles(tran_dir)
    script = root / "main" / "md2docx.py"
    print("\n=== Step 4/4: Markdown to DOCX ===")
    for i, path in enumerate(files, start=1):
        rel_dir = path.parent.relative_to(tran_dir)
        out_dir = docx_dir / rel_dir
        cmd = [
            sys.executable,
            str(script),
            "-i",
            str(path),
            "-o",
            str(out_dir),
            "--template",
            str(args.template.expanduser().resolve()),
        ]
        if args.overwrite:
            cmd.append("--overwrite")
        runCmd(cmd, f"Step 4/4 [{i}/{len(files)}]: {path.name}", root)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = parseArgs(argv)
    try:
        if args.columns < 1:
            raise PipeError("--columns phải > 0")
        if args.limit < 1:
            raise PipeError("--limit phải > 0")
        if args.max_requests < 1:
            raise PipeError("--max-requests phải > 0")
        if args.delay < 0:
            raise PipeError("--delay phải >= 0")
        if args.timeout < 1:
            raise PipeError("--timeout phải > 0")

        root = getRoot()
        in_path = getInput(args.input_path)
        work_dir = getWorkDir(in_path, args.work_dir)
        text_dir = work_dir / "text"
        tran_dir = work_dir / "tran"
        docx_dir = work_dir / "docx"

        print(f"Input : {in_path}")
        print(f"Work  : {work_dir}")
        print(f"Model : {args.model}")
        print(f"Limit : {args.limit}")

        runPdf(args, in_path, text_dir, root)
        splitTexts(text_dir, args.limit)
        runTrans(args, text_dir, tran_dir, root)
        runDocx(args, tran_dir, docx_dir, root)

        print("\nPipeline completed.")
        print(f"TXT : {text_dir}")
        print(f"MD  : {tran_dir}")
        print(f"DOCX: {docx_dir}")
        return 0
    except PipeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
