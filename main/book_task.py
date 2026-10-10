"""Điều phối toàn bộ quy trình sách -> DOCX -> slide.

Quy trình hỗ trợ tiếp tục theo trạng thái thư mục và tự hẹn chạy lại trên
Windows khi Codex/Claude tạm thời hết quota.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO


DEF_RETRY_MIN = 60
RETRY_BUF_MIN = 2
QUOTA_WORDS = (
    "usage limit",
    "quota exceeded",
    "rate limit",
    "rate_limit",
    "limit reached",
    "try again after",
    "retry after",
    "resets at",
    "resource_exhausted",
    "too many requests",
    "http 429",
    "status 429",
)


@dataclass(frozen=True)
class JobPaths:
    work_dir: Path
    docx_dir: Path
    done_dir: Path
    pptx_dir: Path
    mark_run: Path
    mark_done: Path
    retry_cmd: Path


@dataclass(frozen=True)
class ProcResult:
    code: int
    stdout: str
    stderr: str


class TaskError(RuntimeError):
    """Lỗi không thể tự phục hồi."""


class RetryQueued(RuntimeError):
    """Đã hẹn Windows Task Scheduler chạy lại."""


def configConsole() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Điều phối pipeline tạo DOCX và slide từ một cuốn sách."
    )
    parser.add_argument("-i", "--input", required=True, help="File PDF/EPUB đầu vào.")
    parser.add_argument(
        "-m",
        "--model",
        choices=("codex", "claude"),
        default="codex",
        help="Model dùng cho các bước AI (mặc định: codex).",
    )
    parser.add_argument(
        "-t",
        "--type",
        dest="book_type",
        choices=("pdf", "epub"),
        required=True,
        help="Loại sách đầu vào.",
    )
    parser.add_argument("-o", "--output", help="Thư mục làm việc của cuốn sách.")
    parser.add_argument(
        "--non-check",
        action="store_true",
        help="Bỏ bước chờ duyệt DOCX và tự sao chép sang done/.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Cho phép ghi đè trong lần chạy chủ động hiện tại.",
    )
    return parser.parse_args()


def getRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def getInput(args: argparse.Namespace) -> Path:
    in_path = Path(args.input).expanduser().resolve()
    if not in_path.is_file():
        raise TaskError(f"Không tìm thấy file đầu vào: {in_path}")
    if in_path.suffix.lower() != f".{args.book_type}":
        raise TaskError(
            f"File đầu vào phải có đuôi .{args.book_type}: {in_path.name}"
        )
    return in_path


def getWorkDir(args: argparse.Namespace, in_path: Path) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()

    root_dir = getRoot()
    cfg_path = root_dir / "config" / "env_split.py"

    if args.book_type == "pdf":
        from readbook import pipeline_pdf as book_pipe
    else:
        from readbook import pipeline_epub as book_pipe

    try:
        return book_pipe.getWorkDir(in_path, None, cfg_path).resolve()
    except Exception as exc:
        raise TaskError(f"Không xác định được thư mục output mặc định: {exc}") from exc


def getPaths(args: argparse.Namespace, in_path: Path) -> JobPaths:
    work_dir = getWorkDir(args, in_path)
    return JobPaths(
        work_dir=work_dir,
        docx_dir=work_dir / "docx",
        done_dir=work_dir / "done",
        pptx_dir=work_dir / "slide" / "pptx",
        mark_run=work_dir / ".book_task_incomplete",
        mark_done=work_dir / ".book_task_complete",
        retry_cmd=work_dir / ".book_task_retry.cmd",
    )


def listDocx(folder: Path, recursive: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    items = folder.rglob("*.docx") if recursive else folder.glob("*.docx")
    return sorted(
        (item for item in items if not item.name.startswith("~$")),
        key=lambda item: str(item).lower(),
    )


def hasDone(paths: JobPaths) -> bool:
    return bool(listDocx(paths.done_dir))


def hasBookOutput(paths: JobPaths) -> bool:
    if paths.mark_run.exists():
        return False
    return bool(listDocx(paths.docx_dir, recursive=True))


def hasSlideOutput(paths: JobPaths) -> bool:
    done_files = listDocx(paths.done_dir)
    if not done_files or not paths.pptx_dir.is_dir():
        return False

    made_stems = {
        item.stem.casefold() for item in paths.pptx_dir.rglob("*.pptx")
    }
    return all(item.stem.casefold() in made_stems for item in done_files)


def prepareDone(paths: JobPaths) -> list[Path]:
    src_files = listDocx(paths.docx_dir, recursive=True)
    if not src_files:
        raise TaskError(f"Không có DOCX để đưa vào done/: {paths.docx_dir}")

    if paths.done_dir.exists():
        old_files = list(paths.done_dir.iterdir())
        if old_files:
            raise TaskError(
                f"done/ đã tồn tại nhưng không có DOCX hợp lệ: {paths.done_dir}"
            )
        paths.done_dir.rmdir()

    names: dict[str, Path] = {}
    for src_path in src_files:
        key = src_path.name.casefold()
        if key in names:
            raise TaskError(
                "Trùng tên DOCX khi gom vào done/: "
                f"{names[key]} và {src_path}"
            )
        names[key] = src_path

    paths.work_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".done_", dir=paths.work_dir))
    try:
        for src_path in src_files:
            shutil.copy2(src_path, temp_dir / src_path.name)
        temp_dir.replace(paths.done_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return listDocx(paths.done_dir)


def buildBookCmd(
    args: argparse.Namespace, in_path: Path, paths: JobPaths
) -> list[str]:
    main_dir = Path(__file__).resolve().parent
    script = main_dir / "readbook" / f"pipeline_{args.book_type}.py"
    command = [
        sys.executable,
        str(script),
        "-i",
        str(in_path),
        "-o",
        str(paths.work_dir),
        "-m",
        args.model,
    ]
    if args.overwrite:
        command.append("--overwrite")
    return command


def buildSlideCmd(args: argparse.Namespace, paths: JobPaths) -> list[str]:
    script = Path(__file__).resolve().parent / "slide_create" / "pipeline.py"
    command = [
        sys.executable,
        str(script),
        "-i",
        str(paths.done_dir),
        "-m",
        args.model,
    ]
    if args.overwrite:
        command.append("--overwrite")
    return command


def _pumpStream(stream: TextIO, lines: list[str], target: TextIO) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.append(line)
            print(line, end="", file=target, flush=True)
    finally:
        stream.close()


def runProcess(command: list[str]) -> ProcResult:
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )
    except OSError as exc:
        raise TaskError(f"Không thể chạy lệnh: {exc}") from exc

    if process.stdout is None or process.stderr is None:
        process.kill()
        raise TaskError("Không thể đọc stdout/stderr của tiến trình con.")

    out_lines: list[str] = []
    err_lines: list[str] = []
    out_thread = threading.Thread(
        target=_pumpStream,
        args=(process.stdout, out_lines, sys.stdout),
        daemon=True,
    )
    err_thread = threading.Thread(
        target=_pumpStream,
        args=(process.stderr, err_lines, sys.stderr),
        daemon=True,
    )
    out_thread.start()
    err_thread.start()

    try:
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        out_thread.join()
        err_thread.join()

    return ProcResult(code=code, stdout="".join(out_lines), stderr="".join(err_lines))


def isQuotaError(text: str) -> bool:
    lower_text = text.casefold()
    return any(word in lower_text for word in QUOTA_WORDS)


def _readRelative(text: str) -> timedelta | None:
    unit_text = r"hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s"
    pattern = re.compile(
        r"(?:try\s+again|retry)(?:\s+again)?(?:\s+after|\s+in)?"
        rf"\s+((?:\d+(?:\.\d+)?\s*(?:{unit_text})\b[\s,]*){{1,3}})",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        retry_head = re.search(
            r"retry-after\s*[:=]\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE
        )
        if retry_head:
            return timedelta(seconds=float(retry_head.group(1)))
        return None

    total = timedelta()
    parts = re.findall(
        rf"(\d+(?:\.\d+)?)\s*({unit_text})\b", match.group(1), re.IGNORECASE
    )
    for raw_value, raw_unit in parts:
        value = float(raw_value)
        unit = raw_unit.lower()
        if unit.startswith(("h", "hour")):
            total += timedelta(hours=value)
        elif unit.startswith(("m", "min")):
            total += timedelta(minutes=value)
        else:
            total += timedelta(seconds=value)
    return total or None


def _readIsoTime(text: str) -> datetime | None:
    pattern = re.compile(
        r"\b(20\d{2}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}"
        r"(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)\b"
    )
    match = pattern.search(text)
    if not match:
        return None
    raw_value = match.group(1).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def _readClock(text: str, now_time: datetime) -> datetime | None:
    pattern = re.compile(
        r"(?:resets?|retry|available)(?:\s+again)?(?:\s+at)?\s+"
        r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    meridiem = (match.group(4) or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour %= 12
        if meridiem == "pm":
            hour += 12
    elif hour > 23:
        return None

    retry_at = now_time.replace(
        hour=hour, minute=minute, second=second, microsecond=0
    )
    if retry_at <= now_time:
        retry_at += timedelta(days=1)
    return retry_at


def getRetryTime(text: str) -> datetime:
    now_time = datetime.now().astimezone()
    relative = _readRelative(text)
    if relative is not None:
        return now_time + relative + timedelta(minutes=RETRY_BUF_MIN)

    retry_at = _readIsoTime(text)
    if retry_at is None:
        retry_at = _readClock(text, now_time)
    if retry_at is not None:
        return retry_at + timedelta(minutes=RETRY_BUF_MIN)

    return now_time + timedelta(minutes=DEF_RETRY_MIN)


def getTaskName(in_path: Path, book_type: str) -> str:
    source = f"{book_type}|{in_path.resolve()}".casefold().encode("utf-8")
    short_hash = hashlib.sha256(source).hexdigest()[:10]
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", in_path.stem).strip("_.")
    safe_stem = safe_stem[:60] or "book"
    return f"READBOOK_{safe_stem}_{short_hash}"


def buildResume(args: argparse.Namespace, in_path: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "-i",
        str(in_path),
        "-m",
        args.model,
        "-t",
        args.book_type,
    ]
    if args.output:
        command.extend(["-o", str(Path(args.output).expanduser().resolve())])
    if args.non_check:
        command.append("--non-check")
    return command


def _roundMinute(retry_at: datetime) -> datetime:
    local_time = retry_at.astimezone()
    if local_time.second or local_time.microsecond:
        local_time = local_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    min_time = datetime.now().astimezone() + timedelta(minutes=1)
    if local_time < min_time:
        local_time = min_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return local_time


def scheduleRetry(
    task_name: str,
    retry_at: datetime,
    resume_cmd: list[str],
    paths: JobPaths,
) -> datetime:
    if sys.platform != "win32":
        raise TaskError("Tự hẹn chạy lại hiện chỉ hỗ trợ Windows Task Scheduler.")

    paths.work_dir.mkdir(parents=True, exist_ok=True)
    cmd_text = subprocess.list2cmdline(resume_cmd)
    paths.retry_cmd.write_text(
        f"@echo off\r\nchcp 65001 >nul\r\n{cmd_text}\r\n", encoding="utf-8"
    )

    retry_at = _roundMinute(retry_at)
    task_cmd = subprocess.list2cmdline(
        ["cmd.exe", "/d", "/s", "/c", str(paths.retry_cmd)]
    )
    command = [
        "schtasks",
        "/Create",
        "/SC",
        "ONCE",
        "/TN",
        task_name,
        "/TR",
        task_cmd,
        "/ST",
        retry_at.strftime("%H:%M"),
        "/SD",
        retry_at.strftime("%m/%d/%Y"),
        "/F",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise TaskError(f"Không thể tạo Scheduled Task: {details}")
    return retry_at


def removeTask(task_name: str, paths: JobPaths) -> None:
    if sys.platform == "win32":
        query = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if query.returncode == 0:
            deleted = subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if deleted.returncode != 0:
                print(
                    f"[WARN] Không thể xóa Scheduled Task '{task_name}': "
                    f"{(deleted.stderr or deleted.stdout).strip()}",
                    file=sys.stderr,
                )
    paths.retry_cmd.unlink(missing_ok=True)


def markStarted(paths: JobPaths) -> None:
    paths.work_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().isoformat()
    paths.mark_run.write_text(stamp + "\n", encoding="utf-8")
    paths.mark_done.unlink(missing_ok=True)


def markComplete(paths: JobPaths) -> None:
    stamp = datetime.now().astimezone().isoformat()
    paths.mark_done.write_text(stamp + "\n", encoding="utf-8")
    paths.mark_run.unlink(missing_ok=True)


def runStage(
    label: str,
    command: list[str],
    args: argparse.Namespace,
    in_path: Path,
    paths: JobPaths,
    task_name: str,
) -> None:
    print(f"\n=== {label} ===")
    print(f"Command: {subprocess.list2cmdline(command)}")
    result = runProcess(command)
    if result.code == 0:
        return

    all_text = f"{result.stdout}\n{result.stderr}"
    if isQuotaError(all_text):
        retry_at = getRetryTime(all_text)
        actual_time = scheduleRetry(
            task_name,
            retry_at,
            buildResume(args, in_path),
            paths,
        )
        print(
            "\n[QUOTA] Đã hẹn chạy lại tự động lúc "
            f"{actual_time.strftime('%Y-%m-%d %H:%M %Z')}."
        )
        print(f"Scheduled Task: {task_name}")
        raise RetryQueued

    print("\n[ERROR] Tiến trình con thất bại.", file=sys.stderr)
    print(f"Command    : {subprocess.list2cmdline(command)}", file=sys.stderr)
    print(f"Return code: {result.code}", file=sys.stderr)
    if result.stdout.strip():
        print("--- stdout ---", file=sys.stderr)
        print(result.stdout.rstrip(), file=sys.stderr)
    if result.stderr.strip():
        print("--- stderr ---", file=sys.stderr)
        print(result.stderr.rstrip(), file=sys.stderr)
    raise TaskError(f"{label} thất bại với mã {result.code}.")


def runBook(
    args: argparse.Namespace,
    in_path: Path,
    paths: JobPaths,
    task_name: str,
) -> None:
    markStarted(paths)
    runStage(
        "BOOK PIPELINE",
        buildBookCmd(args, in_path, paths),
        args,
        in_path,
        paths,
        task_name,
    )
    if not listDocx(paths.docx_dir, recursive=True):
        raise TaskError(
            "Book pipeline kết thúc nhưng không tạo được DOCX trong "
            f"{paths.docx_dir}"
        )
    markComplete(paths)


def runSlides(
    args: argparse.Namespace,
    in_path: Path,
    paths: JobPaths,
    task_name: str,
) -> None:
    runStage(
        "SLIDE PIPELINE",
        buildSlideCmd(args, paths),
        args,
        in_path,
        paths,
        task_name,
    )
    if not hasSlideOutput(paths):
        raise TaskError(
            "Slide pipeline kết thúc nhưng chưa đủ PPTX tương ứng trong "
            f"{paths.pptx_dir}"
        )


def finishTask(task_name: str, paths: JobPaths) -> int:
    removeTask(task_name, paths)
    print("\n[COMPLETE] Toàn bộ quy trình đã hoàn tất.")
    print(f"Output: {paths.pptx_dir}")
    return 0


def waitReview(paths: JobPaths) -> int:
    print("\n[WAITING] DOCX đã sẵn sàng để kiểm tra và chỉnh sửa.")
    print(f"DOCX : {paths.docx_dir}")
    print(f"Sau khi duyệt, hãy đặt các file hoàn chỉnh vào: {paths.done_dir}")
    print("Sau đó chạy lại đúng lệnh book_task.py; đây không phải là lỗi.")
    return 0


def main() -> int:
    configConsole()
    args = parseArgs()
    try:
        in_path = getInput(args)
        paths = getPaths(args, in_path)
        task_name = getTaskName(in_path, args.book_type)

        print(f"Input : {in_path}")
        print(f"Type  : {args.book_type}")
        print(f"Model : {args.model}")
        print(f"Work  : {paths.work_dir}")

        if hasDone(paths):
            if hasSlideOutput(paths):
                return finishTask(task_name, paths)
            runSlides(args, in_path, paths, task_name)
            return finishTask(task_name, paths)

        if paths.done_dir.exists() and any(paths.done_dir.iterdir()):
            raise TaskError(
                f"done/ tồn tại nhưng không có file DOCX trực tiếp: {paths.done_dir}"
            )

        if not hasBookOutput(paths):
            runBook(args, in_path, paths, task_name)

        if not args.non_check:
            return waitReview(paths)

        made_files = prepareDone(paths)
        print(f"\n[AUTO] Đã đưa {len(made_files)} DOCX vào: {paths.done_dir}")
        runSlides(args, in_path, paths, task_name)
        return finishTask(task_name, paths)

    except RetryQueued:
        return 0
    except KeyboardInterrupt:
        print("\n[STOP] Đã dừng theo yêu cầu người dùng.", file=sys.stderr)
        return 130
    except TaskError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
