#!/usr/bin/env python3
"""
Hyper-Cube Local Coding Agent V3
================================

A polished, dependency-free local coding agent for Ollama.

Designed for:
- Windows + PowerShell
- Python 3.9+
- Ollama running locally
- Small local tool-capable models such as qwen3.5:4b
- Low-memory / locked-down machines

V3 highlights
-------------
1. Live streaming command output.
2. Safe duplicate-filename handling.
3. Native PowerShell command execution on Windows.
4. Turn-safe context pruning that never separates tool calls/results.
5. Persistent .agent session/config state.
6. Model-driven task plan with a visible checklist.
7. Exact edits + guarded line-range edits + insertions.
8. Stale-file detection using SHA-256 snapshots.
9. Lightweight cached repository map with symbols/imports.
10. Windows arrow-key history + Ctrl+C cancellation + /retry /continue /stop.
11. Startup diagnostics for Ollama, model, tools, Git, PowerShell, and session.
12. More polished activity UI while remaining standard-library only.

No third-party Python packages are required.

Typical usage:
    python agent.py

Options:
    python agent.py --model qwen3.5:4b
    python agent.py --project C:\\path\\to\\project
    python agent.py --ctx 8192
    python agent.py --no-resume

Important:
- Put this file in the project root.
- Internal persistent state is stored in .agent/.
- The model never receives or displays its raw hidden reasoning. Instead, the UI
  shows concise plans, tool reasons, task progress, diffs, timings, and results.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# =============================================================================
# Configuration
# =============================================================================

VERSION = "3.0"

OLLAMA_BASE = "http://127.0.0.1:11434"
CHAT_URL = OLLAMA_BASE + "/api/chat"
TAGS_URL = OLLAMA_BASE + "/api/tags"
SHOW_URL = OLLAMA_BASE + "/api/show"

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_CTX = 8192
DEFAULT_TEMP = 0.2

MAX_FILE_CHARS = 80_000
MAX_READ_LINES = 700
MAX_COMMAND_CAPTURE_CHARS = 24_000
MAX_COMMAND_DISPLAY_LINES = 700
MAX_SEARCH_RESULTS = 120
MAX_TREE_ENTRIES = 700
MAX_TOOL_STEPS = 40
MAX_REPO_MAP_FILES = 5000
MAX_REPO_MAP_RESULTS = 120
MAX_INPUT_HISTORY = 100
MAX_SESSION_MESSAGES = 160

# Leave room for tool schemas + completion.
HISTORY_TARGET_RATIO = 0.58

CANCEL_DOUBLE_TAP_SECONDS = 1.5

IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    ".agent",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "node_modules", "dist", "build", "out",
    ".idea",
}

IGNORE_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".pdf", ".zip", ".7z", ".rar", ".tar", ".gz",
    ".exe", ".dll", ".pdb", ".so", ".dylib",
    ".mp3", ".wav", ".mp4", ".mov", ".avi", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2",
    ".class", ".jar", ".pyc",
    ".db", ".sqlite", ".sqlite3",
}

TEXT_EXTENSIONS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".kts", ".scala",
    ".html", ".htm", ".css", ".scss", ".sass",
    ".json", ".jsonc", ".toml", ".yaml", ".yml",
    ".xml", ".md", ".txt", ".ini", ".cfg", ".conf",
    ".sh", ".ps1", ".bat", ".cmd",
}

# Commands that should never be launched by the agent.
BLOCKED_COMMAND_PATTERNS = [
    r"(?i)\bformat(?:\.com)?\b",
    r"(?i)\bdiskpart\b",
    r"(?i)\bshutdown\b",
    r"(?i)\brestart-computer\b",
    r"(?i)\bstop-computer\b",
    r"(?i)\bclear-disk\b",
    r"(?i)\binitialize-disk\b",
    r"(?i)\bremove-partition\b",
    r"(?i)\bremove-item\b[^\n]*\b-recurse\b[^\n]*[a-z]:\\",
    r"(?i)\bdel\b[^\n]*/[sq][^\n]*[a-z]:\\",
    r"(?i)\brd\b[^\n]*/[sq][^\n]*[a-z]:\\",
    r"(?i)\brm\s+-rf\s+[/\\]\s*$",
]


# =============================================================================
# Global state
# =============================================================================

PROJECT_ROOT: Path = Path.cwd()
AGENT_DIR: Path = PROJECT_ROOT / ".agent"
CONFIG_PATH: Path = AGENT_DIR / "config.json"
SESSION_PATH: Path = AGENT_DIR / "session.json"
REPO_MAP_PATH: Path = AGENT_DIR / "repo_map.json"

CURRENT_MODEL = DEFAULT_MODEL
CONTEXT_SIZE = DEFAULT_CTX
TEMPERATURE = DEFAULT_TEMP

APPROVAL_MODE = "safe"  # safe | edit | full
VERBOSE_TOOLS = False
RESUME_ENABLED = True

TURN_TOOL_COUNT = 0
LAST_INTERRUPT_TIME = 0.0
LAST_USER_TEXT = ""

# path -> {"sha256": ..., "size": ..., "mtime_ns": ...}
READ_SNAPSHOTS: Dict[str, Dict[str, Any]] = {}

# (path, existed_before, previous_content)
UNDO_STACK: List[Tuple[Path, bool, str]] = []

# [{"title": str, "status": pending|in_progress|done|blocked, "note": str}]
TASKS: List[Dict[str, str]] = []

# persisted input history
INPUT_HISTORY: List[str] = []

# repository map cache, keyed by project-relative path
REPO_MAP_CACHE: Dict[str, Dict[str, Any]] = {}
REPO_MAP_LOADED = False

POWERSHELL_EXE: Optional[str] = None


# =============================================================================
# Exceptions
# =============================================================================

class AgentError(Exception):
    pass


class AmbiguousPathError(AgentError):
    def __init__(self, user_path: str, matches: List[str]):
        self.user_path = user_path
        self.matches = matches
        joined = "\n".join(f"  - {m}" for m in matches[:20])
        super().__init__(
            f"Ambiguous path '{user_path}'. Multiple matching files exist:\n{joined}\n"
            "Use an explicit project-relative path."
        )


class OperationCancelled(Exception):
    pass


# =============================================================================
# Terminal styling / UI
# =============================================================================

try:
    if os.name == "nt":
        os.system("")
except Exception:
    pass

COLOR_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def color(text: str, *styles: str) -> str:
    if not COLOR_ENABLED:
        return text
    return "".join(styles) + text + C.RESET


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def terminal_width() -> int:
    try:
        return max(76, min(shutil.get_terminal_size((100, 24)).columns, 130))
    except Exception:
        return 100


def rule(ch: str = "─") -> str:
    return ch * terminal_width()


def print_rule(ch: str = "─", style: str = C.BRIGHT_BLACK) -> None:
    print(color(rule(ch), style))


def human_duration(seconds: float) -> str:
    if seconds < 0.001:
        return "<1 ms"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.1f} s"


def short_text(value: Any, limit: int = 180) -> str:
    s = str(value).replace("\r", " ").replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def status_line(label: str, value: str, style: str = C.WHITE) -> None:
    print(
        color(f"  {label:<11}", C.BRIGHT_BLACK)
        + color("│ ", C.BRIGHT_BLACK)
        + color(value, style)
    )


def ui_header(title: str, style: str = C.BRIGHT_CYAN) -> None:
    print()
    print(color(f"◆ {title}", C.BOLD, style))


def ui_success(text: str) -> None:
    print(color("  ✓ ", C.BRIGHT_GREEN) + text)


def ui_warn(text: str) -> None:
    print(color("  ! ", C.BRIGHT_YELLOW) + text)


def ui_error(text: str) -> None:
    print(color("  ✗ ", C.BRIGHT_RED) + text)


def ui_activity(label: str, detail: str = "", style: str = C.BRIGHT_CYAN) -> None:
    line = color("◆ ", style) + color(label, C.BOLD, C.WHITE)
    if detail:
        line += color("  " + detail, C.BRIGHT_BLACK)
    print(line)


class Spinner:
    """Animated one-line spinner. Safe to stop before printing regular output."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = "Working"):
        self.label = label
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.start_time = 0.0
        self._lock = threading.Lock()

    def set_label(self, label: str) -> None:
        with self._lock:
            self.label = label

    def start(self) -> None:
        if not sys.stdout.isatty():
            return
        self.running = True
        self.start_time = time.time()

        def loop() -> None:
            i = 0
            while self.running:
                with self._lock:
                    label = self.label
                elapsed = time.time() - self.start_time
                text = (
                    color(self.FRAMES[i % len(self.FRAMES)], C.BRIGHT_CYAN)
                    + " "
                    + color(label, C.BRIGHT_BLACK)
                    + color(f"  {elapsed:4.1f}s", C.DIM)
                )
                sys.stdout.write("\r\033[2K" + text)
                sys.stdout.flush()
                i += 1
                time.sleep(0.08)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.25)
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()


# =============================================================================
# Persistent config / session
# =============================================================================

def ensure_agent_dir() -> None:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: Any) -> None:
    ensure_agent_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_config() -> None:
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE
    global APPROVAL_MODE, VERBOSE_TOOLS, RESUME_ENABLED

    data = load_json(CONFIG_PATH, {})
    if not isinstance(data, dict):
        return

    CURRENT_MODEL = str(data.get("model", CURRENT_MODEL))

    try:
        CONTEXT_SIZE = max(2048, min(int(data.get("context", CONTEXT_SIZE)), 32768))
    except Exception:
        pass

    try:
        TEMPERATURE = max(0.0, min(float(data.get("temperature", TEMPERATURE)), 2.0))
    except Exception:
        pass

    mode = str(data.get("approval_mode", APPROVAL_MODE))
    if mode in {"safe", "edit", "full"}:
        APPROVAL_MODE = mode

    VERBOSE_TOOLS = bool(data.get("verbose_tools", VERBOSE_TOOLS))
    RESUME_ENABLED = bool(data.get("resume", RESUME_ENABLED))


