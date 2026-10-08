#!/usr/bin/env python3
"""
Hyper-Cube Local Coding Agent V5
==============================


A polished, dependency-free local coding agent for Ollama.


Designed for:
- Windows + PowerShell
- Python 3.9+
- Ollama running locally
- Small local tool-capable models such as qwen3.5:4b
- Low-memory / locked-down machines


V4 foundation inherited from V3
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


V4 context engine inherited by V5
-----------------
- Automatic hierarchical compaction with durable checkpoints.
- Tool-output pruning and same-turn compaction for long agent trajectories.
- One-shot context-overflow recovery and manual /compact.
- Adaptive context sizing based on live RAM/CPU pressure and model metadata.
- Context budgeting includes system prompts, tool schemas, summaries, and output reserve.
- Persistent compacted memory plus full archived pre-compaction history.


V5 speed engine
---------------
- Managed Ollama startup with Q8_0 KV cache and Flash Attention requested.
- Stable prompt prefixes and phase-specific tool schemas.
- Parallel independent read tools with sequential editing and commands.
- Lossless result storage, focused symbol reads, and paged retrieval.
- Mechanical and deterministic compaction before semantic compaction.
- Persistent runtime ledger and automatic task progress.
- The smallest sufficient context window and a warm model while open.
- Latency, prompt-cache, and tool timing profiles plus /benchmark.


No third-party Python packages are required.


Typical usage:
    python pygent_v5.py


Options:
    python pygent_v5.py --model qwen3.5:4b
    python pygent_v5.py --project C:\\path\\to\\project
    python pygent_v5.py --ctx 8192
    python pygent_v5.py --no-resume
    python pygent_v5.py --ollama-exe C:\\path\\to\\ollama.exe
    python pygent_v5.py --ollama-url http://127.0.0.1:11434


Important:
- Put this file in the project root.
- Internal persistent state is stored in .agent/.
- V5 starts a private loopback Ollama server with Q8_0 KV cache and Flash
  Attention requested. It shares the existing model files; no model is changed.
  The server and its runners are stopped when Pygent exits. An existing tray
  server is left running. Unload unused models there to avoid duplicate RAM use.
- --ollama-url opts into an existing server. Its actual cache configuration is
  unknown to Pygent; configure Q8_0 + Flash Attention and restart it yourself.
- /inference distinguishes launch settings from runtime log evidence. An
  unsupported backend can reject or fall back from Q8; this is reported rather
  than treating the Python client's environment as proof. Memory estimates use
  F16 until Q8 allocation is observed in the managed server's runner log.
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
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple




# =============================================================================
# Configuration
# =============================================================================


VERSION = "5.0"


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




def status_line(label: str, value: Any, style: str = C.WHITE) -> None:
    print(
        color(f"  {label:<11}", C.BRIGHT_BLACK)
        + color("│ ", C.BRIGHT_BLACK)
        + color(str(value), style)
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
            try:
                _validate_inside_project(p)
            except AgentError:
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
            try:
                _validate_inside_project(p)
            except AgentError:
                continue
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
            result = compact_result_for_model("read_file", result, {"path": path, "start_line": start_line, "end_line": end_line})


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
    """Stop this owned command and its descendants on timeout/cancellation."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass



def run_powershell_live(command: str, timeout: int) -> Tuple[int, str, float, bool]:
    """Stream a bounded UI preview while spooling all command output to disk."""
    if not POWERSHELL_EXE:
        raise AgentError("PowerShell could not be found.")
    ensure_agent_dir()
    rid = _next_result_id()
    output_path, _meta_path = _result_paths(rid)
    args = [POWERSHELL_EXE, "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", command]
    kwargs: Dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    }
    proc = subprocess.Popen(
        args, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1, **kwargs,
    )
    q: queue.Queue = queue.Queue(maxsize=64)
    finished = threading.Event()
    counts = {"chars": 0, "newlines": 0, "last_newline": True}
    reader_errors: List[str] = []

    def reader() -> None:
        try:
            assert proc.stdout is not None
            with output_path.open("w", encoding="utf-8", newline="") as sink:
                while True:
                    # Bound even a gigantic single output line in RAM.
                    piece = proc.stdout.readline(8192)
                    if not piece:
                        break
                    sink.write(piece)
                    counts["chars"] += len(piece)
                    counts["newlines"] += piece.count("\n")
                    counts["last_newline"] = piece.endswith("\n")
                    try:
                        q.put_nowait(piece)
                    except queue.Full:
                        # Display may lag; the complete disk capture never drops
                        # output and never grows an unbounded in-memory queue.
                        pass
        except Exception as e:
            reader_errors.append(str(e))
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            finished.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    started = time.monotonic()
    captured: List[str] = []
    captured_chars = 0
    display_lines = 0
    output_started = False
    cancelled = False
    timed_out = False
    spinner = Spinner("Command running")
    spinner.start()
    try:
        while not (finished.is_set() and q.empty() and proc.poll() is not None):
            if time.monotonic() - started > timeout:
                timed_out = True
                _terminate_process(proc)
                ui_warn(f"Command timed out after {timeout}s.")
                break
            try:
                piece = q.get(timeout=0.08)
            except queue.Empty:
                continue
            if not output_started:
                spinner.stop()
                print_rule("·", C.BRIGHT_BLACK)
                output_started = True
            if display_lines < MAX_COMMAND_DISPLAY_LINES:
                sys.stdout.write(color(f"│ +{time.monotonic()-started:5.1f}s  ", C.BRIGHT_BLACK) + piece)
                sys.stdout.flush()
                display_lines += max(1, piece.count("\n"))
            if captured_chars < MAX_COMMAND_CAPTURE_CHARS - 256:
                preview = piece[:MAX_COMMAND_CAPTURE_CHARS - 256 - captured_chars]
                captured.append(preview)
                captured_chars += len(preview)
        proc.wait(timeout=2)
    except KeyboardInterrupt:
        cancelled = True
        _terminate_process(proc)
        ui_warn("Command cancelled.")
    finally:
        spinner.stop()
        if proc.poll() is None:
            _terminate_process(proc)
        thread.join(timeout=3)
        if output_started:
            print_rule("·", C.BRIGHT_BLACK)
    if not finished.is_set():
        raise AgentError(f"Command output capture did not finish. Partial output: {output_path}")
    if reader_errors:
        raise AgentError("Command output capture failed: " + reader_errors[0])
    code = 124 if timed_out else 130 if cancelled else int(proc.returncode or 0)
    elapsed = time.monotonic() - started
    lines = counts["newlines"] + (1 if counts["chars"] and not counts["last_newline"] else 0)
    register_stored_result(
        rid, "run_command", {"command": command, "exit_code": code, "cancelled": cancelled},
        counts["chars"], lines, "command_output",
    )
    output = f"Full captured output: {rid} ({counts['chars']:,} chars). Use read_result to page/search it.\n"
    output += "".join(captured)
    return code, output, elapsed, cancelled



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
        result = result[:MAX_COMMAND_CAPTURE_CHARS] + "\n... inline preview truncated; full output stored ..."


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
        if result.returncode != 0:
            return "ERROR: " + (output.strip() or f"git exited with {result.returncode}")
        return output.strip() or "(no output)"
    except FileNotFoundError:
        return "ERROR: git is not installed or not on PATH."
    except Exception as e:
        return f"ERROR: {e}"




def get_git_branch() -> Optional[str]:
    global _GIT_BRANCH_CACHE
    key = str(PROJECT_ROOT)
    cached = globals().get("_GIT_BRANCH_CACHE")
    if cached and cached[0] == key and time.monotonic() - cached[1] < 5.0:
        return cached[2]
    out = run_readonly_git(["branch", "--show-current"])
    branch = None if out.startswith("ERROR:") or out == "(no output)" else out.strip() or None
    _GIT_BRANCH_CACHE = (key, time.monotonic(), branch)
    return branch




def tool_git_status(reason: str = "") -> str:
    return run_readonly_git(["status", "--short", "--branch"])




def tool_git_diff(path: str = ".", reason: str = "") -> str:
    try:
        if path != ".":
            resolve_path(path, allow_missing=True, resolve_basename=False)
    except Exception as e:
        return f"ERROR: {e}"


    result = run_readonly_git(["diff", "--", path])
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


    if url == CHAT_URL and payload and payload.get("model") and payload.get("keep_alive") != 0:
        begin_ollama_model_request(str(payload["model"]))
    req = urllib.request.Request(url, data=data, headers=headers, method=method)


    with ollama_urlopen(req, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
        if isinstance(result, dict) and result.get("error"):
            raise AgentError(str(result["error"]))
        return result




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
    match = re.match(r"exit_code:\s*(-?\d+)", result) if name == "run_command" else None
    failed = (result.startswith("ERROR:") or "denied by user" in result.lower()
              or (match is not None and int(match.group(1)) != 0))
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






# =============================================================================
# V4 context engine: auto-compact + adaptive context
# =============================================================================


# V4 deliberately keeps the durable transcript separate from the active model
# context. Active context can be compacted aggressively without losing history.
VERSION = "4.0"
PS_URL = OLLAMA_BASE + "/api/ps"


AUTO_COMPACT_ENABLED = True
CONTEXT_MODE = "auto"                 # auto | fixed
AUTO_CONTEXT_ENABLED = True
CONTEXT_MIN = 4096
CONTEXT_USER_MAX = 32768
CONTEXT_STEPS = [4096, 6144, 8192, 10240, 12288, 16384, 24576, 32768]
CONTEXT_CHANGE_COOLDOWN = 35.0


# The compactor starts before the hard limit. This is intentionally conservative
# because token counting is estimated and Ollama/model chat templates add tokens.
COMPACT_BUFFER_RATIO = 0.20
COMPACT_BUFFER_MIN = 1200
COMPACT_BUFFER_MAX = 6000
COMPACT_KEEP_RATIO = 0.24
COMPACT_KEEP_MIN = 1200
COMPACT_KEEP_MAX = 6000
COMPACT_SUMMARY_RATIO = 0.14
COMPACT_SUMMARY_MIN = 700
COMPACT_SUMMARY_MAX = 2200
OUTPUT_RESERVE_RATIO = 0.14
OUTPUT_RESERVE_MIN = 900
OUTPUT_RESERVE_MAX = 3000


TOOL_RESULT_ACTIVE_SOFT_LIMIT = 7000
TOOL_RESULT_ARCHIVE_EXCERPT = 2200
REQUEST_ESTIMATE_SAFETY = 1.12


COMPACTED_MEMORY = ""
COMPACTION_GENERATION = 0
COMPACTION_COUNT = 0
LAST_COMPACTION_AT = 0.0
LAST_CONTEXT_CHANGE_AT = 0.0
LAST_CONTEXT_EVENT = ""
MODEL_HAS_RUN = False


_MODEL_SHOW_CACHE: Dict[str, Any] = {}
_MODEL_SHOW_CACHE_AT = 0.0
_MODEL_SHOW_CACHE_MODEL = ""




class ResourceMonitor:
    """Tiny standard-library resource monitor with a rolling sample window."""


    def __init__(self, interval: float = 2.0):
        self.interval = max(0.5, float(interval))
        self.samples: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._prev_cpu: Optional[Tuple[int, int, int]] = None


    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._sample_once()


        def loop() -> None:
            while self.running:
                time.sleep(self.interval)
                self._sample_once()


        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()


    def stop(self) -> None:
        self.running = False


    def _sample_once(self) -> None:
        mem = system_memory_info()
        cpu = self._cpu_percent()
        sample = {
            "time": time.time(),
            "total": int(mem.get("total", 0)),
            "available": int(mem.get("available", 0)),
            "cpu": cpu,
        }
        with self.lock:
            self.samples.append(sample)
            del self.samples[:-30]


    def _cpu_percent(self) -> Optional[float]:
        try:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes


                class FILETIME(ctypes.Structure):
                    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                                ("dwHighDateTime", wintypes.DWORD)]


                idle = FILETIME()
                kernel = FILETIME()
                user = FILETIME()
                ok = ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
                )
                if not ok:
                    return None


                def ft(x: Any) -> int:
                    return (int(x.dwHighDateTime) << 32) | int(x.dwLowDateTime)


                current = (ft(idle), ft(kernel), ft(user))
                if self._prev_cpu is None:
                    self._prev_cpu = current
                    return None


                p_idle, p_kernel, p_user = self._prev_cpu
                self._prev_cpu = current
                d_idle = current[0] - p_idle
                d_total = (current[1] - p_kernel) + (current[2] - p_user)
                if d_total <= 0:
                    return None
                return max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))


            stat = Path("/proc/stat")
            if stat.exists():
                parts = stat.read_text(encoding="utf-8").splitlines()[0].split()[1:]
                vals = [int(x) for x in parts]
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals)
                current = (idle, total, 0)
                if self._prev_cpu is None:
                    self._prev_cpu = current
                    return None
                p_idle, p_total, _ = self._prev_cpu
                self._prev_cpu = current
                d_total = total - p_total
                if d_total <= 0:
                    return None
                return max(0.0, min(100.0, 100.0 * (1.0 - (idle - p_idle) / d_total)))
        except Exception:
            return None
        return None


    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            samples = list(self.samples)
        if not samples:
            mem = system_memory_info()
            return {"total": mem.get("total", 0), "available": mem.get("available", 0), "cpu": None}


        latest = dict(samples[-1])
        recent = samples[-5:]
        avails = [int(x.get("available", 0)) for x in recent if x.get("available")]
        cpus = [float(x["cpu"]) for x in recent if x.get("cpu") is not None]
        latest["stable_available"] = min(avails) if avails else int(latest.get("available", 0))
        latest["cpu_avg"] = sum(cpus) / len(cpus) if cpus else latest.get("cpu")
        return latest




RESOURCE_MONITOR = ResourceMonitor()




def system_memory_info() -> Dict[str, int]:
    """Return total/available physical RAM without third-party packages."""
    try:
        if os.name == "nt":
            import ctypes


            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]


            s = MEMORYSTATUSEX()
            s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
                return {"total": int(s.ullTotalPhys), "available": int(s.ullAvailPhys)}


        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            values: Dict[str, int] = {}
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                key, rest = line.split(":", 1)
                try:
                    values[key] = int(rest.strip().split()[0]) * 1024
                except Exception:
                    pass
            return {
                "total": values.get("MemTotal", 0),
                "available": values.get("MemAvailable", values.get("MemFree", 0)),
            }


        # Generic POSIX fallback.
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        return {"total": int(page * pages), "available": int(page * avail_pages)}
    except Exception:
        return {"total": 0, "available": 0}




def fmt_bytes(value: int) -> str:
    value = max(0, int(value))
    gib = value / (1024 ** 3)
    if gib >= 0.1:
        return f"{gib:.2f} GB"
    return f"{value / (1024 ** 2):.0f} MB"




def model_show_data(force: bool = False) -> Dict[str, Any]:
    global _MODEL_SHOW_CACHE, _MODEL_SHOW_CACHE_AT, _MODEL_SHOW_CACHE_MODEL
    now = time.time()
    if _MODEL_SHOW_CACHE_MODEL != CURRENT_MODEL:
        _MODEL_SHOW_CACHE = {}
    if not force and _MODEL_SHOW_CACHE and now - _MODEL_SHOW_CACHE_AT < 300:
        return _MODEL_SHOW_CACHE
    try:
        _MODEL_SHOW_CACHE = ollama_request_json(
            SHOW_URL,
            method="POST",
            payload={"model": CURRENT_MODEL},
            timeout=20,
        )
        _MODEL_SHOW_CACHE_AT = now
        _MODEL_SHOW_CACHE_MODEL = CURRENT_MODEL
    except Exception:
        if not _MODEL_SHOW_CACHE:
            _MODEL_SHOW_CACHE = {}
    return _MODEL_SHOW_CACHE




def model_declared_context_limit() -> int:
    data = model_show_data()
    info = data.get("model_info", {}) if isinstance(data, dict) else {}
    candidates: List[int] = []
    if isinstance(info, dict):
        for key, value in info.items():
            if str(key).lower().endswith("context_length"):
                try:
                    candidates.append(int(value))
                except Exception:
                    pass
    return max(candidates) if candidates else CONTEXT_USER_MAX




def estimated_kv_bytes_per_token() -> int:
    """Conservative F16 KV-cache estimate from GGUF metadata when available."""
    data = model_show_data()
    info = data.get("model_info", {}) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        return 128 * 1024


    arch = str(info.get("general.architecture", "")).strip()
    prefixes = [arch] if arch else []
    prefixes += [
        str(k).split(".block_count", 1)[0]
        for k in info
        if str(k).endswith(".block_count")
    ]


    for prefix in dict.fromkeys(x for x in prefixes if x):
        try:
            layers = int(info[f"{prefix}.block_count"])
            embed = int(info[f"{prefix}.embedding_length"])
            heads = int(info[f"{prefix}.attention.head_count"])
            kv_heads = int(info.get(f"{prefix}.attention.head_count_kv", heads))
            if layers > 0 and embed > 0 and heads > 0 and kv_heads > 0:
                head_dim = embed / heads
                # K + V, each conservatively assumed F16 (2 bytes).
                raw = 2.0 * layers * kv_heads * head_dim * 2.0
                return int(raw * 1.15)
        except Exception:
            continue


    return 128 * 1024




def effective_context_ceiling() -> int:
    declared = max(CONTEXT_MIN, model_declared_context_limit())
    user_cap = max(CONTEXT_MIN, CONTEXT_USER_MAX)
    snap = RESOURCE_MONITOR.snapshot()
    total = int(snap.get("total", 0))


    # Hardware-aware cap. It is still only a ceiling; live free RAM decides
    # whether an upward step actually happens.
    hardware_cap = 32768
    if total:
        gib = total / (1024 ** 3)
        if gib <= 9.5:
            hardware_cap = 16384
        elif gib <= 13.5:
            hardware_cap = 24576


    return max(CONTEXT_MIN, min(declared, user_cap, hardware_cap))




