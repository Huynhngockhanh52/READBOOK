#!/usr/bin/env python3
"""Translate technical English TXT books to Vietnamese Markdown.

Workflow
--------
- Translate one TXT file given as a positional argument, or every TXT file under
  ``-i/--input-dir``.
- Split source text into blocks separated by a line containing at least ten '='.
- Greedily group blocks into sessions capped at 50,000 characters. A single
  oversized block is kept as its own session and reported as a warning.
- Append each translated session to ``*_vi.md`` so large books do not need to be
  kept in memory as one translated document.

Backends
--------
``gemini``
    Gemini chat API through ``google.genai``. Credentials, model and optional
    instruction are loaded lazily from ``config/env.py``.
``codex``
    Stateful Codex CLI conversation. The instruction prompt is sent first, then
    source sessions are sent by resuming the same Codex thread.
``claude``
    Stateful Claude Code conversation using a captured session id.
``non-codex``
    Stateless ``codex exec``. Every request is ``instruction + session``.
``non-claude``
    Stateless ``claude -p``. Every request is ``instruction + session``.

The default project root is the parent of this script's ``main`` directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


logger = logging.getLogger("en2vi")

sess_limit = 50_000
req_timeout = 1_800
block_sep = "=========="
block_re = re.compile(r"(?m)^\s*={10,}\s*$")
content_tag = "{CONTENT}"
model_opts = ("gemini", "codex", "claude", "non-codex", "non-claude")
non_models = {"non-codex", "non-claude"}


class TranslationError(RuntimeError):
    """Raised when a backend cannot produce a usable translation."""


@dataclass(frozen=True)
class SourceJob:
    input_path: Path
    output_path: Path


@dataclass(frozen=True)
class SessionPlan:
    blocks: list[str]
    sessions: list[str]
    over_ids: list[int]


@dataclass(frozen=True)
class BackendResult:
    text: str
    session_id: str | None = None


def getRoot() -> Path:
    return Path(__file__).resolve().parent.parent


def readText(path: Path, encoding: str = "utf-8") -> str:
    try:
        return path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise TranslationError(
            f"Không thể đọc {path} bằng encoding={encoding!r}. "
            "Hãy dùng --encoding với encoding phù hợp."
        ) from exc
    except OSError as exc:
        raise TranslationError(f"Không thể đọc file {path}: {exc}") from exc


def loadConfig(path: Path) -> object:
    """Load config/env.py without adding project directories to sys.path."""
    if not path.is_file():
        raise TranslationError(f"Không tìm thấy file cấu hình Gemini: {path}")
    spec = importlib.util.spec_from_file_location("en2vi_config", path)
    if spec is None or spec.loader is None:
        raise TranslationError(f"Không thể load file cấu hình Gemini: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise TranslationError(f"Lỗi khi load cấu hình Gemini từ {path}: {exc}") from exc
    return module


def configValue(config: object, *names: str) -> object | None:
    for name in names:
        value = getattr(config, name, None)
        if value is not None and value != "":
            return value
    return None


def loadPrompt(path: Path) -> str:
    """Load the required translation prompt from a UTF-8 Markdown file."""
    if not path.is_file():
        raise TranslationError(f"Không tìm thấy prompt file: {path}")
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TranslationError(f"Không thể đọc prompt file {path}: {exc}") from exc
    if not prompt:
        raise TranslationError(f"Prompt file rỗng: {path}")
    return prompt


def splitBlocks(text: str) -> list[str]:
    """Split on separator lines while preserving meaningful source content."""
    parts = block_re.split(text)
    return [part.strip() for part in parts if part.strip()]


def joinBlocks(blocks: Sequence[str]) -> str:
    return f"\n\n{block_sep}\n\n".join(blocks)


def planSess(text: str, limit: int) -> SessionPlan:
    if limit <= 0:
        raise ValueError("Session limit phải > 0")

    blocks = splitBlocks(text)
    if not blocks and text.strip():
        blocks = [text.strip()]

    sessions: list[str] = []
    current: list[str] = []
    cur_chars = 0
    oversized: list[int] = []
    sep_chars = len(f"\n\n{block_sep}\n\n")

    for index, block in enumerate(blocks, start=1):
        block_chars = len(block)
        if block_chars > limit:
            oversized.append(index)
            if current:
                sessions.append(joinBlocks(current))
                current = []
                cur_chars = 0
            sessions.append(block)
            continue

        extra = block_chars if not current else sep_chars + block_chars
        if current and cur_chars + extra > limit:
            sessions.append(joinBlocks(current))
            current = [block]
            cur_chars = block_chars
        else:
            current.append(block)
            cur_chars += extra

    if current:
        sessions.append(joinBlocks(current))

    return SessionPlan(blocks=blocks, sessions=sessions, over_ids=oversized)


def cleanOutput(text: str) -> str:
    result = text.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*?)\n```", result, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        result = fenced.group(1).strip()
    return result


def outFileName(input_path: Path) -> str:
    # file_text.txt -> file_vi.md, as requested; other.txt -> other_vi.md
    stem = re.sub(r"(?i)_text$", "", input_path.stem)
    if stem.lower().endswith("_vi"):
        return f"{stem}.md"
    return f"{stem}_vi.md"


def defaultOut(input_path: Path, input_dir: Path | None) -> Path:
    if input_dir is not None:
        return input_dir.resolve().parent / "tran"
    return input_path.resolve().parent.parent / "tran"


def getJobs(
    pos_input: Path | None,
    input_option: Path | None,
    output: Path | None,
) -> list[SourceJob]:
    if bool(pos_input) == bool(input_option):
        raise TranslationError("Chỉ định đúng một nguồn bằng FILE.txt hoặc -i/--input PATH.")

    source_arg = pos_input or input_option
    assert source_arg is not None
    source = source_arg.expanduser().resolve()

    if source.is_file():
        if not source.is_file():
            raise TranslationError(f"Không tìm thấy file đầu vào: {source}")
        if source.suffix.lower() != ".txt":
            raise TranslationError(f"File đầu vào phải có đuôi .txt: {source}")

        if output is not None and output.suffix.lower() == ".md":
            target = output.expanduser().resolve()
        else:
            out_dir = output.expanduser().resolve() if output else defaultOut(source, None)
            target = out_dir / outFileName(source)
        return [SourceJob(source, target)]

    source_dir = source
    if not source_dir.is_dir():
        raise TranslationError(f"Không tìm thấy input: {source_dir}")

    files = sorted(path for path in source_dir.rglob("*.txt") if path.is_file())
    if not files:
        raise TranslationError(f"Không có file .txt trong: {source_dir}")

    if output is not None and output.suffix.lower() == ".md":
        raise TranslationError("-o FILE.md chỉ hợp lệ khi dịch một file; với -i hãy dùng -o DIR.")

    out_dir = output.expanduser().resolve() if output else source_dir.parent / "tran"
    jobs: list[SourceJob] = []
    for source in files:
        rel_parent = source.relative_to(source_dir).parent
        target = out_dir / rel_parent / outFileName(source)
        jobs.append(SourceJob(source, target))
    return jobs


def getSessLimit(model: str, hard_limit: int, prompt: str) -> int:
    """Keep stateless prompt+session requests under the requested char limit."""
    if model in non_models:
        if content_tag in prompt:
            overhead = len(prompt) - len(content_tag)
        else:
            # Two newlines are inserted between prompt and source text.
            overhead = len(prompt.rstrip()) + 2
        available = hard_limit - overhead
        if available < 1:
            raise TranslationError(
                f"Prompt dài {len(prompt):,} ký tự, không còn chỗ trong limit {hard_limit:,}."
            )
        return available
    return hard_limit


def fillPrompt(prompt: str, content: str) -> str:
    if content_tag in prompt:
        return prompt.replace(content_tag, content)
    return f"{prompt.rstrip()}\n\n{content.lstrip()}"


def initPrompt(prompt: str) -> str:
    """Prepare a template prompt for a stateful chat's instruction turn."""
    return prompt.replace(content_tag, "")


