#!/usr/bin/env python3
"""Chuyển XHTML đã tách từ EPUB thành TXT có cấu trúc Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from lxml import etree
except ImportError as exc:
    etree = None
    dep_err: Exception | None = exc
else:
    dep_err = None


BLOCK_SEP = "=========="
CHAR_LIMIT = 50_000
EPUB_NS = "http://www.idpf.org/2007/ops"
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
SKIP_TAGS = {"head", "script", "style", "noscript", "template"}
NOTE_CLASSES = {
    "admonition",
    "caution",
    "important",
    "note",
    "sidebar",
    "tip",
    "warning",
}
DOC_CLASSES = {
    "appendix",
    "bibliography",
    "chapter",
    "colophon",
    "dedication",
    "glossary",
    "index",
    "part",
    "preface",
    "prologue",
}


class ConvertError(RuntimeError):
    """Lỗi khiến XHTML không thể chuyển đổi an toàn."""


@dataclass(frozen=True)
class FileJob:
    """Một XHTML nguồn và TXT đích tương ứng."""

    src_path: Path
    out_path: Path


@dataclass(frozen=True)
class ConvResult:
    """Kết quả và thống kê của một file đã chuyển đổi."""

    src_path: Path
    out_path: Path
    title: str
    block_num: int
    chunk_num: int
    over_num: int
    char_num: int
    src_hash: str
    out_hash: str


@dataclass(frozen=True)
class RenderCtx:
    """Ngữ cảnh dùng để chuẩn hóa cấp heading."""

    first_head: Any | None
    base_level: int


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def getRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chuyển XHTML EPUB thành TXT có cấu trúc Markdown.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "xhtml_arg",
        nargs="?",
        type=Path,
        help="Một XHTML/HTML hoặc thư mục part (rút gọn thay cho -i).",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        help="Một XHTML/HTML hoặc thư mục chứa các part.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="out_path",
        type=Path,
        help="File TXT hoặc thư mục text đầu ra.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=CHAR_LIMIT,
        help="Giới hạn ký tự một translation chunk.",
    )
    parser.add_argument(
        "--manifest",
        dest="mani_path",
        type=Path,
        help="Manifest cần cập nhật; mặc định tự tìm cạnh part/.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè TXT đã tồn tại.",
    )
    return parser.parse_args(argv)


def getInput(args: argparse.Namespace) -> Path:
    if args.input_path and args.xhtml_arg:
        raise ConvertError("Chỉ truyền input một lần: dùng -i hoặc positional.")
    in_path = args.input_path or args.xhtml_arg
    if in_path is None:
        raise ConvertError("Thiếu XHTML hoặc thư mục đầu vào.")
    in_path = in_path.expanduser().resolve()
    if not in_path.exists():
        raise ConvertError(f"Input không tồn tại: {in_path}")
    if in_path.is_file() and in_path.suffix.lower() not in {".xhtml", ".html", ".htm"}:
        raise ConvertError(f"Input phải là XHTML/HTML: {in_path}")
    if not in_path.is_file() and not in_path.is_dir():
        raise ConvertError(f"Input không hợp lệ: {in_path}")
    return in_path


def findHtml(in_path: Path) -> list[Path]:
    if in_path.is_file():
        return [in_path]
    files = sorted(
        (
            path
            for path in in_path.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".xhtml", ".html", ".htm"}
        ),
        key=lambda path: str(path.relative_to(in_path)).casefold(),
    )
    if not files:
        raise ConvertError(f"Không tìm thấy XHTML/HTML trong: {in_path}")
    return files


def outFileName(src_path: Path) -> str:
    stem = re.sub(r"(?i)_text$", "", src_path.stem)
    return f"{stem}_text.txt"


def getOutDir(in_path: Path, out_arg: Path | None) -> Path:
    if out_arg is not None:
        out_path = out_arg.expanduser().resolve()
        if in_path.is_dir() and out_path.suffix.lower() == ".txt":
            raise ConvertError("-o FILE.txt chỉ hợp lệ khi input là một file.")
        if in_path.is_dir() or out_path.suffix.lower() != ".txt":
            if out_path.exists() and not out_path.is_dir():
                raise ConvertError(f"Output phải là thư mục: {out_path}")
            return out_path
        return out_path.parent

    base_dir = in_path.parent if in_path.is_file() else in_path
    if base_dir.name.casefold() == "part":
        return base_dir.parent / "text"
    return base_dir / "text"


def makeJobs(
    in_path: Path,
    files: list[Path],
    out_arg: Path | None,
) -> list[FileJob]:
    out_dir = getOutDir(in_path, out_arg)
    direct_out: Path | None = None
    if in_path.is_file() and out_arg is not None:
        test_path = out_arg.expanduser().resolve()
        if test_path.suffix.lower() == ".txt":
            direct_out = test_path

    jobs: list[FileJob] = []
    seen_paths: set[Path] = set()
    for src_path in files:
        if direct_out is not None:
            target = direct_out
        elif in_path.is_dir():
            rel_dir = src_path.parent.relative_to(in_path)
            target = out_dir / rel_dir / outFileName(src_path)
        else:
            target = out_dir / outFileName(src_path)
        target = target.resolve()
        if target == src_path.resolve():
            raise ConvertError("Output không được trùng với XHTML đầu vào.")
        if target in seen_paths:
            raise ConvertError(f"Nhiều XHTML tạo cùng output: {target}")
        seen_paths.add(target)
        jobs.append(FileJob(src_path, target))
    return jobs


def localName(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.rsplit(":", 1)[-1].lower()


def classNames(node: Any) -> set[str]:
    return {
        name.casefold()
        for name in re.split(r"\s+", node.get("class", "").strip())
        if name
    }


def nodeText(node: Any | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def normInline(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def codeSpan(text: str) -> str:
    value = text.strip()
    runs = [len(match.group(0)) for match in re.finditer(r"`+", value)]
    fence = "`" * max(1, (max(runs) + 1) if runs else 1)
    pad = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def imageText(node: Any) -> str:
    alt = node.get("alt", "").strip() or node.get("title", "").strip()
    src = node.get("src", "").strip()
    alt = alt or "image"
    return f"![{alt}]({src})" if src else f"[Hình: {alt}]"


def inlineText(node: Any) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        tag = localName(child.tag)
        if tag in SKIP_TAGS:
            value = ""
        elif tag == "br":
            value = "  \n"
        elif tag in {"strong", "b"}:
            inner = inlineText(child)
            value = f"**{inner}**" if inner else ""
        elif tag in {"em", "i"}:
            inner = inlineText(child)
            value = f"*{inner}*" if inner else ""
        elif tag == "code":
            value = codeSpan("".join(child.itertext()))
        elif tag == "a":
            inner = inlineText(child) or child.get("title", "").strip()
            href = child.get("href", "").strip()
            value = f"[{inner}]({href})" if inner and href else inner
        elif tag == "img":
            value = imageText(child)
        elif tag in BLOCK_TAGS:
            value = nodeText(child)
        else:
            value = inlineText(child)
            raw_text = "".join(child.itertext())
            if value and raw_text:
                if raw_text[0].isspace():
                    value = f" {value}"
                if raw_text[-1].isspace():
                    value = f"{value} "
        if value:
            parts.append(value)
        if child.tail:
            parts.append(child.tail)
    return normInline("".join(parts))


def parseXhtml(path: Path) -> Any:
    if etree is None:
        raise ConvertError("Thiếu lxml. Cài bằng: python -m pip install lxml") from dep_err
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        huge_tree=False,
    )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConvertError(f"Không thể đọc XHTML {path}: {exc}") from exc
    try:
        return etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise ConvertError(f"XHTML không hợp lệ tại {path}: {exc}") from exc


def findBody(root: Any, path: Path) -> Any:
    for node in root.iter():
        if localName(node.tag) == "body":
            return node
    raise ConvertError(f"XHTML không có body: {path}")


def firstHeading(body: Any) -> Any | None:
    for node in body.iter():
        if localName(node.tag) in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if nodeText(node):
                return node
    return None


def getTitle(root: Any, first_head: Any | None, src_path: Path) -> str:
    if first_head is not None:
        title = inlineText(first_head)
        if title:
            return title
    for node in root.iter():
        if localName(node.tag) == "title":
            title = nodeText(node)
            if title:
                return title
    title = re.sub(r"[_-]+", " ", src_path.stem).strip()
    return title or src_path.stem


def getEpubType(node: Any) -> set[str]:
    raw_type = node.get(f"{{{EPUB_NS}}}type", "")
    return {value.casefold() for value in raw_type.split() if value}


def structLevel(node: Any) -> int | None:
    current = node
    while current is not None and localName(current.tag) != "body":
        classes = classNames(current)
        for name in classes:
            match = re.fullmatch(r"sect(?:ion)?[-_ ]?(\d+)", name)
            if match:
                return min(6, int(match.group(1)) + 1)
        if classes & DOC_CLASSES:
            return 1
        epub_type = getEpubType(current)
        if epub_type & DOC_CLASSES:
            return 1
        current = current.getparent()
    return None


def headLevel(node: Any, ctx: RenderCtx) -> int:
    struct_level = structLevel(node)
    if struct_level is not None:
        return struct_level
    tag = localName(node.tag)
    tag_level = int(tag[1])
    level = tag_level - ctx.base_level + 1
    level = max(1, min(6, level))
    if node is not ctx.first_head and level == 1:
        level = 2
    return level


def codeLang(node: Any) -> str:
    for current in (node, *node):
        for name in classNames(current):
            match = re.match(r"(?:language|lang)-([A-Za-z0-9_+.-]+)$", name)
            if match:
                return match.group(1)
    return ""


def renderPre(node: Any) -> str:
    code = "".join(node.itertext()).replace("\r\n", "\n").replace("\r", "\n")
    code = code.strip("\n")
    runs = [len(match.group(0)) for match in re.finditer(r"`+", code)]
    fence = "`" * max(3, (max(runs) + 1) if runs else 3)
    lang = codeLang(node)
    return f"{fence}{lang}\n{code}\n{fence}"


def quoteBlocks(blocks: list[str]) -> str:
    lines: list[str] = []
    for idx, block in enumerate(blocks):
        if idx:
            lines.append(">")
        for line in block.splitlines() or [""]:
            lines.append(f"> {line}" if line else ">")
    return "\n".join(lines)


def listItem(node: Any, ctx: RenderCtx) -> tuple[list[str], list[Any]]:
    blocks: list[str] = []
    nested: list[Any] = []
    if node.text and node.text.strip():
        blocks.append(normInline(node.text))
    for child in node:
        tag = localName(child.tag)
        if tag in {"ul", "ol"}:
            nested.append(child)
        elif tag in {"p", "div", "section"}:
            value = inlineText(child)
            if value:
                blocks.append(value)
        else:
            values = renderNode(child, ctx)
            blocks.extend(values)
        if child.tail and child.tail.strip():
            blocks.append(normInline(child.tail))
    return [value for value in blocks if value], nested


def renderList(node: Any, ctx: RenderCtx, depth: int = 0) -> str:
    ordered = localName(node.tag) == "ol"
    try:
        start_num = int(node.get("start", "1"))
    except ValueError:
        start_num = 1
    lines: list[str] = []
    items = [child for child in node if localName(child.tag) == "li"]
    for idx, item in enumerate(items):
        prefix = f"{start_num + idx}. " if ordered else "- "
        indent = "  " * depth
        blocks, nested = listItem(item, ctx)
        first = blocks[0] if blocks else ""
        first_lines = first.splitlines() or [""]
        lines.append(f"{indent}{prefix}{first_lines[0]}")
        pad = " " * len(prefix)
        for line in first_lines[1:]:
            lines.append(f"{indent}{pad}{line}")
        for block in blocks[1:]:
            for line in block.splitlines():
                lines.append(f"{indent}{pad}{line}")
        for child in nested:
            nested_text = renderList(child, ctx, depth + 1)
            if nested_text:
                lines.extend(nested_text.splitlines())
    return "\n".join(lines)


def tableCell(node: Any) -> str:
    value = inlineText(node).replace("|", r"\|")
    return value.replace("\n", "<br>")


def renderTable(node: Any) -> str:
    rows: list[list[str]] = []
    head_flags: list[bool] = []
    for row in node.iter():
        if localName(row.tag) != "tr":
            continue
        cells = [
            child
            for child in row
            if localName(child.tag) in {"th", "td"}
        ]
        if not cells:
            continue
        rows.append([tableCell(cell) for cell in cells])
        head_flags.append(any(localName(cell.tag) == "th" for cell in cells))
    if not rows:
        return nodeText(node)
    col_num = max(len(row) for row in rows)
    fixed = [row + [""] * (col_num - len(row)) for row in rows]
    if not head_flags[0]:
        fixed.insert(0, [f"Column {idx}" for idx in range(1, col_num + 1)])
    lines = ["| " + " | ".join(fixed[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(col_num)) + " |")
    for row in fixed[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def isPageBreak(node: Any) -> bool:
    epub_type = getEpubType(node)
    role = node.get("role", "").casefold()
    return "pagebreak" in epub_type or role == "doc-pagebreak"


def renderKids(node: Any, ctx: RenderCtx) -> list[str]:
    blocks: list[str] = []
    if node.text and node.text.strip():
        blocks.append(normInline(node.text))
    for child in node:
        blocks.extend(renderNode(child, ctx))
        if child.tail and child.tail.strip():
            blocks.append(normInline(child.tail))
    return [block for block in blocks if block.strip()]


def renderNode(node: Any, ctx: RenderCtx) -> list[str]:
    tag = localName(node.tag)
    if not tag or tag in SKIP_TAGS or isPageBreak(node):
        return []
    if tag == "nav":
        return []
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        if node is ctx.first_head:
            return []
        value = inlineText(node)
        if not value:
            return []
        return [f"{'#' * headLevel(node, ctx)} {value}"]
    if tag == "p":
        value = inlineText(node)
        return [value] if value else []
    if tag == "pre":
        return [renderPre(node)]
    if tag in {"ul", "ol"}:
        value = renderList(node, ctx)
        return [value] if value else []
    if tag == "blockquote":
        value = quoteBlocks(renderKids(node, ctx))
        return [value] if value else []
    if tag == "table":
        value = renderTable(node)
        return [value] if value else []
    if tag == "hr":
        return ["---"]
    if tag == "img":
        value = imageText(node)
        return [value] if value else []
    if tag == "figure":
        blocks = renderKids(node, ctx)
        return blocks
    if tag == "figcaption":
        value = inlineText(node)
        return [f"*{value}*"] if value else []
    if tag == "dl":
        return renderKids(node, ctx)
    if tag == "dt":
        value = inlineText(node)
        return [f"**{value}**"] if value else []
    if tag == "dd":
        blocks = renderKids(node, ctx)
        return [quoteBlocks(blocks)] if blocks else []
    if tag in {"math", "svg"}:
        if etree is None:
            return []
        value = etree.tostring(node, encoding="unicode", with_tail=False).strip()
        return [value] if value else []

    blocks = renderKids(node, ctx)
    if classNames(node) & NOTE_CLASSES and blocks:
        return [quoteBlocks(blocks)]
    return blocks


def toBlocks(src_path: Path) -> tuple[str, list[str]]:
    root = parseXhtml(src_path)
    body = findBody(root, src_path)
    first_head = firstHeading(body)
    title = getTitle(root, first_head, src_path)
    base_level = 1
    if first_head is not None:
        base_level = int(localName(first_head.tag)[1])
    ctx = RenderCtx(first_head, base_level)
    blocks = [f"# {title}"]
    blocks.extend(renderKids(body, ctx))
    clean_blocks: list[str] = []
    for block in blocks:
        value = block.strip()
        if value and (not clean_blocks or value != clean_blocks[-1]):
            clean_blocks.append(value)
    if len(clean_blocks) == 1 and clean_blocks[0] == f"# {title}":
        raise ConvertError(f"XHTML không có nội dung văn bản: {src_path}")
    return title, clean_blocks


def isHeading(block: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", block))


def blockSize(blocks: list[str]) -> int:
    return sum(len(block) for block in blocks) + 2 * max(0, len(blocks) - 1)


def packBlocks(blocks: list[str], limit: int) -> tuple[list[str], int]:
    chunks: list[str] = []
    current: list[str] = []
    over_num = 0
    for block in blocks:
        if len(block) > limit:
            over_num += 1
        trial = current + [block]
        if current and blockSize(trial) > limit:
            carry: list[str] = []
            while current and isHeading(current[-1]):
                carry.insert(0, current.pop())
            if current:
                chunks.append("\n\n".join(current))
                current = carry
            elif carry:
                current = carry
            if current and blockSize(current + [block]) > limit:
                chunks.append("\n\n".join(current))
                current = []
        current.append(block)
    if current:
        chunks.append("\n\n".join(current))
    return chunks, over_num


def makeText(chunks: list[str]) -> str:
    text = f"\n\n{BLOCK_SEP}\n\n".join(chunks)
    return f"{text.rstrip()}\n" if text.strip() else ""


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


def bytesHash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        raise ConvertError(f"Không thể tính SHA-256 của {path}: {exc}") from exc
    return digest.hexdigest()


def convertFile(job: FileJob, limit: int) -> ConvResult:
    title, blocks = toBlocks(job.src_path)
    chunks, over_num = packBlocks(blocks, limit)
    text = makeText(chunks)
    data = text.encode("utf-8")
    try:
        writeAtomic(job.out_path, data)
    except OSError as exc:
        raise ConvertError(f"Không thể ghi TXT {job.out_path}: {exc}") from exc
    return ConvResult(
        src_path=job.src_path,
        out_path=job.out_path,
        title=title,
        block_num=len(blocks),
        chunk_num=len(chunks),
        over_num=over_num,
        char_num=len(text),
        src_hash=fileHash(job.src_path),
        out_hash=bytesHash(data),
    )


def getManiPath(in_path: Path, mani_arg: Path | None) -> Path | None:
    if mani_arg is not None:
        mani_path = mani_arg.expanduser().resolve()
        if not mani_path.is_file():
            raise ConvertError(f"Không tìm thấy manifest: {mani_path}")
        return mani_path
    base_dir = in_path.parent if in_path.is_file() else in_path
    if base_dir.name.casefold() == "part":
        test_path = base_dir.parent / "manifest.json"
        if test_path.is_file():
            return test_path.resolve()
    return None


def readManifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConvertError(f"Không thể đọc manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("parts"), list):
        raise ConvertError(f"Manifest không có danh sách parts hợp lệ: {path}")
    return data


def relName(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def updateManifest(
    mani_path: Path,
    manifest: dict[str, Any],
    results: list[ConvResult],
    limit: int,
) -> int:
    base_dir = mani_path.parent
    result_map = {result.src_path.resolve(): result for result in results}
    updated = 0
    for part in manifest["parts"]:
        if not isinstance(part, dict) or not isinstance(part.get("output"), str):
            continue
        src_path = (base_dir / part["output"]).resolve()
        result = result_map.get(src_path)
        if result is None:
            continue
        part["text"] = {
            "output": relName(result.out_path, base_dir),
            "format": "markdown_in_txt",
            "title": result.title,
            "source_blocks": result.block_num,
            "translation_chunks": result.chunk_num,
            "oversized_blocks": result.over_num,
            "characters": result.char_num,
            "source_sha256": result.src_hash,
            "output_sha256": result.out_hash,
        }
        updated += 1
    manifest["text_conversion"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "separator": BLOCK_SEP,
        "updated_parts": updated,
    }
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        writeAtomic(mani_path, data)
    except OSError as exc:
        raise ConvertError(f"Không thể cập nhật manifest {mani_path}: {exc}") from exc
    return updated


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
        if dep_err is not None or etree is None:
            raise ConvertError("Thiếu lxml. Cài bằng: python -m pip install lxml") from dep_err
        if args.limit < 1:
            raise ConvertError("--limit phải > 0")
        in_path = getInput(args)
        files = findHtml(in_path)
        jobs = makeJobs(in_path, files, args.out_path)
        mani_path = getManiPath(in_path, args.mani_path)
        manifest = readManifest(mani_path) if mani_path is not None else None

        print(f"Input   : {in_path}")
        print(f"Files   : {len(jobs)}")
        print(f"Limit   : {args.limit}")
        print(f"Manifest: {mani_path or '(không tìm thấy, bỏ qua)'}")

        results: list[ConvResult] = []
        skipped = 0
        failed: list[tuple[Path, str]] = []
        for idx, job in enumerate(jobs, start=1):
            if job.out_path.exists() and not args.overwrite:
                skipped += 1
                print(f"[{idx}/{len(jobs)}] SKIP: {job.out_path.name}")
                continue
            try:
                result = convertFile(job, args.limit)
                results.append(result)
                print(
                    f"[{idx}/{len(jobs)}] {job.src_path.name} "
                    f"-> {job.out_path.name} | blocks={result.block_num}, "
                    f"chunks={result.chunk_num}, chars={result.char_num}"
                )
                if result.over_num:
                    print(
                        f"  WARNING: {result.over_num} block vượt --limit "
                        "và được giữ nguyên."
                    )
            except (ConvertError, OSError) as exc:
                failed.append((job.src_path, str(exc)))
                print(f"[{idx}/{len(jobs)}] ERROR: {job.src_path}: {exc}", file=sys.stderr)

        updated = 0
        if manifest is not None and mani_path is not None and results:
            updated = updateManifest(mani_path, manifest, results, args.limit)
            print(f"Manifest updated: {updated} part(s)")

        print(
            f"Completed: converted={len(results)}, skipped={skipped}, "
            f"failed={len(failed)}"
        )
        return 1 if failed else 0
    except ConvertError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Error: Đã dừng bởi người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
