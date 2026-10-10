#!/usr/bin/env python3
"""Convert edited DOCX chapters back to Markdown and extract captioned images."""

from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


dep_err: Exception | None = None
try:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run
    from PIL import Image
except ImportError as exc:
    dep_err = exc


HEAD_STYLES = {
    "heading 1": 1,
    "kc h2": 2,
    "kc h3": 3,
    "kc h4": 4,
    "heading 2": 2,
    "heading 3": 3,
    "heading 4": 4,
}
NORM_STYLE = "kc normal"
CODE_STYLE = "command"
DEF_STYLE = "kc def"
CAP_STYLES = {
    "caption",
    "figure caption",
    "image caption",
    "chú thích",
    "chú thích hình",
}
CAP_RE = re.compile(
    r"^\s*(?:hình|ảnh|figure|fig\.?|image|sơ\s+đồ|biểu\s+đồ)"
    r"(?:\s|\d|[.:–—-])",
    re.IGNORECASE,
)
LIST_RE = re.compile(r"^\s*(?P<mark>(?:\d+[.)]|[•·▪◦-]))\s+")
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
VML_IMAGE = "{urn:schemas-microsoft-com:vml}imagedata"


class ConvertError(RuntimeError):
    """Raised when a DOCX file cannot be converted safely."""


@dataclass(frozen=True)
class FileJob:
    src_path: Path
    out_path: Path
    chapter: str


@dataclass(frozen=True)
class RunPart:
    text: str
    bold: bool
    italic: bool
    code: bool
    url: str | None


@dataclass(frozen=True)
class ImageData:
    blob: bytes
    caption: str
    name: str


def setUtf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            reconfig(encoding="utf-8", errors="replace")


def needDeps() -> None:
    if dep_err is not None:
        raise ConvertError(
            "Thiếu dependency. Hãy chạy: pip install python-docx Pillow"
        ) from dep_err


def parseArgs(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chuyển các DOCX đã chỉnh sửa thành Markdown và trích xuất hình.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_dir",
        type=Path,
        default=Path("done"),
        help="Thư mục chứa các file DOCX đã chỉnh sửa.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_dir",
        type=Path,
        help="Thư mục Markdown; mặc định là slide/md nằm cạnh input.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè Markdown và hình đã tồn tại.",
    )
    return parser.parse_args(argv)


def getChapter(path: Path) -> str:
    if "_" not in path.stem:
        raise ConvertError(
            f"Tên file phải có đuôi chương dạng <tên>_<chương>.docx: {path.name}"
        )
    chapter = path.stem.rsplit("_", 1)[1].strip()
    if not chapter:
        raise ConvertError(f"Không tìm thấy chương trong tên file: {path.name}")
    safe_name = BAD_CHARS.sub("_", chapter).strip(". ")
    if not safe_name:
        raise ConvertError(f"Đuôi chương không hợp lệ: {path.name}")
    return safe_name


def makeJobs(
    in_dir: Path,
    out_arg: Path | None,
) -> tuple[Path, list[FileJob]]:
    input_dir = in_dir.expanduser().resolve()
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
        key=lambda path: path.name.casefold(),
    )
    if not files:
        raise ConvertError(f"Không có file DOCX trong: {input_dir}")

    out_dir = (
        out_arg.expanduser().resolve()
        if out_arg is not None
        else input_dir.parent / "slide" / "md"
    )
    if out_dir.exists() and not out_dir.is_dir():
        raise ConvertError(f"Output phải là thư mục: {out_dir}")

    jobs: list[FileJob] = []
    chapters: dict[str, Path] = {}
    for path in files:
        chapter = getChapter(path)
        chapter_key = chapter.casefold()
        if chapter_key in chapters:
            other = chapters[chapter_key]
            raise ConvertError(
                f"Hai file có cùng đuôi chương {chapter!r}: "
                f"{other.name}, {path.name}"
            )
        chapters[chapter_key] = path
        jobs.append(FileJob(path, out_dir / path.with_suffix(".md").name, chapter))
    return out_dir, jobs


def styleName(para: Any) -> str:
    style = getattr(para, "style", None)
    name = getattr(style, "name", "")
    return str(name or "").strip().casefold()