def save_config() -> None:
    data = {
        "version": VERSION,
        "model": CURRENT_MODEL,
        "context": CONTEXT_SIZE,
        "temperature": TEMPERATURE,
        "approval_mode": APPROVAL_MODE,
        "verbose_tools": VERBOSE_TOOLS,
        "resume": RESUME_ENABLED,
    }
    try:
        atomic_write_json(CONFIG_PATH, data)
    except Exception:
        pass


def serializable_undo_stack() -> List[Dict[str, Any]]:
    # Persisting whole prior file contents could get large. Keep the newest 8
    # and cap each saved copy.
    result = []
    for p, existed, old in UNDO_STACK[-8:]:
        if len(old) > 120_000:
            continue
        result.append({
            "path": project_relative(p),
            "existed": existed,
            "old": old,
        })
    return result


def save_session(messages: List[Dict[str, Any]]) -> None:
    # Persist only complete user-turn groups so a saved session can never begin
    # with an orphaned tool result or lose the assistant tool call it belongs to.
    persisted_messages = messages
    if len(messages) > MAX_SESSION_MESSAGES:
        systems, groups = split_turn_groups(messages)
        kept: List[List[Dict[str, Any]]] = []
        count = len(systems)
        for group in reversed(groups):
            if kept and count + len(group) > MAX_SESSION_MESSAGES:
                break
            kept.insert(0, group)
            count += len(group)

        persisted_messages = list(systems)
        for group in kept:
            persisted_messages.extend(group)

    data = {
        "version": VERSION,
        "saved_at": time.time(),
        "messages": persisted_messages,
        "tasks": TASKS,
        "input_history": INPUT_HISTORY[-MAX_INPUT_HISTORY:],
        "read_snapshots": READ_SNAPSHOTS,
        "undo_stack": serializable_undo_stack(),
    }
    try:
        atomic_write_json(SESSION_PATH, data)
    except Exception:
        pass


def load_session(system_prompt: str) -> Tuple[List[Dict[str, Any]], bool]:
    global TASKS, INPUT_HISTORY, READ_SNAPSHOTS, UNDO_STACK

    if not RESUME_ENABLED:
        return [{"role": "system", "content": system_prompt}], False

    data = load_json(SESSION_PATH, {})
    if not isinstance(data, dict) or not data:
        return [{"role": "system", "content": system_prompt}], False

    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return [{"role": "system", "content": system_prompt}], False

    # Always use the newest system prompt from this script.
    cleaned = [{"role": "system", "content": system_prompt}]
    for m in msgs:
        if isinstance(m, dict) and m.get("role") != "system":
            cleaned.append(m)

    raw_tasks = data.get("tasks", [])
    if isinstance(raw_tasks, list):
        TASKS = [
            {
                "title": str(x.get("title", "")),
                "status": str(x.get("status", "pending")),
                "note": str(x.get("note", "")),
            }
            for x in raw_tasks
            if isinstance(x, dict) and x.get("title")
        ]

    raw_history = data.get("input_history", [])
    if isinstance(raw_history, list):
        INPUT_HISTORY = [str(x) for x in raw_history[-MAX_INPUT_HISTORY:]]

    raw_snapshots = data.get("read_snapshots", {})
    if isinstance(raw_snapshots, dict):
        READ_SNAPSHOTS = {
            str(k): v for k, v in raw_snapshots.items()
            if isinstance(v, dict)
        }

    UNDO_STACK = []
    for item in data.get("undo_stack", []):
        if not isinstance(item, dict):
            continue
        try:
            p = resolve_path(str(item.get("path", "")), allow_missing=True, resolve_basename=False)
            UNDO_STACK.append((p, bool(item.get("existed")), str(item.get("old", ""))))
        except Exception:
            pass

    return cleaned, True


# =============================================================================
# Input editor / keyboard controls
# =============================================================================

def remember_input(text: str) -> None:
    text = text.strip()
    if not text:
        return
    if not INPUT_HISTORY or INPUT_HISTORY[-1] != text:
        INPUT_HISTORY.append(text)
        del INPUT_HISTORY[:-MAX_INPUT_HISTORY]


def _redraw_input(prompt: str, buf: List[str], cursor: int) -> None:
    text = "".join(buf)
    sys.stdout.write("\r\033[2K" + prompt + text)
    right = len(buf) - cursor
    if right > 0:
        sys.stdout.write(f"\033[{right}D")
    sys.stdout.flush()


def windows_readline(prompt: str) -> str:
    import msvcrt

    buf: List[str] = []
    cursor = 0
    history_index = len(INPUT_HISTORY)
    draft = ""

    sys.stdout.write(prompt)
    sys.stdout.flush()

    while True:
        ch = msvcrt.getwch()

        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)

        if ch == "\x03":  # Ctrl+C
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise KeyboardInterrupt

        if ch == "\x1a":  # Ctrl+Z
            continue

        if ch == "\x01":  # Ctrl+A
            cursor = 0
            _redraw_input(prompt, buf, cursor)
            continue

        if ch == "\x05":  # Ctrl+E
            cursor = len(buf)
            _redraw_input(prompt, buf, cursor)
            continue

        if ch == "\x15":  # Ctrl+U
            buf = []
            cursor = 0
            history_index = len(INPUT_HISTORY)
            _redraw_input(prompt, buf, cursor)
            continue

        if ch == "\x08":  # backspace
            if cursor > 0:
                del buf[cursor - 1]
                cursor -= 1
                _redraw_input(prompt, buf, cursor)
            continue

        if ch in ("\x00", "\xe0"):
            key = msvcrt.getwch()

            if key == "K":  # left
                if cursor > 0:
                    cursor -= 1
                    _redraw_input(prompt, buf, cursor)
            elif key == "M":  # right
                if cursor < len(buf):
                    cursor += 1
                    _redraw_input(prompt, buf, cursor)
            elif key == "G":  # home
                cursor = 0
                _redraw_input(prompt, buf, cursor)
            elif key == "O":  # end
                cursor = len(buf)
                _redraw_input(prompt, buf, cursor)
            elif key == "S":  # delete
                if cursor < len(buf):
                    del buf[cursor]
                    _redraw_input(prompt, buf, cursor)
            elif key == "H":  # up
                if INPUT_HISTORY:
                    if history_index == len(INPUT_HISTORY):
                        draft = "".join(buf)
                    history_index = max(0, history_index - 1)
                    buf = list(INPUT_HISTORY[history_index])
                    cursor = len(buf)
                    _redraw_input(prompt, buf, cursor)
            elif key == "P":  # down
                if history_index < len(INPUT_HISTORY):
                    history_index += 1
                    if history_index == len(INPUT_HISTORY):
                        buf = list(draft)
                    else:
                        buf = list(INPUT_HISTORY[history_index])
                    cursor = len(buf)
                    _redraw_input(prompt, buf, cursor)
            continue

        # Printable char
        if ch >= " ":
            buf.insert(cursor, ch)
            cursor += 1
            _redraw_input(prompt, buf, cursor)


def read_user_input(prompt: str) -> str:
    if os.name == "nt" and sys.stdin.isatty() and sys.stdout.isatty():
        return windows_readline(prompt)
    return input(prompt)


# =============================================================================
# Filesystem safety, path resolution, snapshots
# =============================================================================

def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        return str(path)


