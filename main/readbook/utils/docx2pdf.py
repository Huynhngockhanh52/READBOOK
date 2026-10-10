#!/usr/bin/env python3
"""Convert every DOCX in a directory to a sibling ``pdf_vi`` directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ConvertError(RuntimeError):
    """Raised when a DOCX cannot be converted safely."""


@dataclass(frozen=True)
class ConvertJob:
    source: Path
    output: Path


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
    """Extract the suffix from ``<file_name>_<chapter>``."""
    if "_" not in path.stem:
        raise ConvertError(
            f"Tên file không đúng dạng <file_name>_<chapter>.docx: {path.name}"
        )
    token = path.stem.rsplit("_", 1)[1].strip().casefold()
    if not token:
        raise ConvertError(f"Thiếu chapter trong tên file: {path.name}")
    return token


def chapter_id(path: Path, allow_front_matter: bool) -> tuple[int, int]:
    token = chapter_token(path)
    if allow_front_matter and token in FRONT_MATTER:
        return 0, FRONT_MATTER[token]
    if token.isdecimal():
        return 1, int(token)
    hint = " hoặc dùng --front-matter" if not allow_front_matter else ""
    raise ConvertError(
        f"Chapter phải là số (ví dụ 00, 01, 02){hint}: {path.name}"
    )


def chapter_sort_key(path: Path, allow_front_matter: bool) -> tuple[int, int, str]:
    category, order = chapter_id(path, allow_front_matter)
    return category, order, path.name.casefold()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chuyển toàn bộ DOCX trong một thư mục sang PDF.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help=(
            "Thư mục chứa các file <file_name>_<chapter>.docx "
            "(cách viết rút gọn thay cho -i)."
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        help="Thư mục DOCX đầu vào; nếu bỏ trống thì dùng ./done.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_dir",
        type=Path,
        help="Thư mục PDF; mặc định là pdf_vi nằm cạnh thư mục input.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "word", "libreoffice"),
        default="auto",
        help="Công cụ dùng để chuyển đổi.",
    )
    parser.add_argument(
        "--front-matter",
        action="store_true",
        help="Cho phép các hậu tố như cover, foreword, preface, intro trước chương số.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè các file PDF đã tồn tại.",
    )
    return parser.parse_args(argv)


def collect_jobs(
    input_arg: Path,
    output_arg: Path | None,
    overwrite: bool,
    allow_front_matter: bool = False,
) -> tuple[Path, list[ConvertJob]]:
    input_dir = input_arg.expanduser().resolve()
    if not input_dir.is_dir():
        raise ConvertError(f"Không tìm thấy thư mục DOCX: {input_dir}")

    files = sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".docx"
            and not path.name.startswith("~$")
        ),
        key=lambda path: chapter_sort_key(path, allow_front_matter),
    )
    if not files:
        raise ConvertError(f"Không có file .docx trong: {input_dir}")

    chapters: dict[tuple[int, int], Path] = {}
    for path in files:
        chapter = chapter_id(path, allow_front_matter)
        if chapter in chapters:
            raise ConvertError(
                f"Vị trí chapter bị trùng: {chapters[chapter].name}, {path.name}"
            )
        chapters[chapter] = path

    output_dir = (
        output_arg.expanduser().resolve()
        if output_arg is not None
        else input_dir.parent / "pdf_vi"
    )
    if output_dir.exists() and not output_dir.is_dir():
        raise ConvertError(f"Output phải là một thư mục: {output_dir}")

    jobs = [ConvertJob(path, output_dir / f"{path.stem}.pdf") for path in files]
    existing = [job.output.name for job in jobs if job.output.exists()]
    if existing and not overwrite:
        names = ", ".join(existing)
        raise ConvertError(
            f"Output đã tồn tại: {names}. Dùng --overwrite để ghi đè."
        )
    return output_dir, jobs


def find_powershell() -> str:
    command = shutil.which("powershell.exe") or shutil.which("powershell")
    if command is None:
        raise ConvertError("Không tìm thấy PowerShell để điều khiển Microsoft Word.")
    return command


def validate_pdf(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 5:
        raise ConvertError(f"Không tạo được PDF hợp lệ: {path}")
    with path.open("rb") as pdf_file:
        if pdf_file.read(5) != b"%PDF-":
            raise ConvertError(f"File kết quả không phải PDF: {path}")


def convert_with_word(jobs: list[ConvertJob], output_dir: Path) -> None:
    """Use one hidden Word instance through PowerShell COM automation."""
    powershell = find_powershell()
    temp_paths = [
        output_dir / f".{job.output.stem}.{os.getpid()}.{index}.tmp.pdf"
        for index, job in enumerate(jobs)
    ]
    manifest = [
        {"source": str(job.source), "output": str(temp_path)}
        for job, temp_path in zip(jobs, temp_paths)
    ]
    manifest_path: Path | None = None
    script = r"""