def iterBlocks(doc: Any) -> Iterator[Paragraph | Table]:
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def getLink(run_el: Any, para: Paragraph) -> str | None:
    parent = run_el.getparent()
    while parent is not None and parent is not para._p:
        if parent.tag == qn("w:hyperlink"):
            rel_id = parent.get(qn("r:id"))
            if rel_id:
                rel = para.part.rels.get(rel_id)
                if rel is not None:
                    return str(rel.target_ref)
            anchor = parent.get(qn("w:anchor"))
            if anchor:
                return f"#{anchor}"
            return None
        parent = parent.getparent()
    return None


def iterRuns(para: Paragraph) -> Iterator[RunPart]:
    para_code = styleName(para) == CODE_STYLE
    for run_el in para._p.iter(qn("w:r")):
        run = Run(run_el, para)
        text = run.text
        if not text:
            continue
        run_style = getattr(getattr(run, "style", None), "name", "")
        yield RunPart(
            text=text,
            bold=bool(run.bold),
            italic=bool(run.italic),
            code=para_code or str(run_style or "").casefold() == CODE_STYLE,
            url=getLink(run_el, para),
        )


def escText(text: str) -> str:
    text = text.replace("\\", "\\\\")
    for char in ("*", "_", "[", "]"):
        text = text.replace(char, f"\\{char}")
    return text