def _validate_inside_project(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        raise AgentError("Path is outside the project folder.")
    return resolved


def find_exact_basename(name: str, limit: int = 30) -> List[str]:
    matches: List[str] = []
    target = name.lower()

    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.lower() == target:
                rel = (Path(root) / f).relative_to(PROJECT_ROOT).as_posix()
                matches.append(rel)
                if len(matches) >= limit:
                    return matches
    return matches


def resolve_path(
    user_path: str,
    *,
    allow_missing: bool = False,
    resolve_basename: bool = True,
) -> Path:
    if not user_path:
        user_path = "."

    raw = user_path.strip().replace("\\", os.sep).replace("/", os.sep)
    p = Path(raw)

    if p.is_absolute():
        raise AgentError("Use project-relative paths only.")

    candidate = _validate_inside_project(PROJECT_ROOT / p)

    if candidate.exists():
        return candidate

    simple_name = (len(p.parts) == 1 and p.name not in {".", ".."})

    if resolve_basename and simple_name:
        matches = find_exact_basename(p.name)
        if len(matches) == 1:
            return _validate_inside_project(PROJECT_ROOT / matches[0])
        if len(matches) > 1:
            raise AmbiguousPathError(user_path, matches)

    if allow_missing:
        return candidate

    raise AgentError(f"Path does not exist: {user_path}")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def snapshot_file(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    snap = {
        "sha256": file_sha256(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    READ_SNAPSHOTS[project_relative(path)] = snap
    return snap


def fresh_snapshot_error(path: Path) -> Optional[str]:
    rel = project_relative(path)

    if not path.exists():
        return None

    snap = READ_SNAPSHOTS.get(rel)
    if not snap:
        return (
            f"ERROR: {rel} has not been read in this session/context. "
            "Read the relevant file first before modifying it."
        )

    try:
        current_hash = file_sha256(path)
    except Exception as e:
        return f"ERROR: Could not verify {rel}: {e}"

    if current_hash != snap.get("sha256"):
        return (
            f"ERROR: {rel} changed after the agent last read it. "
            "The edit was blocked to avoid overwriting newer changes. "
            "Re-read the file, then retry the edit."
        )

    return None


def is_probably_binary(path: Path) -> bool:
    if path.suffix.lower() in IGNORE_BINARY_EXTS:
        return True

    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except Exception:
        return False


def remember_for_undo(path: Path) -> None:
    existed = path.exists() and path.is_file()
    old = ""
    if existed:
        old = path.read_text(encoding="utf-8", errors="replace")
    UNDO_STACK.append((path, existed, old))
    if len(UNDO_STACK) > 30:
        del UNDO_STACK[:-30]


def undo_last_change() -> str:
    if not UNDO_STACK:
        return "Nothing to undo."

    path, existed, old = UNDO_STACK.pop()
    rel = project_relative(path)

    if existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(old, encoding="utf-8")
        snapshot_file(path)
        return f"Restored {rel}."

    if path.exists() and path.is_file():
        path.unlink()
    READ_SNAPSHOTS.pop(rel, None)
    return f"Removed newly created file {rel}."


# =============================================================================
# Approval / diff
# =============================================================================

def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    full_prompt = (
        "\n"
        + color("  APPROVAL ", C.BOLD, C.BRIGHT_YELLOW)
        + color(prompt, C.WHITE)
        + " "
        + color(suffix, C.BRIGHT_BLACK)
        + ": "
    )
    try:
        answer = read_user_input(full_prompt).strip().lower()
    except KeyboardInterrupt:
        return False

    if not answer:
        return default
    return answer in {"y", "yes"}


def should_auto_approve(kind: str) -> bool:
    if APPROVAL_MODE == "full":
        return kind in {"write", "command", "mkdir"}
    if APPROVAL_MODE == "edit":
        return kind in {"write", "mkdir"}
    return False


def show_diff(path: str, old: str, new: str) -> None:
    diff_lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )

    ui_header(f"DIFF  {path}", C.BRIGHT_MAGENTA)
    print_rule("·", C.BRIGHT_BLACK)

    if not diff_lines:
        print(color("  No textual changes.", C.BRIGHT_BLACK))
        return

    max_lines = 320
    for line in diff_lines[:max_lines]:
        line = line.rstrip("\n")
        if line.startswith("+++") or line.startswith("---"):
            print(color(line, C.BRIGHT_BLACK))
        elif line.startswith("+"):
            print(color(line, C.BRIGHT_GREEN))
        elif line.startswith("-"):
            print(color(line, C.BRIGHT_RED))
        elif line.startswith("@@"):
            print(color(line, C.BRIGHT_CYAN))
        else:
            print(line)

    if len(diff_lines) > max_lines:
        print(
            color(
                f"... diff truncated ({len(diff_lines) - max_lines} more lines) ...",
                C.BRIGHT_BLACK,
            )
        )


# =============================================================================
# Task plan
# =============================================================================

TASK_ICONS = {
    "pending": "○",
    "in_progress": "◆",
    "done": "✓",
    "blocked": "!",
}

TASK_STYLES = {
    "pending": C.BRIGHT_BLACK,
    "in_progress": C.BRIGHT_CYAN,
    "done": C.BRIGHT_GREEN,
    "blocked": C.BRIGHT_YELLOW,
}


def render_tasks() -> None:
    if not TASKS:
        return

    ui_header("TASK", C.BRIGHT_CYAN)
    for i, task in enumerate(TASKS, 1):
        status = task.get("status", "pending")
        icon = TASK_ICONS.get(status, "○")
        style = TASK_STYLES.get(status, C.WHITE)
        line = (
            color(f"  {icon} ", style)
            + color(f"{i:>2}. ", C.BRIGHT_BLACK)
            + color(task.get("title", ""), C.WHITE if status != "done" else C.BRIGHT_BLACK)
        )
        note = task.get("note", "").strip()
        if note:
            line += color("  " + note, C.BRIGHT_BLACK)
        print(line)
    print()


def tool_set_task_plan(tasks: List[str], reason: str = "") -> str:
    global TASKS

    clean = [str(t).strip() for t in tasks if str(t).strip()]
    if not clean:
        return "ERROR: Task plan cannot be empty."

    if len(clean) > 12:
        clean = clean[:12]

    TASKS = [
        {"title": t, "status": "pending", "note": ""}
        for t in clean
    ]
    if TASKS:
        TASKS[0]["status"] = "in_progress"

    render_tasks()
    return f"Task plan set with {len(TASKS)} step(s)."


def tool_update_task(
    index: int,
    status: str,
    note: str = "",
    reason: str = "",
) -> str:
    if not TASKS:
        return "ERROR: No task plan exists."

    try:
        idx = int(index) - 1
    except Exception:
        return "ERROR: index must be an integer."

    if idx < 0 or idx >= len(TASKS):
        return f"ERROR: Task index must be 1-{len(TASKS)}."

    if status not in {"pending", "in_progress", "done", "blocked"}:
        return "ERROR: status must be pending, in_progress, done, or blocked."

    # Keep only one active step unless model explicitly marks others later.
    if status == "in_progress":
        for i, task in enumerate(TASKS):
            if i != idx and task.get("status") == "in_progress":
                task["status"] = "pending"

    TASKS[idx]["status"] = status
    TASKS[idx]["note"] = str(note or "").strip()

    render_tasks()
    return f"Task {index} updated to {status}."


def abandon_current_task() -> None:
    for task in TASKS:
        if task.get("status") == "in_progress":
            task["status"] = "blocked"
            task["note"] = "Stopped by user"
    if TASKS:
        render_tasks()


# =============================================================================
# Repository map
# =============================================================================

LANG_BY_EXT = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C", ".h": "C/C++",
    ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS",
    ".json": "JSON",
    ".md": "Markdown",
}


def analyze_python_file(path: Path, text: str) -> Tuple[List[str], List[str]]:
    symbols: List[str] = []
    imports: List[str] = []

    try:
        tree = ast.parse(text)
    except Exception:
        return symbols, imports

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(f"def {node.name}")
        elif isinstance(node, ast.ClassDef):
            symbols.append(f"class {node.name}")
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"{node.name}.{child.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imports.append(base)

    return symbols[:60], imports[:40]


GENERIC_SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:public|private|protected|internal|static|final|abstract|\s)*\s*class\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*func\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
]

GENERIC_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+"),
    re.compile(r"^\s*using\s+([A-Za-z0-9_\.]+)\s*;"),
]


def analyze_generic_text(text: str) -> Tuple[List[str], List[str]]:
    symbols: List[str] = []
    imports: List[str] = []

    for line in text.splitlines()[:5000]:
        for pattern in GENERIC_SYMBOL_PATTERNS:
            m = pattern.search(line)
            if m:
                symbols.append(m.group(1))
                break

        for pattern in GENERIC_IMPORT_PATTERNS:
            m = pattern.search(line)
            if m:
                imports.append(m.group(1))
                break

        if len(symbols) >= 60 and len(imports) >= 40:
            break

    return symbols[:60], imports[:40]


def load_repo_map_cache() -> None:
    global REPO_MAP_CACHE, REPO_MAP_LOADED
    if REPO_MAP_LOADED:
        return
    data = load_json(REPO_MAP_PATH, {})
    if isinstance(data, dict):
        REPO_MAP_CACHE = data
    else:
        REPO_MAP_CACHE = {}
    REPO_MAP_LOADED = True


def save_repo_map_cache() -> None:
    try:
        atomic_write_json(REPO_MAP_PATH, REPO_MAP_CACHE)
    except Exception:
        pass


def iter_project_files() -> Iterable[Path]:
    count = 0
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in IGNORE_BINARY_EXTS:
                continue
            yield p
            count += 1
            if count >= MAX_REPO_MAP_FILES:
                return


def refresh_repo_map(force: bool = False) -> Tuple[int, int]:
    load_repo_map_cache()

    seen: set[str] = set()
    changed = 0
    total = 0

    spinner = Spinner("Building repository map")
    spinner.start()

    try:
        for path in iter_project_files():
            total += 1
            rel = project_relative(path)
            seen.add(rel)

            try:
                stat = path.stat()
            except Exception:
                continue

            cached = REPO_MAP_CACHE.get(rel)
            if (
                not force
                and isinstance(cached, dict)
                and cached.get("mtime_ns") == stat.st_mtime_ns
                and cached.get("size") == stat.st_size
            ):
                continue

            if is_probably_binary(path):
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lang = LANG_BY_EXT.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "text")
            if path.suffix.lower() in {".py", ".pyw"}:
                symbols, imports = analyze_python_file(path, text)
            else:
                symbols, imports = analyze_generic_text(text)

            REPO_MAP_CACHE[rel] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "language": lang,
                "symbols": symbols,
                "imports": imports,
            }
            changed += 1

        stale = [k for k in REPO_MAP_CACHE if k not in seen]
        for k in stale:
            REPO_MAP_CACHE.pop(k, None)

        save_repo_map_cache()
    finally:
        spinner.stop()

    return total, changed


def tool_repo_map(
    query: str = "",
    refresh: bool = False,
    max_results: int = 80,
    reason: str = "",
) -> str:
    try:
        total, changed = refresh_repo_map(force=bool(refresh))
        max_results = max(1, min(int(max_results), MAX_REPO_MAP_RESULTS))

        q = query.strip().lower()
        rows = []

        for rel, info in sorted(REPO_MAP_CACHE.items()):
            haystack = " ".join([
                rel,
                str(info.get("language", "")),
                " ".join(info.get("symbols", []) or []),
                " ".join(info.get("imports", []) or []),
            ]).lower()

            if q and q not in haystack:
                continue

            symbols = info.get("symbols", []) or []
            imports = info.get("imports", []) or []

            row = f"{rel} [{info.get('language', 'text')}, {info.get('size', 0)} B]"
            if symbols:
                row += " | symbols: " + ", ".join(symbols[:14])
            if imports:
                row += " | imports: " + ", ".join(imports[:10])

            rows.append(row)
            if len(rows) >= max_results:
                rows.append("... more repository-map entries omitted ...")
                break

        header = f"Repository map: {total} files scanned, {changed} refreshed."
        return header + "\n" + ("\n".join(rows) if rows else "(no matching map entries)")
    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# Read-only project helpers
