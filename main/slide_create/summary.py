#!/usr/bin/env python3
"""Summarize Markdown files through Codex CLI or Claude CLI."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CONTENT_TAG = "{{MARKDOWN_CONTENT}}"
CHAR_LIMIT = 125_000
SAFE_LIMIT = 120_000
REQ_TIMEOUT = 1_800
MODEL_OPTS = ("codex", "claude")
TERM_RE = re.compile(
    r"^##\s+0\s*[.):-]?\s+.*thuật\s+ngữ.*$",
    re.IGNORECASE,
)
HEAD_RE = re.compile(r"^(#{1,6})(?!#)\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
TABLE_SEP = re.compile(r"^:?-{3,}:?$")


class SummaryError(RuntimeError):
    """Raised when a summary cannot be created safely."""


@dataclass(frozen=True)
class FileJob:
    src_path: Path
    out_path: Path


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def getRoot() -> Path:
    return Path(__file__).resolve().parents[2]


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tóm tắt Markdown bằng Codex CLI hoặc Claude CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        default=Path("md"),
        help="File Markdown hoặc thư mục chứa Markdown.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        help="File/thư mục output tùy chọn.",
    )
    parser.add_argument(
        "-m",
        "--model",
        choices=MODEL_OPTS,
        default="codex",
        help="CLI backend dùng để tóm tắt.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè summary đã tồn tại.",
    )
    return parser.parse_args(argv)


def loadPrompt() -> str:
    path = getRoot() / "instruction" / "summary_chapter.md"
    if not path.is_file():
        raise SummaryError(f"Không tìm thấy prompt: {path}")
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SummaryError(f"Không thể đọc prompt {path}: {exc}") from exc
    tag_num = prompt.count(CONTENT_TAG)
    if tag_num != 1:
        raise SummaryError(
            f"Prompt phải chứa đúng một placeholder {CONTENT_TAG}; hiện có {tag_num}."
        )
    return prompt


def countChars(text: str) -> int:
    return len(text)


def fillPrompt(template: str, content: str) -> str:
    return template.replace(CONTENT_TAG, content)


def getMdFiles(path: Path) -> tuple[Path, list[Path]]:
    in_path = path.expanduser().resolve()
    if not in_path.exists():
        raise SummaryError(f"Input không tồn tại: {in_path}")
    if in_path.is_file():
        if in_path.suffix.casefold() != ".md":
            raise SummaryError(f"Input phải là file .md: {in_path}")
        return in_path, [in_path]
    if not in_path.is_dir():
        raise SummaryError(f"Input không hợp lệ: {in_path}")
    files = sorted(
        (item for item in in_path.rglob("*.md") if item.is_file()),
        key=lambda item: str(item.relative_to(in_path)).casefold(),
    )
    if not files:
        raise SummaryError(f"Không tìm thấy Markdown trong: {in_path}")
    return in_path, files


def sumName(path: Path) -> str:
    return f"{path.stem}_sum.md"


def makeJobs(
    in_path: Path,
    files: list[Path],
    out_arg: Path | None,
) -> list[FileJob]:
    if in_path.is_file():
        if out_arg is None:
            out_path = in_path.parent.parent / "sum" / sumName(in_path)
        else:
            target = out_arg.expanduser().resolve()
            if target.suffix.casefold() == ".md" and not target.is_dir():
                out_path = target
            else:
                out_path = target / sumName(in_path)
        if out_path.resolve() == in_path.resolve():
            raise SummaryError("Output không được trùng với input.")
        return [FileJob(in_path, out_path)]

    out_root = (
        out_arg.expanduser().resolve()
        if out_arg is not None
        else in_path.parent / "sum"
    )
    if out_root.exists() and not out_root.is_dir():
        raise SummaryError(f"Output phải là thư mục: {out_root}")

    jobs: list[FileJob] = []
    outputs: set[Path] = set()
    for src_path in files:
        rel_path = src_path.relative_to(in_path)
        out_path = out_root / rel_path.parent / sumName(src_path)
        out_key = out_path.resolve()
        if out_key in outputs:
            raise SummaryError(f"Trùng output: {out_path}")
        if out_key == src_path.resolve():
            raise SummaryError(f"Output trùng input: {src_path}")
        outputs.add(out_key)
        jobs.append(FileJob(src_path, out_path))
    return jobs


def fenceMark(line: str) -> str | None:
    match = re.match(r"^\s*(`{3,}|~{3,})", line)
    return match.group(1) if match else None


def splitHeading(text: str, level: int) -> list[str]:
    pattern = re.compile(rf"^#{{{level}}}(?!#)\s+")
    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        if fence is None and pattern.match(line) and current:
            value = "".join(current).strip()
            if value:
                blocks.append(value)
            current = []
        current.append(line)
    value = "".join(current).strip()
    if value:
        blocks.append(value)
    return blocks


def splitParas(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        if fence is None and not line.strip():
            value = "".join(current).strip()
            if value:
                parts.append(value)
            current = []
            continue
        current.append(line)
    value = "".join(current).strip()
    if value:
        parts.append(value)
    return parts


def promptFits(template: str, content: str, limit: int) -> bool:
    return countChars(fillPrompt(template, content)) <= limit


def hardSplit(
    text: str,
    template: str,
    limit: int,
) -> list[str]:
    if promptFits(template, text, limit):
        return [text]
    if not promptFits(template, "x", limit):
        raise SummaryError("Prompt template đã vượt giới hạn ký tự an toàn.")

    pieces: list[str] = []
    remain = text
    while remain:
        low = 1
        high = len(remain)
        best = 0
        while low <= high:
            middle = (low + high) // 2
            if promptFits(template, remain[:middle], limit):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best < 1:
            raise SummaryError("Không thể chia nội dung dưới giới hạn ký tự.")

        cut = best
        if best < len(remain):
            floor = max(1, int(best * 0.75))
            candidates = (
                remain.rfind("\n", floor, best),
                remain.rfind(" ", floor, best),
            )
            cut = max(candidates)
            if cut < floor:
                cut = best
        piece = remain[:cut].strip()
        if piece:
            pieces.append(piece)
        remain = remain[cut:].lstrip()
    return pieces


def splitLarge(
    text: str,
    template: str,
    limit: int,
    min_level: int = 3,
) -> list[str]:
    if promptFits(template, text, limit):
        return [text]
    for level in range(min_level, 7):
        parts = splitHeading(text, level)
        if len(parts) > 1:
            output: list[str] = []
            for part in parts:
                output.extend(splitLarge(part, template, limit, level + 1))
            return output
    paras = splitParas(text)
    if len(paras) > 1:
        output = []
        for para in paras:
            output.extend(splitLarge(para, template, limit, 7))
        return output
    return hardSplit(text, template, limit)


def makeChunks(
    content: str,
    template: str,
    limit: int = SAFE_LIMIT,
) -> list[str]:
    if not content.strip():
        raise SummaryError("Markdown input rỗng.")
    if countChars(fillPrompt(template, "")) >= limit:
        raise SummaryError("Prompt template không còn đủ chỗ cho nội dung.")
    if promptFits(template, content, limit):
        return [content]

    blocks = splitHeading(content, 2)
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(splitLarge(block, template, limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}\n\n{piece}"
        if current and not promptFits(template, candidate, limit):
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    if not chunks or any(not promptFits(template, item, limit) for item in chunks):
        raise SummaryError("Chia chunk thất bại hoặc vẫn vượt giới hạn ký tự.")
    return chunks


def getExe(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise SummaryError(
            f"Không tìm thấy {name!r} trong PATH. Hãy cài đặt và đăng nhập CLI."
        )
    return executable


def runProc(
    args: Sequence[str],
    payload: str,
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(args),
            input=payload,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SummaryError(f"CLI timeout sau {timeout} giây: {args[0]}") from exc
    except OSError as exc:
        raise SummaryError(f"Không thể chạy CLI {args[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if not detail:
            detail = f"exit code={result.returncode}"
        raise SummaryError(f"CLI thất bại ({args[0]}): {detail[-4000:]}")
    return result


def cleanOutput(text: str) -> str:
    value = text.strip().lstrip("\ufeff")
    match = re.fullmatch(
        r"```(?:markdown|md)?\s*\n([\s\S]*?)\n```",
        value,
        re.IGNORECASE,
    )
    if match:
        value = match.group(1).strip()
    return value


def parseCodex(stdout: str) -> str:
    messages: list[str] = []
    errors: list[str] = []
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line.strip())
        except (json.JSONDecodeError, AttributeError):
            continue
        event_type = event.get("type")
        if event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                messages.append(str(item["text"]))
            elif item.get("type") == "error" and item.get("message"):
                errors.append(str(item["message"]))
        elif event_type in {"error", "turn.failed"}:
            error = event.get("message") or event.get("error")
            if error:
                errors.append(str(error))
    output = cleanOutput(messages[-1] if messages else "")
    if not output:
        detail = " | ".join(errors[-3:]) or stdout[-2000:]
        raise SummaryError(f"Codex không trả về summary: {detail}")
    return output


def parseClaude(stdout: str) -> str:
    data: dict[str, object] | None = None
    stripped = stdout.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            data = value
    except json.JSONDecodeError:
        for line in reversed(stripped.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                data = value
                break
    if data is None:
        raise SummaryError(f"Không parse được output Claude: {stripped[-2000:]}")
    if data.get("is_error") is True:
        raise SummaryError(f"Claude trả về lỗi: {data.get('result') or data}")
    output = cleanOutput(str(data.get("result") or ""))
    if not output:
        raise SummaryError("Claude không trả về summary.")
    return output


def runCodex(payload: str, cwd: Path, timeout: int) -> str:
    executable = getExe("codex")
    result = runProc(
        [
            executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-",
        ],
        payload,
        cwd,
        timeout,
    )
    return parseCodex(result.stdout)


def runClaude(payload: str, cwd: Path, timeout: int) -> str:
    executable = getExe("claude")
    result = runProc(
        [executable, "-p", "--output-format", "json"],
        payload,
        cwd,
        timeout,
    )
    return parseClaude(result.stdout)


def runModel(model: str, payload: str, cwd: Path, timeout: int) -> str:
    if model == "codex":
        return runCodex(payload, cwd, timeout)
    if model == "claude":
        return runClaude(payload, cwd, timeout)
    raise SummaryError(f"Backend không được hỗ trợ: {model}")


def isTermHead(line: str) -> bool:
    return bool(TERM_RE.match(line.strip()))


def takeTerms(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    kept: list[str] = []
    term_bodies: list[str] = []
    index = 0
    fence: str | None = None
    while index < len(lines):
        line = lines[index]
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        if fence is None and isTermHead(line):
            index += 1
            body: list[str] = []
            inner_fence: str | None = None
            while index < len(lines):
                item = lines[index]
                inner_mark = fenceMark(item)
                if inner_mark:
                    if inner_fence is None:
                        inner_fence = inner_mark[0]
                    elif inner_mark[0] == inner_fence:
                        inner_fence = None
                head = HEAD_RE.match(item)
                if inner_fence is None and head and len(head.group(1)) == 2:
                    break
                body.append(item)
                index += 1
            value = "\n".join(body).strip()
            if value:
                term_bodies.append(value)
            continue
        kept.append(line)
        index += 1
    return "\n".join(kept).strip(), term_bodies


def tableCells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def termItems(body: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []

    def flushItem() -> None:
        if current:
            value = "\n".join(current).strip()
            if value:
                items.append(value)
            current.clear()

    for line in body.splitlines():
        cells = tableCells(line)
        if cells is not None:
            flushItem()
            if not cells or all(TABLE_SEP.match(cell) for cell in cells):
                continue
            first = re.sub(r"[*_`]", "", cells[0]).strip()
            if first.casefold() in {"thuật ngữ", "term", "terms"}:
                continue
            desc = " | ".join(cells[1:]).strip()
            value = f"- **{first}**"
            if desc:
                value += f": {desc}"
            items.append(value)
        elif BULLET_RE.match(line):
            flushItem()
            current.append(line.strip())
        elif not line.strip():
            flushItem()
        else:
            current.append(line.strip())
    flushItem()

    output: list[str] = []
    for item in items:
        if BULLET_RE.match(item):
            output.append(item)
        else:
            output.append(f"- {item.replace(chr(10), ' ')}")
    return output


def termKey(item: str) -> str:
    value = BULLET_RE.sub("", item.strip(), count=1)
    bold = re.match(r"\*\*(.+?)\*\*", value)
    if bold:
        value = bold.group(1)
    else:
        value = re.split(r"\s*(?::|—|–|\s-\s)\s*", value, maxsplit=1)[0]
    value = re.sub(r"[*_`\[\]()#]", "", value)
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.casefold().split()).strip(" .:;,-")


def dropDupMain(text: str, seen: set[str]) -> str:
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        head = HEAD_RE.match(line)
        if fence is None and head and len(head.group(1)) == 1:
            key = " ".join(head.group(2).casefold().split())
            if key in seen:
                continue
            seen.add(key)
        output.append(line)
    return "\n".join(output).strip()


def addTerms(body: str, terms: list[str]) -> str:
    if not terms:
        return body.strip() + "\n"
    term_block = "## 0. Các thuật ngữ sử dụng\n\n" + "\n".join(terms)
    lines = body.strip().splitlines()
    fence: str | None = None
    for index, line in enumerate(lines):
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        head = HEAD_RE.match(line)
        if fence is None and head and len(head.group(1)) == 1:
            before = "\n".join(lines[: index + 1]).strip()
            after = "\n".join(lines[index + 1 :]).strip()
            parts = [before, term_block]
            if after:
                parts.append(after)
            return "\n\n".join(parts).rstrip() + "\n"
    return f"{term_block}\n\n{body.strip()}\n"


def mergeResults(results: list[str]) -> str:
    if not results:
        raise SummaryError("Không có kết quả chunk để ghép.")
    bodies: list[str] = []
    terms: list[str] = []
    term_keys: set[str] = set()
    main_heads: set[str] = set()

    for result in results:
        body, term_bodies = takeTerms(cleanOutput(result))
        clean_body = dropDupMain(body, main_heads)
        if clean_body:
            bodies.append(clean_body)
        for term_body in term_bodies:
            for item in termItems(term_body):
                key = termKey(item)
                if key and key not in term_keys:
                    term_keys.add(key)
                    terms.append(item)

    merged = "\n\n".join(bodies).strip()
    if not merged and not terms:
        raise SummaryError("Kết quả model rỗng sau khi ghép.")
    return addTerms(merged, terms)


def writeAtomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except OSError as exc:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise SummaryError(f"Không thể ghi output {path}: {exc}") from exc


def processFile(
    job: FileJob,
    template: str,
    model: str,
    cwd: Path,
) -> int:
    try:
        content = job.src_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SummaryError(f"Không thể đọc {job.src_path}: {exc}") from exc
    chunks = makeChunks(content, template)
    results: list[str] = []
    for chunk_id, chunk in enumerate(chunks, start=1):
        payload = fillPrompt(template, chunk)
        char_num = countChars(payload)
        if char_num > CHAR_LIMIT:
            raise SummaryError(
                f"Chunk {chunk_id} vượt giới hạn tuyệt đối: {char_num:,} ký tự."
            )
        if char_num > SAFE_LIMIT:
            raise SummaryError(
                f"Chunk {chunk_id} vượt ngưỡng an toàn: {char_num:,} ký tự."
            )
        print(f"  chunk {chunk_id}/{len(chunks)} ({char_num:,} chars)")
        results.append(runModel(model, payload, cwd, REQ_TIMEOUT))
    summary = mergeResults(results)
    writeAtomic(job.out_path, summary)
    return len(chunks)


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
        in_path, files = getMdFiles(args.input_path)
        jobs = makeJobs(in_path, files, args.output_path)
        template = loadPrompt()
        cwd = getRoot()
    except SummaryError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    done = 0
    skipped = 0
    failed: list[tuple[Path, str]] = []
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {job.src_path} | model={args.model}")
        if job.out_path.exists() and not args.overwrite:
            print(f"  [SKIP] {job.out_path}")
            skipped += 1
            continue
        try:
            chunk_num = processFile(job, template, args.model, cwd)
            print(f"  [DONE] chunks={chunk_num} -> {job.out_path}")
            done += 1
        except (SummaryError, OSError) as exc:
            print(f"  [ERROR] {exc}", file=sys.stderr)
            failed.append((job.src_path, str(exc)))
        except KeyboardInterrupt:
            print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
            return 130

    print(
        f"Completed: files={len(jobs)}, summarized={done}, "
        f"skipped={skipped}, failed={len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
