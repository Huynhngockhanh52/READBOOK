#!/usr/bin/env python3
"""Tách EPUB theo khoảng spine trong config và tạo manifest JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import runpy
import sys
import tempfile
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlsplit

try:
    from lxml import etree
except ImportError as exc:
    etree = None
    dep_err: Exception | None = exc
else:
    dep_err = None


XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MAX_MEMBER = 50_000_000


class SplitError(RuntimeError):
    """Lỗi cấu hình hoặc EPUB không thể tách an toàn."""


@dataclass(frozen=True)
class SpineItem:
    """Một tài liệu trong thứ tự đọc EPUB."""

    index: int
    idref: str
    href: str
    media_type: str
    props: str
    linear: str
    toc_title: str | None = None


@dataclass(frozen=True)
class BookInfo:
    """Metadata và spine cần cho việc tách EPUB."""

    title: str
    creators: list[str]
    language: str | None
    ident: str | None
    opf_path: str
    version: str | None
    spine: list[SpineItem]


@dataclass(frozen=True)
class PartJob:
    """Một part đầu ra và khoảng spine tạo nên part đó."""

    key: str
    start: int
    end: int
    out_path: Path


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
        description=(
            "Tách EPUB thành XHTML theo khoảng spine trong epub_splits và "
            "tạo manifest.json."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "epub_arg",
        nargs="?",
        type=Path,
        help="File EPUB đầu vào (cách viết rút gọn thay cho -i).",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_path",
        type=Path,
        help="File EPUB cần tách.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="out_dir",
        type=Path,
        help="Thư mục part; mặc định data/<nhóm>/<tên sách>/part/.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        default=root / "config" / "env_split.py",
        help="File chứa epub_splits và classification.",
    )
    parser.add_argument(
        "--manifest",
        dest="mani_path",
        type=Path,
        help="Đường dẫn manifest; mặc định nằm cạnh thư mục part/.",
    )
    parser.add_argument(
        "--list-spine",
        action="store_true",
        help="Chỉ hiển thị metadata và spine, không ghi file.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Ghi đè XHTML part và manifest đã tồn tại.",
    )
    return parser.parse_args(argv)


def getInput(args: argparse.Namespace) -> Path:
    if args.input_path and args.epub_arg:
        raise SplitError("Chỉ truyền input một lần: dùng -i hoặc positional.")
    in_path = args.input_path or args.epub_arg
    if in_path is None:
        raise SplitError("Thiếu file EPUB đầu vào. Hãy dùng -i <file.epub>.")
    in_path = in_path.expanduser().resolve()
    if not in_path.is_file():
        raise SplitError(f"Không tìm thấy file EPUB: {in_path}")
    if in_path.suffix.lower() != ".epub":
        raise SplitError(f"Input không phải file EPUB: {in_path}")
    return in_path


def localName(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag.rsplit(":", 1)[-1]


def normMember(name: str, label: str) -> str:
    raw_name = unquote(name).replace("\\", "/")
    norm_name = posixpath.normpath(raw_name)
    if (
        not norm_name
        or norm_name == "."
        or norm_name.startswith("/")
        or norm_name == ".."
        or norm_name.startswith("../")
    ):
        raise SplitError(f"Đường dẫn {label} không an toàn: {name!r}")
    return norm_name


def readMember(arc: zipfile.ZipFile, name: str, label: str) -> bytes:
    member = normMember(name, label)
    try:
        info = arc.getinfo(member)
    except KeyError as exc:
        raise SplitError(f"Không tìm thấy {label} trong EPUB: {member}") from exc
    if info.file_size > MAX_MEMBER:
        raise SplitError(
            f"{label} quá lớn ({info.file_size:,} byte): {member}"
        )
    try:
        return arc.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SplitError(f"Không thể đọc {label} {member}: {exc}") from exc


def parseXml(data: bytes, label: str) -> Any:
    if etree is None:
        raise SplitError("Thiếu lxml. Cài bằng: python -m pip install lxml") from dep_err
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        huge_tree=False,
    )
    try:
        return etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise SplitError(f"XML/XHTML không hợp lệ tại {label}: {exc}") from exc


def childByName(node: Any, name: str) -> Any | None:
    for child in node.iter():
        if localName(child.tag) == name:
            return child
    return None


def nodeText(node: Any | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def resolveHref(base: str, href: str) -> tuple[str, str]:
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        raise SplitError(f"EPUB chứa href ngoài không hợp lệ: {href!r}")
    base_dir = posixpath.dirname(base)
    full_path = posixpath.join(base_dir, parts.path)
    path = normMember(full_path, "href")
    return path, unquote(parts.fragment)


def getOpfPath(arc: zipfile.ZipFile) -> str:
    data = readMember(arc, "META-INF/container.xml", "container.xml")
    root = parseXml(data, "META-INF/container.xml")
    for node in root.iter():
        if localName(node.tag) != "rootfile":
            continue
        full_path = node.get("full-path")
        if full_path:
            return normMember(full_path, "OPF")
    raise SplitError("container.xml không khai báo OPF rootfile.")


def getMeta(opf: Any, name: str) -> list[str]:
    values: list[str] = []
    meta = childByName(opf, "metadata")
    if meta is None:
        return values
    for node in meta.iter():
        if localName(node.tag) == name:
            value = nodeText(node)
            if value:
                values.append(value)
    return values


def getNavMap(
    arc: zipfile.ZipFile,
    opf_path: str,
    items: dict[str, dict[str, str]],
    toc_id: str | None,
) -> dict[str, str]:
    nav_map: dict[str, str] = {}
    nav_item: dict[str, str] | None = None
    for item in items.values():
        props = item.get("props", "").split()
        if "nav" in props:
            nav_item = item
            break

    if nav_item is not None:
        nav_path = nav_item["path"]
        root = parseXml(readMember(arc, nav_path, "EPUB nav"), nav_path)
        toc_nav = None
        for node in root.iter():
            if localName(node.tag) != "nav":
                continue
            nav_type = node.get(f"{{{EPUB_NS}}}type", "")
            if "toc" in nav_type.split():
                toc_nav = node
                break
            if toc_nav is None:
                toc_nav = node
        if toc_nav is not None:
            for node in toc_nav.iter():
                if localName(node.tag) != "a" or not node.get("href"):
                    continue
                try:
                    path, frag = resolveHref(nav_path, node.get("href"))
                except SplitError:
                    continue
                title = nodeText(node)
                if not title:
                    continue
                key = f"{path}#{frag}" if frag else path
                nav_map.setdefault(key, title)
                nav_map.setdefault(path, title)
        return nav_map

    ncx_item = items.get(toc_id or "")
    if ncx_item is None:
        for item in items.values():
            if item.get("media_type") == "application/x-dtbncx+xml":
                ncx_item = item
                break
    if ncx_item is None:
        return nav_map

    ncx_path = ncx_item["path"]
    root = parseXml(readMember(arc, ncx_path, "EPUB NCX"), ncx_path)
    for point in root.iter():
        if localName(point.tag) != "navPoint":
            continue
        title = ""
        src = ""
        for node in point.iter():
            kind = localName(node.tag)
            if kind == "text" and not title:
                title = nodeText(node)
            elif kind == "content" and not src:
                src = node.get("src", "")
        if not title or not src:
            continue
        try:
            path, frag = resolveHref(ncx_path, src)
        except SplitError:
            continue
        key = f"{path}#{frag}" if frag else path
        nav_map.setdefault(key, title)
        nav_map.setdefault(path, title)
    return nav_map


def loadBook(arc: zipfile.ZipFile, in_path: Path) -> BookInfo:
    try:
        mime = readMember(arc, "mimetype", "mimetype").decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SplitError("EPUB mimetype không phải ASCII hợp lệ.") from exc
    if mime != "application/epub+zip":
        raise SplitError(f"EPUB mimetype không hợp lệ: {mime!r}")

    opf_path = getOpfPath(arc)
    opf = parseXml(readMember(arc, opf_path, "OPF"), opf_path)
    manifest = childByName(opf, "manifest")
    spine_node = childByName(opf, "spine")
    if manifest is None or spine_node is None:
        raise SplitError("OPF phải có manifest và spine.")

    items: dict[str, dict[str, str]] = {}
    for node in manifest:
        if localName(node.tag) != "item":
            continue
        item_id = node.get("id", "").strip()
        href = node.get("href", "").strip()
        if not item_id or not href:
            continue
        path, _ = resolveHref(opf_path, href)
        items[item_id] = {
            "id": item_id,
            "href": href,
            "path": path,
            "media_type": node.get("media-type", ""),
            "props": node.get("properties", ""),
        }
    if not items:
        raise SplitError("OPF manifest không có item hợp lệ.")

    toc_id = spine_node.get("toc")
    nav_map = getNavMap(arc, opf_path, items, toc_id)
    spine: list[SpineItem] = []
    for node in spine_node:
        if localName(node.tag) != "itemref":
            continue
        idref = node.get("idref", "").strip()
        item = items.get(idref)
        if item is None:
            raise SplitError(f"Spine tham chiếu manifest id không tồn tại: {idref!r}")
        path = item["path"]
        spine.append(
            SpineItem(
                index=len(spine) + 1,
                idref=idref,
                href=path,
                media_type=item["media_type"],
                props=item["props"],
                linear=node.get("linear", "yes"),
                toc_title=nav_map.get(path),
            )
        )
    if not spine:
        raise SplitError("EPUB spine không có itemref hợp lệ.")

    titles = getMeta(opf, "title")
    creators = getMeta(opf, "creator")
    langs = getMeta(opf, "language")
    idents = getMeta(opf, "identifier")
    return BookInfo(
        title=titles[0] if titles else in_path.stem,
        creators=creators,
        language=langs[0] if langs else None,
        ident=idents[0] if idents else None,
        opf_path=opf_path,
        version=opf.get("version"),
        spine=spine,
    )


def listSpine(book: BookInfo, in_path: Path) -> None:
    print(f"Book    : {book.title}")
    print(f"File    : {in_path}")
    print(f"EPUB    : {book.version or '(unknown)'}")
    print(f"OPF     : {book.opf_path}")
    print(f"Spine   : {len(book.spine)} item(s)")
    for item in book.spine:
        title = item.toc_title or "(no TOC title)"
        print(
            f"[{item.index:03d}] linear={item.linear:<3} "
            f"type={item.media_type or '(unknown)'}\n"
            f"      {item.href}\n"
            f"      {title}"
        )


def loadConfig(cfg_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg_path = cfg_path.expanduser().resolve()
    if not cfg_path.is_file():
        raise SplitError(f"Không tìm thấy config: {cfg_path}")
    try:
        cfg_data = runpy.run_path(str(cfg_path))
    except Exception as exc:
        raise SplitError(f"Không thể đọc config {cfg_path}: {exc}") from exc
    plans = cfg_data.get("epub_splits")
    if not isinstance(plans, dict):
        raise SplitError("Config phải khai báo dictionary tên epub_splits.")
    class_map = cfg_data.get("classification")
    if not isinstance(class_map, dict):
        raise SplitError("Config phải khai báo dictionary tên classification.")
    return plans, class_map


def cleanName(raw_text: Any, label: str) -> str:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SplitError(f"{label} phải là chuỗi không rỗng.")
    value = raw_text.strip()
    if value in {".", ".."} or any(char in '<>:"/\\|?*' for char in value):
        raise SplitError(f"{label} không hợp lệ: {value!r}")
    if value.endswith((".", " ")):
        raise SplitError(f"{label} không được kết thúc bằng dấu chấm/cách.")
    return value


def findClass(class_map: dict[str, Any], book_key: str) -> str:
    matches: list[str] = []
    near_names: list[str] = []
    for raw_key, names in class_map.items():
        class_key = cleanName(raw_key, "Khóa classification")
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise SplitError(f"classification[{class_key!r}] phải là list tên sách.")
        if book_key in names:
            matches.append(class_key)
        near_names.extend(name for name in names if name.casefold() == book_key.casefold())
    if len(matches) > 1:
        keys = ", ".join(matches)
        raise SplitError(f"Tên sách {book_key!r} thuộc nhiều nhóm: {keys}")
    if matches:
        return matches[0]
    if near_names:
        expected = ", ".join(repr(name) for name in near_names)
        raise SplitError(
            f"Không khớp chính xác {book_key!r}; so sánh phân biệt hoa/thường. "
            f"Tên gần giống trong classification: {expected}"
        )
    raise SplitError(f"Không tìm thấy {book_key!r} trong classification.")


def getOutDir(
    out_arg: Path | None,
    in_path: Path,
    class_map: dict[str, Any],
    root: Path,
) -> Path:
    if out_arg is not None:
        return out_arg.expanduser().resolve()
    class_key = findClass(class_map, in_path.stem)
    return (root / "data" / class_key / in_path.stem / "part").resolve()


def pickPlan(plans: dict[str, Any], in_path: Path) -> tuple[str, dict[str, Any]]:
    keys = (in_path.stem, in_path.name)
    for key in keys:
        plan = plans.get(key)
        if plan is not None:
            if not isinstance(plan, dict):
                raise SplitError(f"Cấu hình của {key!r} phải là dictionary.")
            return key, plan

    low_keys = {key.casefold() for key in keys}
    near_keys = [str(key) for key in plans if str(key).casefold() in low_keys]
    if near_keys:
        expected = ", ".join(repr(key) for key in near_keys)
        raise SplitError(
            f"Không khớp chính xác {in_path.stem!r} trong epub_splits; "
            f"tên gần giống: {expected}"
        )
    names = ", ".join(map(str, plans)) or "(trống)"
    raise SplitError(
        f"Không có cấu hình cho {in_path.stem!r}. Các tên hiện có: {names}"
    )


def cleanSuffix(raw_text: Any) -> tuple[str, str]:
    key = cleanName(raw_text, "Tên part")
    suffix = key if key.startswith("_") else f"_{key}"
    return key, suffix


def checkPlans(
    plan: dict[str, Any],
    in_path: Path,
    out_dir: Path,
    spine_num: int,
) -> list[PartJob]:
    if not plan:
        raise SplitError(f"Cấu hình tách của {in_path.stem!r} đang trống.")
    jobs: list[PartJob] = []
    seen_paths: set[Path] = set()
    for raw_key, spine_rng in plan.items():
        key, suffix = cleanSuffix(raw_key)
        if isinstance(spine_rng, int) and not isinstance(spine_rng, bool):
            start = spine_rng
            end = spine_rng
        elif (
            isinstance(spine_rng, (tuple, list))
            and len(spine_rng) == 2
            and all(
                isinstance(val, int) and not isinstance(val, bool)
                for val in spine_rng
            )
        ):
            start, end = spine_rng
        else:
            raise SplitError(
                f"Spine của {raw_key!r} phải là một số nguyên hoặc "
                "khoảng (start, end)."
            )
        if start < 1 or end < start or end > spine_num:
            raise SplitError(
                f"Khoảng {raw_key!r}=({start}, {end}) không hợp lệ; "
                f"EPUB có {spine_num} spine item. Các số này là vị trí "
                "spine, không phải số trang hiển thị. Hãy chạy --list-spine."
            )
        out_path = (out_dir / f"{in_path.stem}{suffix}.xhtml").resolve()
        if out_path in seen_paths:
            raise SplitError(f"Hai part tạo cùng output: {out_path.name}")
        seen_paths.add(out_path)
        jobs.append(PartJob(key, start, end, out_path))
    return jobs


def docTitle(arc: zipfile.ZipFile, item: SpineItem) -> str | None:
    if item.toc_title:
        return item.toc_title
    root = parseXml(readMember(arc, item.href, "spine XHTML"), item.href)
    for node in root.iter():
        if localName(node.tag) in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            title = nodeText(node)
            if title:
                return title
    for node in root.iter():
        if localName(node.tag) == "title":
            title = nodeText(node)
            if title:
                return title
    return None


def partTitle(
    arc: zipfile.ZipFile,
    items: list[SpineItem],
    key: str,
) -> str:
    for item in items:
        title = docTitle(arc, item)
        if title:
            return title
    return key.lstrip("_") or key


def checkMedia(item: SpineItem) -> None:
    valid_types = {"application/xhtml+xml", "text/html"}
    if item.media_type not in valid_types:
        raise SplitError(
            f"Spine item {item.index} không phải XHTML/HTML: "
            f"{item.media_type or '(unknown)'} | {item.href}"
        )


def mergeXhtml(
    arc: zipfile.ZipFile,
    items: list[SpineItem],
    title: str,
    language: str | None,
) -> bytes:
    if etree is None:
        raise SplitError("Thiếu lxml. Cài bằng: python -m pip install lxml") from dep_err
    nsmap = {None: XHTML_NS, "epub": EPUB_NS}
    root = etree.Element(f"{{{XHTML_NS}}}html", nsmap=nsmap)
    if language:
        root.set("lang", language)
        root.set(f"{{{XML_NS}}}lang", language)
    head = etree.SubElement(root, f"{{{XHTML_NS}}}head")
    meta = etree.SubElement(head, f"{{{XHTML_NS}}}meta")
    meta.set("charset", "utf-8")
    title_node = etree.SubElement(head, f"{{{XHTML_NS}}}title")
    title_node.text = title
    body = etree.SubElement(root, f"{{{XHTML_NS}}}body")

    for item in items:
        checkMedia(item)
        src_root = parseXml(
            readMember(arc, item.href, "spine XHTML"),
            item.href,
        )
        src_body = childByName(src_root, "body")
        if src_body is None:
            raise SplitError(f"XHTML không có body: {item.href}")
        section = etree.SubElement(body, f"{{{XHTML_NS}}}section")
        section.set("data-epub-href", item.href)
        section.set("data-spine-index", str(item.index))
        section.set("data-spine-idref", item.idref)
        if src_body.text and src_body.text.strip():
            section.text = src_body.text
        for child in src_body:
            section.append(deepcopy(child))

    return etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        doctype="<!DOCTYPE html>",
        pretty_print=False,
    )


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
        raise SplitError(f"Không thể tính SHA-256 của {path}: {exc}") from exc
    return digest.hexdigest()


def relName(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def spineData(item: SpineItem) -> dict[str, Any]:
    return {
        "index": item.index,
        "idref": item.idref,
        "href": item.href,
        "media_type": item.media_type,
        "properties": item.props.split(),
        "linear": item.linear,
        "toc_title": item.toc_title,
    }


def makeManifest(
    in_path: Path,
    book_key: str,
    book: BookInfo,
    part_data: list[dict[str, Any]],
    cfg_path: Path,
    work_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": relName(in_path, getRoot()),
            "filename": in_path.name,
            "size_bytes": in_path.stat().st_size,
            "sha256": fileHash(in_path),
        },
        "config": {
            "path": relName(cfg_path, getRoot()),
            "book_key": book_key,
            "range_unit": "spine_item_1_based_inclusive",
        },
        "book": {
            "title": book.title,
            "creators": book.creators,
            "language": book.language,
            "identifier": book.ident,
            "epub_version": book.version,
            "opf_path": book.opf_path,
        },
        "spine": [spineData(item) for item in book.spine],
        "parts": part_data,
        "work_dir": relName(work_dir, getRoot()),
    }


def runSplit(args: argparse.Namespace) -> tuple[list[Path], Path | None]:
    if dep_err is not None or etree is None:
        raise SplitError("Thiếu lxml. Cài bằng: python -m pip install lxml") from dep_err
    in_path = getInput(args)
    try:
        arc = zipfile.ZipFile(in_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SplitError(f"Không thể mở EPUB {in_path}: {exc}") from exc

    with arc:
        book = loadBook(arc, in_path)
        if args.list_spine:
            listSpine(book, in_path)
            return [], None

        cfg_path = args.config_path.expanduser().resolve()
        plans, class_map = loadConfig(cfg_path)
        book_key, plan = pickPlan(plans, in_path)
        out_dir = getOutDir(args.out_dir, in_path, class_map, getRoot())
        if out_dir.exists() and not out_dir.is_dir():
            raise SplitError(f"Output part phải là thư mục: {out_dir}")
        mani_path = (
            args.mani_path.expanduser().resolve()
            if args.mani_path is not None
            else out_dir.parent / "manifest.json"
        )
        if mani_path.exists() and mani_path.is_dir():
            raise SplitError(f"Manifest không được là thư mục: {mani_path}")

        jobs = checkPlans(plan, in_path, out_dir, len(book.spine))
        old_files = [job.out_path for job in jobs if job.out_path.exists()]
        if mani_path.exists():
            old_files.append(mani_path)
        if old_files and not args.overwrite:
            names = ", ".join(path.name for path in old_files)
            raise SplitError(f"Output đã tồn tại: {names}. Dùng --overwrite để ghi đè.")

        print(
            f"Book: {book_key} | spine: {len(book.spine)} | "
            f"parts: {len(jobs)}"
        )
        outputs: list[Path] = []
        part_data: list[dict[str, Any]] = []
        for idx, job in enumerate(jobs, start=1):
            items = book.spine[job.start - 1 : job.end]
            title = partTitle(arc, items, job.key)
            data = mergeXhtml(arc, items, title, book.language)
            print(
                f"[{idx}/{len(jobs)}] spine {job.start}-{job.end} "
                f"-> {job.out_path.name}"
            )
            try:
                writeAtomic(job.out_path, data)
            except OSError as exc:
                raise SplitError(f"Không thể ghi {job.out_path}: {exc}") from exc
            outputs.append(job.out_path)
            part_data.append(
                {
                    "order": idx,
                    "key": job.key,
                    "title": title,
                    "spine_range": {
                        "start": job.start,
                        "end": job.end,
                    },
                    "output": relName(job.out_path, out_dir.parent),
                    "spine_items": [spineData(item) for item in items],
                }
            )

        manifest = makeManifest(
            in_path,
            book_key,
            book,
            part_data,
            cfg_path,
            out_dir.parent,
        )
        mani_data = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        try:
            writeAtomic(mani_path, mani_data)
        except OSError as exc:
            raise SplitError(f"Không thể ghi manifest {mani_path}: {exc}") from exc
        return outputs, mani_path


def main(argv: Sequence[str] | None = None) -> int:
    setUtf8()
    try:
        args = parseArgs(argv)
        outputs, mani_path = runSplit(args)
    except SplitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Error: Đã dừng bởi người dùng.", file=sys.stderr)
        return 130

    if args.list_spine:
        return 0
    print(f"Manifest: {mani_path}")
    print(f"Completed: {len(outputs)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