# =============================================================================

def tool_project_info(reason: str = "") -> str:
    counts: Dict[str, int] = {}
    total_files = 0

    for path in iter_project_files():
        total_files += 1
        ext = path.suffix.lower() or "(no extension)"
        counts[ext] = counts.get(ext, 0) + 1

    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:14]
    languages = ", ".join(f"{ext}: {count}" for ext, count in top)

    root_items = []
    try:
        for item in sorted(PROJECT_ROOT.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name in IGNORE_DIRS:
                continue
            root_items.append(item.name + ("/" if item.is_dir() else ""))
            if len(root_items) >= 50:
                break
    except Exception:
        pass

    return (
        f"Project root: {PROJECT_ROOT}\n"
        f"Approx files: {total_files}\n"
        f"Common extensions: {languages or '(none)'}\n"
        f"Top-level: {', '.join(root_items) or '(empty)'}\n"
        f"Git branch: {get_git_branch() or '(not a git repo)'}"
    )


def tool_list_files(
    path: str = ".",
    recursive: bool = False,
    max_depth: int = 3,
    reason: str = "",
) -> str:
    try:
        base = resolve_path(path)
        if not base.is_dir():
            return f"ERROR: Not a directory: {path}"

        max_depth = max(1, min(int(max_depth), 8))
        results: List[str] = []

        if not recursive:
            for item in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if item.name in IGNORE_DIRS:
                    continue
                rel = project_relative(item)
                results.append(rel + ("/" if item.is_dir() else ""))
                if len(results) >= MAX_TREE_ENTRIES:
                    results.append("... output truncated ...")
                    break
            return "\n".join(results) if results else "(empty directory)"

        start_parts = len(base.parts)

        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            depth = len(root_path.parts) - start_parts

            dirs[:] = [
                d for d in dirs
                if d not in IGNORE_DIRS and depth < max_depth
            ]

            rel_root = root_path.relative_to(PROJECT_ROOT)

            if depth > 0:
                results.append(rel_root.as_posix() + "/")

            for name in sorted(files):
                rel = (rel_root / name).as_posix()
                results.append(rel)
                if len(results) >= MAX_TREE_ENTRIES:
                    results.append("... output truncated ...")
                    return "\n".join(results)

        return "\n".join(results) if results else "(empty directory)"
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


def tool_find_files(
    pattern: str,
    path: str = ".",
    max_results: int = 100,
    reason: str = "",
) -> str:
    try:
        base = resolve_path(path)
        if not base.is_dir():
            return f"ERROR: Not a directory: {path}"

        max_results = max(1, min(int(max_results), 300))
        matches: List[str] = []

        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for name in files:
                rel = (Path(root) / name).relative_to(PROJECT_ROOT).as_posix()
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                    matches.append(rel)
                    if len(matches) >= max_results:
                        matches.append("... more matches omitted ...")
                        return "\n".join(matches)

        return "\n".join(matches) if matches else "(no matching files)"
    except Exception as e:
        return f"ERROR: {e}"


def tool_search_text(
    query: str,
    path: str = ".",
    glob: str = "*",
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 60,
    reason: str = "",
) -> str:
    try:
        base = resolve_path(path)
        max_results = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
        results: List[str] = []

        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            matcher = re.compile(query, flags)
        else:
            needle = query if case_sensitive else query.lower()

        candidates: List[Path] = []

        if base.is_file():
            candidates = [base]
        else:
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for name in files:
                    p = Path(root) / name
                    rel = p.relative_to(PROJECT_ROOT).as_posix()
                    if fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(rel, glob):
                        candidates.append(p)

        for p in candidates:
            if is_probably_binary(p):
                continue

            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            rel = project_relative(p)

            for i, line in enumerate(lines, 1):
                if regex:
                    matched = bool(matcher.search(line))
                else:
                    haystack = line if case_sensitive else line.lower()
                    matched = needle in haystack

                if matched:
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if len(results) >= max_results:
                        results.append("... more matches omitted ...")
                        return "\n".join(results)

        return "\n".join(results) if results else "(no matches)"
    except re.error as e:
        return f"ERROR: Invalid regular expression: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def tool_read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 0,
    reason: str = "",
) -> str:
    try:
        p = resolve_path(path)

        if not p.is_file():
            return f"ERROR: Not a file: {path}"
        if is_probably_binary(p):
            return f"ERROR: {project_relative(p)} appears to be binary."

        text = p.read_text(encoding="utf-8", errors="replace")
        snapshot = snapshot_file(p)
        lines = text.splitlines()

        start_line = max(1, int(start_line))
        if int(end_line) <= 0:
            end_line = min(len(lines), start_line + MAX_READ_LINES - 1)
        else:
            end_line = min(len(lines), int(end_line))
            end_line = min(end_line, start_line + MAX_READ_LINES - 1)

        selected = lines[start_line - 1:end_line]
        numbered = [
            f"{line_no:>5} | {line}"
            for line_no, line in enumerate(selected, start_line)
        ]

        result = (
            f"FILE: {project_relative(p)}\n"
            f"SHA256: {snapshot['sha256']}\n"
            f"LINES: {start_line}-{end_line} of {len(lines)}\n"
            + "\n".join(numbered)
        )

        if len(result) > MAX_FILE_CHARS:
            result = result[:MAX_FILE_CHARS] + "\n... file output truncated ..."

        return result
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# Edit helpers with stale-file protection
# =============================================================================

def _approve_and_write(path: Path, old: str, new: str, prompt_text: str) -> str:
    rel = project_relative(path)
    if old == new:
        return "No changes needed."

    show_diff(rel, old, new)

    approved = should_auto_approve("write")
    if not approved:
        approved = confirm(prompt_text)

    if not approved:
        return "Edit denied by user."

    remember_for_undo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    snapshot_file(path)

    # invalidate repo map entry; next map call refreshes it
    REPO_MAP_CACHE.pop(rel, None)

    return f"Successfully updated {rel}. Undo available with /undo."


def tool_write_file(path: str, content: str, reason: str = "") -> str:
    try:
        p = resolve_path(path, allow_missing=True)

        if p.exists() and not p.is_file():
            return f"ERROR: Not a file: {path}"

        old = ""
        if p.exists():
            stale = fresh_snapshot_error(p)
            if stale:
                return stale
            old = p.read_text(encoding="utf-8", errors="replace")

        return _approve_and_write(
            p,
            old,
            content,
            f"Allow write to {project_relative(p)}?",
        )
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


def tool_edit_file(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    reason: str = "",
) -> str:
    try:
        p = resolve_path(path)

        if not p.is_file():
            return f"ERROR: Not a file: {path}"

        stale = fresh_snapshot_error(p)
        if stale:
            return stale

        content = p.read_text(encoding="utf-8", errors="replace")
        occurrences = content.count(old_text)

        if occurrences == 0:
            return (
                "ERROR: old_text was not found exactly. "
                "Re-read the relevant range or use replace_lines with exact line numbers."
            )

        if occurrences > 1 and not replace_all:
            return (
                f"ERROR: old_text occurs {occurrences} times. "
                "Provide more surrounding text, use replace_lines, or set replace_all=true."
            )

        updated = (
            content.replace(old_text, new_text)
            if replace_all
            else content.replace(old_text, new_text, 1)
        )

        return _approve_and_write(
            p,
            content,
            updated,
            f"Apply edit to {project_relative(p)}?",
        )
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


def tool_replace_lines(
    path: str,
    start_line: int,
    end_line: int,
    new_text: str,
    reason: str = "",
) -> str:
    """
    Replace an inclusive line range. Requires a fresh prior read snapshot.
    This is more robust than exact string replacement when whitespace differs.
    """
    try:
        p = resolve_path(path)
        if not p.is_file():
            return f"ERROR: Not a file: {path}"

        stale = fresh_snapshot_error(p)
        if stale:
            return stale

        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total = len(lines)

        start_line = int(start_line)
        end_line = int(end_line)

        if start_line < 1 or end_line < start_line or end_line > total:
            return f"ERROR: Invalid line range {start_line}-{end_line}; file has {total} lines."

        newline = "\r\n" if "\r\n" in content else "\n"

        replacement = new_text
        # Preserve file line structure when replacing interior lines.
        if end_line < total and replacement and not replacement.endswith(("\n", "\r")):
            replacement += newline

        updated = "".join(lines[:start_line - 1]) + replacement + "".join(lines[end_line:])

        return _approve_and_write(
            p,
            content,
            updated,
            f"Replace lines {start_line}-{end_line} in {project_relative(p)}?",
        )
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


def tool_insert_text(
    path: str,
    line: int,
    text: str,
    position: str = "before",
    reason: str = "",
) -> str:
    """
    Insert text before or after a line. line=0 with position='after' appends.
    """
    try:
        p = resolve_path(path)
        if not p.is_file():
            return f"ERROR: Not a file: {path}"

        stale = fresh_snapshot_error(p)
        if stale:
            return stale

        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total = len(lines)
        newline = "\r\n" if "\r\n" in content else "\n"

        position = position.lower().strip()
        if position not in {"before", "after"}:
            return "ERROR: position must be 'before' or 'after'."

        line = int(line)

        if total == 0:
            index = 0
        elif line == 0 and position == "after":
            index = total
        elif line < 1 or line > total:
            return f"ERROR: line must be 1-{total}, or 0 with position='after' to append."
        else:
            index = line - 1 if position == "before" else line

        insert = text
        if insert and not insert.endswith(("\n", "\r")):
            insert += newline

        # If appending after a final line that has no newline, add the separator
        # first so the inserted text cannot accidentally join onto that line.
        if (
            index == total
            and content
            and not content.endswith(("\n", "\r"))
            and insert
        ):
            insert = newline + insert

        updated = "".join(lines[:index]) + insert + "".join(lines[index:])

        return _approve_and_write(
            p,
            content,
            updated,
            f"Insert text in {project_relative(p)}?",
        )
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


