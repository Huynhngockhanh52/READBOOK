#!/usr/bin/env python3
"""Convert summary Markdown into validated slide-section Markdown."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence


yaml_err: Exception | None = None
try:
    import yaml
except ImportError as exc:
    yaml = None
    yaml_err = exc


CHAR_LIMIT = 125_000
SAFE_LIMIT = 120_000
REQ_TIMEOUT = 1_800
MODEL_OPTS = ("codex", "claude")
LAYOUT_TAGS = (
    "{{LAYOUT_CONFIG}}",
    "{{LAYOUTS_AND_RULES}}",
    "{{LAYOUTS}}",
)
SUMMARY_TAGS = (
    "{{SUMMARY_CONTENT}}",
    "{{MARKDOWN_CONTENT}}",
)
SLIDE_RE = re.compile(
    r"^##\s+SLIDE\s+(\d+)\.\s+(.+?)\s*$",
    re.IGNORECASE,
)
SCRIPT_RE = re.compile(r"^\*\*Script:\*\*\s*(.*)$", re.IGNORECASE)
FIELD_RE = re.compile(r"^###\s+(.+?)\s*$")


class SlideError(RuntimeError):
    """Raised when slide Markdown cannot be generated or validated safely."""


@dataclass(frozen=True)
class FileJob:
    src_path: Path
    out_path: Path


@dataclass(frozen=True)
class SlideData:
    number: int
    layout: str
    script: str
    fields: dict[str, str]
    chunk_id: int = 1


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def getRoot() -> Path:
    return Path(__file__).resolve().parents[2]


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chuyển summary Markdown thành nội dung slide đã validate.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        default=Path("sum"),
        help="File summary .md hoặc thư mục chứa summary.",
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
        help="CLI backend dùng để tạo nội dung slide.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè Markdown slide đã tồn tại.",
    )
    return parser.parse_args(argv)


def needYaml() -> None:
    if yaml_err is not None or yaml is None:
        raise SlideError("Thiếu dependency PyYAML. Hãy chạy: pip install PyYAML") from yaml_err


def loadConfig() -> tuple[dict[str, tuple[str, ...]], Any, str]:
    needYaml()
    path = Path(__file__).resolve().parent / "conf" / "base_book.yaml"
    if not path.is_file():
        raise SlideError(f"Không tìm thấy layout config: {path}")
    try:
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SlideError(f"Không thể đọc YAML {path}: {exc}") from exc
    if not isinstance(raw_data, dict):
        raise SlideError("base_book.yaml phải chứa mapping ở cấp cao nhất.")

    raw_layouts = raw_data.get("layouts")
    if not isinstance(raw_layouts, dict) or not raw_layouts:
        raise SlideError("base_book.yaml thiếu mapping layouts.")
    layouts: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_fields in raw_layouts.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise SlideError(f"Tên layout không hợp lệ: {raw_name!r}")
        name = raw_name.strip()
        if not isinstance(raw_fields, list):
            raise SlideError(f"layouts[{name!r}] phải là list placeholder.")
        fields: list[str] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, str) or not raw_field.strip():
                raise SlideError(f"Placeholder không hợp lệ trong layout {name!r}.")
            field = raw_field.strip()
            if field in fields:
                raise SlideError(f"Placeholder {field!r} bị lặp trong layout {name!r}.")
            fields.append(field)
        layouts[name] = tuple(fields)

    rules = raw_data.get("layout_rules")
    request_data = {"layouts": raw_layouts, "layout_rules": rules}
    try:
        config_text = yaml.safe_dump(
            request_data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
    except yaml.YAMLError as exc:
        raise SlideError(f"Không thể serialize layout config: {exc}") from exc
    return layouts, rules, config_text


def loadPrompt() -> str:
    path = getRoot() / "instruction" / "sum2slide.md"
    if not path.is_file():
        raise SlideError(f"Không tìm thấy prompt: {path}")
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SlideError(f"Không thể đọc prompt {path}: {exc}") from exc
    if not prompt:
        raise SlideError(f"Prompt rỗng: {path}")
    return prompt


def injectData(
    prompt: str,
    tags: Sequence[str],
    value: str,
    label: str,
) -> str:
    found: list[str] = []
    for tag in tags:
        found.extend([tag] * prompt.count(tag))
    if len(found) > 1:
        names = ", ".join(found)
        raise SlideError(f"Prompt chứa nhiều placeholder cho {label}: {names}")
    if found:
        return prompt.replace(found[0], value)
    return f"{prompt.rstrip()}\n\n<{label}>\n{value}\n</{label}>"


def buildRequest(prompt: str, config: str, summary: str) -> str:
    request = injectData(prompt, LAYOUT_TAGS, config, "LAYOUT_CONFIG")
    return injectData(request, SUMMARY_TAGS, summary, "SUMMARY_MARKDOWN")


def getMdFiles(path: Path) -> tuple[Path, list[Path]]:
    in_path = path.expanduser().resolve()
    if not in_path.exists():
        raise SlideError(f"Input không tồn tại: {in_path}")
    if in_path.is_file():
        if in_path.suffix.casefold() != ".md":
            raise SlideError(f"Input phải là file .md: {in_path}")
        return in_path, [in_path]
    if not in_path.is_dir():
        raise SlideError(f"Input không hợp lệ: {in_path}")
    files = sorted(
        (item for item in in_path.rglob("*.md") if item.is_file()),
        key=lambda item: str(item.relative_to(in_path)).casefold(),
    )
    if not files:
        raise SlideError(f"Không tìm thấy summary Markdown trong: {in_path}")
    return in_path, files


def slideName(path: Path) -> str:
    stem = path.stem
    if stem.casefold().endswith("_sum"):
        stem = stem[:-4]
    return f"{stem}_slide.md"


def makeJobs(
    in_path: Path,
    files: list[Path],
    out_arg: Path | None,
) -> list[FileJob]:
    if in_path.is_file():
        if out_arg is None:
            out_path = in_path.parent.parent / "section" / slideName(in_path)
        else:
            target = out_arg.expanduser().resolve()
            if target.suffix.casefold() == ".md" and not target.is_dir():
                out_path = target
            else:
                out_path = target / slideName(in_path)
        if out_path.resolve() == in_path.resolve():
            raise SlideError("Output không được trùng với input.")
        return [FileJob(in_path, out_path)]

    out_root = (
        out_arg.expanduser().resolve()
        if out_arg is not None
        else in_path.parent / "section"
    )
    if out_root.exists() and not out_root.is_dir():
        raise SlideError(f"Output phải là thư mục: {out_root}")

    jobs: list[FileJob] = []
    outputs: set[Path] = set()
    for src_path in files:
        rel_path = src_path.relative_to(in_path)
        out_path = out_root / rel_path.parent / slideName(src_path)
        out_key = out_path.resolve()
        if out_key in outputs:
            raise SlideError(f"Trùng output: {out_path}")
        if out_key == src_path.resolve():
            raise SlideError(f"Output trùng input: {src_path}")
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


def requestFits(
    prompt: str,
    config: str,
    summary: str,
    limit: int,
) -> bool:
    return len(buildRequest(prompt, config, summary)) <= limit


def hardSplit(
    text: str,
    prompt: str,
    config: str,
    limit: int,
) -> list[str]:
    if requestFits(prompt, config, text, limit):
        return [text]
    if not requestFits(prompt, config, "x", limit):
        raise SlideError("Prompt và layout config đã vượt giới hạn ký tự an toàn.")

    pieces: list[str] = []
    remain = text
    while remain:
        low = 1
        high = len(remain)
        best = 0
        while low <= high:
            middle = (low + high) // 2
            if requestFits(prompt, config, remain[:middle], limit):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best < 1:
            raise SlideError("Không thể chia summary dưới giới hạn request.")
        cut = best
        if best < len(remain):
            floor = max(1, int(best * 0.75))
            cut = max(
                remain.rfind("\n", floor, best),
                remain.rfind(" ", floor, best),
            )
            if cut < floor:
                cut = best
        piece = remain[:cut].strip()
        if piece:
            pieces.append(piece)
        remain = remain[cut:].lstrip()
    return pieces


def splitLarge(
    text: str,
    prompt: str,
    config: str,
    limit: int,
    min_level: int = 3,
) -> list[str]:
    if requestFits(prompt, config, text, limit):
        return [text]
    for level in range(min_level, 7):
        parts = splitHeading(text, level)
        if len(parts) > 1:
            output: list[str] = []
            for part in parts:
                output.extend(
                    splitLarge(part, prompt, config, limit, level + 1)
                )
            return output
    paras = splitParas(text)
    if len(paras) > 1:
        output = []
        for para in paras:
            output.extend(splitLarge(para, prompt, config, limit, 7))
        return output
    return hardSplit(text, prompt, config, limit)


def makeChunks(
    summary: str,
    prompt: str,
    config: str,
    limit: int = SAFE_LIMIT,
) -> list[str]:
    if not summary.strip():
        raise SlideError("Summary Markdown rỗng.")
    if not requestFits(prompt, config, "", limit):
        raise SlideError("Prompt và layout config không còn chỗ cho summary.")
    if requestFits(prompt, config, summary, limit):
        return [summary]

    blocks = splitHeading(summary, 2)
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(splitLarge(block, prompt, config, limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}\n\n{piece}"
        if current and not requestFits(prompt, config, candidate, limit):
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    if not chunks or any(
        not requestFits(prompt, config, chunk, limit) for chunk in chunks
    ):
        raise SlideError("Chia request thất bại hoặc vẫn vượt giới hạn.")
    return chunks


def getExe(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise SlideError(
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
        raise SlideError(f"CLI timeout sau {timeout} giây: {args[0]}") from exc
    except OSError as exc:
        raise SlideError(f"Không thể chạy CLI {args[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if not detail:
            detail = f"exit code={result.returncode}"
        raise SlideError(f"CLI thất bại ({args[0]}): {detail[-4000:]}")
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
        raise SlideError(f"Codex không trả về nội dung slide: {detail}")
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
        raise SlideError(f"Không parse được output Claude: {stripped[-2000:]}")
    if data.get("is_error") is True:
        raise SlideError(f"Claude trả về lỗi: {data.get('result') or data}")
    output = cleanOutput(str(data.get("result") or ""))
    if not output:
        raise SlideError("Claude không trả về nội dung slide.")
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
    raise SlideError(f"Backend không được hỗ trợ: {model}")


def splitSlides(text: str, chunk_id: int) -> list[tuple[int, str, list[str]]]:
    value = cleanOutput(text)
    blocks: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    preamble: list[str] = []
    fence: str | None = None

    for line in value.splitlines():
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        match = SLIDE_RE.match(line) if fence is None else None
        if match:
            if current is not None:
                blocks.append(current)
            current = (int(match.group(1)), match.group(2).strip(), [])
        elif current is None:
            preamble.append(line)
        else:
            current[2].append(line)
    if current is not None:
        blocks.append(current)

    if any(line.strip() for line in preamble):
        detail = " ".join(line.strip() for line in preamble if line.strip())
        raise SlideError(
            f"Chunk {chunk_id}: có nội dung ngoài slide trước SLIDE 1: {detail[:200]}"
        )
    if not blocks:
        raise SlideError(f"Chunk {chunk_id}: không tìm thấy header '## SLIDE N. <layout>'.")
    return blocks


def parseSlide(
    raw_slide: tuple[int, str, list[str]],
    chunk_id: int,
) -> SlideData:
    number, layout, lines = raw_slide
    script: str | None = None
    fields: dict[str, str] = {}
    mode: str | None = None
    field_name: str | None = None
    buffer: list[str] = []
    fence: str | None = None

    def flushValue() -> None:
        nonlocal script, field_name, buffer
        value = "\n".join(buffer).strip()
        if mode == "script":
            if script is not None:
                raise SlideError(
                    f"Chunk {chunk_id}, slide {number}: Script xuất hiện nhiều lần."
                )
            script = value
        elif mode == "field" and field_name is not None:
            if field_name in fields:
                raise SlideError(
                    f"Chunk {chunk_id}, slide {number}: placeholder "
                    f"{field_name!r} xuất hiện nhiều lần."
                )
            fields[field_name] = value
        elif value:
            raise SlideError(
                f"Chunk {chunk_id}, slide {number}: nội dung không thuộc Script "
                f"hoặc placeholder: {value[:160]}"
            )
        buffer = []
        field_name = None

    for line in lines:
        mark = fenceMark(line)
        if mark:
            if fence is None:
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
        script_match = SCRIPT_RE.match(line) if fence is None else None
        field_match = FIELD_RE.match(line) if fence is None else None
        if script_match:
            flushValue()
            mode = "script"
            first_line = script_match.group(1).strip()
            if first_line:
                buffer.append(first_line)
        elif field_match:
            flushValue()
            mode = "field"
            field_name = field_match.group(1).strip()
            if not field_name:
                raise SlideError(
                    f"Chunk {chunk_id}, slide {number}: placeholder rỗng."
                )
        else:
            buffer.append(line)
    flushValue()

    if script is None:
        raise SlideError(f"Chunk {chunk_id}, slide {number}: thiếu **Script:**.")
    if not script:
        raise SlideError(f"Chunk {chunk_id}, slide {number}: Script rỗng.")
    return SlideData(number, layout, script, fields, chunk_id)


def parseSlides(text: str, chunk_id: int = 1) -> list[SlideData]:
    raw_slides = splitSlides(text, chunk_id)
    slides = [parseSlide(raw_slide, chunk_id) for raw_slide in raw_slides]
    for index in range(1, len(slides)):
        previous = slides[index - 1].number
        current = slides[index].number
        if current != previous + 1:
            raise SlideError(
                f"Chunk {chunk_id}: số slide không liên tục: {previous} -> {current}."
            )
    return slides


def validateSlides(
    slides: list[SlideData],
    layouts: dict[str, tuple[str, ...]],
) -> None:
    if not slides:
        raise SlideError("Không có slide để validate.")
    for index, slide in enumerate(slides, start=1):
        if slide.number != index:
            raise SlideError(
                f"Slide {slide.number}: thứ tự sau khi ghép phải là {index}."
            )
        if slide.layout not in layouts:
            names = ", ".join(layouts)
            raise SlideError(
                f"Slide {slide.number}: layout {slide.layout!r} không tồn tại. "
                f"Layouts hợp lệ: {names}"
            )
        allowed = set(layouts[slide.layout])
        for field in slide.fields:
            if field not in allowed:
                fields = ", ".join(layouts[slide.layout])
                raise SlideError(
                    f"Slide {slide.number}, layout {slide.layout!r}: placeholder "
                    f"{field!r} không hợp lệ. Cho phép: {fields}"
                )


def mergeSlides(chunks: list[list[SlideData]]) -> list[SlideData]:
    merged: list[SlideData] = []
    for chunk in chunks:
        for slide in chunk:
            merged.append(replace(slide, number=len(merged) + 1))
    return merged


def renderSlides(slides: list[SlideData]) -> str:
    blocks: list[str] = []
    for slide in slides:
        lines = [
            f"## SLIDE {slide.number}. {slide.layout}",
            "",
            f"**Script:** {slide.script}",
        ]
        for field, content in slide.fields.items():
            lines.extend(["", f"### {field}", "", content])
        blocks.append("\n".join(lines).rstrip())
    return "\n\n".join(blocks).rstrip() + "\n"


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
        raise SlideError(f"Không thể ghi output {path}: {exc}") from exc


def processFile(
    job: FileJob,
    prompt: str,
    config: str,
    layouts: dict[str, tuple[str, ...]],
    model: str,
    cwd: Path,
) -> tuple[int, int]:
    try:
        summary = job.src_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SlideError(f"Không thể đọc {job.src_path}: {exc}") from exc

    chunks = makeChunks(summary, prompt, config)
    parsed_chunks: list[list[SlideData]] = []
    for chunk_id, chunk in enumerate(chunks, start=1):
        payload = buildRequest(prompt, config, chunk)
        char_num = len(payload)
        if char_num > CHAR_LIMIT:
            raise SlideError(
                f"Chunk {chunk_id} vượt giới hạn tuyệt đối: {char_num:,} ký tự."
            )
        if char_num > SAFE_LIMIT:
            raise SlideError(
                f"Chunk {chunk_id} vượt ngưỡng an toàn: {char_num:,} ký tự."
            )
        print(f"  chunk {chunk_id}/{len(chunks)} ({char_num:,} chars)")
        output = runModel(model, payload, cwd, REQ_TIMEOUT)
        parsed_chunks.append(parseSlides(output, chunk_id))

    slides = mergeSlides(parsed_chunks)
    validateSlides(slides, layouts)
    markdown = renderSlides(slides)
    # Parse the canonical output once more before committing it to disk.
    final_slides = parseSlides(markdown)
    validateSlides(final_slides, layouts)
    writeAtomic(job.out_path, markdown)
    return len(chunks), len(slides)


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
        in_path, files = getMdFiles(args.input_path)
        jobs = makeJobs(in_path, files, args.output_path)
        layouts, _, config = loadConfig()
        prompt = loadPrompt()
        cwd = getRoot()
    except SlideError as exc:
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
            chunk_num, slide_num = processFile(
                job,
                prompt,
                config,
                layouts,
                args.model,
                cwd,
            )
            print(
                f"  [DONE] chunks={chunk_num}, slides={slide_num} "
                f"-> {job.out_path}"
            )
            done += 1
        except (SlideError, OSError) as exc:
            print(f"  [ERROR] {exc}", file=sys.stderr)
            failed.append((job.src_path, str(exc)))
        except KeyboardInterrupt:
            print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
            return 130

    print(
        f"Completed: files={len(jobs)}, generated={done}, "
        f"skipped={skipped}, failed={len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