def runtime_state_message() -> str:
    task_lines = []
    for i, task in enumerate(TASKS[:12], 1):
        task_lines.append(
            f"{i}. [{task.get('status', 'pending')}] {task.get('title', '')}"
            + (f" — {task.get('note', '')}" if task.get('note') else "")
        )


    read_files = list(READ_SNAPSHOTS.keys())[-16:]
    changed: List[str] = []
    for p, _existed, _old in reversed(UNDO_STACK[-12:]):
        rel = project_relative(p)
        if rel not in changed:
            changed.append(rel)


    state = [
        "<runtime_state>",
        f"project={PROJECT_ROOT}",
        f"git_branch={get_git_branch() or '(none)'}",
        f"context={CONTEXT_SIZE}; context_mode={CONTEXT_MODE}; auto_compact={AUTO_COMPACT_ENABLED}",
        f"compaction_generation={COMPACTION_GENERATION}",
    ]
    if task_lines:
        state.append("tasks:\n" + "\n".join(task_lines))
    if read_files:
        state.append("recently_read=" + ", ".join(read_files))
    if changed:
        state.append("recent_agent_edits=" + ", ".join(changed[:10]))
    state.append("</runtime_state>")
    return "\n".join(state)




def prepare_request_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not messages:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]


    result: List[Dict[str, Any]] = [messages[0]]
    if COMPACTED_MEMORY.strip():
        result.append({
            "role": "system",
            "content": (
                "<compacted_session_memory>\n"
                + COMPACTED_MEMORY.strip()
                + "\n</compacted_session_memory>"
            ),
        })
    result.append({"role": "system", "content": runtime_state_message()})
    result.extend(messages[1:])
    return result




def _rough_tokens(value: Any) -> int:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = str(value)
    return max(1, int((len(raw) / 4.0) * REQUEST_ESTIMATE_SAFETY))




def estimate_request_tokens(messages: List[Dict[str, Any]], include_tools: bool = True) -> int:
    prepared = prepare_request_messages(messages)
    total = _rough_tokens(prepared)
    if include_tools:
        total += _rough_tokens(TOOLS)
    # Chat template / special-token uncertainty.
    return total + 96




def output_reserve_tokens() -> int:
    return max(
        OUTPUT_RESERVE_MIN,
        min(OUTPUT_RESERVE_MAX, int(CONTEXT_SIZE * OUTPUT_RESERVE_RATIO)),
    )




def compact_buffer_tokens() -> int:
    return max(
        COMPACT_BUFFER_MIN,
        min(COMPACT_BUFFER_MAX, int(CONTEXT_SIZE * COMPACT_BUFFER_RATIO)),
    )




def compact_keep_tokens() -> int:
    return max(
        COMPACT_KEEP_MIN,
        min(COMPACT_KEEP_MAX, int(CONTEXT_SIZE * COMPACT_KEEP_RATIO)),
    )




def compact_summary_target_tokens() -> int:
    return max(
        COMPACT_SUMMARY_MIN,
        min(COMPACT_SUMMARY_MAX, int(CONTEXT_SIZE * COMPACT_SUMMARY_RATIO)),
    )




def context_trigger_tokens() -> int:
    reserve = max(compact_buffer_tokens(), output_reserve_tokens() + 256)
    return max(CONTEXT_MIN // 2, CONTEXT_SIZE - reserve)




def context_bar(messages: List[Dict[str, Any]]) -> str:
    used = estimate_request_tokens(messages, include_tools=True)
    pct = min(100.0, used / max(1, CONTEXT_SIZE) * 100.0)
    width = 18
    filled = int(width * pct / 100.0)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} ~{used:,}/{CONTEXT_SIZE:,} ({pct:.0f}%)"