def tool_make_directory(path: str, reason: str = "") -> str:
    try:
        p = resolve_path(path, allow_missing=True, resolve_basename=False)

        if p.exists():
            return (
                f"Directory already exists: {project_relative(p)}"
                if p.is_dir()
                else f"ERROR: A file exists at {project_relative(p)}"
            )

        approved = should_auto_approve("mkdir")
        if not approved:
            approved = confirm(f"Create directory {project_relative(p)}?")

        if not approved:
            return "Directory creation denied by user."

        p.mkdir(parents=True, exist_ok=True)
        return f"Created directory {project_relative(p)}."
    except Exception as e:
        return f"ERROR: {e}"


def tool_delete_file(path: str, reason: str = "") -> str:
    # Always explicit approval, even in full mode.
    try:
        p = resolve_path(path)
        if not p.is_file():
            return f"ERROR: Refusing to delete a directory: {path}"

        stale = fresh_snapshot_error(p)
        if stale:
            return stale

        rel = project_relative(p)
        ui_header(f"DELETE  {rel}", C.BRIGHT_RED)

        if not confirm(f"Permanently delete {rel}?"):
            return "Delete denied by user."

        remember_for_undo(p)
        p.unlink()
        READ_SNAPSHOTS.pop(rel, None)
        REPO_MAP_CACHE.pop(rel, None)

        return f"Deleted {rel}. Undo available with /undo."
    except AmbiguousPathError as e:
        return "ERROR: " + str(e)
    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# Native PowerShell command execution with live output
# =============================================================================

def detect_powershell() -> Optional[str]:
    candidates = [
        shutil.which("pwsh"),
        shutil.which("powershell"),
    ]

    if os.name == "nt":
        system_ps = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        candidates.append(str(system_ps) if system_ps.exists() else None)

    for c in candidates:
        if c:
            return c
    return None


def command_is_blocked(command: str) -> Optional[str]:
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, command):
            return pattern
    return None


def _terminate_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_powershell_live(command: str, timeout: int) -> Tuple[int, str, float, bool]:
    """
    Execute through PowerShell and stream output line-by-line.

    Returns (exit_code, captured_output, elapsed, cancelled).
    """
    if not POWERSHELL_EXE:
        raise AgentError("PowerShell could not be found.")

    args = [
        POWERSHELL_EXE,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", command,
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        universal_newlines=True,
        creationflags=creationflags,
    )

    q: queue.Queue = queue.Queue()
    sentinel = object()

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                q.put(line)
        finally:
            q.put(sentinel)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    start = time.time()
    captured: List[str] = []
    captured_chars = 0
    display_lines = 0
    output_started = False
    suppressed_notice = False
    cancelled = False

    spinner = Spinner("Command running")
    spinner.start()

    try:
        stream_finished = False

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                _terminate_process(proc)
                spinner.stop()
                print(color(f"  ! timed out after {timeout}s", C.BRIGHT_YELLOW))
                return 124, "".join(captured), elapsed, False

            try:
                item = q.get(timeout=0.08)
            except queue.Empty:
                if proc.poll() is not None and stream_finished:
                    break
                continue

            if item is sentinel:
                stream_finished = True
                if proc.poll() is not None:
                    break
                continue

            line = str(item)

            if not output_started:
                spinner.stop()
                output_started = True
                print_rule("·", C.BRIGHT_BLACK)

            if display_lines < MAX_COMMAND_DISPLAY_LINES:
                live_elapsed = time.time() - start
                prefix = color(f"│ +{live_elapsed:5.1f}s  ", C.BRIGHT_BLACK)
                sys.stdout.write(prefix + line)
                sys.stdout.flush()
                display_lines += 1
            elif not suppressed_notice:
                print(color("│ ... additional live output suppressed ...", C.BRIGHT_BLACK))
                suppressed_notice = True

            if captured_chars < MAX_COMMAND_CAPTURE_CHARS:
                remaining = MAX_COMMAND_CAPTURE_CHARS - captured_chars
                captured.append(line[:remaining])
                captured_chars += len(line[:remaining])

        proc.wait(timeout=2)

    except KeyboardInterrupt:
        cancelled = True
        _terminate_process(proc)
        spinner.stop()
        print()
        ui_warn("Command cancelled.")
    finally:
        spinner.stop()
        if output_started:
            print_rule("·", C.BRIGHT_BLACK)

    elapsed = time.time() - start
    code = proc.returncode if proc.returncode is not None else (130 if cancelled else 1)

    return code, "".join(captured), elapsed, cancelled


def tool_run_command(
    command: str,
    timeout: int = 120,
    reason: str = "",
) -> str:
    blocked = command_is_blocked(command)
    if blocked:
        return "ERROR: Command rejected by the safety filter."

    timeout = max(1, min(int(timeout), 600))

    ui_header("RUN  PowerShell", C.BRIGHT_YELLOW)
    status_line("command", command, C.WHITE)
    if reason:
        status_line("reason", short_text(reason, 260), C.BRIGHT_BLACK)

    approved = should_auto_approve("command")
    if not approved:
        approved = confirm("Run this PowerShell command?")

    if not approved:
        return "Command denied by user."

    try:
        code, output, elapsed, cancelled = run_powershell_live(command, timeout)
    except Exception as e:
        return f"ERROR: {e}"

    style = C.BRIGHT_GREEN if code == 0 else C.BRIGHT_RED
    print(
        color("  RESULT ", C.BOLD, style)
        + color(f"exit {code}", C.WHITE)
        + color(f"  ·  {human_duration(elapsed)}", C.BRIGHT_BLACK)
    )

    result = f"exit_code: {code}\nelapsed: {elapsed:.2f}s"
    if cancelled:
        result += "\ncancelled: true"
    if output:
        result += "\noutput:\n" + output

    if len(result) > MAX_COMMAND_CAPTURE_CHARS:
        result = result[:MAX_COMMAND_CAPTURE_CHARS] + "\n... captured output truncated ..."

    return result


# =============================================================================
# Git helpers
# =============================================================================

def run_readonly_git(args: List[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip() or "(no output)"
    except FileNotFoundError:
        return "ERROR: git is not installed or not on PATH."
    except Exception as e:
        return f"ERROR: {e}"


def get_git_branch() -> Optional[str]:
    out = run_readonly_git(["branch", "--show-current"])
    if out.startswith("ERROR:") or out == "(no output)":
        return None
    return out.strip() or None


def tool_git_status(reason: str = "") -> str:
    return run_readonly_git(["status", "--short", "--branch"])


def tool_git_diff(path: str = ".", reason: str = "") -> str:
    try:
        if path != ".":
            resolve_path(path, allow_missing=True, resolve_basename=False)
    except Exception as e:
        return f"ERROR: {e}"

    result = run_readonly_git(["diff", "--", path])
    if len(result) > MAX_COMMAND_CAPTURE_CHARS:
        result = result[:MAX_COMMAND_CAPTURE_CHARS] + "\n... diff truncated ..."
    return result


# =============================================================================
# Tool schemas
# =============================================================================

def reason_property() -> Dict[str, Any]:
    return {
        "type": "string",
        "description": "Brief user-visible reason for this action. Do not include hidden chain-of-thought.",
    }


TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "set_task_plan",
            "description": "Set a concise visible task checklist for a non-trivial coding task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered task steps, normally 2-8 items.",
                    },
                    "reason": reason_property(),
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update one visible task-plan step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "blocked"],
                    },
                    "note": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": ["index", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_info",
            "description": "Get a quick project summary.",
            "parameters": {
                "type": "object",
                "properties": {"reason": reason_property()},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_map",
            "description": "Search the cached repository map of files, symbols, and imports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "refresh": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files/directories inside the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "max_depth": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by wildcard pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text across project files and return line matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "case_sensitive": {"type": "boolean"},
                    "regex": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text-file range with line numbers and record a stale-edit safety snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a text file. Existing files must have been read first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in a previously read file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                    "reason": reason_property(),
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "Safely replace an inclusive line range in a previously read file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "new_text": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": ["path", "start_line", "end_line", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_text",
            "description": "Insert text before/after a line in a previously read file. line=0 after appends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string"},
                    "position": {
                        "type": "string",
                        "enum": ["before", "after"],
                    },
                    "reason": reason_property(),
                },
                "required": ["path", "line", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_directory",
            "description": "Create a directory inside the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a previously read file. Always requires explicit confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a PowerShell command in the project root with live output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                    "reason": reason_property(),
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Read Git status.",
            "parameters": {
                "type": "object",
                "properties": {"reason": reason_property()},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Read Git diff for the whole project or one path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "reason": reason_property(),
                },
                "required": [],
            },
        },
    },
]


FUNCTIONS = {
    "set_task_plan": tool_set_task_plan,
    "update_task": tool_update_task,
    "project_info": tool_project_info,
    "repo_map": tool_repo_map,
    "list_files": tool_list_files,
    "find_files": tool_find_files,
    "search_text": tool_search_text,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
    "replace_lines": tool_replace_lines,
    "insert_text": tool_insert_text,
    "make_directory": tool_make_directory,
    "delete_file": tool_delete_file,
    "run_command": tool_run_command,
    "git_status": tool_git_status,
    "git_diff": tool_git_diff,
}


