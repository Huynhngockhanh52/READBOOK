#!/usr/bin/env python3
"""Tách sách PDF rồi chạy pipeline PDF -> TXT -> VI Markdown -> DOCX."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pdf_split


model_opts = ("gemini", "codex", "claude", "non-codex", "non-claude")
char_limit = 50_000


class PipeError(RuntimeError):
    """Lỗi khiến pipeline không thể hoàn tất an toàn."""


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
        description="Tách sách PDF và chạy toàn bộ pipeline dịch sang DOCX.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        required=True,
        help="File PDF sách gốc, thường nằm trong data/ROOT/.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="work_dir",
        type=Path,
        help="Thư mục sách; mặc định tra classification trong env_split.py.",
    )
    parser.add_argument(
        "--split-config",
        dest="split_config",
        type=Path,
        default=root / "config" / "env_split.py",
        help="Cấu hình pdf_splits và classification.",
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
        help="Tạo lại file đã tồn tại ở tất cả công đoạn.",
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
        dest="config_path",
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
        dest="max_requests",
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
    if not in_path.is_file():
        raise PipeError(f"Không tìm thấy PDF sách gốc: {in_path}")
    if in_path.suffix.lower() != ".pdf":
        raise PipeError(f"Input phải là file PDF: {in_path}")
    return in_path


def getWorkDir(
    in_path: Path, out_arg: Path | None, cfg_path: Path
) -> Path:
    if out_arg is not None:
        work_dir = out_arg.expanduser().resolve()
    else:
        try:
            plans, class_map = pdf_split.loadConfig(cfg_path)
            pdf_split.pickPlan(plans, in_path)
            part_dir = pdf_split.getOutDir(None, in_path, class_map, getRoot())
        except pdf_split.SplitError as exc:
            raise PipeError(str(exc)) from exc
        work_dir = part_dir.parent
    if work_dir.exists() and not work_dir.is_dir():
        raise PipeError(f"Output root phải là thư mục: {work_dir}")
    return work_dir


def runCmd(cmd: list[str], label: str, root: Path) -> None:
    print(f"\n=== {label} ===", flush=True)
    try:
        result = subprocess.run(cmd, cwd=str(root), check=False)
    except OSError as exc:
        raise PipeError(f"Không thể chạy {cmd[0]}: {exc}") from exc
    if result.returncode != 0:
        raise PipeError(f"{label} thất bại, exit code={result.returncode}")


def runSplit(
    args: argparse.Namespace, in_path: Path, part_dir: Path, root: Path
) -> None:
    script = root / "main" / "pdf_split.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(in_path),
        "-o",
        str(part_dir),
        "--config",
        str(args.split_config.expanduser().resolve()),
    ]
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Stage 1/2: Split source PDF", root)


def runPipe(
    args: argparse.Namespace, part_dir: Path, work_dir: Path, root: Path
) -> None:
    script = root / "main" / "pipeline.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(part_dir),
        "-o",
        str(work_dir),
        "-m",
        args.model,
        "-c",
        str(args.columns),
        "--limit",
        str(args.limit),
        "--prompt",
        str(args.prompt.expanduser().resolve()),
        "--config",
        str(args.config_path.expanduser().resolve()),
        "--template",
        str(args.template.expanduser().resolve()),
        "--max-requests",
        str(args.max_requests),
        "--delay",
        str(args.delay),
        "--timeout",
        str(args.timeout),
    ]
    if args.ocr:
        cmd.append("--ocr")
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Stage 2/2: PDF parts to TXT, VI Markdown and DOCX", root)


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
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
        cfg_path = args.split_config.expanduser().resolve()
        work_dir = getWorkDir(in_path, args.work_dir, cfg_path)
        part_dir = work_dir / "part"
        text_dir = work_dir / "text"
        tran_dir = work_dir / "tran"
        docx_dir = work_dir / "docx"

        print(f"Input: {in_path}")
        print(f"Work : {work_dir}")
        print(f"Part : {part_dir}")
        print(f"Text : {text_dir}")
        print(f"Tran : {tran_dir}")
        print(f"DOCX : {docx_dir}")

        runSplit(args, in_path, part_dir, root)
        runPipe(args, part_dir, work_dir, root)

        print("\nFull PDF pipeline completed.")
        return 0
    except PipeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