def escAlt(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def wrapCode(text: str) -> str:
    longest = max((len(part) for part in re.findall(r"`+", text)), default=0)
    mark = "`" * max(1, longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{mark}{pad}{text}{pad}{mark}"


def formatRun(part: RunPart) -> str:
    text = part.text
    if part.code:
        value = wrapCode(text)
    else:
        value = escText(text)
        if part.bold and part.italic:
            value = f"***{value}***"
        elif part.bold:
            value = f"**{value}**"
        elif part.italic:
            value = f"*{value}*"
    if part.url:
        value = f"[{value}]({part.url.replace(' ', '%20')})"
    return value


def paraText(para: Paragraph) -> str:
    return "".join(formatRun(part) for part in iterRuns(para)).strip()


def plainText(para: Paragraph) -> str:
    return "".join(part.text for part in iterRuns(para)).strip()


def codeFence(text: str) -> str:
    longest = max((len(part) for part in re.findall(r"`{3,}", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text.rstrip()}\n{fence}"


def paraMd(para: Paragraph) -> str:
    text = paraText(para)
    if not text:
        return ""
    style = styleName(para)
    if style in HEAD_STYLES:
        return f"{'#' * HEAD_STYLES[style]} {text}"
    if style == CODE_STYLE:
        return codeFence(plainText(para))

    match = LIST_RE.match(plainText(para))
    if match:
        prefix = match.group("mark")
        clean_text = LIST_RE.sub("", text, count=1)
        if prefix in {"•", "·", "▪", "◦"}:
            prefix = "-"
        value = f"{prefix} {clean_text}"
    else:
        value = text

    if style == DEF_STYLE:
        return "\n".join(f"> {line}" for line in value.splitlines())
    return value


def cellText(cell: Any) -> str:
    values = [paraText(para) for para in cell.paragraphs]
    text = "<br>".join(value for value in values if value)
    return text.replace("|", "\\|")


def tableMd(table: Table) -> str:
    rows = [[cellText(cell) for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    col_num = max(len(row) for row in rows)
    rows = [row + [""] * (col_num - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    divider = "| " + " | ".join("---" for _ in range(col_num)) + " |"
    lines.insert(1, divider)
    return "\n".join(lines)


def imageRels(para: Paragraph) -> list[str]:
    rel_ids: list[str] = []
    for blip in para._p.iter(qn("a:blip")):
        rel_id = blip.get(qn("r:embed"))
        if rel_id:
            rel_ids.append(rel_id)
    for image in para._p.iter(VML_IMAGE):
        rel_id = image.get(qn("r:id"))
        if rel_id:
            rel_ids.append(rel_id)
    return rel_ids


def isCaption(para: Paragraph) -> bool:
    text = plainText(para)
    if not text:
        return False
    style = styleName(para)
    return style in CAP_STYLES or "caption" in style or bool(CAP_RE.match(text))


def nextCaption(
    blocks: list[Paragraph | Table],
    start: int,
) -> tuple[int, Paragraph] | None:
    for idx in range(start + 1, len(blocks)):
        block = blocks[idx]
        if isinstance(block, Table):
            return None
        if imageRels(block):
            return None
        if not plainText(block):
            continue
        if isCaption(block):
            return idx, block
        return None
    return None


def readImage(para: Paragraph, rel_id: str) -> bytes:
    part = para.part.related_parts.get(rel_id)
    blob = getattr(part, "blob", None)
    if not isinstance(blob, bytes):
        raise ConvertError(f"Không đọc được dữ liệu hình có relationship {rel_id!r}.")
    return blob


def makeJpeg(blob: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image.load()
            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                rgba = image.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, "white")
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                image = canvas
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=95, optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise ConvertError(f"Không thể chuyển hình sang JPEG: {exc}") from exc


def convertDoc(job: FileJob) -> tuple[str, list[ImageData], int]:
    try:
        doc = Document(job.src_path)
    except Exception as exc:
        raise ConvertError(f"Không thể mở DOCX {job.src_path}: {exc}") from exc

    blocks = list(iterBlocks(doc))
    used_caps: set[int] = set()
    md_blocks: list[str] = []
    images: list[ImageData] = []
    ignored = 0

    for idx, block in enumerate(blocks):
        if idx in used_caps:
            continue
        if isinstance(block, Table):
            value = tableMd(block)
            if value:
                md_blocks.append(value)
            continue

        rel_ids = imageRels(block)
        if rel_ids:
            cap_item = nextCaption(blocks, idx)
            if cap_item is None:
                ignored += len(rel_ids)
            else:
                cap_idx, cap_para = cap_item
                caption = plainText(cap_para)
                used_caps.add(cap_idx)
                for rel_id in rel_ids:
                    image_num = len(images) + 1
                    name = f"{job.chapter}.{image_num}.jpg"
                    blob = readImage(block, rel_id)
                    images.append(ImageData(blob, caption, name))
                    md_blocks.append(f"![{escAlt(caption)}](img/{name})")

        value = paraMd(block)
        if value:
            md_blocks.append(value)

    markdown = "\n\n".join(md_blocks).rstrip() + "\n"
    return markdown, images, ignored


def writeResult(
    job: FileJob,
    markdown: str,
    images: list[ImageData],
    img_dir: Path,
    overwrite: bool,
) -> None:
    targets = [img_dir / image.name for image in images]
    if not overwrite:
        exists = [path for path in targets if path.exists()]
        if exists:
            names = ", ".join(path.name for path in exists)
            raise ConvertError(f"Hình output đã tồn tại: {names}")

    job.out_path.parent.mkdir(parents=True, exist_ok=True)
    if images:
        img_dir.mkdir(parents=True, exist_ok=True)
    for image, path in zip(images, targets):
        jpeg = makeJpeg(image.blob)
        path.write_bytes(jpeg)
    job.out_path.write_text(markdown, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    args = parseArgs(argv)
    try:
        needDeps()
        out_dir, jobs = makeJobs(args.input_dir, args.output_dir)
        img_dir = out_dir / "img"
        done = 0
        skipped = 0
        failed: list[tuple[Path, str]] = []

        for idx, job in enumerate(jobs, start=1):
            print(f"[{idx}/{len(jobs)}] {job.src_path.name}")
            if job.out_path.exists() and not args.overwrite:
                print(f"[SKIP] Markdown đã tồn tại: {job.out_path}")
                skipped += 1
                continue
            try:
                markdown, images, ignored = convertDoc(job)
                writeResult(job, markdown, images, img_dir, args.overwrite)
                print(
                    f"[DONE] {job.out_path.name}: "
                    f"images={len(images)}, ignored_without_caption={ignored}"
                )
                done += 1
            except (ConvertError, OSError) as exc:
                print(f"[ERROR] {job.src_path}: {exc}", file=sys.stderr)
                failed.append((job.src_path, str(exc)))

        print(
            f"Completed: files={len(jobs)}, converted={done}, "
            f"skipped={skipped}, failed={len(failed)}"
        )
        return 1 if failed else 0
    except (ConvertError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[ERROR] Đã dừng bởi người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