# =============================================================================
# Agent prompt
# =============================================================================

SYSTEM_PROMPT = """You are Hyper-Cube Agent V3, a local autonomous coding agent.

You operate on exactly one project through the provided tools.

WORKFLOW
- For non-trivial requests, create a short task plan first and keep it updated.
- Inspect before editing. Existing files MUST be read before modification.
- Prefer repo_map/search_text/find_files before broad recursive reading.
- If a filename is ambiguous, do not guess. Ask the user for the explicit path.
- Prefer edit_file for exact small edits, replace_lines when line ranges are clearer,
  insert_text for insertion/appending, and write_file for new files or major rewrites.
- After edits, run the smallest useful validation command when practical.
- If validation fails, inspect the output and iterate.
- Finish with a concise summary of changes, validation, and remaining issues.

VISIBLE PROGRESS
- Keep progress concise.
- You may emit a short PLAN or NEXT sentence.
- Every tool call should include a brief reason when useful.
- Do NOT reveal raw hidden chain-of-thought. Provide concise conclusions and action
  rationales instead.

PATHS / SAFETY
- Use project-relative paths only.
- Never access files outside the project root.
- Never bypass approval prompts.
- Never modify unrelated files.
- Never run destructive system commands.
- If multiple files share a basename, use the explicit path from tool results or ask.
- If an edit is blocked because a file changed since it was read, re-read it first.

EFFICIENCY
- This machine has limited RAM and uses a small local model.
- Keep context and tool output focused.
- Do not repeatedly re-read unchanged files.
- Use partial line reads where possible.
- Use the repository map to understand project structure cheaply.
"""


# =============================================================================
# Ollama API / diagnostics
# =============================================================================

def ollama_request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    data = None
    headers: Dict[str, str] = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def installed_models() -> List[str]:
    try:
        data = ollama_request_json(TAGS_URL)
        names = []
        for item in data.get("models", []) or []:
            name = item.get("name") or item.get("model")
            if name:
                names.append(str(name))
        return names
    except Exception:
        return []


def model_capabilities(model: str) -> Tuple[Optional[bool], List[str]]:
    try:
        data = ollama_request_json(
            SHOW_URL,
            method="POST",
            payload={"model": model},
            timeout=20,
        )
        if "capabilities" not in data:
            return None, []
        caps = data.get("capabilities", []) or []
        caps = [str(x) for x in caps]
        return ("tools" in caps), caps
    except Exception:
        return None, []


def git_available() -> bool:
    try:
        r = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False