def context_status_lines(messages: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    snap = RESOURCE_MONITOR.snapshot()
    total = int(snap.get("total", 0))
    avail = int(snap.get("stable_available", snap.get("available", 0)))
    cpu = snap.get("cpu_avg")
    ceiling = effective_context_ceiling()
    kv = estimated_kv_bytes_per_token()


    lines = [
        f"mode={CONTEXT_MODE}; auto_context={AUTO_CONTEXT_ENABLED}",
        f"current={CONTEXT_SIZE:,}; ceiling={ceiling:,}; model_declared={model_declared_context_limit():,}",
        f"estimated_KV={kv / 1024:.0f} KB/token",
    ]
    if total:
        lines.append(
            f"RAM available={fmt_bytes(avail)} / {fmt_bytes(total)}"
            + (f"; CPU avg={float(cpu):.0f}%" if cpu is not None else "")
        )
    if messages is not None:
        used = estimate_request_tokens(messages)
        lines.append(
            f"request_estimate={used:,}; auto-compact trigger={context_trigger_tokens():,}; "
            f"output reserve={output_reserve_tokens():,}"
        )
    if LAST_CONTEXT_EVENT:
        lines.append("last_event=" + LAST_CONTEXT_EVENT)
    return lines




def _context_steps() -> List[int]:
    ceiling = effective_context_ceiling()
    vals = [x for x in CONTEXT_STEPS if CONTEXT_MIN <= x <= ceiling]
    if CONTEXT_SIZE not in vals and CONTEXT_MIN <= CONTEXT_SIZE <= ceiling:
        vals.append(CONTEXT_SIZE)
    return sorted(set(vals))




def maybe_auto_tune_context(messages: List[Dict[str, Any]], allow_increase: bool = True) -> bool:
    global CONTEXT_SIZE, LAST_CONTEXT_CHANGE_AT, LAST_CONTEXT_EVENT


    if not AUTO_CONTEXT_ENABLED or CONTEXT_MODE != "auto":
        return False


    now = time.time()
    if now - LAST_CONTEXT_CHANGE_AT < CONTEXT_CHANGE_COOLDOWN:
        return False


    snap = RESOURCE_MONITOR.snapshot()
    total = int(snap.get("total", 0))
    avail = int(snap.get("stable_available", snap.get("available", 0)))
    cpu = snap.get("cpu_avg")
    if total <= 0 or avail <= 0:
        return False


    steps = _context_steps()
    if not steps:
        return False


    used = estimate_request_tokens(messages)
    pressure = used / max(1, CONTEXT_SIZE)
    reserve = max(int(total * 0.16), int(1.15 * 1024 ** 3))
    emergency = max(int(total * 0.09), int(700 * 1024 ** 2))


    # Memory distress: shrink by one safe step. The normal preflight immediately
    # compacts if the active request no longer fits the smaller window.
    if avail < emergency and CONTEXT_SIZE > CONTEXT_MIN:
        lower = [x for x in steps if x < CONTEXT_SIZE]
        if lower:
            new_ctx = lower[-1]
            CONTEXT_SIZE = new_ctx
            LAST_CONTEXT_CHANGE_AT = now
            LAST_CONTEXT_EVENT = (
                f"auto-decreased to {new_ctx:,}: low available RAM ({fmt_bytes(avail)})"
            )
            save_config()
            ui_warn(LAST_CONTEXT_EVENT)
            return True


    if not allow_increase or not MODEL_HAS_RUN or pressure < 0.56:
        return False


    # Avoid making an already CPU-saturated local session even heavier. This is
    # advisory; memory remains the primary criterion.
    if cpu is not None and float(cpu) >= 97.0:
        return False


    higher = [x for x in steps if x > CONTEXT_SIZE]
    if not higher:
        return False


    candidate = higher[0]
    extra_tokens = candidate - CONTEXT_SIZE
    extra_memory = int(extra_tokens * estimated_kv_bytes_per_token())


    if avail - extra_memory < reserve:
        return False


    old = CONTEXT_SIZE
    CONTEXT_SIZE = candidate
    LAST_CONTEXT_CHANGE_AT = now
    LAST_CONTEXT_EVENT = (
        f"auto-increased {old:,} → {candidate:,}; RAM headroom after estimated KV growth "
        f"≈ {fmt_bytes(avail - extra_memory)}"
    )
    save_config()
    ui_success(LAST_CONTEXT_EVENT)
    return True




def _safe_tool_excerpt(text: str, limit: int = TOOL_RESULT_ARCHIVE_EXCERPT) -> str:
    if len(text) <= limit * 2:
        return text
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return (
        text[:limit]
        + f"\n... [middle pruned; sha256={digest}; original_chars={len(text)}] ...\n"
        + text[-limit:]
    )




def _summary_message_repr(msg: Dict[str, Any]) -> str:
    role = str(msg.get("role", "unknown"))
    if role == "tool":
        name = str(msg.get("tool_name", "tool"))
        return f"TOOL RESULT [{name}]:\n{_safe_tool_excerpt(str(msg.get('content', '')))}"


    content = str(msg.get("content", ""))
    calls = msg.get("tool_calls") or []
    call_text = ""
    if calls:
        compact_calls = []
        for c in calls[:8]:
            fn = c.get("function", {}) if isinstance(c, dict) else {}
            args = fn.get("arguments", {}) if isinstance(fn, dict) else {}
            if isinstance(args, dict):
                args = {
                    k: (f"<{len(str(v))} chars>" if k in {"content", "old_text", "new_text", "text"} else v)
                    for k, v in args.items()
                }
            compact_calls.append({"name": fn.get("name"), "arguments": args})
        call_text = "\nTOOL CALLS: " + json.dumps(compact_calls, ensure_ascii=False)


    if len(content) > 6000:
        content = _safe_tool_excerpt(content, 2600)
    return f"{role.upper()}:\n{content}{call_text}"




def _interaction_units(group: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    if not group:
        return None, []
    user = group[0] if group[0].get("role") == "user" else None
    rest = group[1:] if user is not None else group[:]
    units: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []


    for msg in rest:
        if msg.get("role") == "assistant":
            if current:
                units.append(current)
            current = [msg]
        else:
            if not current:
                current = [msg]
            else:
                current.append(msg)
    if current:
        units.append(current)
    return user, units




def _active_tool_prune(msg: Dict[str, Any], newest: bool = False) -> Dict[str, Any]:
    if msg.get("role") != "tool":
        return msg
    content = str(msg.get("content", ""))
    limit = TOOL_RESULT_ACTIVE_SOFT_LIMIT if newest else max(2600, TOOL_RESULT_ACTIVE_SOFT_LIMIT // 2)
    if len(content) <= limit:
        return msg
    copy_msg = dict(msg)
    rid = store_full_result(tool_name=str(msg.get("tool_name", "tool")), raw_result=content, args={}, kind="active_tool_result")
    copy_msg["content"] = f"Exact result archived as {rid}; use read_result.\n" + _safe_tool_excerpt(content, limit // 2)
    return copy_msg




def select_compaction_split(
    messages: List[Dict[str, Any]],
    keep_tokens: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (messages_to_summarize, new_active_messages)."""
    systems, groups = split_turn_groups(messages)
    base_system = systems[:1] or [{"role": "system", "content": SYSTEM_PROMPT}]
    if not groups:
        return [], list(base_system)


    recent_groups: List[List[Dict[str, Any]]] = []
    old_messages: List[Dict[str, Any]] = []
    used = 0


    # Always handle the newest group specially, including a long in-progress turn.
    newest_group = groups[-1]
    newest_tokens = _rough_tokens(newest_group)


    if newest_tokens <= keep_tokens:
        recent_groups = [newest_group]
        used = newest_tokens
    else:
        user, units = _interaction_units(newest_group)
        kept_units: List[List[Dict[str, Any]]] = []
        budget = max(500, keep_tokens - (_rough_tokens(user) if user else 0) - 80)
        unit_used = 0


        for unit in reversed(units):
            # Estimate with tool outputs softly pruned, so one giant command output
            # cannot monopolize the entire post-compaction tail.
            probe = []
            for idx, m in enumerate(unit):
                probe.append(_active_tool_prune(m, newest=(len(kept_units) == 0 and idx == len(unit) - 1)))
            t = _rough_tokens(probe)
            if kept_units and unit_used + t > budget:
                break
            kept_units.insert(0, probe)
            unit_used += t


        cut = max(0, len(units) - len(kept_units))
        for unit in units[:cut]:
            old_messages.extend(unit)


        active_group: List[Dict[str, Any]] = []
        if user is not None:
            active_group.append(user)
        if old_messages:
            active_group.append({
                "role": "assistant",
                "content": "[Earlier work in this same turn was compacted into session memory.]",
            })
        for unit in kept_units:
            active_group.extend(unit)
        recent_groups = [active_group]
        used = _rough_tokens(active_group)


    # Add earlier complete groups from newest backwards while they fit.
    for group in reversed(groups[:-1]):
        t = _rough_tokens(group)
        if used + t <= keep_tokens:
            recent_groups.insert(0, group)
            used += t
        else:
            break


    kept_group_count = len(recent_groups)
    earlier_cut = len(groups) - kept_group_count


    # If the newest group was internally split, earlier_cut arithmetic includes
    # it as a kept group. Add only truly older complete groups here.
    older_complete = groups[:max(0, len(groups) - kept_group_count)]
    old_messages = [m for group in older_complete for m in group] + old_messages


    active = list(base_system)
    for group in recent_groups:
        active.extend(group)


    # Preserve every removed interaction in order. Two distinct tool calls can
    # legitimately have identical serialized content, so value-based de-duplication
    # would silently erase real history.
    return old_messages, active




def _split_compaction_text(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut > start + max_chars // 2:
                end = cut
        chunks.append(text[start:end])
        start = end
    return [c for c in chunks if c.strip()]




COMPACTION_SYSTEM_PROMPT = """You are the continuation-memory compactor for a coding agent.
Produce a dense, factual checkpoint that lets the same coding agent continue without the old transcript.
Do not solve the user's task. Do not add new facts. Preserve exact technical details when they matter.


Use these headings exactly when relevant:
## Goal
## User requirements and constraints
## Current task plan
## Decisions and architecture
## Files and symbols
## Changes already made
## Commands, tests, and outcomes
## Errors and blockers
## Important exact values
## Pending work and next step


Rules:
- Prefer concrete file paths, symbol names, commands, error text, and outcomes.
- Preserve unresolved questions and user corrections.
- Do not retain huge raw tool output when a concise factual result is enough.
- If an older checkpoint is supplied, update it rather than blindly duplicating it.
- Keep the checkpoint compact enough for a small local model context.
Return only the checkpoint."""




def compact_model_call(previous: str, chunk: str, target_tokens: int) -> str:
    prompt = (
        "PREVIOUS CHECKPOINT:\n"
        + (previous.strip() if previous.strip() else "(none)")
        + "\n\nNEW HISTORY TO MERGE:\n"
        + chunk.strip()
        + "\n\nUpdate the checkpoint with all information that remains necessary."
    )
    payload = {
        "model": CURRENT_MODEL,
        "messages": [
            {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "num_ctx": CONTEXT_SIZE,
            "temperature": 0.0,
            "num_predict": int(target_tokens),
        },
    }
    data = ollama_request_json(CHAT_URL, method="POST", payload=payload, timeout=600)
    msg = data.get("message", {}) if isinstance(data, dict) else {}
    return str(msg.get("content", "")).strip()




def deterministic_compaction_fallback(
    prior: str,
    old_messages: List[Dict[str, Any]],
) -> str:
    lines = []
    if prior.strip():
        lines.append("## Earlier checkpoint\n" + prior.strip())
    lines.append("## Deterministic recovery summary")


    for msg in old_messages[-24:]:
        role = msg.get("role")
        if role == "user":
            lines.append("USER: " + short_text(msg.get("content", ""), 900))
        elif role == "assistant" and msg.get("content"):
            lines.append("ASSISTANT: " + short_text(msg.get("content", ""), 700))
        elif role == "tool":
            lines.append(
                f"TOOL {msg.get('tool_name', 'tool')}: "
                + short_text(msg.get("content", ""), 700)
            )


    if TASKS:
        lines.append("## Current task plan")
        for i, task in enumerate(TASKS, 1):
            lines.append(f"{i}. [{task.get('status')}] {task.get('title')} {task.get('note', '')}".strip())


    return "\n".join(lines)[-9000:]




def _compaction_archive_path() -> Path:
    return AGENT_DIR / "compactions.jsonl"




def archive_compaction(
    removed: List[Dict[str, Any]],
    prior_summary: str,
    new_summary: str,
    reason: str,
    before_tokens: int,
    after_tokens: int,
) -> None:
    try:
        ensure_agent_dir()
        record = {
            "time": time.time(),
            "generation": COMPACTION_GENERATION,
            "reason": reason,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "prior_summary": prior_summary,
            "new_summary": new_summary,
            "removed_messages": removed,
        }
        with _compaction_archive_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass




def compact_session(
    messages: List[Dict[str, Any]],
    reason: str,
    force: bool = False,
) -> List[Dict[str, Any]]:
    global COMPACTED_MEMORY, COMPACTION_GENERATION, COMPACTION_COUNT, LAST_COMPACTION_AT


    before = estimate_request_tokens(messages)
    keep = compact_keep_tokens()
    old_messages, active = select_compaction_split(messages, keep)


    if not old_messages and not force:
        return messages


    # Manual compaction on a short session still compacts all but the newest
    # conversational turn where possible.
    if not old_messages and force:
        systems, groups = split_turn_groups(messages)
        if len(groups) > 1:
            old_messages = [m for g in groups[:-1] for m in g]
            active = (systems[:1] or [{"role": "system", "content": SYSTEM_PROMPT}]) + groups[-1]
        else:
            ui_warn("There is not enough older context to compact yet.")
            return messages


    ui_header("AUTO COMPACT" if not force else "COMPACT", C.BRIGHT_CYAN)
    status_line("reason", reason, C.BRIGHT_BLACK)
    status_line("before", f"~{before:,} / {CONTEXT_SIZE:,} tokens", C.WHITE)
    status_line("keep tail", f"~{keep:,} tokens target", C.WHITE)


    material = "\n\n".join(_summary_message_repr(m) for m in old_messages)
    target = compact_summary_target_tokens()


    # Keep each summarization request comfortably inside the same local model's
    # context, even when compaction was triggered by an emergency overflow.
    chunk_token_budget = max(900, int(CONTEXT_SIZE * 0.47))
    chunk_chars = max(4000, chunk_token_budget * 4)
    chunks = _split_compaction_text(material, chunk_chars)


    prior = COMPACTED_MEMORY
    summary = prior
    spinner = Spinner("Compacting session memory")
    spinner.start()
    started = time.time()
    failed: Optional[str] = None


    try:
        for i, chunk in enumerate(chunks or [""]):
            spinner.set_label(f"Compacting memory {i + 1}/{max(1, len(chunks))}")
            summary = compact_model_call(summary, chunk, target)
            if not summary:
                raise AgentError("Compaction model returned an empty checkpoint.")
            # Bound pathological verbose summaries before the next merge pass.
            if len(summary) > 12000:
                summary = summary[:12000]
    except Exception as e:
        failed = str(e)
        summary = deterministic_compaction_fallback(prior, old_messages)
    finally:
        spinner.stop()


    COMPACTED_MEMORY = summary.strip()
    COMPACTION_GENERATION += 1
    COMPACTION_COUNT += 1
    LAST_COMPACTION_AT = time.time()


    after = estimate_request_tokens(active)
    archive_compaction(old_messages, prior, COMPACTED_MEMORY, reason, before, after)
    save_session(active)


    elapsed = time.time() - started
    if failed:
        ui_warn("Model-based summary failed; used deterministic fallback: " + short_text(failed, 180))
    ui_success(
        f"checkpoint {COMPACTION_GENERATION} complete · ~{before:,} → ~{after:,} tokens · {human_duration(elapsed)}"
    )
    status_line("summary", f"~{_rough_tokens(COMPACTED_MEMORY):,} tokens", C.WHITE)
    print()
    return active




def is_context_overflow_error(error: BaseException) -> bool:
    text = str(error).lower()
    patterns = [
        "context length", "context window", "too many tokens", "prompt too long",
        "input too long", "exceeds the context", "context size", "maximum context",
        "token limit", "context limit",
    ]
    return any(p in text for p in patterns)




def ensure_context_capacity(
    messages: List[Dict[str, Any]],
    reason: str,
) -> List[Dict[str, Any]]:
    # First try to grow the window safely if the computer has real headroom.
    maybe_auto_tune_context(messages, allow_increase=True)


    used = estimate_request_tokens(messages)
    trigger = context_trigger_tokens()


    if AUTO_COMPACT_ENABLED and used >= trigger:
        return compact_session(
            messages,
            reason=f"{reason}: request estimate {used:,} reached trigger {trigger:,}",
            force=False,
        )


    # Even with automatic compaction disabled, never knowingly send a request
    # that has effectively no completion reserve. This is an emergency guard.
    hard_guard = CONTEXT_SIZE - max(512, output_reserve_tokens() // 2)
    if used >= hard_guard:
        return compact_session(
            messages,
            reason=f"emergency hard guard: {used:,} estimated tokens",
            force=True,
        )


    return messages




def prune_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """V4 compatibility shim: compaction replaces destructive history pruning."""
    return ensure_context_capacity(messages, "history maintenance")




# Extend the system prompt without bloating every message with implementation detail.
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("Hyper-Cube Agent V3", "Hyper-Cube Agent V4") + """


V4 CONTEXT CONTINUITY
- Session memory may be compacted automatically. Treat <compacted_session_memory> as factual prior context.
- Treat <runtime_state> as current harness state and prefer it over stale older transcript details.
- Do not resist or redo completed work merely because older raw tool output was compacted.
- When an edit is blocked as stale, re-read that file and continue.
"""




# -----------------------------------------------------------------------------
# V4 persistence overrides
# -----------------------------------------------------------------------------




def load_config() -> None:
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE
    global APPROVAL_MODE, VERBOSE_TOOLS, RESUME_ENABLED
    global AUTO_COMPACT_ENABLED, AUTO_CONTEXT_ENABLED, CONTEXT_MODE, CONTEXT_USER_MAX


    data = load_json(CONFIG_PATH, {})
    if not isinstance(data, dict):
        return


    CURRENT_MODEL = str(data.get("model", CURRENT_MODEL))
    try:
        CONTEXT_SIZE = max(CONTEXT_MIN, min(int(data.get("context", CONTEXT_SIZE)), 32768))
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
    AUTO_COMPACT_ENABLED = bool(data.get("auto_compact", AUTO_COMPACT_ENABLED))
    AUTO_CONTEXT_ENABLED = bool(data.get("auto_context", AUTO_CONTEXT_ENABLED))


    ctx_mode = str(data.get("context_mode", CONTEXT_MODE))
    if ctx_mode in {"auto", "fixed"}:
        CONTEXT_MODE = ctx_mode
    try:
        CONTEXT_USER_MAX = max(CONTEXT_MIN, min(int(data.get("context_max", CONTEXT_USER_MAX)), 32768))
    except Exception:
        pass




def save_config() -> None:
    data = {
        "version": VERSION,
        "model": CURRENT_MODEL,
        "context": CONTEXT_SIZE,
        "temperature": TEMPERATURE,
        "approval_mode": APPROVAL_MODE,
        "verbose_tools": VERBOSE_TOOLS,
        "resume": RESUME_ENABLED,
        "auto_compact": AUTO_COMPACT_ENABLED,
        "auto_context": AUTO_CONTEXT_ENABLED,
        "context_mode": CONTEXT_MODE,
        "context_max": CONTEXT_USER_MAX,
    }
    try:
        atomic_write_json(CONFIG_PATH, data)
    except Exception:
        pass




def _trim_session_messages_v4(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(messages) <= MAX_SESSION_MESSAGES:
        return messages
    systems, groups = split_turn_groups(messages)
    kept: List[List[Dict[str, Any]]] = []
    count = len(systems)
    for group in reversed(groups):
        if kept and count + len(group) > MAX_SESSION_MESSAGES:
            break
        kept.insert(0, group)
        count += len(group)
    result = list(systems[:1])
    for group in kept:
        result.extend(group)
    return result




def save_session(messages: List[Dict[str, Any]]) -> None:
    data = {
        "version": VERSION,
        "saved_at": time.time(),
        "messages": _trim_session_messages_v4(messages),
        "compacted_memory": COMPACTED_MEMORY,
        "compaction_generation": COMPACTION_GENERATION,
        "compaction_count": COMPACTION_COUNT,
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
    global COMPACTED_MEMORY, COMPACTION_GENERATION, COMPACTION_COUNT


    if not RESUME_ENABLED:
        return [{"role": "system", "content": system_prompt}], False


    data = load_json(SESSION_PATH, {})
    if not isinstance(data, dict) or not data:
        return [{"role": "system", "content": system_prompt}], False


    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return [{"role": "system", "content": system_prompt}], False


    cleaned = [{"role": "system", "content": system_prompt}]
    for m in msgs:
        if isinstance(m, dict) and m.get("role") != "system":
            cleaned.append(m)


    COMPACTED_MEMORY = str(data.get("compacted_memory", "") or "")
    try:
        COMPACTION_GENERATION = int(data.get("compaction_generation", 0))
        COMPACTION_COUNT = int(data.get("compaction_count", COMPACTION_GENERATION))
    except Exception:
        COMPACTION_GENERATION = 0
        COMPACTION_COUNT = 0


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
        READ_SNAPSHOTS = {str(k): v for k, v in raw_snapshots.items() if isinstance(v, dict)}


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




# -----------------------------------------------------------------------------
# V4 UI / diagnostics overrides
# -----------------------------------------------------------------------------




def print_banner() -> None:
    width = terminal_width()
    title = " HYPER-CUBE LOCAL CODING AGENT V5 "
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
    status_line("context", f"{CONTEXT_SIZE:,} · {CONTEXT_MODE}", C.WHITE)
    status_line("compact", "auto" if AUTO_COMPACT_ENABLED else "manual/emergency", C.WHITE)
    status_line("approval", APPROVAL_MODE, C.BRIGHT_YELLOW)
    branch = get_git_branch()
    if branch:
        status_line("git branch", branch, C.WHITE)
    print()




def run_startup_diagnostics(session_resumed: bool) -> None:
    RESOURCE_MONITOR.start()
    # Give the first memory sample a moment to exist; do not delay materially.
    time.sleep(0.03)


    ui_header("STARTUP DIAGNOSTICS", C.BRIGHT_CYAN)
    models = installed_models()
    if models:
        ui_success(f"Ollama connected  ·  {len(models)} model(s) installed")
    else:
        ui_error("Ollama unavailable or no installed models were returned")


    if CURRENT_MODEL in models:
        ui_success(f"Model found  ·  {CURRENT_MODEL}")
    else:
        ui_warn(f"Configured model not found in model list  ·  {CURRENT_MODEL}")


    supports_tools, _caps = model_capabilities(CURRENT_MODEL) if CURRENT_MODEL in models else (None, [])
    if supports_tools is True:
        ui_success("Tool calling supported")
    elif supports_tools is False:
        ui_error("Model reports no tool-calling capability")
    else:
        ui_warn("Could not verify model tool capability")


    if POWERSHELL_EXE:
        ui_success(f"PowerShell  ·  {POWERSHELL_EXE}")
    else:
        ui_error("PowerShell was not found")


    if git_available():
        ui_success("Git available")
    else:
        ui_warn("Git unavailable; Git helpers will not work")


    ui_success("Previous agent session resumed" if session_resumed else "New agent session")
    ui_success(
        f"Context engine  ·  {CONTEXT_SIZE:,} current / {effective_context_ceiling():,} adaptive ceiling"
    )
    ui_success(
        f"Auto compact  ·  trigger ≈ {context_trigger_tokens():,} request tokens; keep ≈ {compact_keep_tokens():,}"
    )


    snap = RESOURCE_MONITOR.snapshot()
    if snap.get("total"):
        cpu = snap.get("cpu_avg")
        ui_success(
            "Resource monitor  ·  RAM "
            + fmt_bytes(int(snap.get("available", 0)))
            + " free / "
            + fmt_bytes(int(snap.get("total", 0)))
            + (f" · CPU {float(cpu):.0f}%" if cpu is not None else "")
        )


    if COMPACTED_MEMORY:
        ui_success(
            f"Compacted memory restored  ·  generation {COMPACTION_GENERATION} · ~{_rough_tokens(COMPACTED_MEMORY):,} tokens"
        )
    print()




# -----------------------------------------------------------------------------
# V4 Ollama stream override with full request accounting / better errors
# -----------------------------------------------------------------------------




def stream_ollama_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    global MODEL_HAS_RUN


    request_messages = prepare_request_messages(messages)
    payload = {
        "model": CURRENT_MODEL,
        "messages": request_messages,
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
    seen_calls: set = set()
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
                    key = str(call.get("id")) if call.get("id") else json.dumps(call, sort_keys=True, ensure_ascii=False)
                    if key not in seen_calls:
                        seen_calls.add(key)
                        tool_calls.append(call)


                if chunk.get("done"):
                    final_meta = chunk


    except KeyboardInterrupt:
        spinner.stop()
        raise OperationCancelled("Model generation cancelled.")
    except urllib.error.HTTPError as e:
        spinner.stop()
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        raise AgentError(f"Ollama HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        spinner.stop()
        raise AgentError(
            "Could not connect to Ollama at 127.0.0.1:11434. Make sure Ollama is running."
        ) from e
    finally:
        spinner.stop()


    MODEL_HAS_RUN = True
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




# -----------------------------------------------------------------------------
# V4 slash commands. Delegate all unchanged commands to V3 implementation.
# -----------------------------------------------------------------------------


_V3_SLASH_COMMAND = slash_command




def slash_command(
    text: str,
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    global AUTO_COMPACT_ENABLED, AUTO_CONTEXT_ENABLED
    global CONTEXT_MODE, CONTEXT_SIZE, CONTEXT_USER_MAX, COMPACTED_MEMORY


    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""


    if cmd in {"/compact", "/summarize"}:
        low = arg.lower()
        if low in {"status", "stats"}:
            print()
            status_line("enabled", str(AUTO_COMPACT_ENABLED), C.WHITE)
            status_line("generation", str(COMPACTION_GENERATION), C.WHITE)
            status_line("count", str(COMPACTION_COUNT), C.WHITE)
            status_line("summary", f"~{_rough_tokens(COMPACTED_MEMORY):,} tokens", C.WHITE)
            status_line("trigger", f"~{context_trigger_tokens():,} request tokens", C.WHITE)
            status_line("keep tail", f"~{compact_keep_tokens():,} tokens", C.WHITE)
            print()
            return "handled", messages, None
        if low == "show":
            print()
            print(COMPACTED_MEMORY or "(no compacted memory yet)")
            print()
            return "handled", messages, None
        if low in {"auto on", "on"}:
            AUTO_COMPACT_ENABLED = True
            save_config()
            ui_success("Automatic compaction enabled")
            return "handled", messages, None
        if low in {"auto off", "off"}:
            AUTO_COMPACT_ENABLED = False
            save_config()
            ui_warn("Automatic compaction disabled; emergency overflow recovery remains enabled")
            return "handled", messages, None


        messages = compact_session(messages, reason="manual /compact", force=True)
        return "handled", messages, None


    if cmd in {"/context", "/autocontext"}:
        low = arg.lower()
        if cmd == "/autocontext" and low in {"on", "off"}:
            AUTO_CONTEXT_ENABLED = low == "on"
            CONTEXT_MODE = "auto" if AUTO_CONTEXT_ENABLED else "fixed"
            save_config()
            ui_success(f"Adaptive context: {AUTO_CONTEXT_ENABLED}")
            return "handled", messages, None


        if not low or low in {"status", "show"}:
            print()
            for line in context_status_lines(messages):
                print(color("  " + line, C.WHITE))
            print()
            return "handled", messages, None


        if low == "auto" or low == "auto on":
            AUTO_CONTEXT_ENABLED = True
            CONTEXT_MODE = "auto"
            save_config()
            ui_success("Adaptive context enabled")
            maybe_auto_tune_context(messages, allow_increase=True)
            return "handled", messages, None


        if low in {"auto off", "fixed"}:
            AUTO_CONTEXT_ENABLED = False
            CONTEXT_MODE = "fixed"
            save_config()
            ui_success(f"Context fixed at {CONTEXT_SIZE:,}")
            return "handled", messages, None


        if low.startswith("max "):
            try:
                CONTEXT_USER_MAX = max(CONTEXT_MIN, min(int(low.split()[1]), 32768))
                save_config()
                ui_success(f"Adaptive context maximum set to {CONTEXT_USER_MAX:,}")
            except Exception:
                ui_error("Usage: /context max 16384")
            return "handled", messages, None


        try:
            value = max(CONTEXT_MIN, min(int(low), 32768))
            CONTEXT_SIZE = value
            CONTEXT_MODE = "fixed"
            AUTO_CONTEXT_ENABLED = False
            save_config()
            ui_success(f"Context fixed at {CONTEXT_SIZE:,}")
        except Exception:
            ui_error("Usage: /context [status|auto|auto off|max N|N]")
        return "handled", messages, None


    if cmd == "/ctx":
        if arg.lower() == "auto":
            AUTO_CONTEXT_ENABLED = True
            CONTEXT_MODE = "auto"
            save_config()
            ui_success("Adaptive context enabled")
            return "handled", messages, None
        try:
            CONTEXT_SIZE = max(CONTEXT_MIN, min(int(arg), 32768))
            AUTO_CONTEXT_ENABLED = False
            CONTEXT_MODE = "fixed"
            save_config()
            ui_success(f"Context fixed at {CONTEXT_SIZE:,}")
        except Exception:
            ui_error("Usage: /ctx 8192 or /ctx auto")
        return "handled", messages, None


    if cmd == "/memory":
        print()
        status_line("checkpoint", f"generation {COMPACTION_GENERATION}", C.WHITE)
        status_line("tokens", f"~{_rough_tokens(COMPACTED_MEMORY):,}", C.WHITE)
        if COMPACTED_MEMORY:
            print_rule("·", C.BRIGHT_BLACK)
            print(COMPACTED_MEMORY)
            print_rule("·", C.BRIGHT_BLACK)
        else:
            print(color("  No compacted session memory yet.", C.BRIGHT_BLACK))
        print()
        return "handled", messages, None


    return _V3_SLASH_COMMAND(text, messages)




# Add V4 commands to the displayed help string used by the delegated V3 /help.
HELP_TEXT = HELP_TEXT.replace(
    "/ctx <2048-32768>        Change context size",
    "/ctx <N>|auto            Fix context size or enable adaptive context\n"
    "/context [...]           Context status/auto/max controls\n"
    "/compact                 Manually compact session memory\n"
    "/compact status|show     Compaction status or checkpoint\n"
    "/memory                  Show current compacted checkpoint",
)




# -----------------------------------------------------------------------------
# V4 turn loop: preflight, auto compact, adaptive context, overflow recovery
# -----------------------------------------------------------------------------




def process_user_turn(
    user_text: str,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    global TURN_TOOL_COUNT, LAST_USER_TEXT


    TURN_TOOL_COUNT = 0
    LAST_USER_TEXT = user_text
    turn_start = time.time()
    messages.append({"role": "user", "content": user_text})
    save_session(messages)


    final_meta: Dict[str, Any] = {}
    overflow_recovered = False


    for _step in range(MAX_TOOL_STEPS):
        try:
            messages = ensure_context_capacity(messages, reason="preflight")
            save_session(messages)
            response = stream_ollama_chat(messages)
        except OperationCancelled:
            double = register_interrupt()
            if double:
                abandon_current_task()
                ui_warn("Task abandoned.")
                messages.append({"role": "system", "content": "The user abandoned the previous task."})
            else:
                ui_warn(
                    "Current generation cancelled. Press Ctrl+C again within "
                    f"{CANCEL_DOUBLE_TAP_SECONDS:.1f}s to abandon the whole task."
                )
            save_session(messages)
            return messages
        except Exception as e:
            if is_context_overflow_error(e) and not overflow_recovered:
                overflow_recovered = True
                ui_warn("Ollama reported context overflow. Compacting and retrying this step once.")
                messages = compact_session(
                    messages,
                    reason="provider context-overflow recovery",
                    force=True,
                )
                continue
            print()
            ui_error(str(e))
            print()
            save_session(messages)
            return messages


        message = response.get("message", {}) or {}
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls") or []
        final_meta = response.get("_meta", {}) or {}


        assistant_message: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)


        if not tool_calls:
            # An idle boundary is a safe time to evaluate a possible future
            # context increase without interrupting a tool trajectory.
            maybe_auto_tune_context(messages, allow_increase=True)
            elapsed = time.time() - turn_start
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
                    messages.append({"role": "system", "content": "The user abandoned the previous task."})
                else:
                    ui_warn(
                        "Current operation cancelled. Press Ctrl+C again quickly to abandon the whole task."
                    )
                save_session(messages)
                return messages


            messages.append(build_tool_message(call, name, result))
            save_session(messages)


        # Do not wait for the next user turn. Long same-turn tool trajectories
        # are exactly where coding harnesses most often hit the context wall.
        messages = ensure_context_capacity(messages, reason="after tool results")
        save_session(messages)


    ui_warn(f"Stopped after {MAX_TOOL_STEPS} tool steps to prevent an infinite loop.")
    save_session(messages)
    return messages




def run_agent() -> None:
    global LAST_INTERRUPT_TIME


    messages, resumed = load_session(SYSTEM_PROMPT)
    maybe_auto_tune_context(messages, allow_increase=True)
    warm_model_background()


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
        description="Hyper-Cube Local Coding Agent V4 for Ollama."
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
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE, RESUME_ENABLED, POWERSHELL_EXE, CONTEXT_MODE, AUTO_CONTEXT_ENABLED


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
        CONTEXT_SIZE = max(CONTEXT_MIN, min(int(args.ctx), 32768))
        CONTEXT_MODE = "fixed"
        AUTO_CONTEXT_ENABLED = False
    if args.temperature is not None:
        TEMPERATURE = max(0.0, min(float(args.temperature), 2.0))
    if args.no_resume:
        RESUME_ENABLED = False


    POWERSHELL_EXE = detect_powershell()


    # Persistent state folder is used by the V4 harness.
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
# =============================================================================
# V5 PERFORMANCE ENGINE
# =============================================================================
#
# V5 is intentionally implemented as a clean override layer over the validated
# V4 harness. The V4 safety, editing, persistence, repository map, compaction,
# and adaptive-context machinery remain available. V5 replaces the hot paths:
# request construction, tool routing, tool execution, result retention,
# performance telemetry, context selection, and task progress.
#
# Design goals:
# - Same primary model quality.
# - Fewer model round trips.
# - Smaller prompts.
# - Better prompt-cache locality.
# - Parallel read-only tools.
# - Lossless paging for large tool/file results.
# - Cheap compaction before semantic compaction.
# - Persistent harness-owned state.
# - Smallest context that comfortably fits, not largest context possible.
# - Keep Ollama's model warm while Pygent is open.
# - No third-party Python packages.
# =============================================================================

import concurrent.futures
import atexit
from collections import deque

VERSION = "5.0"

# ----------------------------- V5 paths/state -------------------------------

RESULTS_DIR: Path = AGENT_DIR / "results"
LEDGER_PATH: Path = AGENT_DIR / "ledger.json"
PERF_PATH: Path = AGENT_DIR / "performance.jsonl"

RESULT_INLINE_LIMIT = 11_000
COMMAND_INLINE_LIMIT = 6_000
SOURCE_INLINE_LIMIT = 16_000
SMART_READ_DEFAULT_LINES = 220
SMART_READ_MAX_INLINE_LINES = 260
RESULT_PAGE_LINES = 220
MAX_RESULT_FILES = 0  # 0 retains all exact results referenced by session archives.

TOOL_PARALLELISM = 4
MODEL_KEEP_ALIVE: Any = -1
WARM_MODEL_ON_START = True
RELEASE_MODEL_ON_EXIT = True

# Context should have enough free space for the response/tool call, but V5
# intentionally chooses the smallest tier that fits comfortably.
V5_CONTEXT_HEADROOM_RATIO = 0.10
V5_CONTEXT_HEADROOM_MIN = 640
V5_CONTEXT_HEADROOM_MAX = 1800
V5_CONTEXT_DOWNSHIFT_COOLDOWN = 20.0

# Mechanical compaction happens before expensive model-based compaction.
MECHANICAL_COMPACT_TRIGGER_RATIO = 0.68
MECHANICAL_KEEP_RECENT_GROUPS = 2
MECHANICAL_TOOL_ARG_LIMIT = 900
MECHANICAL_TOOL_RESULT_LIMIT = 1800

# Profiler keeps a small in-memory window and appends exact records to JSONL.
PERF_HISTORY: List[Dict[str, Any]] = []
PERF_HISTORY_LIMIT = 80

# Result counter and deterministic runtime ledger.
RESULT_COUNTER = 0
_RESULT_STATE_LOCK = threading.RLock()
SESSION_LEDGER: Dict[str, Any] = {
    "current_goal": "",
    "read_files": [],
    "modified_files": [],
    "commands": [],
    "tests": [],
    "errors": [],
    "results": [],
    "last_tool": "",
    "last_activity": "",
    "last_answer": "",
}

# Tool profile changes only at natural phase boundaries. Keeping a profile
# stable across consecutive calls improves prompt-cache reuse.
ACTIVE_TOOL_PROFILE = "explore"
REQUESTED_TOOL_PROFILE: Optional[str] = None

# Warm-up state is display-only and never sent to the model.
MODEL_WARM_STATE = "unknown"
_MODEL_WARM_THREAD: Optional[threading.Thread] = None
_MODEL_WARM_MODEL = ""

# Q8 is a server-start setting, not an /api/chat option. Own the server by
# default so a tray process with stale settings cannot silently defeat it.
DEFAULT_KV_CACHE_TYPE = "q8_0"
OLLAMA_SERVER_MODE = "not started"
OLLAMA_SERVER_ENV: Dict[str, str] = {}
_OLLAMA_SERVER_PROCESS: Optional[subprocess.Popen] = None
_OLLAMA_LOG_HANDLE: Any = None
_OLLAMA_LOG_PATH: Optional[Path] = None
_OLLAMA_LOG_MODEL = ""
_OLLAMA_LOG_OFFSET = 0
_OLLAMA_EVIDENCE_LOCK = threading.Lock()
_OLLAMA_LAST_WARNING = ""


def set_ollama_base(url: str) -> None:
    global OLLAMA_BASE, CHAT_URL, TAGS_URL, SHOW_URL, PS_URL
    global _MODEL_SHOW_CACHE, _MODEL_SHOW_CACHE_AT
    parsed = urllib.parse.urlsplit(url.strip())
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise AgentError("--ollama-url must be an HTTP(S) base URL without credentials, query, or fragment.")
    try:
        parsed.port  # Validate malformed/out-of-range ports before any request.
    except ValueError as e:
        raise AgentError(f"Invalid Ollama URL port: {e}") from e
    OLLAMA_BASE = url.strip().rstrip("/")
    CHAT_URL = OLLAMA_BASE + "/api/chat"
    TAGS_URL = OLLAMA_BASE + "/api/tags"
    SHOW_URL = OLLAMA_BASE + "/api/show"
    PS_URL = OLLAMA_BASE + "/api/ps"
    _MODEL_SHOW_CACHE = {}
    _MODEL_SHOW_CACHE_AT = 0.0


def ollama_urlopen(request: Any, timeout: int) -> Any:
    # A local private server must not be sent through an inherited web proxy.
    # Keep the user's normal proxy behavior for explicitly chosen external URLs.
    if OLLAMA_SERVER_MODE == "managed":
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def find_ollama_executable(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(explicit)
    found = shutil.which("ollama")
    if found:
        return found
    candidates: List[Path] = []
    if os.name == "nt":
        for variable, suffix in (
            ("LOCALAPPDATA", "Programs/Ollama/ollama.exe"),
            ("ProgramFiles", "Ollama/ollama.exe"),
        ):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / suffix)
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/Applications/Ollama.app/Contents/Resources/ollama"),
            Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama"),
        ])
    return next((str(p) for p in candidates if p.is_file()), None)


def managed_ollama_log(model_only: bool = False, limit: int = 131_072) -> str:
    if _OLLAMA_LOG_PATH is None:
        return ""
    try:
        with _OLLAMA_LOG_PATH.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            start = max(0, end - limit)
            if model_only:
                start = max(start, _OLLAMA_LOG_OFFSET)
            f.seek(start)
            return f.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def begin_ollama_model_request(model: str) -> None:
    global _OLLAMA_LOG_MODEL, _OLLAMA_LOG_OFFSET, _OLLAMA_LAST_WARNING
    # An empty warm-up, compaction, and streamed chat all use this boundary.
    # Never reuse a previous model's cache evidence after /model changes.
    with _OLLAMA_EVIDENCE_LOCK:
        if model != _OLLAMA_LOG_MODEL:
            _OLLAMA_LOG_MODEL = model
            _OLLAMA_LOG_OFFSET = (
                _OLLAMA_LOG_PATH.stat().st_size
                if _OLLAMA_LOG_PATH and _OLLAMA_LOG_PATH.exists() else 0
            )
            _OLLAMA_LAST_WARNING = ""


def stop_managed_ollama() -> None:
    global _OLLAMA_SERVER_PROCESS, _OLLAMA_LOG_HANDLE, OLLAMA_SERVER_MODE
    proc = _OLLAMA_SERVER_PROCESS
    _OLLAMA_SERVER_PROCESS = None
    try:
        if proc is not None:
            if os.name == "nt" and proc.poll() is None:
                # Only this exact owned PID and its child runners, never a
                # name-wide taskkill that could terminate the user's tray app.
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
            elif os.name != "nt":
                # start_new_session owns the group, including model runners.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if proc.poll() is None:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        proc.kill()
                    proc.wait(timeout=3)
    finally:
        if _OLLAMA_LOG_HANDLE is not None:
            _OLLAMA_LOG_HANDLE.close()
            _OLLAMA_LOG_HANDLE = None
        if proc is not None:
            OLLAMA_SERVER_MODE = "managed (stopped)"


def start_ollama_server(
    executable: Optional[str] = None,
    external_url: Optional[str] = None,
    timeout: float = 30.0,
) -> None:
    global _OLLAMA_SERVER_PROCESS, _OLLAMA_LOG_HANDLE, _OLLAMA_LOG_PATH
    global OLLAMA_SERVER_MODE, OLLAMA_SERVER_ENV
    global _OLLAMA_LOG_MODEL, _OLLAMA_LOG_OFFSET, _OLLAMA_LAST_WARNING
    _OLLAMA_LOG_MODEL, _OLLAMA_LOG_OFFSET, _OLLAMA_LAST_WARNING = "", 0, ""
    if external_url:
        set_ollama_base(external_url)
        OLLAMA_SERVER_MODE = "external (configuration unverified)"
        OLLAMA_SERVER_ENV = {}
        return
    exe = find_ollama_executable(executable)
    if not exe:
        raise AgentError(
            "Ollama executable not found. Install Ollama or pass --ollama-exe PATH. "
            "To use a separately configured server, pass --ollama-url http://127.0.0.1:11434."
        )
    ensure_agent_dir()
    # Ollama does not accept a inherited listening socket. Reserve a candidate
    # loopback port, then require this child to log that it bound that address.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    host = f"127.0.0.1:{port}"
    set_ollama_base("http://" + host)
    env = os.environ.copy()
    env.update({
        "OLLAMA_HOST": host,
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": DEFAULT_KV_CACHE_TYPE,
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
    })
    OLLAMA_SERVER_ENV = {k: env[k] for k in (
        "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE",
    )}
    # Retain OLLAMA_MODELS and all other user settings in the child environment.
    # Per-PID log names allow two projects to run without clobbering evidence.
    _OLLAMA_LOG_PATH = AGENT_DIR / f"ollama-q8-{os.getpid()}.log"
    _OLLAMA_LOG_HANDLE = _OLLAMA_LOG_PATH.open("wb")
    kwargs: Dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    try:
        _OLLAMA_SERVER_PROCESS = subprocess.Popen(
            [exe, "serve"], env=env, stdin=subprocess.DEVNULL,
            stdout=_OLLAMA_LOG_HANDLE, stderr=subprocess.STDOUT, **kwargs,
        )
        OLLAMA_SERVER_MODE = "managed"
        deadline = time.monotonic() + timeout
        # Bypass proxy variables only for the owned loopback readiness probe.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if _OLLAMA_SERVER_PROCESS.poll() is not None:
                raise AgentError("Managed Ollama exited during startup.")
            if f"Listening on {host}" in managed_ollama_log():
                try:
                    with opener.open(OLLAMA_BASE + "/api/version", timeout=1) as r:
                        ready = json.loads(r.read().decode("utf-8"))
                    if ready.get("version") and _OLLAMA_SERVER_PROCESS.poll() is None:
                        return
                except (OSError, ValueError, urllib.error.URLError):
                    pass
            time.sleep(0.1)
        raise AgentError(f"Managed Ollama did not become ready within {timeout:g} seconds.")
    except BaseException as e:
        stop_managed_ollama()
        if isinstance(e, KeyboardInterrupt):
            raise
        raise AgentError(f"{e} See the server log: {_OLLAMA_LOG_PATH}") from e


atexit.register(stop_managed_ollama)

# V5 wraps selected V4 functions before overriding their names.
_V4_ENSURE_AGENT_DIR = ensure_agent_dir
_V4_LOAD_CONFIG = load_config
_V4_SAVE_CONFIG = save_config
_V4_SAVE_SESSION = save_session
_V4_LOAD_SESSION = load_session
_V4_TOOL_READ_FILE = tool_read_file
_V4_COMPACT_SESSION = compact_session
_V4_SLASH_COMMAND_V5_BASE = slash_command
_V4_RUN_STARTUP_DIAGNOSTICS = run_startup_diagnostics


# -------------------------- persistence / directories ------------------------

def ensure_agent_dir() -> None:
    _V4_ENSURE_AGENT_DIR()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _bounded_unique(items: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    for item in items:
        s = str(item)
        if not s:
            continue
        if s in out:
            out.remove(s)
        out.append(s)
    return out[-limit:]


def load_ledger() -> None:
    global SESSION_LEDGER, RESULT_COUNTER
    data = load_json(LEDGER_PATH, {})
    if not isinstance(data, dict):
        return

    merged = dict(SESSION_LEDGER)
    merged.update(data)
    for key in ("read_files", "modified_files", "commands", "tests", "errors", "results"):
        if not isinstance(merged.get(key), list):
            merged[key] = []
    SESSION_LEDGER = merged

    try:
        RESULT_COUNTER = max(int(data.get("result_counter", 0)), RESULT_COUNTER)
    except Exception:
        pass


def save_ledger() -> None:
    try:
        with _RESULT_STATE_LOCK:
            ensure_agent_dir()
            data = dict(SESSION_LEDGER)
            data["result_counter"] = RESULT_COUNTER
            atomic_write_json(LEDGER_PATH, data)
    except Exception:
        pass


def load_config() -> None:
    global MODEL_KEEP_ALIVE, WARM_MODEL_ON_START, RELEASE_MODEL_ON_EXIT
    _V4_LOAD_CONFIG()
    data = load_json(CONFIG_PATH, {})
    if not isinstance(data, dict):
        return

    MODEL_KEEP_ALIVE = data.get("keep_alive", MODEL_KEEP_ALIVE)
    WARM_MODEL_ON_START = bool(data.get("warm_model_on_start", WARM_MODEL_ON_START))
    RELEASE_MODEL_ON_EXIT = bool(data.get("release_model_on_exit", RELEASE_MODEL_ON_EXIT))


def save_config() -> None:
    _V4_SAVE_CONFIG()
    try:
        data = load_json(CONFIG_PATH, {})
        if not isinstance(data, dict):
            data = {}
        data.update({
            "version": VERSION,
            "keep_alive": MODEL_KEEP_ALIVE,
            "warm_model_on_start": WARM_MODEL_ON_START,
            "release_model_on_exit": RELEASE_MODEL_ON_EXIT,
        })
        atomic_write_json(CONFIG_PATH, data)
    except Exception:
        pass


def save_session(messages: List[Dict[str, Any]]) -> None:
    _V4_SAVE_SESSION(messages)
    save_ledger()


def load_session(system_prompt: str) -> Tuple[List[Dict[str, Any]], bool]:
    messages, resumed = _V4_LOAD_SESSION(system_prompt)
    load_ledger()
    if not resumed:
        reset_session_ledger()
    return messages, resumed


def reset_session_ledger() -> None:
    global SESSION_LEDGER
    SESSION_LEDGER = {
        "current_goal": "", "read_files": [], "modified_files": [],
        "commands": [], "tests": [], "errors": [], "results": [],
        "last_tool": "", "last_activity": "", "last_answer": "",
        "result_counter": RESULT_COUNTER,
    }
    save_ledger()


# ------------------------------- profiler -----------------------------------

def _ns_seconds(value: Any) -> float:
    try:
        return max(0.0, float(value or 0) / 1_000_000_000.0)
    except Exception:
        return 0.0


def _append_perf_record(record: Dict[str, Any]) -> None:
    PERF_HISTORY.append(record)
    del PERF_HISTORY[:-PERF_HISTORY_LIMIT]

    try:
        ensure_agent_dir()
        with PERF_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_recent_perf() -> None:
    if PERF_HISTORY:
        return
    try:
        if not PERF_PATH.exists():
            return
        with PERF_PATH.open("r", encoding="utf-8", errors="replace") as source:
            lines = deque(source, maxlen=PERF_HISTORY_LIMIT * 3)
        for raw in lines:
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    if obj.get("kind") == "tool_batch":
                        for sample in reversed(PERF_HISTORY):
                            if sample.get("request_id") == obj.get("request_id"):
                                sample.update({k: obj[k] for k in ("tool_wall_s", "tool_calls")})
                                break
                    else:
                        PERF_HISTORY.append(obj)
                        del PERF_HISTORY[:-PERF_HISTORY_LIMIT]
            except Exception:
                pass
    except Exception:
        pass


def record_perf(
    meta: Dict[str, Any],
    *,
    profile: str,
    wall_seconds: float,
    request_estimate: int,
    tool_schema_tokens: int,
) -> Dict[str, Any]:
    prompt_count = int(meta.get("prompt_eval_count") or 0)
    cached_count = int(meta.get("prompt_eval_cached_count") or 0)
    eval_count = int(meta.get("eval_count") or 0)

    prompt_seconds = _ns_seconds(meta.get("prompt_eval_duration"))
    eval_seconds = _ns_seconds(meta.get("eval_duration"))
    load_seconds = _ns_seconds(meta.get("load_duration"))
    total_seconds = _ns_seconds(meta.get("total_duration")) or wall_seconds

    uncached = max(0, prompt_count - cached_count)
    cache_pct = (100.0 * cached_count / prompt_count) if prompt_count else 0.0
    decode_tps = (eval_count / eval_seconds) if eval_count and eval_seconds > 0 else 0.0
    prompt_tps = (uncached / prompt_seconds) if uncached and prompt_seconds > 0 else 0.0

    components = {
        "load": load_seconds,
        "prompt": prompt_seconds,
        "decode": eval_seconds,
        "other": max(0.0, total_seconds - load_seconds - prompt_seconds - eval_seconds),
    }
    bottleneck = max(components, key=components.get) if total_seconds > 0 else "unknown"

    rec = {
        "kind": "model",
        "request_id": time.time_ns(),
        "time": time.time(),
        "model": CURRENT_MODEL,
        "profile": profile,
        "context": CONTEXT_SIZE,
        "request_estimate": request_estimate,
        "tool_schema_tokens": tool_schema_tokens,
        "total_s": total_seconds,
        "wall_s": wall_seconds,
        "load_s": load_seconds,
        "prompt_s": prompt_seconds,
        "decode_s": eval_seconds,
        "prompt_tokens": prompt_count,
        "cached_prompt_tokens": cached_count,
        "uncached_prompt_tokens": uncached,
        "cache_pct": cache_pct,
        "output_tokens": eval_count,
        "decode_tps": decode_tps,
        "prompt_tps": prompt_tps,
        "bottleneck": bottleneck,
        "ttft_s": meta.get("ttft_s"),
    }
    _append_perf_record(rec)
    return rec


def perf_summary_text(limit: int = 8) -> str:
    load_recent_perf()
    rows = PERF_HISTORY[-max(1, limit):]
    if not rows:
        return "No performance samples yet."

    def avg(key: str) -> float:
        vals = [float(x.get(key, 0) or 0) for x in rows]
        return sum(vals) / len(vals) if vals else 0.0

    bottlenecks: Dict[str, int] = {}
    for r in rows:
        b = str(r.get("bottleneck", "unknown"))
        bottlenecks[b] = bottlenecks.get(b, 0) + 1
    main_bottleneck = max(bottlenecks, key=bottlenecks.get)

    last = rows[-1]
    return "\n".join([
        f"samples={len(rows)}; dominant_bottleneck={main_bottleneck}",
        f"avg total={avg('total_s'):.2f}s; prompt={avg('prompt_s'):.2f}s; decode={avg('decode_s'):.2f}s; load={avg('load_s'):.2f}s",
        f"avg prompt cache={avg('cache_pct'):.1f}%; avg decode={avg('decode_tps'):.1f} tok/s",
        f"avg tools={avg('tool_wall_s'):.2f}s; tool calls={sum(int(x.get('tool_calls', 0)) for x in rows)}",
        f"last request≈{int(last.get('request_estimate', 0)):,} tokens; tools≈{int(last.get('tool_schema_tokens', 0)):,}; profile={last.get('profile')}",
    ])


# --------------------------- Ollama/model metadata ---------------------------

def model_quantization() -> str:
    data = model_show_data()
    details = data.get("details", {}) if isinstance(data, dict) else {}
    if isinstance(details, dict):
        q = details.get("quantization_level")
        if q:
            return str(q)

    info = data.get("model_info", {}) if isinstance(data, dict) else {}
    if isinstance(info, dict):
        q = info.get("general.file_type")
        if q:
            return str(q)

    return "unknown"


def server_inference_environment() -> Dict[str, str]:
    owned = _OLLAMA_SERVER_PROCESS is not None and _OLLAMA_SERVER_PROCESS.poll() is None
    kv, flash = "unknown", "unknown"
    warming_another_model = (_MODEL_WARM_THREAD is not None and _MODEL_WARM_THREAD.is_alive()
                             and _MODEL_WARM_MODEL != CURRENT_MODEL)
    if owned and _OLLAMA_LOG_MODEL == CURRENT_MODEL and not warming_another_model:
        log = managed_ollama_log(model_only=True)
        # Only the latest context construction belongs to the current runner.
        # A newly constructing context must not inherit old positive evidence.
        starts = list(re.finditer(r"(?im)^.*llama_(?:new_)?context[^\n]*constructing", log))
        if starts:
            log = log[starts[-1].start():]
        for line in log.splitlines():
            lower = line.lower()
            # These are actual llama.cpp allocation summaries, NOT environment
            # echoes, model-weight quantization, or runner command-line flags.
            if "kv" in lower and "cache" in lower:
                match = re.search(r"\bK\s*\((f16|q8_0|q4_0)\).*\bV\s*\((f16|q8_0|q4_0)\)", line, re.I)
                if match:
                    k, v = (x.lower() for x in match.groups())
                    kv = k if k == v else f"mixed K={k}, V={v}"
            if re.search(r"\bflash_attn\s*=\s*(?:0|false|disabled)\b", lower):
                flash = "disabled"
            elif re.search(r"\bflash_attn\s*=\s*(?:1|true|enabled)\b", lower):
                flash = "enabled"
            elif re.search(r"flash[ _-](?:attention|attn).*(?:not supported|unsupported|disabled|forcing off)", lower):
                flash = "disabled"
            elif re.search(r"flash[ _-](?:attention|attn).*\benabled\b", lower):
                flash = "enabled"
    return {
        "flash_attention_env": OLLAMA_SERVER_ENV.get("OLLAMA_FLASH_ATTENTION", "unknown (external server)"),
        "kv_cache_env": OLLAMA_SERVER_ENV.get("OLLAMA_KV_CACHE_TYPE", "unknown (external server)"),
        "server_mode": OLLAMA_SERVER_MODE,
        "runtime_kv_cache": kv,
        "runtime_flash_attention": flash,
    }


def warn_ollama_runtime_fallback() -> None:
    global _OLLAMA_LAST_WARNING
    env = server_inference_environment()
    kv, flash = env["runtime_kv_cache"], env["runtime_flash_attention"]
    if env["server_mode"] != "managed":
        return
    if kv not in {"unknown", DEFAULT_KV_CACHE_TYPE} or flash == "disabled":
        warning = f"Q8 KV cache could not be confirmed: runtime KV={kv}, Flash Attention={flash}."
        if warning != _OLLAMA_LAST_WARNING:
            ui_warn(warning + " Check /inference and the Ollama log for backend support.")
            _OLLAMA_LAST_WARNING = warning


def print_inference_settings() -> None:
    env = server_inference_environment()
    status_line("Ollama server", env["server_mode"], C.WHITE)
    status_line("Ollama URL", OLLAMA_BASE, C.WHITE)
    status_line("KV requested", DEFAULT_KV_CACHE_TYPE, C.WHITE)
    status_line("KV launch", env["kv_cache_env"], C.WHITE)
    status_line("KV runtime", env["runtime_kv_cache"], C.WHITE)
    status_line("Flash launch", env["flash_attention_env"], C.WHITE)
    status_line("Flash runtime", env["runtime_flash_attention"], C.WHITE)
    if env["server_mode"] == "managed":
        status_line("Ollama log", str(_OLLAMA_LOG_PATH), C.BRIGHT_BLACK)
        if env["runtime_kv_cache"] == "unknown":
            ui_warn("Q8 requested at server launch; runtime allocation is not yet confirmed in the log.")
        warn_ollama_runtime_fallback()
    else:
        ui_warn("External server settings cannot be verified from Pygent's environment.")
        ui_warn("Start that server with OLLAMA_KV_CACHE_TYPE=q8_0 and OLLAMA_FLASH_ATTENTION=1, then restart it.")


def estimated_kv_bytes_per_token() -> int:
    """
    V5 improves V4's estimate for hybrid Qwen3.5-like architectures.

    If model metadata identifies recurrent layers, only non-recurrent
    full-attention layers grow a normal K/V cache with sequence length.
    """
    data = model_show_data()
    info = data.get("model_info", {}) if isinstance(data, dict) else {}
    if not isinstance(info, dict):
        return 96 * 1024

    arch = str(info.get("general.architecture", "")).strip()
    prefixes = [arch] if arch else []
    prefixes += [
        str(k).split(".block_count", 1)[0]
        for k in info
        if str(k).endswith(".block_count")
    ]

    for prefix in dict.fromkeys(x for x in prefixes if x):
        try:
            layers = int(info[f"{prefix}.block_count"])
            embed = int(info[f"{prefix}.embedding_length"])
            heads = int(info[f"{prefix}.attention.head_count"])
            kv_heads = int(info.get(f"{prefix}.attention.head_count_kv", heads))

            recurrent = info.get(f"{prefix}.recurrent_layers")
            if isinstance(recurrent, list) and recurrent:
                attention_layers = sum(1 for x in recurrent if not bool(x))
                if attention_layers > 0:
                    layers = attention_layers

            # Qwen3.5 metadata may expose explicit K/V lengths.
            key_len = info.get(f"{prefix}.attention.key_length")
            val_len = info.get(f"{prefix}.attention.value_length")
            if key_len is not None and val_len is not None:
                raw = layers * kv_heads * (int(key_len) + int(val_len)) * 2.0
            else:
                head_dim = embed / heads
                raw = 2.0 * layers * kv_heads * head_dim * 2.0

            # Keep F16 budgeting until this model's managed runner actually
            # allocates both caches as Q8. Q8_0 stores 34 bytes per 32 values,
            # compared with F16's 64 bytes (including Q8 block scale overhead).
            env = server_inference_environment()
            if env["runtime_kv_cache"] == "q8_0" and env["runtime_flash_attention"] != "disabled":
                raw *= 34.0 / 64.0

            return max(8 * 1024, int(raw * 1.15))
        except Exception:
            continue

    return 96 * 1024


# ------------------------------- result store --------------------------------

def _next_result_id() -> str:
    global RESULT_COUNTER
    with _RESULT_STATE_LOCK:
        RESULT_COUNTER += 1
        return f"R{RESULT_COUNTER:06d}"


def _result_paths(result_id: str) -> Tuple[Path, Path]:
    rid = re.sub(r"[^A-Za-z0-9_-]", "", result_id.upper())
    return RESULTS_DIR / f"{rid}.txt", RESULTS_DIR / f"{rid}.json"


def _extract_diagnostic_lines(text: str, max_lines: int = 28) -> List[str]:
    patterns = (
        "error", "exception", "traceback", "failed", "failure", "fatal",
        "warning", "assert", "syntaxerror", "typeerror", "valueerror",
        "filenotfound", "permission", "exit_code:",
    )
    out: List[str] = []
    seen = set()
    for line in text.splitlines():
        low = line.lower()
        if any(p in low for p in patterns):
            s = line.rstrip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= max_lines:
                break
    return out


def store_full_result(
    *,
    tool_name: str,
    raw_result: str,
    args: Dict[str, Any],
    kind: str = "tool_result",
) -> str:
    ensure_agent_dir()
    rid = _next_result_id()
    text_path, meta_path = _result_paths(rid)

    with text_path.open("w", encoding="utf-8", newline="") as sink:
        sink.write(raw_result)
    register_stored_result(rid, tool_name, args, len(raw_result), len(raw_result.splitlines()), kind)
    return rid


def register_stored_result(
    rid: str, tool_name: str, args: Dict[str, Any], chars: int,
    lines: int, kind: str = "tool_result",
) -> None:
    _text_path, meta_path = _result_paths(rid)
    meta = {
        "id": rid,
        "time": time.time(),
        "kind": kind,
        "tool": tool_name,
        "chars": chars,
        "lines": lines,
        "args": {
            k: (f"<{len(str(v))} chars>" if k in {"content", "old_text", "new_text", "text"} else v)
            for k, v in args.items()
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    with _RESULT_STATE_LOCK:
        SESSION_LEDGER["results"] = _bounded_unique(
            list(SESSION_LEDGER.get("results", [])) + [rid],
            40,
        )
        save_ledger()
        _cleanup_old_result_files()


def _cleanup_old_result_files() -> None:
    if MAX_RESULT_FILES <= 0:
        return
    try:
        metas = sorted(
            RESULTS_DIR.glob("R*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for meta_path in metas[MAX_RESULT_FILES:]:
            txt = meta_path.with_suffix(".txt")
            try:
                meta_path.unlink()
            except Exception:
                pass
            try:
                txt.unlink()
            except Exception:
                pass
    except Exception:
        pass


def compact_result_for_model(
    tool_name: str,
    raw_result: str,
    args: Dict[str, Any],
) -> str:
    limit = RESULT_INLINE_LIMIT
    if tool_name == "run_command":
        limit = COMMAND_INLINE_LIMIT
    elif tool_name in {"read_file", "read_symbol"}:
        limit = SOURCE_INLINE_LIMIT

    if len(raw_result) <= limit:
        return raw_result

    rid = store_full_result(
        tool_name=tool_name,
        raw_result=raw_result,
        args=args,
    )
    lines = raw_result.splitlines()
    diagnostics = _extract_diagnostic_lines(raw_result)

    head_count = 42 if tool_name in {"read_file", "read_symbol"} else 20
    tail_count = 20
    head = lines[:head_count]
    tail = lines[-tail_count:] if len(lines) > head_count else []

    parts = [
        f"RESULT STORED: {rid}",
        f"tool={tool_name}; full_chars={len(raw_result):,}; full_lines={len(lines):,}",
        "The complete lossless result is stored locally. Use read_result if more is needed.",
    ]

    def preview(selected: List[str]) -> str:
        text = "\n".join(selected)
        cap = limit // 3
        return text if len(text) <= cap else text[:cap] + "\n[preview ends; exact continuation is stored]"

    if diagnostics:
        parts += ["", "Relevant diagnostics:", preview(diagnostics[:28])]

    if head:
        parts += ["", f"First {len(head)} lines (preview):", preview(head)]
    if tail:
        parts += ["", f"Last {len(tail)} lines (preview):", preview(tail)]

    return "\n".join(parts)


def tool_read_result(
    result_id: str, start_line: int = 1, end_line: int = 0,
    query: str = "", reason: str = "", start_char: int = -1,
    max_chars: int = 10_000,
) -> str:
    """Page exact disk results without loading a large command transcript."""
    try:
        text_path, meta_path = _result_paths(result_id)
        if not text_path.exists():
            return f"ERROR: Stored result not found: {result_id}"
        meta = load_json(meta_path, {})
        heading = f"RESULT: {result_id} ({meta.get('tool', 'unknown')})"
        budget = max(256, min(int(max_chars), 16_000))
        with text_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            if int(start_char) >= 0:
                skip = int(start_char)
                remaining = skip
                while remaining:
                    discarded = f.read(min(65_536, remaining))
                    if not discarded:
                        break
                    remaining -= len(discarded)
                chunk = f.read(budget)
                actual_start = skip - remaining
                return (heading + f"\nCHARACTERS: {actual_start}-{actual_start+len(chunk)} (zero-based)"
                        + f"\nNext page: start_char={actual_start+len(chunk)}\n" + chunk)
            start = max(1, int(start_line))
            end = start + RESULT_PAGE_LINES - 1
            if int(end_line) > 0:
                end = min(end, max(start, int(end_line)))
            selected: List[str] = []
            chars = 0
            offset = 0
            first_offset = 0
            for number, line in enumerate(f, 1):
                line_offset = offset
                offset += len(line)
                if query:
                    if query.lower() not in line.lower():
                        continue
                elif number < start:
                    continue
                elif number > end:
                    break
                if not selected:
                    first_offset = line_offset
                if chars + len(line) > budget:
                    if not selected:
                        f.seek(0)
                        # Reuse character paging to return the exact beginning
                        # of an oversized line and an offset for its remainder.
                        return tool_read_result(result_id, start_char=first_offset, max_chars=budget)
                    break
                rendered = f"{number:>5} | {line.rstrip(chr(10))}"
                selected.append(rendered)
                chars += len(rendered)
                if query and len(selected) >= 120:
                    break
            label = f"QUERY: {query}" if query else f"LINES: from {start} of {meta.get('lines', '?')}"
            return heading + "\n" + label + "\n" + ("\n".join(selected) or "(no matches or end of result)")
    except Exception as e:
        return f"ERROR: {e}"



# ------------------------------ smart source read ----------------------------

def tool_read_file(
    path: str,
    start_line: int = 1,
    end_line: int = 0,
    reason: str = "",
) -> str:
    # Default reads are smaller in V5. Explicit ranges are respected up to the
    # V4 safety ceiling, then losslessly paged by compact_result_for_model.
    if int(end_line or 0) <= 0:
        end_line = int(start_line) + SMART_READ_DEFAULT_LINES - 1
    return _V4_TOOL_READ_FILE(
        path=path,
        start_line=start_line,
        end_line=end_line,
        reason=reason,
    )


def tool_read_symbol(
    path: str,
    symbol: str,
    reason: str = "",
) -> str:
    try:
        p = resolve_path(path)
        if not p.is_file():
            return f"ERROR: Not a file: {path}"
        if is_probably_binary(p):
            return f"ERROR: {project_relative(p)} appears binary."

        text = p.read_text(encoding="utf-8", errors="replace")
        rel = project_relative(p)

        if p.suffix.lower() in {".py", ".pyw"}:
            try:
                tree = ast.parse(text)
                wanted = symbol.strip()
                candidates: List[Tuple[str, int, int]] = []

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = getattr(node, "name", "")
                        end = int(getattr(node, "end_lineno", node.lineno))
                        candidates.append((name, int(node.lineno), end))

                exact = [x for x in candidates if x[0] == wanted]
                if len(exact) == 1:
                    name, start, end = exact[0]
                    return _V4_TOOL_READ_FILE(rel, start, end, reason)
                if len(exact) > 1:
                    return f"ERROR: Symbol '{symbol}' is ambiguous in {rel}."

                partial = [x for x in candidates if wanted.lower() in x[0].lower()]
                if len(partial) == 1:
                    name, start, end = partial[0]
                    return _V4_TOOL_READ_FILE(rel, start, end, reason)
            except Exception:
                pass

        # Generic fallback: locate a definition-like line and read a focused
        # window. This is retrieval, not summarization, so the source remains exact.
        patterns = [
            rf"\bclass\s+{re.escape(symbol)}\b",
            rf"\bdef\s+{re.escape(symbol)}\b",
            rf"\bfunction\s+{re.escape(symbol)}\b",
            rf"\bfn\s+{re.escape(symbol)}\b",
            rf"\b{re.escape(symbol)}\s*\(",
        ]
        lines = text.splitlines()
        hits: List[int] = []
        for i, line in enumerate(lines, 1):
            if any(re.search(pat, line) for pat in patterns):
                hits.append(i)

        if len(hits) == 1:
            start = max(1, hits[0] - 12)
            end = min(len(lines), hits[0] + 180)
            return _V4_TOOL_READ_FILE(rel, start, end, reason)
        if not hits:
            return f"ERROR: Symbol '{symbol}' was not found in {rel}."
        return f"ERROR: Symbol '{symbol}' matched multiple locations in {rel}: {hits[:12]}"
    except Exception as e:
        return f"ERROR: {e}"


# Register V5 read tools.
FUNCTIONS["read_file"] = tool_read_file
FUNCTIONS["read_symbol"] = tool_read_symbol
FUNCTIONS["read_result"] = tool_read_result


# ------------------------ tool capability profiles ---------------------------

def _schema_by_name() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in TOOLS:
        try:
            name = item["function"]["name"]
            out[name] = item
        except Exception:
            pass
    return out


# Capture V4 schemas before replacing TOOLS.
_V4_TOOL_SCHEMAS = _schema_by_name()

READ_SYMBOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_symbol",
        "description": "Read one function/class/symbol from a source file without loading the entire file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "symbol": {"type": "string"},
                "reason": reason_property(),
            },
            "required": ["path", "symbol"],
        },
    },
}

READ_RESULT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_result",
        "description": "Page or search a complete lossless tool result previously stored as R######. Use start_char for huge single lines.",
        "parameters": {
            "type": "object",
            "properties": {
                "result_id": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "query": {"type": "string"},
                "start_char": {"type": "integer", "description": "Zero-based character offset for exact pages of very long lines; omit for line paging."},
                "max_chars": {"type": "integer", "description": "Character-page size, capped at 16000."},
                "reason": reason_property(),
            },
            "required": ["result_id"],
        },
    },
}

def tool_request_capabilities(
    profile: str,
    reason: str = "",
) -> str:
    global REQUESTED_TOOL_PROFILE
    profile = str(profile).strip().lower()
    if profile not in {"explore", "edit", "validate", "full"}:
        return "ERROR: profile must be explore, edit, validate, or full."
    REQUESTED_TOOL_PROFILE = profile
    return f"Capability profile '{profile}' requested for the next model step."


REQUEST_CAP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "request_capabilities",
        "description": "Request a broader or different tool capability profile for the next model step.",
        "parameters": {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "enum": ["explore", "edit", "validate", "full"],
                },
                "reason": reason_property(),
            },
            "required": ["profile"],
        },
    },
}
FUNCTIONS["request_capabilities"] = tool_request_capabilities


def _tool_schema(name: str) -> Dict[str, Any]:
    if name == "read_symbol":
        return READ_SYMBOL_SCHEMA
    if name == "read_result":
        return READ_RESULT_SCHEMA
    if name == "request_capabilities":
        return REQUEST_CAP_SCHEMA
    return _V4_TOOL_SCHEMAS[name]


# The harness advances routine task status from actual tool activity.
# The full profile retains update_task for explicit plan corrections.
CORE_TOOL_NAMES = [
    "set_task_plan",
    "repo_map",
    "list_files",
    "find_files",
    "search_text",
    "read_file",
    "read_symbol",
    "read_result",
    "project_info",
    "request_capabilities",
]

EDIT_TOOL_NAMES = CORE_TOOL_NAMES + [
    "write_file",
    "edit_file",
    "replace_lines",
    "insert_text",
    "make_directory",
    "delete_file",
]

VALIDATE_TOOL_NAMES = EDIT_TOOL_NAMES + [
    "run_command",
    "git_status",
    "git_diff",
]

FULL_TOOL_NAMES = list(_V4_TOOL_SCHEMAS)  # Includes task corrections on escalation.
for extra in ("read_symbol", "read_result", "request_capabilities"):
    if extra not in FULL_TOOL_NAMES:
        FULL_TOOL_NAMES.append(extra)

TOOL_PROFILES: Dict[str, List[Dict[str, Any]]] = {
    "explore": [_tool_schema(n) for n in CORE_TOOL_NAMES],
    "edit": [_tool_schema(n) for n in EDIT_TOOL_NAMES],
    "validate": [_tool_schema(n) for n in VALIDATE_TOOL_NAMES],
    "full": [_tool_schema(n) for n in FULL_TOOL_NAMES],
}

# Compatibility: global TOOLS is the current profile, not the giant all-tool list.
TOOLS = TOOL_PROFILES[ACTIVE_TOOL_PROFILE]


def tools_for_profile(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    p = profile or ACTIVE_TOOL_PROFILE
    return TOOL_PROFILES.get(p, TOOL_PROFILES["full"])


def select_initial_tool_profile(user_text: str) -> str:
    low = user_text.lower()

    validate_words = (
        "run test", "run the test", "test it", "build it", "compile",
        "lint", "pytest", "execute", "run this", "run the program",
    )
    edit_words = (
        "fix", "change", "modify", "edit", "add ", "implement", "create",
        "refactor", "remove", "rename", "update", "make ", "write ",
    )
    explore_words = (
        "explain", "inspect", "find", "where", "what does", "how does",
        "understand", "review", "analyze", "look through",
    )

    if any(x in low for x in validate_words):
        return "validate"
    if any(x in low for x in edit_words):
        return "edit"
    if any(x in low for x in explore_words):
        return "explore"
    return "edit"


def set_tool_profile(profile: str, announce: bool = False) -> None:
    global ACTIVE_TOOL_PROFILE, TOOLS
    profile = profile if profile in TOOL_PROFILES else "full"
    if profile == ACTIVE_TOOL_PROFILE:
        TOOLS = TOOL_PROFILES[profile]
        return
    ACTIVE_TOOL_PROFILE = profile
    TOOLS = TOOL_PROFILES[profile]
    if announce:
        ui_success(f"Tool profile → {profile}")


# ------------------------ stable-prefix request layout ------------------------

def runtime_state_message() -> str:
    task_lines = []
    for i, task in enumerate(TASKS[:10], 1):
        task_lines.append(
            f"{i}. [{task.get('status', 'pending')}] {task.get('title', '')}"
            + (f" — {task.get('note', '')}" if task.get("note") else "")
        )

    ledger = SESSION_LEDGER
    state = [
        "<runtime_state>",
        f"project={PROJECT_ROOT}",
        f"git_branch={get_git_branch() or '(none)'}",
        f"context={CONTEXT_SIZE}; profile={ACTIVE_TOOL_PROFILE}; auto_compact={AUTO_COMPACT_ENABLED}",
        f"compaction_generation={COMPACTION_GENERATION}",
    ]

    if ledger.get("current_goal"):
        state.append("current_goal=" + short_text(ledger["current_goal"], 500))
    if task_lines:
        state.append("tasks:\n" + "\n".join(task_lines))
    if ledger.get("modified_files"):
        state.append("modified_files=" + ", ".join(ledger["modified_files"][-12:]))
    if ledger.get("read_files"):
        state.append("recently_read=" + ", ".join(ledger["read_files"][-12:]))
    if ledger.get("tests"):
        state.append("recent_tests=" + " | ".join(ledger["tests"][-5:]))
    if ledger.get("errors"):
        state.append("recent_errors=" + " | ".join(ledger["errors"][-4:]))
    if ledger.get("results"):
        state.append("stored_results=" + ", ".join(ledger["results"][-12:]))

    state.append("</runtime_state>")
    return "\n".join(state)


def prepare_request_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    V5 keeps the longest possible prefix immutable for Ollama prompt caching.

    Stable system prompt and transcript come first. Dynamic compacted memory and
    runtime state are appended at the end, so changing task status does not
    invalidate the entire earlier prompt prefix.
    """
    if not messages:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    result = list(messages)

    if COMPACTED_MEMORY.strip():
        result.append({
            "role": "system",
            "content": (
                "<compacted_session_memory>\n"
                + COMPACTED_MEMORY.strip()
                + "\n</compacted_session_memory>"
            ),
        })

    result.append({"role": "system", "content": runtime_state_message()})
    return result


def estimate_request_tokens(
    messages: List[Dict[str, Any]],
    include_tools: bool = True,
    profile: Optional[str] = None,
) -> int:
    prepared = prepare_request_messages(messages)
    total = _rough_tokens(prepared)
    if include_tools:
        total += _rough_tokens(tools_for_profile(profile))
    return total + 96


# -------------------- smallest-context-that-fits policy ----------------------

def _context_headroom_for(size: int) -> int:
    return max(
        V5_CONTEXT_HEADROOM_MIN,
        min(V5_CONTEXT_HEADROOM_MAX, int(size * V5_CONTEXT_HEADROOM_RATIO)),
    )


def _required_context_tokens(messages: List[Dict[str, Any]], profile: Optional[str] = None) -> int:
    request = estimate_request_tokens(messages, include_tools=True, profile=profile)
    # Reserve output/tool-call room independent of current context size.
    completion = max(900, min(2600, int(request * 0.16)))
    return request + completion + _context_headroom_for(max(CONTEXT_MIN, request))


def _safe_context_ceiling_from_resources() -> int:
    return effective_context_ceiling()


def choose_context_tier(messages: List[Dict[str, Any]], profile: Optional[str] = None) -> int:
    required = _required_context_tokens(messages, profile)
    ceiling = _safe_context_ceiling_from_resources()
    candidates = [x for x in CONTEXT_STEPS if CONTEXT_MIN <= x <= ceiling]
    if not candidates:
        return min(max(CONTEXT_MIN, CONTEXT_SIZE), ceiling)

    for tier in candidates:
        if tier >= required:
            return tier
    return candidates[-1]


def _ram_allows_context_growth(new_size: int) -> bool:
    if new_size <= CONTEXT_SIZE:
        return True

    snap = RESOURCE_MONITOR.snapshot()
    total = int(snap.get("total", 0))
    avail = int(snap.get("stable_available", snap.get("available", 0)))
    if total <= 0 or avail <= 0:
        return False

    delta_tokens = max(0, new_size - CONTEXT_SIZE)
    estimated_extra = delta_tokens * estimated_kv_bytes_per_token()

    # Preserve a large Windows/Ollama safety margin on an 8 GB system.
    safety = max(900 * 1024 * 1024, int(total * 0.12))
    return (avail - estimated_extra) >= safety


def maybe_auto_tune_context(
    messages: List[Dict[str, Any]],
    allow_increase: bool = True,
) -> bool:
    global CONTEXT_SIZE, LAST_CONTEXT_CHANGE_AT, LAST_CONTEXT_EVENT

    if not AUTO_CONTEXT_ENABLED or CONTEXT_MODE != "auto":
        return False

    now = time.time()
    if now - LAST_CONTEXT_CHANGE_AT < V5_CONTEXT_DOWNSHIFT_COOLDOWN:
        return False

    ideal = choose_context_tier(messages, ACTIVE_TOOL_PROFILE)
    old = CONTEXT_SIZE

    # V5 can both grow and shrink. Shrinking avoids paying KV/prompt overhead
    # for a context size that is not currently needed.
    if ideal > old:
        if not allow_increase or not _ram_allows_context_growth(ideal):
            return False
        CONTEXT_SIZE = ideal
        LAST_CONTEXT_EVENT = f"V5 latency policy increased context {old:,} → {ideal:,}"
    elif ideal < old:
        CONTEXT_SIZE = ideal
        LAST_CONTEXT_EVENT = f"V5 latency policy reduced context {old:,} → {ideal:,}"
    else:
        return False

    LAST_CONTEXT_CHANGE_AT = now
    save_config()
    return True


# --------------------------- harness-owned ledger ----------------------------

def _ledger_add(key: str, value: str, limit: int) -> None:
    current = SESSION_LEDGER.get(key, [])
    if not isinstance(current, list):
        current = []
    SESSION_LEDGER[key] = _bounded_unique(current + [str(value)], limit)


def update_ledger_after_tool(
    name: str,
    args: Dict[str, Any],
    raw_result: str,
    model_result: str,
) -> None:
    SESSION_LEDGER["last_tool"] = name
    SESSION_LEDGER["last_activity"] = time.time()

    path = str(args.get("path", "") or "")
    if name in {"read_file", "read_symbol"} and path and not raw_result.startswith("ERROR:"):
        _ledger_add("read_files", path, 30)

    if name in {
        "write_file", "edit_file", "replace_lines",
        "insert_text", "delete_file", "make_directory",
    } and path and not raw_result.startswith("ERROR:") and "denied by user" not in raw_result.lower():
        _ledger_add("modified_files", path, 30)

    if name == "run_command":
        cmd = str(args.get("command", ""))
        if cmd:
            _ledger_add("commands", short_text(cmd, 300), 18)

        m = re.match(r"exit_code:\s*(-?\d+)", raw_result)
        code = int(m.group(1)) if m else None
        if code is not None:
            record = f"{cmd} → exit {code}"
            if re.search(r"\b(?:pytest|unittest|test|tests|build|compile|py_compile|compileall|lint|ruff|mypy|tsc|check)\b", cmd, re.I):
                _ledger_add("tests", short_text(record, 380), 12)
            if code != 0:
                diagnostics = _extract_diagnostic_lines(raw_result, 4)
                _ledger_add(
                    "errors",
                    short_text(" | ".join(diagnostics) if diagnostics else record, 600),
                    10,
                )

    if raw_result.startswith("ERROR:"):
        _ledger_add("errors", short_text(f"{name}: {raw_result}", 650), 10)

    rid_match = re.search(r"\bR\d{6}\b", model_result)
    if rid_match:
        _ledger_add("results", rid_match.group(0), 40)

    save_ledger()


def _task_keyword_match(title: str, phase: str) -> bool:
    low = title.lower()
    words = {
        "explore": ("inspect", "find", "locate", "understand", "review", "reproduce", "analyze"),
        "edit": ("fix", "change", "implement", "edit", "refactor", "add", "create", "update"),
        "validate": ("test", "validate", "verify", "run", "build", "lint", "check"),
    }[phase]
    return any(w in low for w in words)


def auto_task_progress(tool_name: str, result: str) -> None:
    if not TASKS or tool_name in {"set_task_plan", "request_capabilities"}:
        return

    phase = (
        "validate" if tool_name in {"run_command", "git_status", "git_diff"}
        else "edit" if tool_name in {
            "write_file", "edit_file", "replace_lines", "insert_text",
            "make_directory", "delete_file",
        }
        else "explore"
    )

    target = None
    for i, task in enumerate(TASKS):
        if task.get("status") in {"pending", "in_progress", "blocked"} and _task_keyword_match(task.get("title", ""), phase):
            target = i
            break

    if target is None:
        for i, task in enumerate(TASKS):
            if task.get("status") in {"pending", "in_progress"}:
                target = i
                break

    if target is None:
        return

    # Earlier unfinished steps are considered complete only when advancing into
    # a later concrete phase. This avoids a separate model round trip merely to
    # update the checklist.
    exit_match = re.match(r"exit_code:\s*(-?\d+)", result) if tool_name == "run_command" else None
    failed = (result.startswith("ERROR:") or "denied by user" in result.lower()
              or "cancelled: true" in result.lower()
              or (exit_match is not None and int(exit_match.group(1)) != 0))
    if phase in {"edit", "validate"} and not failed:
        for i in range(target):
            if TASKS[i].get("status") in {"pending", "in_progress"}:
                TASKS[i]["status"] = "done"

    for i, task in enumerate(TASKS):
        if i != target and task.get("status") == "in_progress":
            task["status"] = "pending"

    TASKS[target]["status"] = "blocked" if failed else "in_progress"

    if phase == "validate" and not failed and exit_match is not None and int(exit_match.group(1)) == 0:
        TASKS[target]["status"] = "done"

    render_tasks()


def finalize_tasks_after_answer(answer: str) -> None:
    if not TASKS:
        return

    low = answer.lower()
    clearly_blocked = any(
        x in low for x in (
            "could not complete", "unable to complete", "still failing",
            "remaining issue", "blocked by",
        )
    )

    for task in TASKS:
        if task.get("status") == "in_progress":
            task["status"] = "blocked" if clearly_blocked else "done"
            break


# -------------------------- parallel tool execution --------------------------

PARALLEL_SAFE_TOOLS = {
    "project_info",
    "list_files",
    "find_files",
    "search_text",
    "read_file",
    "read_symbol",
    "read_result",
    "git_status",
    "git_diff",
}


def _invoke_tool_quiet(name: str, args: Dict[str, Any]) -> Tuple[str, float]:
    func = FUNCTIONS.get(name)
    if not func:
        return f"ERROR: Unknown tool: {name}", 0.0

    started = time.time()
    try:
        result = func(**args)
    except TypeError as e:
        result = f"ERROR: Bad arguments for {name}: {e}"
    except Exception as e:
        result = f"ERROR: Tool failed: {e}"
    return result, time.time() - started


def _finalize_tool_execution(
    name: str,
    args: Dict[str, Any],
    raw_result: str,
    elapsed: float,
) -> str:
    model_result = compact_result_for_model(name, raw_result, args)
    update_ledger_after_tool(name, args, raw_result, model_result)
    auto_task_progress(name, raw_result)
    display_tool_result(name, raw_result, elapsed)
    return model_result


def execute_tool_calls_batch(
    calls: List[Dict[str, Any]],
) -> List[Tuple[Dict[str, Any], str, str]]:
    """
    Execute independent read-only tool calls concurrently while preserving the
    model's original result order.

    Unsafe/mutating calls remain sequential. Consecutive read-only calls are
    grouped into one small thread pool.
    """
    global TURN_TOOL_COUNT, REQUESTED_TOOL_PROFILE
    batch_started = time.monotonic()

    output: List[Tuple[Dict[str, Any], str, str]] = []
    i = 0

    while i < len(calls):
        name, args = parse_tool_args(calls[i])

        if "_invalid_raw_arguments" in args:
            TURN_TOOL_COUNT += 1
            display_tool_call(TURN_TOOL_COUNT, name, args)
            raw = f"ERROR: Invalid tool arguments: {args['_invalid_raw_arguments']}"
            model_result = _finalize_tool_execution(name, args, raw, 0.0)
            output.append((calls[i], name, model_result))
            i += 1
            continue

        if name in PARALLEL_SAFE_TOOLS:
            group: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
            j = i
            while j < len(calls):
                n, a = parse_tool_args(calls[j])
                if n not in PARALLEL_SAFE_TOOLS or "_invalid_raw_arguments" in a:
                    break
                group.append((calls[j], n, a))
                j += 1

            # Show the batch before execution so the user can see exactly what
            # the agent is doing.
            for _call, n, a in group:
                TURN_TOOL_COUNT += 1
                display_tool_call(TURN_TOOL_COUNT, n, a)

            workers = min(TOOL_PARALLELISM, len(group))
            if len(group) > 1:
                ui_success(f"Parallel read batch · {len(group)} tools / {workers} workers")

            if workers <= 1:
                completed = [_invoke_tool_quiet(group[0][1], group[0][2])]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [
                        pool.submit(_invoke_tool_quiet, n, a)
                        for _call, n, a in group
                    ]
                    completed = [f.result() for f in futures]

            for (call, n, a), (raw, elapsed) in zip(group, completed):
                model_result = _finalize_tool_execution(n, a, raw, elapsed)
                output.append((call, n, model_result))

            i = j
            continue

        # Sequential unsafe/mutating tool.
        TURN_TOOL_COUNT += 1
        display_tool_call(TURN_TOOL_COUNT, name, args)
        raw, elapsed = _invoke_tool_quiet(name, args)
        model_result = _finalize_tool_execution(name, args, raw, elapsed)
        output.append((calls[i], name, model_result))
        i += 1

    if REQUESTED_TOOL_PROFILE:
        set_tool_profile(REQUESTED_TOOL_PROFILE, announce=True)
        REQUESTED_TOOL_PROFILE = None

    if PERF_HISTORY:
        sample = PERF_HISTORY[-1]
        event = {"kind": "tool_batch", "request_id": sample.get("request_id"),
                 "tool_wall_s": time.monotonic() - batch_started, "tool_calls": len(output)}
        sample.update({k: event[k] for k in ("tool_wall_s", "tool_calls")})
        try:
            with PERF_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError:
            pass

    return output


# ---------------------- cheap mechanical compaction --------------------------

def compact_model_call(previous: str, chunk: str, target_tokens: int) -> str:
    """Semantic compaction call with the same warm model lease as normal chat."""
    prompt = (
        "PREVIOUS CHECKPOINT:\n"
        + (previous.strip() if previous.strip() else "(none)")
        + "\n\nNEW HISTORY TO MERGE:\n"
        + chunk.strip()
        + "\n\nUpdate the checkpoint with all information that remains necessary."
    )
    payload = {
        "model": CURRENT_MODEL,
        "messages": [
            {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "keep_alive": MODEL_KEEP_ALIVE,
        "options": {
            "num_ctx": CONTEXT_SIZE,
            "temperature": 0.0,
            "num_predict": int(target_tokens),
        },
    }
    data = ollama_request_json(CHAT_URL, method="POST", payload=payload, timeout=600)
    msg = data.get("message", {}) if isinstance(data, dict) else {}
    return str(msg.get("content", "")).strip()


def _archive_large_tool_call_args(call: Dict[str, Any]) -> Dict[str, Any]:
    cloned = json.loads(json.dumps(call))
    fn = cloned.get("function", {}) or {}
    args = fn.get("arguments", {}) or {}

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return cloned

    if not isinstance(args, dict):
        return cloned

    changed = False
    for key in ("content", "old_text", "new_text", "text"):
        value = args.get(key)
        if isinstance(value, str) and len(value) > MECHANICAL_TOOL_ARG_LIMIT:
            args[key] = f"<archived completed tool argument: {len(value):,} chars>"
            changed = True

    if changed:
        fn["arguments"] = args
    return cloned


def mechanical_compact_history(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    systems, groups = split_turn_groups(messages)
    if len(groups) <= MECHANICAL_KEEP_RECENT_GROUPS:
        return messages, False

    changed = False
    keep_start = max(0, len(groups) - MECHANICAL_KEEP_RECENT_GROUPS)
    new_groups: List[List[Dict[str, Any]]] = []

    for gi, group in enumerate(groups):
        if gi >= keep_start:
            new_groups.append(group)
            continue

        ng: List[Dict[str, Any]] = []
        for msg in group:
            role = msg.get("role")

            if role == "assistant" and msg.get("tool_calls"):
                nm = dict(msg)
                nm["tool_calls"] = [
                    _archive_large_tool_call_args(c)
                    for c in (msg.get("tool_calls") or [])
                ]
                if nm["tool_calls"] != msg.get("tool_calls"):
                    changed = True
                ng.append(nm)
                continue

            if role == "tool":
                content = str(msg.get("content", ""))
                if len(content) > MECHANICAL_TOOL_RESULT_LIMIT:
                    rid = store_full_result(
                        tool_name=str(msg.get("tool_name", "historical_tool")),
                        raw_result=content,
                        args={},
                        kind="historical_tool_result",
                    )
                    nm = dict(msg)
                    nm["content"] = (
                        f"Historical tool result archived as {rid}; "
                        f"{len(content):,} chars. Use read_result if exact older output is needed."
                    )
                    ng.append(nm)
                    changed = True
                    continue

            ng.append(msg)

        new_groups.append(ng)

    result = list(systems)
    for group in new_groups:
        result.extend(group)
    return result, changed


def _tool_heaviness(messages: List[Dict[str, Any]]) -> float:
    if not messages:
        return 0.0
    toolish = 0
    for m in messages:
        if m.get("role") == "tool" or m.get("tool_calls"):
            toolish += 1
    return toolish / len(messages)


def deterministic_ledger_checkpoint(old_messages: List[Dict[str, Any]]) -> str:
    user_texts = [
        str(m.get("content", ""))
        for m in old_messages
        if m.get("role") == "user" and str(m.get("content", "")).strip()
    ]
    assistant_texts = [
        str(m.get("content", ""))
        for m in old_messages
        if m.get("role") == "assistant"
        and str(m.get("content", "")).strip()
        and not m.get("tool_calls")
    ]

    parts = [
        "V5 deterministic checkpoint.",
        "Harness ledger is authoritative for concrete tool state.",
    ]
    if COMPACTED_MEMORY.strip():
        parts.append("Prior compacted memory:\n" + COMPACTED_MEMORY.strip())
    if SESSION_LEDGER.get("current_goal"):
        parts.append("Current goal: " + str(SESSION_LEDGER["current_goal"]))
    if user_texts:
        parts.append("Older user requests:\n- " + "\n- ".join(user_texts))
    if assistant_texts:
        parts.append("Older conclusions:\n- " + "\n- ".join(assistant_texts))
    if SESSION_LEDGER.get("modified_files"):
        parts.append("Modified files: " + ", ".join(SESSION_LEDGER["modified_files"][-20:]))
    if SESSION_LEDGER.get("tests"):
        parts.append("Recent validation: " + " | ".join(SESSION_LEDGER["tests"][-8:]))
    if SESSION_LEDGER.get("errors"):
        parts.append("Recent errors: " + " | ".join(SESSION_LEDGER["errors"][-6:]))

    result_ids = sorted(set(re.findall(r"\bR\d{6}\b", json.dumps(old_messages))))
    if result_ids:
        parts.append("Exact older results: " + ", ".join(result_ids))
    return "\n".join(parts)


def compact_session(
    messages: List[Dict[str, Any]],
    reason: str,
    force: bool = False,
) -> List[Dict[str, Any]]:
    global COMPACTED_MEMORY, COMPACTION_GENERATION, COMPACTION_COUNT, LAST_COMPACTION_AT

    before = estimate_request_tokens(messages, profile=ACTIVE_TOOL_PROFILE)

    # Tier 1: lossless mechanical shrinking of old tool payloads.
    mechanically, changed = mechanical_compact_history(messages)
    if changed:
        after_mech = estimate_request_tokens(mechanically, profile=ACTIVE_TOOL_PROFILE)
        if after_mech < context_trigger_tokens() and not force:
            ui_success(f"Mechanical compact · ~{before:,} → ~{after_mech:,} tokens · no model call")
            return mechanically
        messages = mechanically

    # Tier 2: if the old material is overwhelmingly tool chatter, build a
    # deterministic ledger checkpoint rather than spending a model call.
    keep = compact_keep_tokens()
    old_messages, active = select_compaction_split(messages, keep)

    checkpoint = deterministic_ledger_checkpoint(old_messages) if old_messages else ""
    if old_messages and _tool_heaviness(old_messages) >= 0.72 and len(checkpoint) <= 12_000:
        prior = COMPACTED_MEMORY
        COMPACTED_MEMORY = checkpoint
        COMPACTION_GENERATION += 1
        COMPACTION_COUNT += 1
        LAST_COMPACTION_AT = time.time()
        archive_compaction(
            old_messages,
            prior,
            COMPACTED_MEMORY,
            "V5 deterministic tool-heavy compaction: " + reason,
            before,
            estimate_request_tokens(active, profile=ACTIVE_TOOL_PROFILE),
        )
        ui_success(
            f"Deterministic compact checkpoint {COMPACTION_GENERATION} · no model call"
        )
        return active

    # Tier 3: V4's semantic hierarchical compactor for nuanced conversation.
    return _V4_COMPACT_SESSION(messages, reason, force)


def ensure_context_capacity(
    messages: List[Dict[str, Any]],
    reason: str,
) -> List[Dict[str, Any]]:
    # First pick the smallest context tier that comfortably fits.
    maybe_auto_tune_context(messages, allow_increase=True)

    used = estimate_request_tokens(messages, profile=ACTIVE_TOOL_PROFILE)
    trigger = context_trigger_tokens()

    if used >= int(trigger * MECHANICAL_COMPACT_TRIGGER_RATIO):
        mechanically, changed = mechanical_compact_history(messages)
        if changed:
            messages = mechanically
            used = estimate_request_tokens(messages, profile=ACTIVE_TOOL_PROFILE)

    # Re-evaluate tier after mechanical shrinking. This often permits a context
    # downshift, reducing memory and future prompt cost.
    maybe_auto_tune_context(messages, allow_increase=True)
    trigger = context_trigger_tokens()

    if AUTO_COMPACT_ENABLED and used >= trigger:
        return compact_session(
            messages,
            reason=f"{reason}: request estimate {used:,} reached trigger {trigger:,}",
            force=False,
        )

    hard_guard = CONTEXT_SIZE - max(512, output_reserve_tokens() // 2)
    if used >= hard_guard:
        return compact_session(
            messages,
            reason=f"emergency hard guard: {used:,} estimated tokens",
            force=True,
        )

    return messages


def prune_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return ensure_context_capacity(messages, "history maintenance")


# ------------------------------- warm model ---------------------------------

def _load_or_unload_model(keep_alive: Any) -> bool:
    global MODEL_WARM_STATE, _OLLAMA_LOG_MODEL
    requested_model = CURRENT_MODEL
    payload = {
        "model": requested_model,
        "messages": [],
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"num_ctx": CONTEXT_SIZE},
    }
    try:
        ollama_request_json(
            CHAT_URL,
            method="POST",
            payload=payload,
            timeout=300,
        )
        if requested_model == CURRENT_MODEL:
            MODEL_WARM_STATE = "unloaded" if keep_alive == 0 else "warm"
            if keep_alive == 0:
                _OLLAMA_LOG_MODEL = ""
        return True
    except Exception:
        return False


def warm_model_background() -> None:
    global _MODEL_WARM_THREAD, _MODEL_WARM_MODEL, MODEL_WARM_STATE
    if not WARM_MODEL_ON_START:
        return
    if _MODEL_WARM_THREAD and _MODEL_WARM_THREAD.is_alive():
        return

    MODEL_WARM_STATE = "warming"
    _MODEL_WARM_MODEL = CURRENT_MODEL

    def worker() -> None:
        global MODEL_WARM_STATE
        ok = _load_or_unload_model(MODEL_KEEP_ALIVE)
        if not ok and _MODEL_WARM_MODEL == CURRENT_MODEL:
            MODEL_WARM_STATE = "warm-up failed"

    _MODEL_WARM_THREAD = threading.Thread(target=worker, daemon=True)
    _MODEL_WARM_THREAD.start()


def unload_model() -> None:
    global MODEL_WARM_STATE
    if not RELEASE_MODEL_ON_EXIT:
        return
    if _load_or_unload_model(0):
        MODEL_WARM_STATE = "unloaded"


# -------------------------- streaming / cache metrics ------------------------

def stream_ollama_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    global MODEL_HAS_RUN, MODEL_WARM_STATE

    profile = ACTIVE_TOOL_PROFILE
    active_tools = tools_for_profile(profile)
    prepared = prepare_request_messages(messages)
    request_est = estimate_request_tokens(messages, profile=profile)
    schema_est = _rough_tokens(active_tools)
    begin_ollama_model_request(CURRENT_MODEL)

    payload = {
        "model": CURRENT_MODEL,
        "messages": prepared,
        "tools": active_tools,
        "stream": True,
        "keep_alive": MODEL_KEEP_ALIVE,
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
    started = time.time()

    got_visible_text = False
    saw_thinking = False
    thinking_chars = 0
    content_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    seen_calls: set[str] = set()
    final_meta: Dict[str, Any] = {}
    first_token_at: Optional[float] = None

    try:
        with ollama_urlopen(req, timeout=600) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue

                chunk = json.loads(raw_line.decode("utf-8"))
                if chunk.get("error"):
                    raise AgentError(str(chunk["error"]))
                message = chunk.get("message", {}) or {}
                if first_token_at is None and any(message.get(k) for k in ("content", "thinking", "tool_calls")):
                    first_token_at = time.time() - started

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
                    key = str(call.get("id")) if call.get("id") else json.dumps(call, sort_keys=True, ensure_ascii=False)
                    if key not in seen_calls:
                        seen_calls.add(key)
                        tool_calls.append(call)

                if chunk.get("done"):
                    final_meta = chunk

    except KeyboardInterrupt:
        spinner.stop()
        raise OperationCancelled("Model generation cancelled.")
    except urllib.error.HTTPError as e:
        spinner.stop()
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        raise AgentError(f"Ollama HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        spinner.stop()
        raise AgentError(
            f"Could not connect to Ollama at {OLLAMA_BASE}. Check /inference and the server log."
        ) from e
    finally:
        spinner.stop()

    if not final_meta:
        raise AgentError("Ollama stream ended before completion. Use /retry to retry this request.")

    MODEL_HAS_RUN = True
    MODEL_WARM_STATE = "warm"
    warn_ollama_runtime_fallback()

    if got_visible_text:
        print("\n")
    elif saw_thinking:
        print(
            color("  ◇ reasoning complete", C.BRIGHT_BLACK)
            + color(f"  ·  {thinking_chars:,} hidden chars", C.DIM)
        )

    perf = record_perf(
        dict(final_meta, ttft_s=first_token_at),
        profile=profile,
        wall_seconds=time.time() - started,
        request_estimate=request_est,
        tool_schema_tokens=schema_est,
    )

    return {
        "message": {
            "role": "assistant",
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
        },
        "_meta": final_meta,
        "_perf": perf,
    }


# -------------------------- phase/profile transitions ------------------------

def _transition_profile_after_tools(executed_names: List[str], results: List[str]) -> None:
    if not executed_names:
        return

    if any(n == "request_capabilities" for n in executed_names):
        return

    if any(n in {
        "write_file", "edit_file", "replace_lines", "insert_text",
        "make_directory", "delete_file",
    } for n in executed_names):
        # After a change, give the model validation tools for the next step.
        set_tool_profile("validate")
        return

    if ACTIVE_TOOL_PROFILE == "explore":
        # Stay explore until the model explicitly requests edit or the user's
        # original task was an edit task.
        return


# --------------------------- V5 system instructions --------------------------

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("Hyper-Cube Agent V4", "Hyper-Cube Agent V5") + """

V5 LATENCY DISCIPLINE
- Batch independent read-only investigations in the SAME response whenever the paths/searches are already known.
- Prefer repo_map, search_text, read_symbol, and focused read_file ranges over broad file dumps.
- Large exact outputs may be represented by a lossless R###### result pointer. Use read_result only for the portion you actually need.
- The harness owns routine task-status advancement. Do not spend a model step merely updating checklist status.
- Tool capability schemas are phase-scoped. If a needed tool is unavailable, call request_capabilities with the smallest sufficient profile.
- Do not ask for a larger context window. The harness chooses the smallest safe context and compacts automatically.
- Reuse facts already present in runtime_state/compacted memory rather than re-reading unchanged files.
"""


# ----------------------------- V5 diagnostics -------------------------------

def run_startup_diagnostics(session_resumed: bool) -> None:
    _V4_RUN_STARTUP_DIAGNOSTICS(session_resumed)
    load_recent_perf()

    ui_header("V5 SPEED ENGINE", C.BRIGHT_CYAN)
    ui_success(f"Tool profiles · explore {len(TOOL_PROFILES['explore'])} / edit {len(TOOL_PROFILES['edit'])} / validate {len(TOOL_PROFILES['validate'])}")
    ui_success(f"Result store · lossless paging at {RESULT_INLINE_LIMIT:,} chars")
    ui_success(f"Parallel read tools · up to {TOOL_PARALLELISM} workers")
    ui_success(f"Model keep-alive · {MODEL_KEEP_ALIVE}")
    ui_success(f"Model quantization · {model_quantization()}")

    print_inference_settings()
    status_line("warm state", MODEL_WARM_STATE, C.WHITE)

    if PERF_HISTORY:
        print(color("  " + perf_summary_text(6).replace("\n", "\n  "), C.BRIGHT_BLACK))
    print()


# ------------------------------ V5 slash UI ---------------------------------

def benchmark_current_request(messages: List[Dict[str, Any]], repeats: int = 2) -> None:
    """Measure the latest real coding prompt; never execute returned tools."""
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not users:
        ui_warn("Run a coding request first, then use /benchmark [1-5].")
        return
    probe = messages[:users[-1] + 1]
    prepared = prepare_request_messages(probe)
    tools = tools_for_profile()
    payload = {
        "model": CURRENT_MODEL, "messages": prepared, "tools": tools,
        "stream": True, "keep_alive": MODEL_KEEP_ALIVE,
        "options": {"num_ctx": CONTEXT_SIZE, "temperature": TEMPERATURE, "num_predict": 256},
    }
    ui_header("CODING REQUEST BENCHMARK", C.BRIGHT_CYAN)
    print("  Same coding prompt and tool schemas; 256 output tokens maximum per sample.")
    print("  Returned tool calls are measured only. Quality and full-task speed require actual coding runs.")
    spinner = Spinner("Benchmarking model")
    try:
        for number in range(1, max(1, min(repeats, 5)) + 1):
            begin_ollama_model_request(CURRENT_MODEL)
            req = urllib.request.Request(CHAT_URL, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            started = time.monotonic()
            first: Optional[float] = None
            meta: Dict[str, Any] = {}
            spinner.start()
            with ollama_urlopen(req, timeout=600) as response:
                for raw in response:
                    if not raw.strip():
                        continue
                    chunk = json.loads(raw.decode("utf-8"))
                    if chunk.get("error"):
                        raise AgentError(str(chunk["error"]))
                    msg = chunk.get("message", {}) or {}
                    if first is None and any(msg.get(k) for k in ("content", "thinking", "tool_calls")):
                        first = time.monotonic() - started
                    if chunk.get("done"):
                        meta = chunk
            spinner.stop()
            if not meta:
                raise AgentError("Benchmark stream ended without completion metadata.")
            sample = record_perf(dict(meta, ttft_s=first), profile="benchmark:" + ACTIVE_TOOL_PROFILE,
                                 wall_seconds=time.monotonic()-started,
                                 request_estimate=estimate_request_tokens(probe), tool_schema_tokens=_rough_tokens(tools))
            first_label = f"{first:.2f}s" if first is not None else "no output"
            print(f"  {number}: first token {first_label}; total {sample['wall_s']:.2f}s; "
                  f"decode {sample['decode_tps']:.1f} tok/s; prompt cache {sample['cache_pct']:.1f}%")
        warn_ollama_runtime_fallback()
    except KeyboardInterrupt:
        ui_warn("Benchmark cancelled.")
    except Exception as e:
        ui_error(f"Benchmark failed: {e}")
    finally:
        spinner.stop()


HELP_TEXT = HELP_TEXT + """

V5 speed commands:
/perf                    Show recent Ollama latency/cache profile
/perf reset              Clear in-memory profiler view (JSONL history stays)
/benchmark [1-5]          Measure the latest coding prompt without executing tools
/results                  List recent stored R###### results
/result R###### [line]    Read a stored result page
/tools                    Show current capability profile/schema sizes
/inference                Show model weights, Q8 launch settings and runtime evidence
/warm                     Warm the model now
/unload                   Unload the model from Ollama memory
""".rstrip()

_V4_SLASH_COMMAND_FOR_V5 = slash_command


def slash_command(
    text: str,
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    global PERF_HISTORY, ACTIVE_TOOL_PROFILE
    global COMPACTED_MEMORY
    global MODEL_WARM_STATE, MODEL_HAS_RUN

    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/model" and arg:
        result = _V4_SLASH_COMMAND_FOR_V5(text, messages)
        MODEL_WARM_STATE = "unknown"
        MODEL_HAS_RUN = False
        begin_ollama_model_request(CURRENT_MODEL)
        return result

    if cmd in {"/new", "/clear"}:
        COMPACTED_MEMORY = ""
        if cmd == "/new":
            reset_session_ledger()
        return _V4_SLASH_COMMAND_FOR_V5(text, messages)

    if cmd == "/benchmark":
        try:
            count = int(arg or "2")
            if count < 1 or count > 5:
                raise ValueError()
        except ValueError:
            ui_error("Usage: /benchmark [1-5]")
            return "handled", messages, None
        benchmark_current_request(messages, count)
        return "handled", messages, None

    if cmd == "/perf":
        if arg.lower() == "reset":
            PERF_HISTORY = []
            ui_success("In-memory performance window cleared.")
        else:
            print()
            print(perf_summary_text(10))
            if PERF_HISTORY:
                last = PERF_HISTORY[-1]
                print_rule("·", C.BRIGHT_BLACK)
                status_line("last total", f"{float(last.get('total_s', 0)):.2f}s", C.WHITE)
                status_line("load", f"{float(last.get('load_s', 0)):.2f}s", C.WHITE)
                status_line("prompt", f"{float(last.get('prompt_s', 0)):.2f}s", C.WHITE)
                status_line("decode", f"{float(last.get('decode_s', 0)):.2f}s", C.WHITE)
                status_line("cache", f"{float(last.get('cache_pct', 0)):.1f}%", C.WHITE)
                status_line("decode rate", f"{float(last.get('decode_tps', 0)):.1f} tok/s", C.WHITE)
            print()
        return "handled", messages, None

    if cmd == "/results":
        print()
        for rid in SESSION_LEDGER.get("results", [])[-20:]:
            _txt, meta = _result_paths(rid)
            data = load_json(meta, {})
            print(
                color(f"  {rid}", C.BRIGHT_CYAN)
                + color(
                    f"  {data.get('tool', '')} · {int(data.get('lines', 0)):,} lines · {int(data.get('chars', 0)):,} chars",
                    C.BRIGHT_BLACK,
                )
            )
        if not SESSION_LEDGER.get("results"):
            print(color("  No stored results yet.", C.BRIGHT_BLACK))
        print()
        return "handled", messages, None

    if cmd == "/result":
        bits = arg.split()
        if not bits:
            ui_error("Usage: /result R000001 [start_line]")
            return "handled", messages, None
        start = 1
        if len(bits) > 1:
            try:
                start = int(bits[1])
            except Exception:
                pass
        print()
        print(tool_read_result(bits[0], start_line=start))
        print()
        return "handled", messages, None

    if cmd == "/tools":
        print()
        status_line("profile", ACTIVE_TOOL_PROFILE, C.BRIGHT_CYAN)
        for name, schemas in TOOL_PROFILES.items():
            status_line(name, f"{len(schemas)} tools · ~{_rough_tokens(schemas):,} schema tokens", C.WHITE)
        print()
        return "handled", messages, None

    if cmd == "/inference":
        print()
        status_line("model", CURRENT_MODEL, C.WHITE)
        status_line("quantization", model_quantization(), C.BRIGHT_CYAN)
        print_inference_settings()
        status_line("keep alive", MODEL_KEEP_ALIVE, C.WHITE)
        status_line("warm state", MODEL_WARM_STATE, C.WHITE)
        status_line("KV estimate", f"{estimated_kv_bytes_per_token()/1024:.1f} KB/token", C.WHITE)
        print()
        return "handled", messages, None

    if cmd == "/warm":
        ok = _load_or_unload_model(MODEL_KEEP_ALIVE)
        ui_success("Model warm.") if ok else ui_error("Model warm-up failed.")
        warn_ollama_runtime_fallback()
        return "handled", messages, None

    if cmd == "/unload":
        ok = _load_or_unload_model(0)
        ui_success("Model unloaded.") if ok else ui_error("Model unload failed.")
        return "handled", messages, None

    return _V4_SLASH_COMMAND_FOR_V5(text, messages)


# ---------------------------- V5 turn loop ----------------------------------

def process_user_turn(
    user_text: str,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    global TURN_TOOL_COUNT, LAST_USER_TEXT

    TURN_TOOL_COUNT = 0
    LAST_USER_TEXT = user_text
    SESSION_LEDGER["current_goal"] = user_text
    save_ledger()

    # Select once at the task boundary; keep stable through a phase for cache locality.
    set_tool_profile(select_initial_tool_profile(user_text))
    turn_start = time.time()
    messages.append({"role": "user", "content": user_text})
    save_session(messages)

    final_meta: Dict[str, Any] = {}
    overflow_recovered = False

    for _step in range(MAX_TOOL_STEPS):
        try:
            messages = ensure_context_capacity(messages, reason="V5 preflight")
            save_session(messages)
            response = stream_ollama_chat(messages)
        except OperationCancelled:
            double = register_interrupt()
            if double:
                abandon_current_task()
                ui_warn("Task abandoned.")
                messages.append({"role": "system", "content": "The user abandoned the previous task."})
            else:
                ui_warn(
                    "Current generation cancelled. Press Ctrl+C again within "
                    f"{CANCEL_DOUBLE_TAP_SECONDS:.1f}s to abandon the whole task."
                )
            save_session(messages)
            return messages
        except Exception as e:
            if is_context_overflow_error(e) and not overflow_recovered:
                overflow_recovered = True
                ui_warn("Context overflow. Compacting and retrying this model step once.")
                messages = compact_session(
                    messages,
                    reason="V5 provider context-overflow recovery",
                    force=True,
                )
                continue
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
            finalize_tasks_after_answer(content)
            SESSION_LEDGER["last_answer"] = short_text(content, 1200)
            save_ledger()

            # Shrink context at idle boundaries if the active request no longer
            # needs the current tier.
            maybe_auto_tune_context(messages, allow_increase=True)

            elapsed = time.time() - turn_start
            save_session(messages)
            print_turn_footer(messages, elapsed, final_meta)
            return messages

        try:
            executed = execute_tool_calls_batch(tool_calls)
        except (KeyboardInterrupt, OperationCancelled):
            for call in tool_calls:
                name, _args = parse_tool_args(call)
                messages.append(build_tool_message(call, name, "ERROR: Tool batch interrupted. Some actions may have finished; reinspect before retrying."))
            ui_warn("Tool batch cancelled. Use /continue or /retry after checking completed actions.")
            save_session(messages)
            return messages
        names: List[str] = []
        results: List[str] = []

        for call, name, result in executed:
            names.append(name)
            results.append(result)
            messages.append(build_tool_message(call, name, result))

        _transition_profile_after_tools(names, results)

        # Long same-turn trajectories are preflighted immediately.
        messages = ensure_context_capacity(messages, reason="V5 after tool batch")
        save_session(messages)

    ui_warn(f"Stopped after {MAX_TOOL_STEPS} tool steps to prevent an infinite loop.")
    save_session(messages)
    return messages


# ----------------------------- V5 footer ------------------------------------

def print_turn_footer(
    messages: List[Dict[str, Any]],
    elapsed: float,
    meta: Dict[str, Any],
) -> None:
    print_rule("─", C.BRIGHT_BLACK)

    parts = [
        f"{TURN_TOOL_COUNT} tool call{'s' if TURN_TOOL_COUNT != 1 else ''}",
        human_duration(elapsed),
        f"profile {ACTIVE_TOOL_PROFILE}",
    ]

    if PERF_HISTORY:
        last = PERF_HISTORY[-1]
        if last.get("decode_tps"):
            parts.append(f"{float(last['decode_tps']):.1f} tok/s")
        if last.get("cache_pct") is not None:
            parts.append(f"cache {float(last.get('cache_pct', 0)):.0f}%")

    parts.append(context_bar(messages))
    print(color("  " + "  ·  ".join(parts), C.BRIGHT_BLACK))
    print()


# -------------------------- V5 entry point ----------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hyper-Cube Local Coding Agent V5 for Ollama."
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--project", default=".")
    parser.add_argument("--ctx", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--ollama-exe", default=None, help="Ollama executable path for the managed Q8 server")
    parser.add_argument("--ollama-url", default=None, help="Use an external server instead (Q8 configuration unverified)")
    args = parser.parse_args()
    if args.ollama_exe and args.ollama_url:
        parser.error("--ollama-exe and --ollama-url cannot be combined")

    global PROJECT_ROOT, AGENT_DIR, CONFIG_PATH, SESSION_PATH, REPO_MAP_PATH
    global RESULTS_DIR, LEDGER_PATH, PERF_PATH
    global CURRENT_MODEL, CONTEXT_SIZE, TEMPERATURE, RESUME_ENABLED, POWERSHELL_EXE
    global CONTEXT_MODE, AUTO_CONTEXT_ENABLED

    PROJECT_ROOT = Path(args.project).resolve()
    if not PROJECT_ROOT.exists() or not PROJECT_ROOT.is_dir():
        print(f"ERROR: Project directory does not exist: {PROJECT_ROOT}")
        sys.exit(1)

    AGENT_DIR = PROJECT_ROOT / ".agent"
    CONFIG_PATH = AGENT_DIR / "config.json"
    SESSION_PATH = AGENT_DIR / "session.json"
    REPO_MAP_PATH = AGENT_DIR / "repo_map.json"
    RESULTS_DIR = AGENT_DIR / "results"
    LEDGER_PATH = AGENT_DIR / "ledger.json"
    PERF_PATH = AGENT_DIR / "performance.jsonl"

    CURRENT_MODEL = DEFAULT_MODEL
    CONTEXT_SIZE = DEFAULT_CTX
    TEMPERATURE = DEFAULT_TEMP

    load_config()

    if args.model:
        CURRENT_MODEL = args.model
    if args.ctx is not None:
        CONTEXT_SIZE = max(CONTEXT_MIN, min(int(args.ctx), 32768))
        CONTEXT_MODE = "fixed"
        AUTO_CONTEXT_ENABLED = False
    if args.temperature is not None:
        TEMPERATURE = max(0.0, min(float(args.temperature), 2.0))
    if args.no_resume:
        RESUME_ENABLED = False

    POWERSHELL_EXE = detect_powershell()

    try:
        ensure_agent_dir()
    except Exception as e:
        print(f"ERROR: Could not create {AGENT_DIR}: {e}")
        sys.exit(1)

    load_ledger()
    load_recent_perf()
    save_config()

    try:
        start_ollama_server(executable=args.ollama_exe, external_url=args.ollama_url)
        RESOURCE_MONITOR.start()
        run_agent()
    except KeyboardInterrupt:
        print()
        save_config()
        save_ledger()
        print(color("Interrupted. Exiting.", C.BRIGHT_BLACK))
    except Exception as e:
        print()
        ui_error(f"Fatal error: {e}")
        save_config()
        save_ledger()
        raise
    finally:
        RESOURCE_MONITOR.stop()
        if _OLLAMA_SERVER_PROCESS is not None:
            # Stopping the owned server releases its warm model, including an
            # in-flight background warm-up, without waiting on a load request.
            stop_managed_ollama()
        elif OLLAMA_SERVER_MODE.startswith("external") and RELEASE_MODEL_ON_EXIT:
            unload_model()


if __name__ == "__main__":
    main()
