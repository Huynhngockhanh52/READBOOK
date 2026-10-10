#!/usr/bin/env python3
"""Run the complete DOCX-to-PowerPoint slide creation pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


MODEL_OPTS = ("codex", "claude")


class PipeError(RuntimeError):
    """Raised when a pipeline stage cannot finish safely."""


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline: DOCX → Markdown → Summary → Slide Markdown → PPTX.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_dir",
        type=Path,
        default=Path("done"),
        help="Thư mục chứa các chương DOCX đã chỉnh sửa.",
    )
    parser.add_argument(
        "-m",
        "--model",
        choices=MODEL_OPTS,
        default="codex",
        help="Backend dùng cho bước summary và tạo nội dung slide.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè output đã tồn tại ở tất cả công đoạn.",
    )
    return parser.parse_args(argv)


def getInput(path: Path) -> Path:
    in_dir = path.expanduser().resolve()
    if not in_dir.is_dir():
        raise PipeError(f"Không tìm thấy thư mục DOCX: {in_dir}")
    files = [
        item
        for item in in_dir.iterdir()
        if item.is_file()
        and item.suffix.casefold() == ".docx"
        and not item.name.startswith("~$")
    ]
    if not files:
        raise PipeError(f"Không có file DOCX trong: {in_dir}")
    return in_dir


def runCmd(cmd: list[str], label: str, cwd: Path) -> None:
    print(f"\n=== {label} ===", flush=True)
    try:
        result = subprocess.run(cmd, cwd=str(cwd), check=False)
    except OSError as exc:
        raise PipeError(f"Không thể chạy {cmd[0]}: {exc}") from exc
    if result.returncode != 0:
        raise PipeError(f"{label} thất bại, exit code={result.returncode}")


def baseCmd(script: Path) -> list[str]:
    return [sys.executable, str(script)]


def addOverwrite(cmd: list[str], overwrite: bool) -> None:
    if overwrite:
        cmd.append("--overwrite")


def runDocxToMd(
    code_dir: Path,
    in_dir: Path,
    md_dir: Path,
    root: Path,
    overwrite: bool,
) -> None:
    cmd = baseCmd(code_dir / "utils" / "docx2md.py")
    cmd.extend(["-i", str(in_dir), "-o", str(md_dir)])
    addOverwrite(cmd, overwrite)
    runCmd(cmd, "Stage 1/4: DOCX → Markdown", root)


def runSummary(
    code_dir: Path,
    md_dir: Path,
    sum_dir: Path,
    model: str,
    root: Path,
    overwrite: bool,
) -> None:
    cmd = baseCmd(code_dir / "summary.py")
    cmd.extend(
        [
            "-i",
            str(md_dir),
            "-o",
            str(sum_dir),
            "-m",
            model,
        ]
    )
    addOverwrite(cmd, overwrite)
    runCmd(cmd, "Stage 2/4: Markdown → Summary", root)


def runSumToSlide(
    code_dir: Path,
    sum_dir: Path,
    section_dir: Path,
    model: str,
    root: Path,
    overwrite: bool,
) -> None:
    cmd = baseCmd(code_dir / "sum2slide.py")
    cmd.extend(
        [
            "-i",
            str(sum_dir),
            "-o",
            str(section_dir),
            "-m",
            model,
        ]
    )
    addOverwrite(cmd, overwrite)
    runCmd(cmd, "Stage 3/4: Summary → Slide Markdown", root)


def getSections(section_dir: Path) -> list[Path]:
    if not section_dir.is_dir():
        raise PipeError(f"Không tìm thấy thư mục section: {section_dir}")
    files = sorted(
        (item for item in section_dir.rglob("*_slide.md") if item.is_file()),
        key=lambda item: str(item.relative_to(section_dir)).casefold(),
    )
    if not files:
        raise PipeError(f"Không có file *_slide.md trong: {section_dir}")
    return files


def runPowerPoint(
    code_dir: Path,
    section_dir: Path,
    pptx_dir: Path,
    root: Path,
    overwrite: bool,
) -> int:
    files = getSections(section_dir)
    script = code_dir / "slide_create.py"
    print("\n=== Stage 4/4: Slide Markdown → PowerPoint ===")
    for index, path in enumerate(files, start=1):
        rel_dir = path.parent.relative_to(section_dir)
        out_dir = pptx_dir / rel_dir
        cmd = baseCmd(script)
        cmd.extend(["-i", str(path), "-o", str(out_dir)])
        addOverwrite(cmd, overwrite)
        runCmd(
            cmd,
            f"Stage 4/4 [{index}/{len(files)}]: {path.name}",
            root,
        )
    return len(files)


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
        in_dir = getInput(args.input_dir)
        book_dir = in_dir.parent
        slide_dir = book_dir / "slide"
        md_dir = slide_dir / "md"
        sum_dir = slide_dir / "sum"
        section_dir = slide_dir / "section"
        pptx_dir = slide_dir / "pptx"
        code_dir = Path(__file__).resolve().parent
        root = Path(__file__).resolve().parents[2]

        print(f"Input  : {in_dir}")
        print(f"Model  : {args.model}")
        print(f"MD     : {md_dir}")
        print(f"Summary: {sum_dir}")
        print(f"Section: {section_dir}")
        print(f"PPTX   : {pptx_dir}")

        runDocxToMd(code_dir, in_dir, md_dir, root, args.overwrite)
        runSummary(
            code_dir,
            md_dir,
            sum_dir,
            args.model,
            root,
            args.overwrite,
        )
        runSumToSlide(
            code_dir,
            sum_dir,
            section_dir,
            args.model,
            root,
            args.overwrite,
        )
        pptx_num = runPowerPoint(
            code_dir,
            section_dir,
            pptx_dir,
            root,
            args.overwrite,
        )

        print("\nSlide pipeline completed.")
        print(f"PowerPoint files: {pptx_num}")
        print(f"Output: {pptx_dir}")
        return 0
    except PipeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