def print_banner() -> None:
    width = terminal_width()
    title = " HYPER-CUBE LOCAL CODING AGENT V3 "
    inner = max(0, width - 2)
    left = max(0, (inner - len(title)) // 2)
    right = max(0, inner - len(title) - left)

    print()
    print(color("╭" + "─" * inner + "╮", C.CYAN))
    print(
        color("│", C.CYAN)
        + " " * left
        + color(title, C.BOLD, C.BRIGHT_CYAN)
        + " " * right
        + color("│", C.CYAN)
    )
    print(color("╰" + "─" * inner + "╯", C.CYAN))

    status_line("project", str(PROJECT_ROOT), C.WHITE)
    status_line("model", CURRENT_MODEL, C.BRIGHT_CYAN)
    status_line("context", f"{CONTEXT_SIZE:,} tokens", C.WHITE)
    status_line("approval", APPROVAL_MODE, C.BRIGHT_YELLOW)

    branch = get_git_branch()
    if branch:
        status_line("git branch", branch, C.WHITE)

    print()


def run_startup_diagnostics(session_resumed: bool) -> None:
    ui_header("STARTUP DIAGNOSTICS", C.BRIGHT_CYAN)

    # Ollama
    models = installed_models()
    ollama_ok = bool(models)
    if ollama_ok:
        ui_success(f"Ollama connected  ·  {len(models)} model(s) installed")
    else:
        ui_error("Ollama unavailable or no installed models were returned")

    # Model
    if CURRENT_MODEL in models:
        ui_success(f"Model found  ·  {CURRENT_MODEL}")
    else:
        ui_warn(f"Configured model not found in model list  ·  {CURRENT_MODEL}")

    # Tools
    supports_tools, caps = model_capabilities(CURRENT_MODEL) if CURRENT_MODEL in models else (None, [])
    if supports_tools is True:
        ui_success("Tool calling supported")
    elif supports_tools is False:
        ui_error("Model reports no tool-calling capability")
    else:
        ui_warn("Could not verify model tool capability")

    # PowerShell
    if POWERSHELL_EXE:
        ui_success(f"PowerShell  ·  {POWERSHELL_EXE}")
    else:
        ui_error("PowerShell was not found")

    # Git
    if git_available():
        ui_success("Git available")
    else:
        ui_warn("Git unavailable; Git helpers will not work")

    # Persistent state
    if session_resumed:
        ui_success("Previous agent session resumed")
    else:
        ui_success("New agent session")

    ui_success(f"Context budget  ·  {CONTEXT_SIZE:,} tokens")

    print()


# =============================================================================
# Streaming Ollama chat
# =============================================================================

def stream_ollama_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload = {
        "model": CURRENT_MODEL,
        "messages": messages,
        "tools": TOOLS,
        "stream": True,
        "options": {
            "num_ctx": CONTEXT_SIZE,
            "temperature": TEMPERATURE,
        },
    }

    req = urllib.request.Request(
        CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    spinner = Spinner("Model working")
    spinner.start()

    got_visible_text = False
    saw_thinking = False
    thinking_chars = 0

    content_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    seen_calls: set[str] = set()
    final_meta: Dict[str, Any] = {}

    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue

                chunk = json.loads(raw_line.decode("utf-8"))
                message = chunk.get("message", {}) or {}

                thinking_piece = message.get("thinking", "") or ""
                if thinking_piece:
                    saw_thinking = True
                    thinking_chars += len(thinking_piece)
                    if not got_visible_text:
                        spinner.set_label("Model reasoning")

                piece = message.get("content", "") or ""
                if piece:
                    if not got_visible_text:
                        spinner.stop()
                        if saw_thinking:
                            print(
                                color("  ◇ reasoning complete", C.BRIGHT_BLACK)
                                + color(f"  ·  {thinking_chars:,} hidden chars", C.DIM)
                            )
                        print()
                        sys.stdout.write(color("Agent  ❯ ", C.BOLD, C.BRIGHT_CYAN))
                        sys.stdout.flush()
                        got_visible_text = True

                    sys.stdout.write(piece)
                    sys.stdout.flush()
                    content_parts.append(piece)

                calls = message.get("tool_calls") or []
                for call in calls:
                    if call.get("id"):
                        key = str(call.get("id"))
                    else:
                        key = json.dumps(call, sort_keys=True, ensure_ascii=False)

                    if key not in seen_calls:
                        seen_calls.add(key)
                        tool_calls.append(call)

                if chunk.get("done"):
                    final_meta = chunk

    except KeyboardInterrupt:
        spinner.stop()
        raise OperationCancelled("Model generation cancelled.")
    except urllib.error.URLError as e:
        spinner.stop()
        raise AgentError(
            "Could not connect to Ollama at 127.0.0.1:11434. "
            "Make sure Ollama is running."
        ) from e
    finally:
        spinner.stop()

    if got_visible_text:
        print("\n")
    elif saw_thinking:
        print(
            color("  ◇ reasoning complete", C.BRIGHT_BLACK)
            + color(f"  ·  {thinking_chars:,} hidden chars", C.DIM)
        )

    return {
        "message": {
            "role": "assistant",
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
        },
        "_meta": final_meta,
    }


# =============================================================================
# Tool-call rendering / execution
# =============================================================================

def parse_tool_args(call: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    fn = call.get("function", {}) or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments", {}) or {}

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"_invalid_raw_arguments": args}

    if not isinstance(args, dict):
        args = {"_invalid_raw_arguments": str(args)}

    return name, args


def tool_category(name: str) -> Tuple[str, str]:
    if name in {"project_info", "repo_map", "list_files", "find_files", "search_text", "read_file"}:
        return "Exploring", C.BRIGHT_CYAN
    if name in {"write_file", "edit_file", "replace_lines", "insert_text", "make_directory", "delete_file"}:
        return "Editing", C.BRIGHT_MAGENTA
    if name == "run_command":
        return "Testing", C.BRIGHT_YELLOW
    if name in {"git_status", "git_diff"}:
        return "Git", C.BRIGHT_BLUE
    if name in {"set_task_plan", "update_task"}:
        return "Planning", C.BRIGHT_CYAN
    return "Tool", C.BRIGHT_CYAN


def display_tool_call(index: int, name: str, args: Dict[str, Any]) -> None:
    category, style = tool_category(name)
    ui_activity(category, f"{index:02d} · {name}", style)

    reason = args.get("reason")
    if reason:
        status_line("reason", short_text(reason, 260), C.BRIGHT_BLACK)

    hidden = {"content", "old_text", "new_text", "text", "reason", "tasks", "note"}
    display_args = {k: v for k, v in args.items() if k not in hidden}

    if name == "write_file":
        display_args["content"] = f"<{len(str(args.get('content', ''))):,} chars>"
    elif name == "edit_file":
        display_args["old_text"] = f"<{len(str(args.get('old_text', ''))):,} chars>"
        display_args["new_text"] = f"<{len(str(args.get('new_text', ''))):,} chars>"
    elif name in {"replace_lines", "insert_text"}:
        display_args["new text"] = f"<{len(str(args.get('new_text', args.get('text', '')))):,} chars>"

    for key, value in display_args.items():
        status_line(key[:11], short_text(value, 230), C.WHITE)


def display_tool_result(name: str, result: str, elapsed: float) -> None:
    failed = result.startswith("ERROR:")
    style = C.BRIGHT_RED if failed else C.BRIGHT_GREEN
    word = "FAILED" if failed else "DONE"

    print(
        color(f"  {word:<7}", C.BOLD, style)
        + color(f" {name}", C.WHITE)
        + color(f"  ·  {human_duration(elapsed)}", C.BRIGHT_BLACK)
    )

    if VERBOSE_TOOLS and name not in {
        "run_command", "write_file", "edit_file",
        "replace_lines", "insert_text",
        "set_task_plan", "update_task",
    }:
        print_rule("·", C.BRIGHT_BLACK)
        preview = result[:5000]
        print(preview)
        if len(result) > 5000:
            print(color("... tool result truncated ...", C.BRIGHT_BLACK))
        print_rule("·", C.BRIGHT_BLACK)


def execute_tool_call(call: Dict[str, Any]) -> Tuple[str, str]:
    global TURN_TOOL_COUNT

    name, args = parse_tool_args(call)
    TURN_TOOL_COUNT += 1
    display_tool_call(TURN_TOOL_COUNT, name, args)

    if "_invalid_raw_arguments" in args:
        result = f"ERROR: Invalid tool arguments: {args['_invalid_raw_arguments']}"
        display_tool_result(name, result, 0.0)
        return name, result

    func = FUNCTIONS.get(name)
    if not func:
        result = f"ERROR: Unknown tool: {name}"
        display_tool_result(name, result, 0.0)
        return name, result

    start = time.time()

    try:
        result = func(**args)
    except KeyboardInterrupt:
        raise OperationCancelled(f"{name} cancelled.")
    except TypeError as e:
        result = f"ERROR: Bad arguments for {name}: {e}"
    except Exception as e:
        result = f"ERROR: Tool failed: {e}"

    elapsed = time.time() - start
    display_tool_result(name, result, elapsed)
    return name, result


# =============================================================================
# Context management: prune whole turns only
# =============================================================================

def estimate_tokens_from_messages(messages: List[Dict[str, Any]]) -> int:
    try:
        text = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(messages)
    return max(1, len(text) // 4)


def context_bar(messages: List[Dict[str, Any]]) -> str:
    used = estimate_tokens_from_messages(messages)
    pct = min(100.0, used / max(1, CONTEXT_SIZE) * 100.0)
    width = 18
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} ~{used:,}/{CONTEXT_SIZE:,} ({pct:.0f}%)"


def split_turn_groups(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """
    Split messages into:
    - leading system messages
    - complete user-turn groups

    A group starts with role=user and includes following assistant/tool messages
    until the next user message. This ensures pruning never separates an
    assistant tool call from its tool result.
    """
    system_msgs: List[Dict[str, Any]] = []
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")

        if role == "system" and not groups and not current:
            system_msgs.append(msg)
            continue

        if role == "user":
            if current:
                groups.append(current)
            current = [msg]
        else:
            if not current:
                # Preserve unusual non-user messages as a standalone group.
                current = [msg]
            else:
                current.append(msg)

    if current:
        groups.append(current)

    return system_msgs, groups


def prune_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    target = int(CONTEXT_SIZE * HISTORY_TARGET_RATIO)
    if estimate_tokens_from_messages(messages) <= target:
        return messages

    systems, groups = split_turn_groups(messages)
    kept: List[List[Dict[str, Any]]] = []

    # Keep newest complete turn groups.
    for group in reversed(groups):
        candidate_groups = [group] + kept
        candidate = systems + [
            {
                "role": "system",
                "content": (
                    "Older complete conversation turns were pruned to fit the local "
                    "context budget. Reinspect files if earlier details are needed."
                ),
            }
        ]
        for g in candidate_groups:
            candidate.extend(g)

        if estimate_tokens_from_messages(candidate) > target and kept:
            break

        kept = candidate_groups

    result = list(systems)
    result.append({
        "role": "system",
        "content": (
            "Older complete conversation turns were pruned to fit the local "
            "context budget. Tool-call/result pairs were preserved."
        ),
    })
    for group in kept:
        result.extend(group)

    return result


# =============================================================================
# Slash commands
# =============================================================================

HELP_TEXT = """
/help                    Show commands
/status                  Show model/project/context/approval/task status
/tree [path]             Recursive project tree
/files [path]            One directory
/map [query]             Search cached repository map
/map-refresh             Force repository-map refresh
/models                  List installed Ollama models
/model <name>            Switch model
/ctx <2048-32768>        Change context size
/temp <0.0-2.0>          Change temperature
/mode safe               Ask before edits and commands
/mode edit               Auto-approve edits; ask before commands
/mode full               Auto-approve edits and commands; deletes still ask
/verbose                 Toggle tool-result previews
/git                     Git status
/diff [path]             Git diff
/tasks                   Show task checklist
/undo                    Undo last agent file change
/retry                   Retry the previous user request from scratch
/continue                Continue the current task
/stop                    Stop/abandon the current task
/clear                   Clear chat history, keep config
/new                     New session: clear chat, tasks, snapshots, undo
/history                 Show context usage
/resume on|off           Toggle automatic session resume
/exit                    Save and exit

Keyboard:
↑ / ↓                    Input history on Windows
← / → Home / End         Edit command line
Ctrl+A / Ctrl+E          Start/end of line
Ctrl+U                   Clear input line
Ctrl+C                    Cancel current generation/command
Ctrl+C again quickly      Abandon the current task

Examples:
- Fix the enemy movement bug, then run the smallest useful test.
- Inspect the project and explain how the upgrade system works.
- Refactor src/playerStats.py without changing behavior.
""".strip()


def slash_command(
    text: str,
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """
    Returns (action, messages, injected_user_text)
    action: handled | exit | process
    """
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE
    global APPROVAL_MODE, VERBOSE_TOOLS, RESUME_ENABLED
    global TASKS, READ_SNAPSHOTS, UNDO_STACK

    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in {"/exit", "/quit"}:
        return "exit", messages, None

    if cmd == "/help":
        print()
        print(color(HELP_TEXT, C.WHITE))
        print()
        return "handled", messages, None

    if cmd == "/status":
        print()
        status_line("project", str(PROJECT_ROOT), C.WHITE)
        status_line("model", CURRENT_MODEL, C.BRIGHT_CYAN)
        status_line("context", f"{CONTEXT_SIZE:,}", C.WHITE)
        status_line("temp", str(TEMPERATURE), C.WHITE)
        status_line("approval", APPROVAL_MODE, C.BRIGHT_YELLOW)
        status_line("verbose", str(VERBOSE_TOOLS), C.WHITE)
        status_line("history", context_bar(messages), C.BRIGHT_CYAN)
        status_line("snapshots", str(len(READ_SNAPSHOTS)), C.WHITE)
        status_line("undo", str(len(UNDO_STACK)), C.WHITE)
        print()
        render_tasks()
        return "handled", messages, None

    if cmd in {"/tree", "/files"}:
        path = arg or "."
        print()
        print(tool_list_files(path=path, recursive=(cmd == "/tree"), max_depth=4))
        print()
        return "handled", messages, None

    if cmd == "/map":
        print()
        print(tool_repo_map(query=arg, refresh=False, max_results=100))
        print()
        return "handled", messages, None

    if cmd == "/map-refresh":
        print()
        print(tool_repo_map(query="", refresh=True, max_results=100))
        print()
        return "handled", messages, None

    if cmd == "/models":
        print()
        models = installed_models()
        if not models:
            ui_error("No models found, or Ollama is unavailable.")
        else:
            for model in models:
                marker = "●" if model == CURRENT_MODEL else "○"
                style = C.BRIGHT_CYAN if model == CURRENT_MODEL else C.WHITE
                print(color(f"  {marker} {model}", style))
        print()
        return "handled", messages, None

    if cmd == "/model":
        if not arg:
            print(f"Current model: {CURRENT_MODEL}")
        else:
            CURRENT_MODEL = arg
            save_config()
            ui_success(f"Model switched to {CURRENT_MODEL}")
        return "handled", messages, None

    if cmd == "/ctx":
        try:
            CONTEXT_SIZE = max(2048, min(int(arg), 32768))
            save_config()
            ui_success(f"Context set to {CONTEXT_SIZE:,} tokens")
        except Exception:
            ui_error("Usage: /ctx 8192")
        return "handled", messages, None

    if cmd == "/temp":
        try:
            TEMPERATURE = max(0.0, min(float(arg), 2.0))
            save_config()
            ui_success(f"Temperature set to {TEMPERATURE}")
        except Exception:
            ui_error("Usage: /temp 0.2")
        return "handled", messages, None

    if cmd == "/mode":
        mode = arg.lower()
        if mode not in {"safe", "edit", "full"}:
            ui_error("Usage: /mode safe|edit|full")
        else:
            APPROVAL_MODE = mode
            save_config()
            if mode == "full":
                ui_warn("Full mode: edits and commands auto-approve. Deletes still require confirmation.")
            else:
                ui_success(f"Approval mode set to {mode}")
        return "handled", messages, None

    if cmd == "/verbose":
        VERBOSE_TOOLS = not VERBOSE_TOOLS
        save_config()
        ui_success(f"Verbose tool output: {VERBOSE_TOOLS}")
        return "handled", messages, None

    if cmd == "/git":
        print()
        print(tool_git_status())
        print()
        return "handled", messages, None

    if cmd == "/diff":
        print()
        print(tool_git_diff(path=arg or "."))
        print()
        return "handled", messages, None

    if cmd == "/tasks":
        render_tasks()
        if not TASKS:
            print(color("No active task plan.\n", C.BRIGHT_BLACK))
        return "handled", messages, None

    if cmd == "/undo":
        print()
        ui_success(undo_last_change())
        print()
        save_session(messages)
        return "handled", messages, None

    if cmd == "/retry":
        # Find the last user turn, drop it and everything after it, then reprocess text.
        last_index = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_index = i
                break

        if last_index is None:
            ui_warn("Nothing to retry.")
            return "handled", messages, None

        retry_text = str(messages[last_index].get("content", "")).strip()
        if not retry_text:
            ui_warn("Last user message is empty.")
            return "handled", messages, None

        messages = messages[:last_index]
        ui_success("Retrying previous request from a clean turn.")
        return "process", messages, retry_text

    if cmd == "/continue":
        return "process", messages, "Continue the current task from where you left off. Reinspect anything necessary."

    if cmd == "/stop":
        abandon_current_task()
        messages.append({
            "role": "system",
            "content": "The user stopped the previous task. Do not continue it unless asked.",
        })
        save_session(messages)
        ui_warn("Current task stopped.")
        return "handled", messages, None

    if cmd == "/clear":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_session(messages)
        ui_success("Conversation history cleared.")
        return "handled", messages, None

    if cmd == "/new":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        TASKS = []
        READ_SNAPSHOTS = {}
        UNDO_STACK = []
        save_session(messages)
        ui_success("Started a new agent session.")
        return "handled", messages, None

    if cmd == "/history":
        print()
        print(color(context_bar(messages), C.BRIGHT_CYAN))
        print(color(f"{len(messages)} messages in active history", C.BRIGHT_BLACK))
        print()
        return "handled", messages, None

    if cmd == "/resume":
        val = arg.lower()
        if val not in {"on", "off"}:
            ui_error("Usage: /resume on|off")
        else:
            RESUME_ENABLED = val == "on"
            save_config()
            ui_success(f"Automatic session resume: {RESUME_ENABLED}")
        return "handled", messages, None

    ui_error(f"Unknown command: {cmd}. Try /help.")
    return "handled", messages, None


# =============================================================================
# Interrupt behavior
# =============================================================================

def register_interrupt() -> bool:
    """
    Returns True when this is the second Ctrl+C within the double-tap window.
    """
    global LAST_INTERRUPT_TIME
    now = time.time()
    double = (now - LAST_INTERRUPT_TIME) <= CANCEL_DOUBLE_TAP_SECONDS
    LAST_INTERRUPT_TIME = now
    return double


# =============================================================================
# Turn footer / agent loop
# =============================================================================

def print_turn_footer(
    messages: List[Dict[str, Any]],
    elapsed: float,
    meta: Dict[str, Any],
) -> None:
    print_rule("─", C.BRIGHT_BLACK)

    parts = [
        f"{TURN_TOOL_COUNT} tool call{'s' if TURN_TOOL_COUNT != 1 else ''}",
        human_duration(elapsed),
    ]

    eval_count = meta.get("eval_count")
    eval_duration = meta.get("eval_duration")
    if eval_count and eval_duration:
        try:
            seconds = eval_duration / 1_000_000_000
            if seconds > 0:
                parts.append(f"{eval_count / seconds:.1f} tok/s")
        except Exception:
            pass

    parts.append(context_bar(messages))
    print(color("  " + "  ·  ".join(parts), C.BRIGHT_BLACK))
    print()


def build_tool_message(call: Dict[str, Any], name: str, result: str) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "role": "tool",
        "content": result,
        "tool_name": name,
    }
    if call.get("id"):
        msg["tool_call_id"] = call["id"]
    return msg


def process_user_turn(
    user_text: str,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    global TURN_TOOL_COUNT, LAST_USER_TEXT

    TURN_TOOL_COUNT = 0
    LAST_USER_TEXT = user_text
    turn_start = time.time()

    messages.append({"role": "user", "content": user_text})
    messages = prune_history(messages)
    save_session(messages)

    final_meta: Dict[str, Any] = {}

    for _step in range(MAX_TOOL_STEPS):
        try:
            response = stream_ollama_chat(messages)
        except OperationCancelled:
            double = register_interrupt()
            if double:
                abandon_current_task()
                ui_warn("Task abandoned.")
                messages.append({
                    "role": "system",
                    "content": "The user abandoned the previous task.",
                })
            else:
                ui_warn(
                    "Current generation cancelled. Press Ctrl+C again within "
                    f"{CANCEL_DOUBLE_TAP_SECONDS:.1f}s to abandon the whole task."
                )
            save_session(messages)
            return messages
        except Exception as e:
            print()
            ui_error(str(e))
            print()
            save_session(messages)
            return messages

        message = response.get("message", {}) or {}
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls") or []
        final_meta = response.get("_meta", {}) or {}

        assistant_message: Dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        messages.append(assistant_message)

        if not tool_calls:
            elapsed = time.time() - turn_start
            messages = prune_history(messages)
            save_session(messages)
            print_turn_footer(messages, elapsed, final_meta)
            return messages

        for call in tool_calls:
            try:
                name, result = execute_tool_call(call)
            except OperationCancelled:
                double = register_interrupt()
                if double:
                    abandon_current_task()
                    ui_warn("Task abandoned.")
                    messages.append({
                        "role": "system",
                        "content": "The user abandoned the previous task.",
                    })
                else:
                    ui_warn(
                        "Current operation cancelled. Press Ctrl+C again quickly "
                        "to abandon the whole task."
                    )
                save_session(messages)
                return messages

            messages.append(build_tool_message(call, name, result))
            save_session(messages)

        messages = prune_history(messages)

    ui_warn(f"Stopped after {MAX_TOOL_STEPS} tool steps to prevent an infinite loop.")
    save_session(messages)
    return messages


def run_agent() -> None:
    global LAST_INTERRUPT_TIME

    messages, resumed = load_session(SYSTEM_PROMPT)

    print_banner()
    run_startup_diagnostics(resumed)

    if TASKS:
        render_tasks()

    print(
        color("Type ", C.BRIGHT_BLACK)
        + color("/help", C.BRIGHT_CYAN)
        + color(" for commands. ", C.BRIGHT_BLACK)
        + color("Ctrl+C", C.BRIGHT_CYAN)
        + color(" cancels the current operation.", C.BRIGHT_BLACK)
    )
    print()

    while True:
        prompt = color("You", C.BOLD, C.BRIGHT_GREEN) + color("  ❯ ", C.BRIGHT_BLACK)

        try:
            user_text = read_user_input(prompt).strip()
        except KeyboardInterrupt:
            if register_interrupt():
                abandon_current_task()
                messages.append({
                    "role": "system",
                    "content": "The user abandoned the current task.",
                })
                save_session(messages)
                ui_warn("Current task abandoned.")
            else:
                ui_warn(
                    "Input cleared. Press Ctrl+C again within "
                    f"{CANCEL_DOUBLE_TAP_SECONDS:.1f}s to abandon the current task."
                )
            continue
        except EOFError:
            print()
            save_session(messages)
            save_config()
            return

        if not user_text:
            continue

        remember_input(user_text)

        if user_text.startswith("/"):
            action, messages, injected = slash_command(user_text, messages)

            if action == "exit":
                save_session(messages)
                save_config()
                print(color("\nSession saved. Exiting.", C.BRIGHT_BLACK))
                return

            if action == "handled":
                save_session(messages)
                continue

            if action == "process" and injected:
                user_text = injected
            else:
                continue

        messages = process_user_turn(user_text, messages)


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hyper-Cube Local Coding Agent V3 for Ollama."
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Ollama model override (default config: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Project directory (default: current directory)",
    )
    parser.add_argument(
        "--ctx",
        type=int,
        default=None,
        help=f"Context override (default config: {DEFAULT_CTX})",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help=f"Temperature override (default config: {DEFAULT_TEMP})",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume a previous .agent/session.json for this launch.",
    )
    args = parser.parse_args()

    global PROJECT_ROOT, AGENT_DIR, CONFIG_PATH, SESSION_PATH, REPO_MAP_PATH
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE, RESUME_ENABLED, POWERSHELL_EXE

    PROJECT_ROOT = Path(args.project).resolve()
    if not PROJECT_ROOT.exists() or not PROJECT_ROOT.is_dir():
        print(f"ERROR: Project directory does not exist: {PROJECT_ROOT}")
        sys.exit(1)

    AGENT_DIR = PROJECT_ROOT / ".agent"
    CONFIG_PATH = AGENT_DIR / "config.json"
    SESSION_PATH = AGENT_DIR / "session.json"
    REPO_MAP_PATH = AGENT_DIR / "repo_map.json"

    # Start with defaults, then persistent config, then CLI overrides.
    CURRENT_MODEL = DEFAULT_MODEL
    CONTEXT_SIZE = DEFAULT_CTX
    TEMPERATURE = DEFAULT_TEMP

    load_config()

    if args.model:
        CURRENT_MODEL = args.model
    if args.ctx is not None:
        CONTEXT_SIZE = max(2048, min(int(args.ctx), 32768))
    if args.temperature is not None:
        TEMPERATURE = max(0.0, min(float(args.temperature), 2.0))
    if args.no_resume:
        RESUME_ENABLED = False

    POWERSHELL_EXE = detect_powershell()

    # Persistent state folder is a deliberate V3 feature.
    try:
        ensure_agent_dir()
    except Exception as e:
        print(f"ERROR: Could not create {AGENT_DIR}: {e}")
        sys.exit(1)

    save_config()

    try:
        run_agent()
    except KeyboardInterrupt:
        print()
        save_config()
        print(color("Interrupted. Exiting.", C.BRIGHT_BLACK))
    except Exception as e:
        print()
        ui_error(f"Fatal error: {e}")
        save_config()
        raise


if __name__ == "__main__":
    main()