def getExe(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise TranslationError(
            f"Không tìm thấy executable {name!r} trong PATH. Hãy cài đặt/đăng nhập CLI trước."
        )
    return executable


def runProc(
    args: Sequence[str],
    *,
    input_text: str,
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(args),
            input=input_text,
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
        raise TranslationError(f"CLI timeout sau {timeout}s: {' '.join(args[:4])} ...") from exc
    except OSError as exc:
        raise TranslationError(f"Không thể chạy CLI: {args[0]}: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code={result.returncode}"
        raise TranslationError(f"CLI thất bại ({args[0]}): {detail[-4000:]}")
    return result


def parseCodex(stdout: str) -> BackendResult:
    thread_id: str | None = None
    messages: list[str] = []
    errors: list[str] = []

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id") or thread_id
        elif event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                messages.append(str(item["text"]))
            elif item.get("type") == "error" and item.get("message"):
                errors.append(str(item["message"]))
        elif event.get("type") in {"error", "turn.failed"}:
            err = event.get("message") or event.get("error")
            if err:
                errors.append(str(err))

    # Codex may emit multiple assistant messages around tool/progress events.
    # The last agent_message is the final answer for the turn.
    text = cleanOutput(messages[-1] if messages else "")
    if not text and errors:
        raise TranslationError("Codex không trả về nội dung: " + " | ".join(errors[-3:]))
    return BackendResult(text=text, session_id=thread_id)


def parseClaude(stdout: str) -> BackendResult:
    data: dict[str, object] | None = None
    stripped = stdout.strip()
    if stripped:
        try:
            candidate = json.loads(stripped)
            if isinstance(candidate, dict):
                data = candidate
        except json.JSONDecodeError:
            for line in reversed(stripped.splitlines()):
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    data = candidate
                    break

    if data is None:
        raise TranslationError(f"Không parse được JSON output của Claude: {stripped[-2000:]}")
    if data.get("is_error") is True:
        raise TranslationError(f"Claude trả về lỗi: {data.get('result') or data}")

    result = cleanOutput(str(data.get("result") or ""))
    session_id = str(data["session_id"]) if data.get("session_id") else None
    return BackendResult(text=result, session_id=session_id)


class TranslationBackend(ABC):
    def __init__(self, *, prompt: str, cwd: Path, timeout: int) -> None:
        self.prompt = prompt
        self.cwd = cwd
        self.timeout = timeout

    @property
    def stateful(self) -> bool:
        return False

    def start(self) -> None:
        """Initialize a stateful conversation if required."""

    @abstractmethod
    def translate(self, session: str) -> str:
        raise NotImplementedError


class CodexBackend(TranslationBackend):
    def __init__(self, *, prompt: str, cwd: Path, timeout: int, stateful: bool) -> None:
        super().__init__(prompt=prompt, cwd=cwd, timeout=timeout)
        self.executable = getExe("codex")
        self._stateful = stateful
        self.session_id: str | None = None

    @property
    def stateful(self) -> bool:
        return self._stateful

    def _newTurn(self, payload: str) -> BackendResult:
        result = runProc(
            [self.executable, "exec", "--json", "--color", "never", "--skip-git-repo-check", "-"],
            input_text=payload,
            cwd=self.cwd,
            timeout=self.timeout,
        )
        return parseCodex(result.stdout)

    def _resumeTurn(self, payload: str) -> BackendResult:
        if not self.session_id:
            raise TranslationError("Codex session chưa được khởi tạo.")
        result = runProc(
            [
                self.executable,
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                self.session_id,
                "-",
            ],
            input_text=payload,
            cwd=self.cwd,
            timeout=self.timeout,
        )
        return parseCodex(result.stdout)

    def start(self) -> None:
        if not self._stateful:
            return
        init = self._newTurn(initPrompt(self.prompt))
        if not init.session_id:
            raise TranslationError("Codex không trả về thread_id để tiếp tục session.")
        self.session_id = init.session_id
        logger.debug("Codex thread_id=%s", self.session_id)

    def translate(self, session: str) -> str:
        if self._stateful:
            response = self._resumeTurn(session)
        else:
            response = self._newTurn(fillPrompt(self.prompt, session))
        if not response.text:
            raise TranslationError("Codex trả về output rỗng.")
        return response.text

class ClaudeBackend(TranslationBackend):
    def __init__(self, *, prompt: str, cwd: Path, timeout: int, stateful: bool) -> None:
        super().__init__(prompt=prompt, cwd=cwd, timeout=timeout)
        self.executable = getExe("claude")
        self._stateful = stateful
        self.session_id: str | None = None

    @property
    def stateful(self) -> bool:
        return self._stateful

    def _call(self, payload: str, session_id: str | None = None) -> BackendResult:
        args = [self.executable, "-p", "--output-format", "json"]
        if session_id:
            args.extend(["--resume", session_id])
        result = runProc(args, input_text=payload, cwd=self.cwd, timeout=self.timeout)
        return parseClaude(result.stdout)

    def start(self) -> None:
        if not self._stateful:
            return
        init = self._call(initPrompt(self.prompt))
        if not init.session_id:
            raise TranslationError("Claude không trả về session_id để tiếp tục hội thoại.")
        self.session_id = init.session_id
        logger.debug("Claude session_id=%s", self.session_id)

    def translate(self, session: str) -> str:
        if self._stateful:
            if not self.session_id:
                raise TranslationError("Claude session chưa được khởi tạo.")
            response = self._call(session, self.session_id)
            self.session_id = response.session_id or self.session_id
        else:
            response = self._call(fillPrompt(self.prompt, session))
        if not response.text:
            raise TranslationError("Claude trả về output rỗng.")
        return response.text

class GeminiBackend(TranslationBackend):
    def __init__(
        self,
        *,
        prompt: str,
        cwd: Path,
        timeout: int,
        config: object,
        max_reqs: int = 5,
        delay: float = 0.0,
        retries: int = 3,
    ) -> None:
        super().__init__(prompt=prompt, cwd=cwd, timeout=timeout)
        self.api_key = configValue(config, "API_GEMINI_KEY", "GEMINI_API_KEY")
        self.model = configValue(config, "MODEL_31_PRE", "MODEL_35", "MODEL")
        self.api_url = configValue(
            config, "API_GEMINI_URL", "GEMINI_API_URL", "API_ENDPOINT"
        )
        self.max_reqs = max(1, max_reqs)
        self.delay = max(0.0, delay)
        self.retries = max(1, retries)
        self.req_count = 0
        self.chat: object | None = None

        missing = [
            name
            for name, value in (
                ("API_GEMINI_KEY", self.api_key),
                ("MODEL_31_PRE/MODEL_35/MODEL", self.model),
            )
            if not value
        ]
        if missing:
            raise TranslationError(f"Thiếu cấu hình Gemini: {', '.join(missing)}")

        try:
            from google import genai
        except ImportError as exc:
            raise TranslationError(
                "Thiếu package google-genai. Cài bằng: pip install google-genai"
            ) from exc

        options: dict[str, object] = {"timeout": timeout * 1000}
        if self.api_url:
            options["base_url"] = str(self.api_url)
        try:
            self.client = genai.Client(
                api_key=str(self.api_key),
                http_options=options,
            )
        except Exception as exc:
            raise TranslationError(f"Không thể khởi tạo Gemini client: {exc}") from exc

    def _newChat(self, instruction: str) -> object:
        try:
            chat = self.client.chats.create(model=str(self.model))
            chat.send_message(instruction)
        except Exception as exc:
            raise TranslationError(f"Không thể khởi tạo Gemini chat: {exc}") from exc
        return chat

    def start(self) -> None:
        self.chat = self._newChat(initPrompt(self.prompt))
        self.req_count = 0

    def _send(self, chat: object, content: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            if self.delay:
                time.sleep(self.delay)
            try:
                response = chat.send_message(content)
                text = cleanOutput(str(response.text or ""))
                if not text:
                    raise TranslationError("Gemini trả về output rỗng.")
                return text
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    wait = min(2 ** (attempt - 1), 8)
                    logger.warning(
                        "Gemini request lỗi, thử lại %d/%d sau %ds: %s",
                        attempt,
                        self.retries,
                        wait,
                        exc,
                    )
                    time.sleep(wait)
        raise TranslationError(f"Gemini API thất bại: {last_error}")

    def translate(self, session: str) -> str:
        if self.chat is None:
            self.start()
        if self.req_count >= self.max_reqs:
            logger.info("Reset Gemini chat sau %d request.", self.req_count)
            self.start()
        assert self.chat is not None
        result = self._send(self.chat, session)
        self.req_count += 1
        return result

def makeBackend(
    model: str,
    *,
    prompt: str,
    cwd: Path,
    timeout: int,
    config: object | None,
    max_reqs: int,
    delay: float,
) -> TranslationBackend:
    if model == "gemini":
        if config is None:
            raise TranslationError("Chưa load config/env.py cho Gemini.")
        return GeminiBackend(
            prompt=prompt,
            cwd=cwd,
            timeout=timeout,
            config=config,
            max_reqs=max_reqs,
            delay=delay,
        )
    if model == "codex":
        return CodexBackend(prompt=prompt, cwd=cwd, timeout=timeout, stateful=True)
    if model == "non-codex":
        return CodexBackend(prompt=prompt, cwd=cwd, timeout=timeout, stateful=False)
    if model == "claude":
        return ClaudeBackend(prompt=prompt, cwd=cwd, timeout=timeout, stateful=True)
    if model == "non-claude":
        return ClaudeBackend(prompt=prompt, cwd=cwd, timeout=timeout, stateful=False)
    raise TranslationError(f"Model không được hỗ trợ: {model}")


def appendMd(path: Path, text: str) -> None:
    cleaned = cleanOutput(text)
    if not cleaned:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    need_newline = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if need_newline:
            handle.write("\n\n")
        handle.write(cleaned)
        handle.write("\n")


def runJob(
    job: SourceJob,
    *,
    model: str,
    prompt: str,
    config: object | None,
    hard_limit: int,
    timeout: int,
    max_reqs: int,
    delay: float,
    overwrite: bool,
    encoding: str,
    dry_run: bool,
) -> bool:
    if job.output_path.exists() and not overwrite:
        logger.info("SKIP (đã tồn tại, dùng --overwrite để ghi đè): %s", job.output_path)
        return False

    source_text = readText(job.input_path, encoding=encoding)
    if not source_text.strip():
        raise TranslationError(f"File đầu vào rỗng: {job.input_path}")
    sess_cap = getSessLimit(model, hard_limit, prompt)
    plan = planSess(source_text, sess_cap)

    logger.info(
        "%s: %d chars, %d blocks -> %d sessions (session limit=%d)",
        job.input_path,
        len(source_text),
        len(plan.blocks),
        len(plan.sessions),
        sess_cap,
    )
    if plan.over_ids:
        logger.warning(
            "Có block vượt limit và sẽ đứng riêng: %s",
            ", ".join(map(str, plan.over_ids)),
        )

    if dry_run:
        for index, session in enumerate(plan.sessions, start=1):
            logger.info("  session %d/%d: %d chars", index, len(plan.sessions), len(session))
        logger.info("  output: %s", job.output_path)
        return True

    backend = makeBackend(
        model,
        prompt=prompt,
        # Keep agentic CLIs away from the code repository so repo-level coding
        # instructions do not leak into the translation conversation.
        cwd=job.input_path.parent,
        timeout=timeout,
        config=config,
        max_reqs=max_reqs,
        delay=delay,
    )
    backend.start()

    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and job.output_path.exists():
        job.output_path.unlink()

    for index, session in enumerate(plan.sessions, start=1):
        logger.info("Dịch session %d/%d (%d chars)", index, len(plan.sessions), len(session))
        try:
            translated = backend.translate(session)
            appendMd(job.output_path, translated)
        except Exception as exc:
            raise TranslationError(
                f"Lỗi tại session {index}/{len(plan.sessions)} của {job.input_path}: {exc}"
            ) from exc

    logger.info("DONE: %s", job.output_path)
    return True


def makeParser() -> argparse.ArgumentParser:
    root = getRoot()
    parser = argparse.ArgumentParser(
        description="Dịch sách kỹ thuật English -> Vietnamese từ TXT sang Markdown.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="Một file .txt cần dịch.",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_opt",
        type=Path,
        help="Một file .txt hoặc thư mục chứa các file .txt (recursive).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Output file/thư mục. Mặc định: lùi một cấp từ thư mục chứa input "
            "và tạo tran/. Với một file có thể chỉ định trực tiếp FILE.md."
        ),
    )
    parser.add_argument(
        "-m",
        "--model",
        choices=model_opts,
        default="codex",
        help="Backend dịch thuật.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Cho phép xóa và dịch lại file output đã tồn tại.",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=root / "instruction" / "en2vi_prompt.md",
        help="File instruction prompt gửi cho model.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "env.py",
        help="File Python chứa cấu hình Gemini.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=5,
        help="Số request dịch tối đa trước khi tạo Gemini chat mới.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Số giây chờ trước mỗi Gemini API request.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=sess_limit,
        help="Giới hạn ký tự cho một message/request.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=req_timeout,
        help="Timeout tối đa cho mỗi CLI/API request (giây).",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding của file TXT đầu vào.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ phân tích file/blocks/sessions/output, không gọi model và không ghi file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Bật log chi tiết.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = makeParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        if args.limit <= 0:
            raise TranslationError("--limit phải > 0")
        if args.timeout <= 0:
            raise TranslationError("--timeout phải > 0")
        if args.max_requests <= 0:
            raise TranslationError("--max-requests phải > 0")
        if args.delay < 0:
            raise TranslationError("--delay phải >= 0")

        prompt_path = args.prompt.expanduser().resolve()
        config_path = args.config.expanduser().resolve()
        config: object | None = None
        if args.model == "gemini" and config_path.is_file():
            config = loadConfig(config_path)
        elif args.model == "gemini" and not args.dry_run:
            raise TranslationError(f"Không tìm thấy file cấu hình Gemini: {config_path}")
        prompt = loadPrompt(prompt_path)

        jobs = getJobs(args.input, args.input_opt, args.output)

        logger.info("Backend: %s", args.model)
        logger.info("Prompt: %s (%d chars)", prompt_path, len(prompt))
        logger.info("Số file: %d", len(jobs))

        success = 0
        skipped = 0
        failed: list[tuple[Path, str]] = []
        for file_index, job in enumerate(jobs, start=1):
            logger.info("=== File %d/%d: %s ===", file_index, len(jobs), job.input_path)
            try:
                processed = runJob(
                    job,
                    model=args.model,
                    prompt=prompt,
                    config=config,
                    hard_limit=args.limit,
                    timeout=args.timeout,
                    max_reqs=args.max_requests,
                    delay=args.delay,
                    overwrite=args.overwrite,
                    encoding=args.encoding,
                    dry_run=args.dry_run,
                )
                if processed:
                    success += 1
                else:
                    skipped += 1
            except (TranslationError, OSError) as exc:
                failed.append((job.input_path, str(exc)))
                logger.error("FAILED: %s: %s", job.input_path, exc)

        logger.info(
            "Hoàn tất: discovered=%d, translated=%d, skipped=%d, failed=%d",
            len(jobs), success, skipped, len(failed),
        )
        for path, message in failed:
            logger.error("  %s: %s", path, message)
        return 1 if failed else 0
    except KeyboardInterrupt:
        logger.error("Đã dừng bởi người dùng. File Markdown đã ghi trước đó được giữ nguyên.")
        return 130
    except (TranslationError, OSError) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
