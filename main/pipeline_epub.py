#!/usr/bin/env python3
"""Chạy pipeline EPUB -> XHTML -> TXT -> VI Markdown -> DOCX."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    import epub_split
except ImportError:
    from . import epub_split


MODEL_OPTS = ("gemini", "codex", "claude", "non-codex", "non-claude")
CHAR_LIMIT = 50_000


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
        description="Tách EPUB và chạy toàn bộ pipeline dịch sang DOCX.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        required=True,
        help="File EPUB sách gốc, thường nằm trong data/ROOT/.",
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
        help="Cấu hình epub_splits và classification.",
    )
    parser.add_argument(
        "-m",
        "--model",
        choices=MODEL_OPTS,
        default="codex",
        help="Backend dịch thuật của en2vi.py.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Tạo lại file đã tồn tại ở tất cả công đoạn.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=CHAR_LIMIT,
        help="Giới hạn ký tự cho translation chunk và session.",
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
        help="Số giây chờ trước mỗi Gemini request.",
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
        raise PipeError(f"Không tìm thấy EPUB sách gốc: {in_path}")
    if in_path.suffix.lower() != ".epub":
        raise PipeError(f"Input phải là file EPUB: {in_path}")
    return in_path


def getWorkDir(
    in_path: Path,
    out_arg: Path | None,
    cfg_path: Path,
) -> Path:
    if out_arg is not None:
        work_dir = out_arg.expanduser().resolve()
    else:
        try:
            plans, class_map = epub_split.loadConfig(cfg_path)
            epub_split.pickPlan(plans, in_path)
            part_dir = epub_split.getOutDir(
                None,
                in_path,
                class_map,
                getRoot(),
            )
        except epub_split.SplitError as exc:
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
    args: argparse.Namespace,
    in_path: Path,
    part_dir: Path,
    mani_path: Path,
    root: Path,
) -> None:
    script = root / "main" / "epub_split.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(in_path),
        "-o",
        str(part_dir),
        "--config",
        str(args.split_config.expanduser().resolve()),
        "--manifest",
        str(mani_path),
    ]
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Stage 1/4: Split EPUB by configured spine", root)


def runText(
    args: argparse.Namespace,
    part_dir: Path,
    text_dir: Path,
    mani_path: Path,
    root: Path,
) -> None:
    script = root / "main" / "book_epub2text.py"
    cmd = [
        sys.executable,
        str(script),
        "-i",
        str(part_dir),
        "-o",
        str(text_dir),
        "--limit",
        str(args.limit),
        "--manifest",
        str(mani_path),
    ]
    if args.overwrite:
        cmd.append("--overwrite")
    runCmd(cmd, "Stage 2/4: XHTML to Markdown-formatted TXT", root)


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
        str(args.config_path.expanduser().resolve()),
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
    runCmd(cmd, "Stage 3/4: Translate TXT to Vietnamese Markdown", root)


def getMdFiles(tran_dir: Path) -> list[Path]:
    files = sorted(
        (path for path in tran_dir.rglob("*.md") if path.is_file()),
        key=lambda path: str(path.relative_to(tran_dir)).casefold(),
    )
    if not files:
        raise PipeError(f"Không tìm thấy Markdown sau bước dịch: {tran_dir}")
    return files


def runDocx(
    args: argparse.Namespace,
    tran_dir: Path,
    docx_dir: Path,
    root: Path,
) -> None:
    files = getMdFiles(tran_dir)
    script = root / "main" / "md2docx.py"
    print("\n=== Stage 4/4: Markdown to DOCX ===")
    for idx, path in enumerate(files, start=1):
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
        runCmd(
            cmd,
            f"Stage 4/4 [{idx}/{len(files)}]: {path.name}",
            root,
        )


def fileHash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise PipeError(f"Không thể tính SHA-256 của {path}: {exc}") from exc
    return digest.hexdigest()


def readChars(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise PipeError(f"Không thể đọc Markdown {path}: {exc}") from exc


def relName(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def tranName(text_path: Path) -> str:
    stem = re.sub(r"(?i)_text$", "", text_path.stem)
    if stem.casefold().endswith("_vi"):
        return f"{stem}.md"
    return f"{stem}_vi.md"


def docxName(md_path: Path) -> str:
    stem = md_path.stem
    if stem.casefold().endswith("_vi"):
        stem = stem[:-3] or md_path.stem
    return f"{stem}.docx"


def readManifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PipeError(f"Không tìm thấy manifest: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipeError(f"Không thể đọc manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("parts"), list):
        raise PipeError(f"Manifest không có danh sách parts hợp lệ: {path}")
    return data


def writeAtomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_id, temp_raw = tempfile.mkstemp(
        prefix=f".{path.stem}_",
        suffix=path.suffix,
        dir=str(path.parent),
    )
    os.close(file_id)
    temp_path = Path(temp_raw)
    try:
        temp_path.write_bytes(data)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def updateManifest(
    mani_path: Path,
    text_dir: Path,
    tran_dir: Path,
    docx_dir: Path,
    model: str,
) -> int:
    manifest = readManifest(mani_path)
    base_dir = mani_path.parent
    updated = 0
    for part in manifest["parts"]:
        if not isinstance(part, dict):
            continue
        text_data = part.get("text")
        if not isinstance(text_data, dict):
            raise PipeError(
                f"Manifest part {part.get('key')!r} chưa có dữ liệu text."
            )
        text_ref = text_data.get("output")
        if not isinstance(text_ref, str) or not text_ref:
            raise PipeError(
                f"Manifest part {part.get('key')!r} thiếu text.output."
            )
        text_path = (base_dir / text_ref).resolve()
        try:
            rel_dir = text_path.parent.relative_to(text_dir.resolve())
        except ValueError as exc:
            raise PipeError(
                f"TXT trong manifest nằm ngoài text directory: {text_path}"
            ) from exc
        md_path = (tran_dir / rel_dir / tranName(text_path)).resolve()
        docx_path = (docx_dir / rel_dir / docxName(md_path)).resolve()
        if not md_path.is_file():
            raise PipeError(f"Thiếu Markdown bản dịch: {md_path}")
        if not docx_path.is_file():
            raise PipeError(f"Thiếu DOCX: {docx_path}")
        part["translation"] = {
            "output": relName(md_path, base_dir),
            "characters": readChars(md_path),
            "size_bytes": md_path.stat().st_size,
            "sha256": fileHash(md_path),
        }
        part["docx"] = {
            "output": relName(docx_path, base_dir),
            "size_bytes": docx_path.stat().st_size,
            "sha256": fileHash(docx_path),
        }
        updated += 1

    manifest["pipeline"] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "model": model,
        "updated_parts": updated,
    }
    mani_data = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    try:
        writeAtomic(mani_path, mani_data)
    except OSError as exc:
        raise PipeError(f"Không thể cập nhật manifest {mani_path}: {exc}") from exc
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
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
        mani_path = work_dir / "manifest.json"

        print(f"Input   : {in_path}")
        print(f"Work    : {work_dir}")
        print(f"Part    : {part_dir}")
        print(f"Text    : {text_dir}")
        print(f"Tran    : {tran_dir}")
        print(f"DOCX    : {docx_dir}")
        print(f"Manifest: {mani_path}")
        print(f"Model   : {args.model}")
        print(f"Limit   : {args.limit}")

        runSplit(args, in_path, part_dir, mani_path, root)
        runText(args, part_dir, text_dir, mani_path, root)
        runTrans(args, text_dir, tran_dir, root)
        runDocx(args, tran_dir, docx_dir, root)
        updated = updateManifest(
            mani_path,
            text_dir,
            tran_dir,
            docx_dir,
            args.model,
        )

        print("\nFull EPUB pipeline completed.")
        print(f"Parts tracked: {updated}")
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