$ErrorActionPreference = 'Stop'
$items = Get-Content -LiteralPath $env:DOCX2PDF_MANIFEST_PATH -Raw -Encoding UTF8 | ConvertFrom-Json
$word = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    foreach ($item in @($items)) {
        $doc = $null
        try {
            $doc = $word.Documents.Open([string]$item.source, $false, $true)
            $doc.ExportAsFixedFormat([string]$item.output, 17)
        }
        finally {
            if ($null -ne $doc) { $doc.Close($false) }
        }
    }
}
finally {
    if ($null -ne $word) { $word.Quit() }
}
"""
    try:
        file_id, manifest_raw = tempfile.mkstemp(
            prefix=".docx2pdf_", suffix=".json", dir=str(output_dir)
        )
        manifest_path = Path(manifest_raw)
        with os.fdopen(file_id, "w", encoding="utf-8-sig") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False)

        process_env = os.environ.copy()
        process_env["DOCX2PDF_MANIFEST_PATH"] = str(manifest_path)
        result = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            env=process_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ConvertError(
                "Microsoft Word không thể chuyển DOCX sang PDF"
                + (f": {detail}" if detail else ".")
            )

        for temp_path in temp_paths:
            validate_pdf(temp_path)
        for job, temp_path in zip(jobs, temp_paths):
            temp_path.replace(job.output)
    finally:
        if manifest_path is not None:
            manifest_path.unlink(missing_ok=True)
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)


def find_libreoffice() -> str:
    candidates = (
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ConvertError(
        "Không tìm thấy LibreOffice. Hãy cài LibreOffice hoặc dùng --backend word."
    )


def convert_with_libreoffice(jobs: list[ConvertJob], output_dir: Path) -> None:
    soffice = find_libreoffice()
    for job in jobs:
        with tempfile.TemporaryDirectory(prefix=".docx2pdf_", dir=output_dir) as tmp:
            result = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    str(job.source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            temp_path = Path(tmp) / f"{job.source.stem}.pdf"
            if result.returncode != 0 or not temp_path.exists():
                detail = (result.stderr or result.stdout).strip()
                raise ConvertError(
                    f"LibreOffice không thể chuyển {job.source.name}"
                    + (f": {detail}" if detail else ".")
                )
            validate_pdf(temp_path)
            temp_path.replace(job.output)


def run(args: argparse.Namespace) -> list[Path]:
    if args.input_dir is not None and args.input_path is not None:
        raise ConvertError("Chỉ truyền input một lần: dùng -i hoặc positional.")
    input_dir = args.input_path or args.input_dir or Path("done")
    output_dir, jobs = collect_jobs(
        input_dir,
        args.output_dir,
        args.overwrite,
        args.front_matter,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    backend = args.backend
    if backend == "auto":
        backend = "word" if os.name == "nt" else "libreoffice"

    print(f"Input:   {jobs[0].source.parent}")
    print(f"Output:  {output_dir}")
    print(f"Backend: {backend} | files: {len(jobs)}")
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {job.source.name} -> {job.output.name}")

    if backend == "word":
        convert_with_word(jobs, output_dir)
    else:
        convert_with_libreoffice(jobs, output_dir)
    return [job.output for job in jobs]


def main(argv: Sequence[str] | None = None) -> int:
    set_utf8()
    try:
        outputs = run(parse_args(argv))
    except ConvertError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Đã hủy.", file=sys.stderr)
        return 130
    print(f"Hoàn tất: {len(outputs)} file PDF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
