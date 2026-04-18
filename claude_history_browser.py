#!/usr/bin/env python3
"""
Claude History Browser
Browse your local Claude conversation history (.jsonl files) via a web UI.

Usage:
    python3 claude_history_browser.py

On first run, a Finder window will open so you can choose your history folder.
The path is saved to ~/.claude_history_browser.json for future sessions.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── App metadata (shown in the About dialog and MD export headers) ───────────
APP_NAME = "Claude History Browser"
APP_VERSION = "1.1.0"
APP_AUTHOR = "@jamaia1971"
APP_LICENSE = "MIT"
APP_REPO = "https://github.com/jamaia1971/claude-history-browser"
APP_COPYRIGHT = "Claude © Anthropic, PBC. This tool is an independent project and is not affiliated with Anthropic."

# ── Try to import Flask, install if missing ─────────────────────────────────
try:
    from flask import Flask, jsonify, request, render_template_string, Response
except ImportError:
    print("📦 Installing Flask...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--quiet"])
    from flask import Flask, jsonify, request, render_template_string, Response

# ── Config ───────────────────────────────────────────────────────────────────
CONFIG_FILE = Path.home() / ".claude_history_browser.json"
app = Flask(__name__)
HISTORY_PATH: Path = None  # set at startup


# ── Folder picker (macOS Finder) ─────────────────────────────────────────────
def pick_folder_mac(prompt_text: str = None):
    """Open a macOS Finder "choose folder" dialog and return the POSIX path.

    An optional custom ``prompt_text`` can be passed so the same helper can
    serve both "pick your history folder" and "pick a backup destination" flows.
    """
    if not prompt_text:
        prompt_text = (
            "Select your Claude history folder "
            "(the folder containing project subfolders with .jsonl files):"
        )
    # AppleScript uses double quotes for strings; escape any embedded quotes
    # and backslashes in the caller-supplied prompt to keep the script valid.
    safe_prompt = prompt_text.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Finder"
        activate
    end tell
    try
        set chosen to choose folder with prompt "{safe_prompt}"
        return POSIX path of chosen
    on error
        return ""
    end try
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    path = result.stdout.strip()
    return path if path else None


def normalize_path_input(raw: str) -> str | None:
    """Clean a path string the user typed or pasted.

    Handles quotes, leading/trailing whitespace, ~ expansion, and shell-style
    escaped spaces (e.g. /Users/name/My\\ Folder). Returns None if empty.
    """
    if not raw:
        return None
    s = raw.strip()
    # Strip surrounding quotes
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        s = s[1:-1]
    # Undo shell-escaped spaces like "My\ Folder"
    s = s.replace("\\ ", " ")
    s = os.path.expanduser(s)
    return s or None


def prompt_folder_path() -> str | None:
    """Ask the user for a history folder via Finder OR typed/pasted path.

    Loops until a valid existing directory is supplied, or the user aborts
    by entering 'q' / pressing Ctrl+C.
    """
    print(
        "\nHow would you like to choose your Claude history folder?\n"
        "  [1] Open a Finder window to pick it\n"
        "  [2] Type or paste the folder path\n"
        "  [q] Quit\n"
    )
    while True:
        try:
            choice = input("Your choice [1/2/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if choice in ("q", "quit", "exit"):
            return None

        if choice in ("", "1", "finder", "f"):
            print("🔍 Opening Finder...")
            chosen = pick_folder_mac()
            if chosen and Path(chosen).is_dir():
                return chosen
            print("⚠️  No folder selected via Finder. Try again.")
            continue

        if choice in ("2", "paste", "p", "path"):
            try:
                raw = input("Paste the full path to your history folder: ")
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            cleaned = normalize_path_input(raw)
            if not cleaned:
                print("⚠️  Empty path. Try again.")
                continue
            p = Path(cleaned)
            if not p.exists():
                print(f"⚠️  Path does not exist: {p}")
                continue
            if not p.is_dir():
                print(f"⚠️  Not a folder: {p}")
                continue
            return str(p)

        print("⚠️  Please enter 1, 2, or q.")


# ── Config persistence ───────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def resolve_history_path() -> Path:
    cfg = load_config()
    saved = cfg.get("history_path")
    if saved:
        p = Path(saved)
        if p.exists():
            print(f"📂 Using saved history path: {p}")
            return p
        else:
            print(f"⚠️  Saved path no longer exists: {p}")

    chosen = prompt_folder_path()
    if not chosen:
        print("❌ No folder selected. Exiting.")
        sys.exit(1)

    p = Path(chosen)
    cfg["history_path"] = str(p)
    save_config(cfg)
    print(f"✅ Saved history path: {p}")
    return p


# ── JSONL parsing ─────────────────────────────────────────────────────────────
def parse_jsonl(filepath: Path):
    messages = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return messages


def extract_text(content) -> str:
    """Turn content (str or list of blocks) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("type", "")
                if t == "text":
                    parts.append(block.get("text", ""))
                elif t == "tool_use":
                    parts.append(f"[Tool: {block.get('name', '?')}]")
                elif t == "tool_result":
                    inner = block.get("content", "")
                    if isinstance(inner, list):
                        inner = " ".join(
                            b.get("text", "") for b in inner if isinstance(b, dict)
                        )
                    parts.append(f"[Result: {str(inner)[:120]}]")
        return "\n".join(parts)
    return str(content)


def content_blocks(content):
    """Return structured blocks for the UI."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type", "")
            if t == "text":
                blocks.append({"type": "text", "text": b.get("text", "")})
            elif t == "thinking":
                blocks.append({"type": "thinking", "text": b.get("thinking", "")})
            elif t == "tool_use":
                inp = b.get("input", {})
                blocks.append(
                    {
                        "type": "tool_use",
                        "name": b.get("name", "?"),
                        "input": json.dumps(inp, indent=2)[:2000]
                        if inp
                        else "",
                    }
                )
            elif t == "tool_result":
                inner = b.get("content", "")
                if isinstance(inner, list):
                    inner = "\n".join(
                        x.get("text", "")
                        for x in inner
                        if isinstance(x, dict) and x.get("type") == "text"
                    )
                blocks.append(
                    {"type": "tool_result", "text": str(inner)[:3000]}
                )
        return blocks
    return []


def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


# Cache of per-folder project info keyed by the parent directory, so we don't
# re-scan jsonl files every time we need a display name. Each value is a dict
# {"display": str, "session": str | None} — where "session" is the Cowork
# session nickname (e.g. "vigilant-keen-davinci") when one can be detected
# from the conversation's cwd / paths, and "display" is the best human-facing
# label to put in the Project column (the mounted folder name if we can find
# one, otherwise just the cwd basename).
_PROJECT_INFO_CACHE: dict[str, dict] = {}

# Cowork session nicknames follow an adjective-adjective-noun pattern like
# "vigilant-keen-davinci" or "epic-intelligent-fermat" (animal/scientist name
# at the end). Matching this lets us decide when to dig deeper for the real
# mounted project folder instead of showing the nickname.
_COWORK_SESSION_PATTERN = re.compile(r"^[a-z][a-z]+-[a-z][a-z]+-[a-z][a-z]+$")

# Matches "/sessions/<nickname>/mnt/<folder>" inside any string. Group 1 is
# the session nickname; group 2 is the mounted folder name (which can contain
# spaces — we stop at the next slash, quote, or backslash).
_COWORK_MOUNT_REGEX = re.compile(r"/sessions/([^/\"\\\s]+)/mnt/([^/\"\\]+)")


def _extract_cwd_from_jsonl(filepath: Path) -> str | None:
    """Peek at the first few JSON lines of a .jsonl file and return the
    `cwd` field if we find one. Claude Code / Cowork transcripts include
    this on most records, so it's a reliable way to recover the actual
    project path (the folder name on disk is a lossy dash-encoded form)."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = rec.get("cwd")
                if isinstance(cwd, str) and cwd.strip():
                    return cwd.strip()
    except Exception:
        return None
    return None


def _decode_claude_folder_name(name: str) -> str:
    """Best-effort decode of a Claude Code project folder name.

    Claude Code encodes the cwd by replacing '/' with '-', so a folder
    like '-Users-joao-code-my-proj' originally came from '/Users/joao/code/my-proj'.
    This is lossy when the original path contains hyphens, so we only use
    this as a fallback when the .jsonl files don't carry a `cwd` field.
    """
    if not name:
        return name
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name.replace("-", "/")


def _looks_like_cowork_session(name: str) -> bool:
    """True if `name` matches the Cowork session-nickname pattern."""
    return bool(_COWORK_SESSION_PATTERN.match(name or ""))


def _scan_cowork_mount(parent: Path) -> tuple[str | None, str | None]:
    """Scan early JSONL lines in ``parent`` for ``/sessions/X/mnt/Y`` style
    paths and return the most common ``(mount_folder, session_name)``.

    When a conversation ran inside a Cowork session with a user-selected
    workspace folder, tool-call arguments and file paths typically reference
    ``/sessions/<nickname>/mnt/<real-folder>/...`` — and Cowork's system
    prompt explicitly records a ``Folder: /sessions/<nick>/mnt/<folder>``
    line. Counting those references and picking the most-seen ``<folder>``
    gives us the actual project the user was working in (e.g. "history
    browser" instead of "vigilant-keen-davinci").
    """
    mount_counts = Counter()
    mount_to_session: dict[str, str] = {}
    try:
        files = sorted(parent.glob("*.jsonl"))[:8]  # cap I/O for big folders
    except Exception:
        return None, None

    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    # System-prompt text usually arrives within the first
                    # ~200 lines; cap well above 40 so we don't miss it in
                    # long conversations that start with a lot of tool use.
                    if i >= 250:
                        break
                    # JSON sometimes escapes slashes as "\/" — normalize so
                    # our regex can match paths embedded inside JSON strings.
                    if "\\/" in line:
                        line = line.replace("\\/", "/")
                    for m in _COWORK_MOUNT_REGEX.finditer(line):
                        sess = m.group(1)
                        mount = m.group(2).strip().strip("/")
                        # Skip obvious plumbing mounts (hidden dot-dirs like
                        # .claude, .local-plugins). A user-named folder that
                        # starts with "tmp" is perfectly legitimate, so we
                        # do NOT filter those anymore.
                        if not mount or mount.startswith("."):
                            continue
                        mount_counts[mount] += 1
                        mount_to_session.setdefault(mount, sess)
        except Exception:
            continue

    if not mount_counts:
        return None, None
    best = mount_counts.most_common(1)[0][0]
    return best, mount_to_session.get(best)


def project_info(filepath: Path) -> dict:
    """Return ``{"display": str, "session": str | None}`` for a jsonl file.

    Preference order for ``display``:
      1. If the jsonl's ``cwd`` looks like a Cowork session root
         (basename matches the nickname pattern) AND we can find a
         ``/sessions/<nick>/mnt/<folder>`` reference in the file, use
         ``<folder>``. The nickname is returned as ``session``.
      2. Otherwise, the basename of ``cwd`` recorded inside the .jsonl.
      3. Otherwise, the decoded on-disk folder name (lossy).
      4. Otherwise, the raw folder name.

    Files sitting directly in HISTORY_PATH get display "(root)".
    """
    parent = filepath.parent
    parent_key = str(parent)
    cached = _PROJECT_INFO_CACHE.get(parent_key)
    if cached is not None:
        return cached

    # Files at the root of the history folder
    try:
        rel = parent.relative_to(HISTORY_PATH)
        if str(rel) in ("", "."):
            info = {"display": "(root)", "session": None}
            _PROJECT_INFO_CACHE[parent_key] = info
            return info
    except Exception:
        pass

    # 1. Try to pull cwd from any .jsonl in this parent folder.
    cwd = None
    try:
        for sibling in parent.glob("*.jsonl"):
            cwd = _extract_cwd_from_jsonl(sibling)
            if cwd:
                break
    except Exception:
        cwd = None

    session: str | None = None
    if cwd:
        cwd_stripped = cwd.rstrip("/\\")
        name = os.path.basename(cwd_stripped) or cwd_stripped
        # Only treat this as a Cowork session when the full cwd actually
        # starts with "/sessions/" AND the basename matches the nickname
        # pattern — otherwise a regular local repo like ~/code/claude-history-browser
        # would be mistakenly "resolved" to some mount.
        is_cowork_root = (
            cwd_stripped.startswith("/sessions/")
            and _looks_like_cowork_session(name)
        )
        if is_cowork_root:
            mount, sess = _scan_cowork_mount(parent)
            if mount:
                session = sess or name
                name = mount
            else:
                session = name  # keep the nickname so the UI can show it
    else:
        # 2. Fall back to decoding the folder name on disk.
        decoded = _decode_claude_folder_name(parent.name)
        decoded_stripped = decoded.rstrip("/\\")
        name = os.path.basename(decoded_stripped) or parent.name
        is_cowork_root = (
            decoded_stripped.startswith("/sessions/")
            and _looks_like_cowork_session(name)
        )
        if is_cowork_root:
            mount, sess = _scan_cowork_mount(parent)
            if mount:
                session = sess or name
                name = mount

    info = {"display": name, "session": session}
    _PROJECT_INFO_CACHE[parent_key] = info
    return info


def project_display_name(filepath: Path) -> str:
    """Thin wrapper — returns just the display label."""
    return project_info(filepath)["display"]


def project_key(filepath: Path) -> str:
    """Backwards-compatible alias used in several places."""
    return project_display_name(filepath)


def _first_nonempty(messages, key):
    """Return the first non-empty value of `key` across the records."""
    for m in messages:
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def conversation_summary(filepath: Path) -> dict | None:
    messages = parse_jsonl(filepath)
    if not messages:
        return None

    turns = [m for m in messages if m.get("type") in ("user", "assistant")]
    user_turns = [m for m in turns if m.get("type") == "user"]
    if not user_turns:
        return None

    # Title from first user message
    first_user_content = user_turns[0].get("message", {}).get("content", "")
    first_text = extract_text(first_user_content)
    title = first_text.strip().splitlines()[0][:90] or "Untitled"
    preview = first_text.strip()[:200]

    # Timestamps
    timestamps = [parse_ts(m.get("timestamp")) for m in turns]
    timestamps = [t for t in timestamps if t]
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None

    # Session / model info
    model = None
    for m in messages:
        if m.get("type") == "assistant":
            model = m.get("message", {}).get("model")
            if model:
                break

    # Token usage tally.
    # Claude Code / Cowork transcripts store a ``usage`` dict on each
    # assistant turn with four counters: plain input tokens, cache-creation
    # input tokens, cache-read input tokens, and output tokens. We sum all
    # four across the conversation so the reader header can show the user a
    # rough "cost" figure for the thread. These are PER-TURN counts, not a
    # context-window snapshot — see HISTORY_RETENTION.md / the context-window
    # report for the distinction.
    tokens_in = 0
    tokens_out = 0
    tokens_cache_read = 0
    tokens_cache_creation = 0
    for m in messages:
        if m.get("type") != "assistant":
            continue
        usage = (m.get("message") or {}).get("usage") or {}
        try:
            tokens_in += int(usage.get("input_tokens") or 0)
            tokens_out += int(usage.get("output_tokens") or 0)
            tokens_cache_read += int(usage.get("cache_read_input_tokens") or 0)
            tokens_cache_creation += int(
                usage.get("cache_creation_input_tokens") or 0
            )
        except (TypeError, ValueError):
            # Older transcripts may have non-numeric or missing counters;
            # silently skip rather than break the whole summary.
            pass

    # Extra metadata pulled from the JSONL records themselves.
    # Claude Code / Cowork transcripts commonly carry these fields.
    session_id = _first_nonempty(messages, "sessionId")
    cwd = _first_nonempty(messages, "cwd")
    git_branch = _first_nonempty(messages, "gitBranch")
    cc_version = _first_nonempty(messages, "version")
    user_type = _first_nonempty(messages, "userType")

    pinfo = project_info(filepath)
    return {
        "id": filepath.stem,
        "file": str(filepath),
        "project": pinfo["display"],
        # Cowork session nickname when the conversation ran inside a Cowork
        # session — used as a secondary label / tooltip in the UI so the
        # user can tell which session a conversation came from.
        "project_session": pinfo.get("session"),
        "title": title,
        "preview": preview,
        "turn_count": len(turns),
        "user_count": len(user_turns),
        "model": model or "unknown",
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
        "size_kb": round(filepath.stat().st_size / 1024, 1),
        "session_id": session_id,
        "cwd": cwd,
        "git_branch": git_branch,
        "cc_version": cc_version,
        "user_type": user_type,
        # Token usage totals (summed across all assistant turns).
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cache_read": tokens_cache_read,
        "tokens_cache_creation": tokens_cache_creation,
    }


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


# Inline SVG favicon — purple rounded square with a magnifying glass (lupa),
# evoking the "browse / search conversations" purpose of the app.
# Served from /favicon.svg (modern browsers) and /favicon.ico (legacy fallback,
# which Safari and most browsers will happily render from SVG bytes).
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#c67eff"/>'
    '<circle cx="13.5" cy="13.5" r="5.8" fill="none" stroke="#0f1117" '
    'stroke-width="2.8"/>'
    '<line x1="17.8" y1="17.8" x2="24" y2="24" stroke="#0f1117" '
    'stroke-width="3.2" stroke-linecap="round"/>'
    '</svg>'
)


@app.route("/favicon.svg")
def favicon_svg():
    return Response(FAVICON_SVG, mimetype="image/svg+xml")


@app.route("/favicon.ico")
def favicon_ico():
    # Safari / older browsers still request /favicon.ico by default.
    # Return the SVG bytes with an SVG mimetype — browsers accept it.
    return Response(FAVICON_SVG, mimetype="image/svg+xml")


@app.route("/api/projects")
def api_projects():
    """Return list of projects — every directory (at any depth) that
    contains .jsonl files, relative to HISTORY_PATH."""
    projects = set()
    for f in HISTORY_PATH.rglob("*.jsonl"):
        projects.add(project_key(f))
    return jsonify(sorted(projects, key=lambda x: x.lower()))


@app.route("/api/conversations")
def api_conversations():
    """Return summaries of all conversations, optionally filtered by project.

    Scans HISTORY_PATH recursively so conversations in nested subfolders
    are included.
    """
    project_filter = request.args.get("project", "")
    search = request.args.get("q", "").lower()

    # Gather candidate files recursively, then filter by project if requested.
    all_files = list(HISTORY_PATH.rglob("*.jsonl"))
    if project_filter:
        all_files = [f for f in all_files if project_key(f) == project_filter]

    # Sort newest first
    all_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    results = []
    for f in all_files:
        summary = conversation_summary(f)
        if not summary:
            continue
        if search and search not in (summary["title"] + summary["preview"]).lower():
            # Deep search: scan file content
            try:
                raw = f.read_text(errors="replace")
                if search not in raw.lower():
                    continue
                summary["_matched_content"] = True
            except Exception:
                continue
        results.append(summary)

    return jsonify(results)


@app.route("/api/conversation/<path:conv_id>")
def api_conversation(conv_id):
    """Return full message list for a conversation."""
    # Find the file
    target = None
    for f in HISTORY_PATH.rglob(f"{conv_id}.jsonl"):
        target = f
        break
    if not target:
        return jsonify({"error": "Not found"}), 404

    raw = parse_jsonl(target)
    turns = []
    for m in raw:
        t = m.get("type")
        if t not in ("user", "assistant"):
            continue
        content = m.get("message", {}).get("content", "")
        # Per-turn token usage. Only assistant turns carry a `usage` dict
        # (the API emits it with the response). We surface just input +
        # output here — the conversation-level tooltip still shows the
        # cache-read / cache-write breakdown for the whole thread.
        turn = {
            "role": t,
            "blocks": content_blocks(content),
            "timestamp": m.get("timestamp"),
            "uuid": m.get("uuid"),
            "model": m.get("message", {}).get("model"),
        }
        if t == "assistant":
            usage = (m.get("message") or {}).get("usage") or {}
            try:
                turn["tokens_in"] = int(usage.get("input_tokens") or 0)
                turn["tokens_out"] = int(usage.get("output_tokens") or 0)
            except (TypeError, ValueError):
                # Defensive: older transcripts may have malformed counters.
                turn["tokens_in"] = 0
                turn["tokens_out"] = 0
        turns.append(turn)
    return jsonify({"turns": turns, "total": len(turns)})


@app.route("/api/search")
def api_search():
    """Full-text search across all conversations."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])

    results = []
    for f in HISTORY_PATH.rglob("*.jsonl"):
        try:
            raw = f.read_text(errors="replace")
            if q not in raw.lower():
                continue
        except Exception:
            continue

        summary = conversation_summary(f)
        if not summary:
            continue

        # Find matching excerpts
        messages = parse_jsonl(f)
        excerpts = []
        for m in messages:
            if m.get("type") not in ("user", "assistant"):
                continue
            text = extract_text(m.get("message", {}).get("content", ""))
            idx = text.lower().find(q)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(text), idx + len(q) + 60)
                excerpts.append(
                    {
                        "role": m.get("type"),
                        "snippet": ("..." if start > 0 else "")
                        + text[start:end]
                        + ("..." if end < len(text) else ""),
                    }
                )
            if len(excerpts) >= 3:
                break

        summary["excerpts"] = excerpts
        results.append(summary)

        if len(results) >= 50:
            break

    return jsonify(results)


@app.route("/api/config")
def api_config():
    return jsonify({"history_path": str(HISTORY_PATH)})


@app.route("/api/config/change", methods=["POST"])
def api_config_change():
    """Let user pick a new folder at runtime.

    Two modes:
      - {"mode": "finder"}  → open a Finder window to pick a folder
      - {"mode": "path", "path": "/abs/path"}  → use the supplied path directly
    If no body is supplied, defaults to Finder for backward compatibility.
    """
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "finder").lower()

    if mode == "path":
        raw = body.get("path", "")
        cleaned = normalize_path_input(raw)
        if not cleaned:
            return jsonify({"error": "Empty path"}), 400
        p = Path(cleaned)
        if not p.exists():
            return jsonify({"error": f"Path does not exist: {p}"}), 400
        if not p.is_dir():
            return jsonify({"error": f"Not a folder: {p}"}), 400
        chosen = str(p)
    else:
        chosen = pick_folder_mac()
        if not chosen:
            return jsonify({"error": "No folder selected"}), 400

    global HISTORY_PATH
    HISTORY_PATH = Path(chosen)
    cfg = load_config()
    cfg["history_path"] = str(HISTORY_PATH)
    save_config(cfg)
    return jsonify({"history_path": str(HISTORY_PATH)})


# ── Markdown export ──────────────────────────────────────────────────────────
def _md_escape_fence(text: str) -> str:
    """Avoid breaking out of a fenced code block."""
    return text.replace("```", "``\u200b`")


def conversation_to_markdown(filepath: Path) -> str:
    """Render a single .jsonl conversation as a Markdown document."""
    summary = conversation_summary(filepath)
    if not summary:
        return ""

    lines = []
    lines.append(f"# {summary['title']}")
    lines.append("")
    lines.append("## Conversation information")
    lines.append("")
    lines.append(f"- **Conversation ID:** `{summary['id']}`")
    lines.append(f"- **Project:** `{summary['project']}`")
    if summary.get("project_session"):
        lines.append(f"- **Cowork session:** `{summary['project_session']}`")
    if summary.get("cwd"):
        lines.append(f"- **Working directory (cwd):** `{summary['cwd']}`")
    if summary.get("git_branch"):
        lines.append(f"- **Git branch / commit:** `{summary['git_branch']}`")
    if summary.get("session_id"):
        lines.append(f"- **Session ID:** `{summary['session_id']}`")
    if summary.get("first_ts"):
        lines.append(f"- **Started:** {summary['first_ts']}")
    if summary.get("last_ts"):
        lines.append(f"- **Last turn:** {summary['last_ts']}")
    lines.append(f"- **Messages:** {summary['user_count']} user · {summary['turn_count']} total")
    lines.append(f"- **Model:** {summary['model']}")
    if summary.get("cc_version"):
        lines.append(f"- **Claude Code version:** {summary['cc_version']}")
    if summary.get("user_type"):
        lines.append(f"- **User type:** {summary['user_type']}")
    lines.append(f"- **Source file:** `{summary['file']}`")
    lines.append(f"- **File size:** {summary['size_kb']} KB")
    lines.append(f"- **Exported by:** {APP_NAME} v{APP_VERSION}")
    lines.append(f"- **Exported at:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for m in parse_jsonl(filepath):
        role = m.get("type")
        if role not in ("user", "assistant"):
            continue
        blocks = content_blocks(m.get("message", {}).get("content", ""))
        ts = m.get("timestamp") or ""
        who = "👤 You" if role == "user" else "✦ Claude"
        header = f"### {who}"
        if ts:
            header += f"  ·  `{ts}`"
        lines.append(header)
        lines.append("")

        for b in blocks:
            t = b.get("type")
            if t == "text":
                lines.append(b.get("text", ""))
                lines.append("")
            elif t == "thinking":
                lines.append("<details><summary>🧠 Thinking</summary>")
                lines.append("")
                lines.append("```")
                lines.append(_md_escape_fence(b.get("text", "")))
                lines.append("```")
                lines.append("")
                lines.append("</details>")
                lines.append("")
            elif t == "tool_use":
                lines.append(f"**🔧 Tool: `{b.get('name', '?')}`**")
                lines.append("")
                lines.append("```json")
                lines.append(_md_escape_fence(b.get("input", "")))
                lines.append("```")
                lines.append("")
            elif t == "tool_result":
                lines.append("**📤 Tool result**")
                lines.append("")
                lines.append("```")
                lines.append(_md_escape_fence(b.get("text", "")))
                lines.append("```")
                lines.append("")

        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


@app.route("/api/about")
def api_about():
    """App metadata for the About dialog."""
    return jsonify({
        "name": APP_NAME,
        "version": APP_VERSION,
        "author": APP_AUTHOR,
        "license": APP_LICENSE,
        "repo": APP_REPO,
        "copyright": APP_COPYRIGHT,
    })


def _build_export_markdown(ids):
    """Shared builder used by both /api/download and /api/copy."""
    all_files = {f.stem: f for f in HISTORY_PATH.rglob("*.jsonl")}

    parts = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts.append(f"# Claude History Export")
    parts.append("")
    parts.append(f"- **Exported:** {stamp}")
    parts.append(f"- **Conversations:** {len(ids)}")
    parts.append(f"- **Generator:** {APP_NAME} v{APP_VERSION} — {APP_REPO}")
    parts.append(f"- **License:** {APP_LICENSE}")
    parts.append(f"- **Notice:** {APP_COPYRIGHT}")
    parts.append("")
    parts.append("---")
    parts.append("")

    missing = []
    for cid in ids:
        f = all_files.get(cid)
        if not f:
            missing.append(cid)
            continue
        md = conversation_to_markdown(f)
        if md:
            parts.append(md)

    if missing:
        parts.append("")
        parts.append(f"> ⚠️ Could not find: {', '.join(missing)}")
        parts.append("")

    return "\n".join(parts)


@app.route("/api/copy", methods=["POST"])
def api_copy():
    """Return the selected conversations as a raw Markdown string in JSON —
    so the browser can drop it on the system clipboard."""
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "No conversations selected"}), 400
    payload = _build_export_markdown(ids)
    return jsonify({"markdown": payload, "length": len(payload)})


@app.route("/api/download", methods=["POST"])
def api_download():
    """Bundle the selected conversations into a single Markdown file.

    Request body: {"ids": ["<conv_id>", ...]}
    """
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "No conversations selected"}), 400

    payload = _build_export_markdown(ids)
    filename = f"claude-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    return Response(
        payload,
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Back-up (copy the whole history folder tree to a safe location) ──────────
def _human_size(num_bytes: int) -> str:
    """Render a byte count as a human-readable string (e.g. '12.4 MB')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _copy_history_tree(src: Path, dst: Path):
    """Recursively copy ``src`` → ``dst``, returning (files, bytes) counters.

    Uses shutil.copy2 to preserve timestamps so the backup still reflects when
    each original conversation was recorded. Symlinks are followed (we want a
    real, self-contained copy). Files that fail to copy are collected and
    reported so one bad permission doesn't abort the whole run.
    """
    files_copied = 0
    bytes_copied = 0
    errors = []

    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src, followlinks=True):
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            src_file = Path(root) / name
            dst_file = target_dir / name
            try:
                shutil.copy2(src_file, dst_file)
                files_copied += 1
                try:
                    bytes_copied += src_file.stat().st_size
                except OSError:
                    pass
            except Exception as exc:  # keep going even on unreadable files
                errors.append(f"{src_file}: {exc}")

    return files_copied, bytes_copied, errors


@app.route("/api/backup", methods=["POST"])
def api_backup():
    """Copy the entire history folder to a user-chosen destination.

    The goal is to protect conversations from being wiped by system cleanup
    or by a Claude app maintenance / update routine. We copy HISTORY_PATH
    into a timestamped subfolder under the chosen destination, so repeated
    backups to the same folder don't overwrite each other.

    Request body (JSON, all optional):
      - "mode": "finder" (default) or "path"
      - "path": destination folder (required when mode == "path")
    """
    if HISTORY_PATH is None or not HISTORY_PATH.exists():
        return jsonify({"error": "History folder is not configured."}), 400

    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "finder").lower()

    if mode == "path":
        raw = body.get("path", "")
        cleaned = normalize_path_input(raw)
        if not cleaned:
            return jsonify({"error": "Empty destination path"}), 400
        dest_root = Path(cleaned)
        if not dest_root.exists():
            return jsonify({"error": f"Destination does not exist: {dest_root}"}), 400
        if not dest_root.is_dir():
            return jsonify({"error": f"Destination is not a folder: {dest_root}"}), 400
    else:
        chosen = pick_folder_mac(
            "Choose a folder to back up your Claude history into "
            "(a timestamped subfolder will be created there):"
        )
        if not chosen:
            return jsonify({"error": "No destination folder selected"}), 400
        dest_root = Path(chosen)

    # Refuse to back up inside the source folder — that would create an
    # ever-growing nested copy and could recurse through the walk.
    try:
        dest_resolved = dest_root.resolve()
        src_resolved = HISTORY_PATH.resolve()
        if dest_resolved == src_resolved or src_resolved in dest_resolved.parents:
            return jsonify({
                "error": (
                    "Destination is inside the history folder. "
                    "Please pick a location outside of it."
                )
            }), 400
    except Exception:
        pass  # best-effort safety check; continue if resolution fails

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"claude-history-backup-{stamp}"
    backup_dir = dest_root / backup_name

    try:
        files_copied, bytes_copied, errors = _copy_history_tree(HISTORY_PATH, backup_dir)
    except Exception as exc:
        return jsonify({"error": f"Backup failed: {exc}"}), 500

    # Drop a small manifest so the user can tell what this backup is later.
    try:
        manifest = {
            "generator": f"{APP_NAME} v{APP_VERSION}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(HISTORY_PATH),
            "destination": str(backup_dir),
            "files_copied": files_copied,
            "bytes_copied": bytes_copied,
            "errors": errors[:50],  # cap so the manifest stays small
            "notice": APP_COPYRIGHT,
        }
        (backup_dir / "BACKUP_INFO.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # manifest is nice-to-have, not essential

    return jsonify({
        "destination": str(backup_dir),
        "files_copied": files_copied,
        "bytes_copied": bytes_copied,
        "bytes_human": _human_size(bytes_copied),
        "errors": errors,
        "error_count": len(errors),
    })


# ── HTML / CSS / JS template ──────────────────────────────────────────────────
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude History Browser</title>
<meta name="application-name" content="Claude History Browser">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="alternate icon" href="/favicon.ico">
<link rel="mask-icon" href="/favicon.svg" color="#c67eff">
<link rel="apple-touch-icon" href="/favicon.svg">
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --border: #2e3250;
    --accent: #c67eff;
    --accent2: #7c9fff;
    --text: #e8eaf6;
    --text2: #9fa8c7;
    --text3: #5c6380;
    --user-bg: #1e2d4a;
    --asst-bg: #1e1a2e;
    --tool-bg: #1a2218;
    --think-bg: #1a1e12;
    --result-bg: #121824;
    --radius: 10px;
    --sidebar-w: 620px;
    --splitter-w: 6px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; height: 100vh; display: flex; flex-direction: column; }
  body.resizing { cursor: col-resize; user-select: none; }
  body.resizing * { user-select: none !important; }

  /* ── Header ── */
  header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; }
  header h1 { font-size: 16px; font-weight: 600; color: var(--accent); white-space: nowrap; cursor: pointer; user-select: none; padding: 2px 6px; border-radius: 6px; transition: background 0.15s, color 0.15s; }
  header h1:hover { background: var(--surface2); color: #e0a8ff; }
  header h1 span { color: var(--text2); font-weight: 400; }
  #search-global { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text); font-size: 13px; outline: none; }
  #search-global:focus { border-color: var(--accent); }
  #path-btn { background: var(--surface2); border: 1px solid var(--border); color: var(--text2); border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; white-space: nowrap; }
  #path-btn:hover { color: var(--accent); border-color: var(--accent); }

  /* ── About modal ── */
  #about-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: none; align-items: center; justify-content: center; z-index: 100; }
  #about-backdrop.open { display: flex; }
  #about-modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; max-width: 460px; width: calc(100% - 32px); padding: 22px 24px; box-shadow: 0 12px 48px rgba(0,0,0,0.5); color: var(--text); }
  #about-modal h2 { font-size: 18px; color: var(--accent); margin-bottom: 4px; }
  #about-modal .about-version { font-size: 12px; color: var(--text3); margin-bottom: 14px; }
  #about-modal dl { display: grid; grid-template-columns: 110px 1fr; gap: 6px 12px; font-size: 13px; margin-bottom: 14px; }
  #about-modal dt { color: var(--text3); }
  #about-modal dd { color: var(--text); word-break: break-word; }
  #about-modal a { color: var(--accent2); text-decoration: none; }
  #about-modal a:hover { text-decoration: underline; }
  #about-modal .about-copyright { font-size: 11px; color: var(--text3); border-top: 1px solid var(--border); padding-top: 10px; line-height: 1.5; }
  #about-close { margin-top: 14px; background: var(--accent); color: #0f1117; border: 0; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-weight: 600; font-size: 13px; }
  #about-close:hover { filter: brightness(1.1); }

  /* ── Layout ── */
  .body { display: flex; flex: 1; overflow: hidden; }

  /* ── Sidebar ── */
  aside { width: var(--sidebar-w); min-width: 320px; max-width: calc(100vw - 360px); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0; }
  .sidebar-top { padding: 10px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; align-items: center; gap: 8px; }
  #project-select { flex: 1; min-width: 0; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; color: var(--text); font-size: 13px; cursor: pointer; }

  /* ── Action buttons: Download + Copy, side by side ── */
  .action-row { display: flex; gap: 6px; }
  .action-btn { flex: 1; min-width: 0; border-radius: 6px; padding: 6px 8px; cursor: pointer; font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: center; transition: filter 0.15s, background 0.15s, color 0.15s, border-color 0.15s; }
  #download-btn { background: var(--accent); color: #0f1117; border: 1px solid var(--accent); }
  #download-btn:disabled { background: transparent; color: var(--accent); cursor: not-allowed; opacity: 0.55; }
  #download-btn:not(:disabled):hover { filter: brightness(1.1); }
  #copy-btn { background: transparent; color: var(--accent2); border: 1px solid var(--accent2); }
  #copy-btn:disabled { color: var(--text3); border-color: var(--border); cursor: not-allowed; opacity: 0.55; }
  #copy-btn:not(:disabled):hover { background: var(--accent2); color: #0f1117; }
  #copy-btn.copied { background: #2f8a4e; border-color: #2f8a4e; color: #fff; }
  /* Back-up button: uses a warm/amber tone so it reads as a "safety" action,
     visually distinct from download (accent) and copy (accent2). It's always
     enabled because backing up doesn't require any selection. */
  #backup-btn { background: transparent; color: #f0b45a; border: 1px solid #c88a3a; }
  #backup-btn:not(:disabled):hover { background: #f0b45a; color: #0f1117; border-color: #f0b45a; }
  #backup-btn:disabled { color: var(--text3); border-color: var(--border); cursor: not-allowed; opacity: 0.55; }
  #backup-btn.backed-up { background: #2f8a4e; border-color: #2f8a4e; color: #fff; }

  /* ── Backup result modal ── */
  #backup-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: none; align-items: center; justify-content: center; z-index: 120; }
  #backup-backdrop.open { display: flex; }
  #backup-modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; max-width: 560px; width: calc(100% - 32px); padding: 22px 24px; box-shadow: 0 12px 48px rgba(0,0,0,0.5); color: var(--text); }
  #backup-modal h2 { font-size: 17px; color: #f0b45a; margin-bottom: 6px; }
  #backup-modal .bm-sub { font-size: 12px; color: var(--text3); margin-bottom: 14px; line-height: 1.5; }
  #backup-modal dl { display: grid; grid-template-columns: 130px 1fr; gap: 6px 12px; font-size: 13px; margin-bottom: 14px; }
  #backup-modal dt { color: var(--text3); }
  #backup-modal dd { color: var(--text); word-break: break-all; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  #backup-modal .bm-errors { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; max-height: 160px; overflow-y: auto; font-size: 11px; color: #e89393; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; word-break: break-all; }
  #backup-modal .bm-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
  #backup-modal button { border: 0; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-weight: 600; font-size: 13px; }
  #backup-modal .bm-close { background: var(--accent); color: #0f1117; }
  #backup-modal .bm-close:hover { filter: brightness(1.1); }

  /* ── Splitter / resizer between sidebar and main ── */
  .splitter {
    width: var(--splitter-w);
    flex-shrink: 0;
    background: var(--border);
    cursor: col-resize;
    position: relative;
    transition: background 0.15s;
  }
  .splitter:hover,
  .splitter.dragging { background: var(--accent); }
  .splitter::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 2px;
    height: 40px;
    background: var(--text3);
    border-radius: 2px;
    opacity: 0.6;
  }
  .splitter:hover::after,
  .splitter.dragging::after { background: #fff; opacity: 0.9; }

  /* ── Active filter pills ── */
  .pills { display: flex; flex-wrap: wrap; gap: 6px; min-height: 0; }
  .pill { background: var(--surface2); border: 1px solid var(--border); border-radius: 999px; padding: 3px 10px; font-size: 11px; color: var(--text2); display: inline-flex; align-items: center; gap: 6px; }
  .pill .close { cursor: pointer; color: var(--text3); font-weight: 700; }
  .pill .close:hover { color: var(--accent); }

  /* ── Conversation table ── */
  #conv-count { padding: 6px 14px; font-size: 11px; color: var(--text3); border-bottom: 1px solid var(--border); flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; }
  #conv-list { flex: 1; overflow-y: auto; }
  /* Column layout: the CONVERSATION column is the most important, so give
     it a hard floor (minmax) and let it grow. Date and Project columns
     have their own floors so they stay readable but can shrink a little
     when the sidebar is narrow. */
  .col-header, .conv-item { display: grid; grid-template-columns: 28px minmax(280px, 2.6fr) minmax(88px, 1fr) minmax(110px, 1.1fr); align-items: stretch; }
  .col-header { background: var(--surface2); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 2; font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text3); }
  .col-header > div { padding: 8px 10px; border-right: 1px solid var(--border); }
  .col-header > div:last-child { border-right: 0; }
  .conv-item { border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.15s; }
  .conv-item:hover { background: var(--surface2); }
  .conv-item.active { background: var(--surface2); box-shadow: inset 3px 0 0 var(--accent); }
  .conv-item > .cell { padding: 10px; border-right: 1px solid var(--border); overflow: hidden; }
  .conv-item > .cell:last-child { border-right: 0; }
  .cell-check { display: flex; align-items: center; justify-content: center; padding: 0 !important; }
  .cell-check input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; accent-color: var(--accent); }
  .cell-main { min-width: 0; }
  .conv-title { font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--text); margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .conv-preview { font-size: 12px; color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conv-meta-sub { font-size: 10px; color: var(--text3); margin-top: 3px; }
  .cell-date, .cell-project { font-size: 11px; color: var(--text2); display: flex; flex-direction: column; justify-content: center; }
  .cell-date .date { color: var(--text); font-weight: 500; }
  .cell-date .time { color: var(--text3); margin-top: 2px; }
  .cell-project { color: var(--text); word-break: break-word; }
  /* Smaller, dimmer line shown under the project name when the conversation
     ran inside a Cowork session — so the nickname is still visible without
     dominating the column. */
  .cell-project .proj-session { font-size: 10px; color: var(--text3); margin-top: 2px; font-style: italic; }
  .filter-btn { background: transparent; border: 1px solid transparent; color: inherit; font: inherit; cursor: pointer; padding: 2px 4px; border-radius: 4px; text-align: left; width: 100%; }
  .filter-btn:hover { background: var(--bg); border-color: var(--accent); color: var(--accent); }

  /* ── Main panel ── */
  main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
  #welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--text3); padding: 20px; text-align: center; }
  #welcome h2 { color: var(--text2); }
  #conv-view { flex: 1; overflow-y: auto; padding: 20px 24px; display: none; }
  #conv-header { padding: 12px 24px; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; display: none; }
  #conv-header h2 { font-size: 15px; font-weight: 600; color: var(--text); }
  #conv-header .meta { font-size: 12px; color: var(--text3); margin-top: 3px; }
  /* Conversation toolbar: filter chips + compact toggle. Sits below the
     header, above the reader. Hidden until a conversation is open. */
  #conv-toolbar { display: none; align-items: center; gap: 12px; padding: 8px 24px; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap; }
  .filter-row { display: flex; align-items: center; gap: 6px; flex: 1; flex-wrap: wrap; min-width: 0; }
  .filter-row .filter-label { font-size: 10px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.06em; margin-right: 4px; }
  /* Per-category show/hide chip. Pressed (.on) = visible category. */
  .filter-btn-ct { background: transparent; border: 1px solid var(--border); color: var(--text3); border-radius: 4px; padding: 3px 10px; font-size: 11px; font-family: inherit; cursor: pointer; transition: all 0.15s ease; white-space: nowrap; }
  .filter-btn-ct:hover { color: var(--text); border-color: var(--accent); }
  .filter-btn-ct.on { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
  /* Compact-blocks toggle lives in the toolbar, pushed to the right. */
  #compact-toggle { background: transparent; color: var(--text3); border: 1px solid var(--border); border-radius: 4px; padding: 3px 10px; font-size: 11px; font-family: inherit; cursor: pointer; transition: all 0.15s ease; white-space: nowrap; margin-left: auto; }
  #compact-toggle:hover { border-color: var(--accent); color: var(--accent); }
  #compact-toggle.on { background: var(--accent); color: var(--bg); border-color: var(--accent); }
  /* Token tally in the conversation header. Slight accent colour + help
     cursor hints that hovering reveals a cache-usage breakdown tooltip. */
  #conv-header .meta .meta-tokens {
    color: var(--text2);
    cursor: help;
    border-bottom: 1px dotted var(--border);
  }

  /* ── Messages ── */
  .turn { margin-bottom: 18px; }
  .turn-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
  .turn.user .turn-label { color: var(--accent2); }
  .turn.assistant .turn-label { color: var(--accent); }
  /* Per-turn token badge sits inline after the role label. Muted color +
     help cursor hints that a tooltip (with full counts) is available. */
  .turn-tokens { font-weight: 500; color: var(--text3); text-transform: none; letter-spacing: 0; font-size: 10px; margin-left: 6px; border-bottom: 1px dotted var(--border); cursor: help; }
  /* padding-right leaves room for the per-turn copy button in the top-right. */
  .bubble { position: relative; border-radius: var(--radius); padding: 12px 64px 12px 16px; font-size: 13px; line-height: 1.6; transition: outline-color 0.15s ease; }
  /* Per-turn copy button — always visible at low opacity for discoverability,
     full opacity on bubble hover, and a brief green flash on successful copy. */
  .copy-turn-btn { position: absolute; top: 6px; right: 6px; background: rgba(0,0,0,0.25); border: 1px solid var(--border); color: var(--text3); border-radius: 4px; padding: 3px 8px; font-size: 10px; font-family: inherit; line-height: 1; cursor: pointer; opacity: 0.45; transition: opacity 0.15s ease, color 0.15s ease, border-color 0.15s ease, background 0.15s ease; }
  .bubble:hover .copy-turn-btn { opacity: 1; }
  .copy-turn-btn:hover { color: var(--accent); border-color: var(--accent); }
  .copy-turn-btn.flash { opacity: 1; background: var(--accent); color: var(--bg); border-color: var(--accent); }
  .turn.user .bubble { background: var(--user-bg); }
  .turn.assistant .bubble { background: var(--asst-bg); }
  .turn.active-turn .bubble { outline: 2px solid var(--accent); outline-offset: 3px; }
  /* Tool result turns: Claude's API wraps tool outputs in user-role messages,
     so they arrive labeled "user" but were never typed by the human. We show
     them in a quieter result-toned bubble so they're clearly distinguishable
     from actual user text. */
  .turn.tool-result .turn-label { color: var(--text3); }
  .turn.tool-result .bubble { background: var(--result-bg); border-left: 3px solid var(--border); }
  /* System turns: blocks that are purely synthetic — system-reminders, image
     markers, command messages — injected by the client rather than the user. */
  .turn.system .turn-label { color: var(--text3); }
  .turn.system .bubble { background: var(--surface); opacity: 0.85; border-left: 3px solid var(--border); }
  /* Inline meta blocks: a single metadata line inside an otherwise-user turn. */
  .block-meta { color: var(--text3); font-size: 11px; font-style: italic; opacity: 0.8; padding: 4px 8px; border-left: 2px solid var(--border); white-space: pre-wrap; word-break: break-word; }

  /* ── Content blocks ── */
  .block + .block { margin-top: 8px; }
  .block-text { white-space: pre-wrap; word-break: break-word; }
  .block-thinking { background: var(--think-bg); border: 1px solid #3a3e1a; border-radius: 6px; padding: 8px 12px; font-size: 12px; color: #9aaa60; }
  .block-thinking details summary { cursor: pointer; font-weight: 600; color: #b8c870; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .block-thinking .think-body { white-space: pre-wrap; margin-top: 6px; }
  .block-tool { background: var(--tool-bg); border: 1px solid #1e3020; border-radius: 6px; padding: 8px 12px; }
  .block-tool .tool-name { font-size: 11px; font-weight: 700; color: #6dcc88; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
  /* Default (full) view: no max-height, no overflow cap — tool/result blocks
     render in full. Compact view (toggle in header) caps them at 240px with
     a scrollbar so you can scan a long conversation without endless scrolling. */
  .block-tool pre { font-size: 11px; color: #8ecf9e; white-space: pre-wrap; word-break: break-all; }
  .block-result { background: var(--result-bg); border: 1px solid #1a2535; border-radius: 6px; padding: 8px 12px; }
  .block-result .result-label { font-size: 11px; font-weight: 600; color: var(--text3); margin-bottom: 4px; }
  .block-result pre { font-size: 11px; color: var(--text2); white-space: pre-wrap; word-break: break-all; }
  #conv-view.compact-blocks .block-tool pre,
  #conv-view.compact-blocks .block-result pre { max-height: 240px; overflow: auto; }

  /* ── Search results ── */
  #search-results { flex: 1; overflow-y: auto; padding: 16px 24px; display: none; }
  .sr-item { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; margin-bottom: 10px; cursor: pointer; }
  .sr-item:hover { border-color: var(--accent); }
  .sr-title { font-weight: 600; font-size: 13px; color: var(--text); margin-bottom: 4px; }
  .sr-meta { font-size: 11px; color: var(--text3); margin-bottom: 6px; }
  .sr-snippet { font-size: 12px; color: var(--text2); background: var(--surface2); border-radius: 4px; padding: 5px 8px; margin-top: 4px; white-space: pre-wrap; word-break: break-word; }
  .sr-snippet em { color: var(--accent); font-style: normal; font-weight: 600; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<header>
  <h1 id="app-title" title="About this app">Claude <span>History Browser</span></h1>
  <input id="search-global" type="search" placeholder="Search all conversations... (press Enter)" />
  <button id="path-btn" title="Change history folder">📂 Change folder</button>
</header>

<!-- About modal -->
<div id="about-backdrop" role="dialog" aria-modal="true" aria-labelledby="about-title">
  <div id="about-modal">
    <h2 id="about-title">Claude History Browser</h2>
    <div class="about-version" id="about-version">v—</div>
    <dl>
      <dt>Author</dt><dd id="about-author">—</dd>
      <dt>License</dt><dd id="about-license">—</dd>
      <dt>Repository</dt><dd><a id="about-repo" href="#" target="_blank" rel="noopener noreferrer">—</a></dd>
    </dl>
    <div class="about-copyright" id="about-copyright">—</div>
    <button id="about-close" type="button">Close</button>
  </div>
</div>

<!-- Backup result modal -->
<div id="backup-backdrop" role="dialog" aria-modal="true" aria-labelledby="backup-title">
  <div id="backup-modal">
    <h2 id="backup-title">🛟 Backup complete</h2>
    <div class="bm-sub" id="backup-sub">Your history folder has been copied to a safe location.</div>
    <dl>
      <dt>Destination</dt><dd id="backup-dest">—</dd>
      <dt>Files copied</dt><dd id="backup-files">—</dd>
      <dt>Total size</dt><dd id="backup-size">—</dd>
    </dl>
    <div id="backup-errors-wrap" style="display:none;">
      <div style="font-size:12px;color:var(--text3);margin-bottom:4px;">
        <span id="backup-errors-count">0</span> file(s) could not be copied:
      </div>
      <div class="bm-errors" id="backup-errors"></div>
    </div>
    <div class="bm-actions">
      <button id="backup-close" class="bm-close" type="button">Close</button>
    </div>
  </div>
</div>

<div class="body">
  <aside>
    <div class="sidebar-top">
      <div class="row">
        <select id="project-select"><option value="">All projects</option></select>
      </div>
      <div class="action-row">
        <button id="download-btn" class="action-btn" disabled title="Download the selected conversations as a single .md file">⬇︎ Download (0)</button>
        <button id="copy-btn" class="action-btn" disabled title="Copy the selected conversations to the clipboard as Markdown">⧉ Copy (0)</button>
        <button id="backup-btn" class="action-btn" title="Back up the entire history folder to another location so it survives system cleanups or Claude app updates">🛟 Back-up</button>
      </div>
      <div id="filter-pills" class="pills"></div>
    </div>
    <div id="conv-count">Loading…</div>
    <div class="col-header">
      <div title="Select all visible" style="display:flex;align-items:center;justify-content:center;padding:0;">
        <input id="select-all" type="checkbox" style="width:16px;height:16px;cursor:pointer;accent-color:var(--accent);" />
      </div>
      <div>Conversation</div>
      <div>Date &amp; Hour</div>
      <div>Project</div>
    </div>
    <div id="conv-list"></div>
  </aside>

  <div id="splitter" class="splitter" title="Drag to resize"></div>

  <main>
    <div id="welcome">
      <h2>Claude History Browser</h2>
      <p>Select a conversation from the left, or search above.<br/>
      Check boxes on the left to bundle conversations into a single <code>.md</code> export.</p>
    </div>
    <div id="conv-header">
      <h2 id="ch-title"></h2>
      <div class="meta" id="ch-meta"></div>
    </div>
    <!-- Toolbar: category filters + compact-blocks toggle. Lives between the
         header and the reader. All chips are ON by default (everything shown). -->
    <div id="conv-toolbar">
      <div class="filter-row">
        <span class="filter-label">Show:</span>
        <button class="filter-btn-ct on" data-filter="you"      type="button" title="Show/hide the text you typed (plus [Image:…] and system-reminder metadata that came from your side).">👤 You</button>
        <button class="filter-btn-ct on" data-filter="claude"   type="button" title="Show/hide Claude's prose replies. Does NOT hide the tool calls / thinking / results that sit alongside them — those have their own chips.">✦ Claude</button>
        <button class="filter-btn-ct on" data-filter="tool"     type="button" title="Show/hide 🔧 tool-call blocks (what Claude asked a tool to do). Leaves the surrounding Claude message in place.">🔧 Tool</button>
        <button class="filter-btn-ct on" data-filter="thinking" type="button" title="Show/hide 🧠 internal reasoning blocks. Leaves the surrounding Claude message in place.">🧠 Thinking</button>
        <button class="filter-btn-ct on" data-filter="result"   type="button" title="Show/hide 📤 tool outputs and ⚙️ system-injected turns. These appear between Claude's calls and her next reply.">📤 Result</button>
      </div>
      <button id="compact-toggle" type="button" title="Clip long tool inputs and tool results at ~240px with an inner scrollbar, so you can scan a long conversation faster. Toggle off to see each block in full.">🗜 Compact tool blocks</button>
    </div>
    <div id="conv-view"></div>
    <div id="search-results"></div>
  </main>
</div>

<script>
let allConversations = [];   // raw results from server (already project-filtered server-side)
let displayedConversations = []; // after client-side day filter
let currentProject = '';
let dayFilter = '';          // yyyy-mm-dd (client side)
let selected = new Set();    // conv ids selected for download
let currentTurnIndex = -1;   // index of the focused .turn in the reading pane (-1 = none)

// ── Compact-blocks toggle ────────────────────────────────────────────────────
// Caps .block-tool pre and .block-result pre at 240px with an inner scrollbar.
// Default is OFF (full content visible). Preference persists via localStorage.
function applyCompactBlocks(on) {
  const view = document.getElementById('conv-view');
  const btn  = document.getElementById('compact-toggle');
  if (view) view.classList.toggle('compact-blocks', !!on);
  if (btn) {
    btn.classList.toggle('on', !!on);
    btn.textContent = on ? '🗜 Compact: on' : '🗜 Compact tool blocks';
  }
  try { localStorage.setItem('chb-compact-blocks', on ? '1' : '0'); } catch (e) {}
}
function initCompactToggle() {
  let saved = '0';
  try { saved = localStorage.getItem('chb-compact-blocks') || '0'; } catch (e) {}
  applyCompactBlocks(saved === '1');
  const btn = document.getElementById('compact-toggle');
  if (btn) btn.addEventListener('click', () => {
    const view = document.getElementById('conv-view');
    const next = !(view && view.classList.contains('compact-blocks'));
    applyCompactBlocks(next);
  });
}

// ── Turn / block filters ─────────────────────────────────────────────────────
// Five independent chips that show/hide categories in the reading pane:
//   you      — user turns (text you typed)
//   claude   — assistant turns (Claude's replies)
//   tool     — tool_use blocks (🔧) — lives inside assistant turns
//   thinking — thinking blocks (🧠) — lives inside assistant turns
//   result   — tool_result blocks AND "📤 Tool result" / "⚙️ System" user-role turns
//
// A chip ON = category visible. A chip OFF = category hidden.
// State persists in localStorage under `chb-turn-filters` as a comma list of
// enabled categories (so "add a new filter later" keeps older prefs usable).
let FILTERS = {you: true, claude: true, tool: true, thinking: true, result: true};

function applyFilters() {
  const view = document.getElementById('conv-view');
  if (!view) return;
  const turns = view.querySelectorAll('.turn');
  turns.forEach(turnEl => {
    const isUser      = turnEl.classList.contains('user');
    const isAssistant = turnEl.classList.contains('assistant');
    const isToolRes   = turnEl.classList.contains('tool-result');
    const isSystem    = turnEl.classList.contains('system');

    // Block-level visibility. Each block type maps to exactly one chip:
    //   .block-text    inside a user turn       → YOU
    //   .block-text    inside an assistant turn → CLAUDE
    //   .block-thinking (always in assistant)   → THINKING
    //   .block-tool    (always in assistant)    → TOOL
    //   .block-result                            → RESULT
    //   .block-meta    (image markers, system-reminders in user turn) → YOU
    //     (meta blocks are muted filler that sits alongside the user's real
    //     typed text; hiding YOU should take them with it so the bubble
    //     doesn't stay visible as just a grey metadata line.)
    //
    // A block starts visible and can be flipped hidden by the matching OFF
    // chip. The turn then shows iff at least one of its blocks is visible.
    const blocks = turnEl.querySelectorAll('.block');
    let anyVisible = false;
    blocks.forEach(b => {
      let show = true;
      if (b.classList.contains('block-text')) {
        if (isUser && !FILTERS.you) show = false;
        if (isAssistant && !FILTERS.claude) show = false;
      }
      if (b.classList.contains('block-thinking') && !FILTERS.thinking) show = false;
      if (b.classList.contains('block-tool')     && !FILTERS.tool)     show = false;
      if (b.classList.contains('block-result')   && !FILTERS.result)   show = false;
      if (b.classList.contains('block-meta')     && !FILTERS.you)      show = false;
      b.style.display = show ? '' : 'none';
      if (show) anyVisible = true;
    });

    // Category-level gates for turns whose identity isn't captured by their
    // blocks. "Tool result" and "System" user-role turns sit under RESULT in
    // the UI, so RESULT's chip state governs them even though the individual
    // block rules above would already hide them via .block-result / .block-meta.
    let turnHidden = false;
    if ((isToolRes || isSystem) && !FILTERS.result) turnHidden = true;

    // Empty-turn fallback (a turn with no .block children, which shouldn't
    // normally happen but defends against future parser changes): use the
    // classifier kind to decide visibility.
    if (!blocks.length) {
      if (isUser && !FILTERS.you) turnHidden = true;
      if (isAssistant && !FILTERS.claude) turnHidden = true;
    }

    const hideByEmpty = blocks.length > 0 && !anyVisible;
    turnEl.style.display = (turnHidden || hideByEmpty) ? 'none' : '';
  });

  // Clamp the active-turn cursor to a visible turn so arrow-nav stays usable.
  const visibleTurns = Array.from(turns).filter(t => t.style.display !== 'none');
  if (!visibleTurns.length) {
    currentTurnIndex = -1;
  } else if (currentTurnIndex >= 0 && turns[currentTurnIndex] && turns[currentTurnIndex].style.display === 'none') {
    // The previously active turn got hidden — jump to the first visible one.
    const firstIdx = Array.from(turns).indexOf(visibleTurns[0]);
    if (firstIdx >= 0) setActiveTurn(firstIdx, {scroll: false});
  }
}

function saveFilters() {
  try {
    const on = Object.keys(FILTERS).filter(k => FILTERS[k]);
    localStorage.setItem('chb-turn-filters', on.join(','));
  } catch (e) {}
}

function initFilters() {
  // Load persisted prefs (if any). Absence = all on (default).
  try {
    const raw = localStorage.getItem('chb-turn-filters');
    if (raw !== null) {
      const on = new Set(raw.split(',').filter(Boolean));
      Object.keys(FILTERS).forEach(k => { FILTERS[k] = on.has(k); });
    }
  } catch (e) {}

  // Reflect state onto the chips + wire click handlers.
  document.querySelectorAll('.filter-btn-ct').forEach(btn => {
    const key = btn.dataset.filter;
    if (!key) return;
    btn.classList.toggle('on', !!FILTERS[key]);
    btn.addEventListener('click', () => {
      FILTERS[key] = !FILTERS[key];
      btn.classList.toggle('on', FILTERS[key]);
      saveFilters();
      applyFilters();
    });
  });
}

// ── Splitter / resizer ───────────────────────────────────────────────────────
function setSidebarWidth(px) {
  const min = 320;
  const max = Math.max(min + 40, window.innerWidth - 360);
  const clamped = Math.min(Math.max(px, min), max);
  document.documentElement.style.setProperty('--sidebar-w', clamped + 'px');
  try { localStorage.setItem('chb-sidebar-w', String(clamped)); } catch (e) {}
}

function initSplitter() {
  // Restore saved width
  try {
    const saved = parseInt(localStorage.getItem('chb-sidebar-w') || '', 10);
    if (!Number.isNaN(saved) && saved > 0) setSidebarWidth(saved);
  } catch (e) {}

  const splitter = document.getElementById('splitter');
  if (!splitter) return;

  let dragging = false;
  const onMove = (e) => {
    if (!dragging) return;
    const x = (e.touches ? e.touches[0].clientX : e.clientX);
    setSidebarWidth(x);
    if (e.cancelable) e.preventDefault();
  };
  const stop = () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove('dragging');
    document.body.classList.remove('resizing');
  };
  const start = (e) => {
    dragging = true;
    splitter.classList.add('dragging');
    document.body.classList.add('resizing');
    if (e.cancelable) e.preventDefault();
  };

  splitter.addEventListener('mousedown', start);
  splitter.addEventListener('touchstart', start, {passive: false});
  document.addEventListener('mousemove', onMove);
  document.addEventListener('touchmove', onMove, {passive: false});
  document.addEventListener('mouseup', stop);
  document.addEventListener('touchend', stop);

  // Double-click resets to default width
  splitter.addEventListener('dblclick', () => setSidebarWidth(620));
}

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  initSplitter();
  initSelectAll();
  initCompactToggle();
  initFilters();
  await loadProjects();
  await loadConversations();
}

function initSelectAll() {
  const el = document.getElementById('select-all');
  if (!el) return;
  el.addEventListener('change', () => {
    if (el.checked) {
      displayedConversations.forEach(c => selected.add(c.id));
    } else {
      displayedConversations.forEach(c => selected.delete(c.id));
    }
    renderList(displayedConversations);
  });
}

function syncSelectAllCheckbox() {
  const el = document.getElementById('select-all');
  if (!el) return;
  if (!displayedConversations.length) {
    el.checked = false;
    el.indeterminate = false;
    return;
  }
  const total = displayedConversations.length;
  const sel = displayedConversations.filter(c => selected.has(c.id)).length;
  el.checked = sel === total;
  el.indeterminate = sel > 0 && sel < total;
}

async function loadProjects() {
  const res = await fetch('/api/projects');
  const projects = await res.json();
  const sel = document.getElementById('project-select');
  projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    sel.appendChild(opt);
  });
  sel.addEventListener('change', () => {
    currentProject = sel.value;
    loadConversations();
  });
}

async function loadConversations(q = '') {
  let url = '/api/conversations';
  const params = new URLSearchParams();
  if (currentProject) params.set('project', currentProject);
  if (q) params.set('q', q);
  if ([...params].length) url += '?' + params;

  const res = await fetch(url);
  allConversations = await res.json();
  applyFiltersAndRender();
}

function applyFiltersAndRender() {
  let convs = allConversations.slice();
  if (dayFilter) {
    convs = convs.filter(c => {
      const iso = c.last_ts || c.first_ts;
      if (!iso) return false;
      return iso.slice(0, 10) === dayFilter;
    });
  }
  displayedConversations = convs;
  renderList(convs);
  renderPills();
  updateDownloadBtn();
}

function renderPills() {
  const pills = document.getElementById('filter-pills');
  pills.innerHTML = '';
  if (currentProject) {
    pills.appendChild(mkPill(`project: ${currentProject}`, () => {
      currentProject = '';
      document.getElementById('project-select').value = '';
      loadConversations();
    }));
  }
  if (dayFilter) {
    pills.appendChild(mkPill(`day: ${dayFilter}`, () => {
      dayFilter = '';
      applyFiltersAndRender();
    }));
  }
}

function mkPill(label, onClose) {
  const el = document.createElement('span');
  el.className = 'pill';
  el.innerHTML = `${esc(label)} <span class="close" title="Clear">✕</span>`;
  el.querySelector('.close').addEventListener('click', onClose);
  return el;
}

function renderList(convs) {
  const list = document.getElementById('conv-list');
  const count = document.getElementById('conv-count');
  count.innerHTML = `<span>${convs.length} conversation${convs.length !== 1 ? 's' : ''}</span>`
    + (selected.size ? `<span>${selected.size} selected</span>` : '');
  list.innerHTML = '';
  convs.forEach(c => {
    const div = document.createElement('div');
    div.className = 'conv-item' + (selected.has(c.id) ? ' active-selected' : '');
    div.dataset.id = c.id;
    const iso = c.last_ts || c.first_ts || '';
    const dayStr = iso ? iso.slice(0, 10) : '';
    const d = iso ? new Date(iso) : null;
    const dateDisp = d ? d.toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'}) : '—';
    const timeDisp = d ? d.toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'}) : '';

    div.innerHTML = `
      <div class="cell cell-check">
        <input type="checkbox" ${selected.has(c.id) ? 'checked' : ''} />
      </div>
      <div class="cell cell-main">
        <div class="conv-title">${esc(c.title)}</div>
        <div class="conv-preview">${esc(c.preview)}</div>
        <div class="conv-meta-sub">${c.user_count} msgs · ${esc(c.model || '')}</div>
      </div>
      <div class="cell cell-date">
        <button class="filter-btn" data-day="${dayStr}" title="Filter to this day">
          <div class="date">${dateDisp}</div>
          <div class="time">${timeDisp}</div>
        </button>
      </div>
      <div class="cell cell-project">
        <button class="filter-btn" data-project="${esc(c.project)}"
          title="${esc(c.project_session ? 'Filter to this project — Cowork session: ' + c.project_session : 'Filter to this project')}">
          <div>${esc(c.project)}</div>
          ${c.project_session && c.project_session !== c.project
              ? `<div class="proj-session">↳ ${esc(c.project_session)}</div>`
              : ''}
        </button>
      </div>`;

    // Checkbox handler
    const cb = div.querySelector('input[type="checkbox"]');
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', () => {
      if (cb.checked) selected.add(c.id);
      else selected.delete(c.id);
      updateDownloadBtn();
      const countEl = document.getElementById('conv-count');
      countEl.innerHTML = `<span>${convs.length} conversation${convs.length !== 1 ? 's' : ''}</span>`
        + (selected.size ? `<span>${selected.size} selected</span>` : '');
    });

    // Date filter
    const dayBtn = div.querySelector('[data-day]');
    dayBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!dayStr) return;
      dayFilter = dayStr;
      applyFiltersAndRender();
    });

    // Project filter
    const projBtn = div.querySelector('[data-project]');
    projBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      currentProject = c.project;
      document.getElementById('project-select').value = c.project;
      loadConversations();
    });

    // Row click → open conversation
    div.addEventListener('click', () => openConversation(c));

    list.appendChild(div);
  });
}

function updateDownloadBtn() {
  const dl = document.getElementById('download-btn');
  const cp = document.getElementById('copy-btn');
  const n = selected.size;
  if (dl) {
    dl.textContent = `⬇︎ Download (${n})`;
    dl.disabled = n === 0;
  }
  if (cp) {
    // Don't overwrite the transient "Copied!" label while it's showing.
    if (!cp.classList.contains('copied')) {
      cp.textContent = `⧉ Copy (${n})`;
    }
    cp.disabled = n === 0;
  }
  syncSelectAllCheckbox();
}

// ── Open conversation ────────────────────────────────────────────────────────
async function openConversation(c) {
  // Highlight active
  document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
  const el = document.querySelector(`.conv-item[data-id="${c.id}"]`);
  if (el) el.classList.add('active');

  // Show header + toolbar
  const header = document.getElementById('conv-header');
  header.style.display = 'block';
  const toolbar = document.getElementById('conv-toolbar');
  if (toolbar) toolbar.style.display = 'flex';
  document.getElementById('ch-title').textContent = c.title;
  const date = c.last_ts ? new Date(c.last_ts).toLocaleString() : '';
  const projLabel = c.project_session && c.project_session !== c.project
    ? `${c.project} (${c.project_session})`
    : c.project;

  // Build a token summary segment for the header. We show input/output totals
  // inline (compact, e.g. "124.5K in / 48.2K out") and surface the cache-read
  // / cache-creation breakdown as a tooltip so the header stays scannable.
  const metaEl = document.getElementById('ch-meta');
  metaEl.innerHTML = '';

  const leftText = `${projLabel}  ·  ${c.user_count} messages  ·  `;
  metaEl.appendChild(document.createTextNode(leftText));

  if (typeof c.tokens_in === 'number' || typeof c.tokens_out === 'number') {
    const tokenSpan = document.createElement('span');
    tokenSpan.className = 'meta-tokens';
    tokenSpan.textContent = `${formatTokens(c.tokens_in)} in / ${formatTokens(c.tokens_out)} out`;
    // Tooltip: full counts with commas + cache breakdown.
    const tipParts = [
      `Input: ${(c.tokens_in || 0).toLocaleString()} tokens`,
      `Output: ${(c.tokens_out || 0).toLocaleString()} tokens`,
    ];
    if (c.tokens_cache_read) {
      tipParts.push(`Cache read: ${c.tokens_cache_read.toLocaleString()} tokens`);
    }
    if (c.tokens_cache_creation) {
      tipParts.push(`Cache write: ${c.tokens_cache_creation.toLocaleString()} tokens`);
    }
    tipParts.push('', 'Totals are summed across assistant turns — not a snapshot of the context window.');
    tokenSpan.title = tipParts.join('\n');
    metaEl.appendChild(tokenSpan);
    metaEl.appendChild(document.createTextNode('  ·  '));
  }

  metaEl.appendChild(document.createTextNode(`${date}  ·  ${c.model || ''}`));

  // Hide search results / welcome
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('search-results').style.display = 'none';

  const view = document.getElementById('conv-view');
  view.style.display = 'block';
  view.innerHTML = '<p style="color:var(--text3);padding:20px">Loading…</p>';

  const res = await fetch(`/api/conversation/${c.id}`);
  const data = await res.json();
  renderConversation(data.turns, view);
}

// ── Reading-pane keyboard navigation ─────────────────────────────────────────
//
// UP/DOWN arrows move the "active turn" cursor through the selected
// conversation's messages. The active turn gets a subtle outline around its
// bubble and is smooth-scrolled into view. We only intercept the keys when:
//   - the reading pane (#conv-view) is visible,
//   - the active element isn't an input/textarea/select/contenteditable,
//   - no modifier key (Ctrl/Meta/Alt) is held — so Cmd-Up / Cmd-Down still
//     jump to top/bottom as the browser normally does.

function setActiveTurn(idx, {scroll = true} = {}) {
  const view = document.getElementById('conv-view');
  if (!view) return;
  const turns = view.querySelectorAll('.turn');
  if (!turns.length) { currentTurnIndex = -1; return; }
  // Clamp
  if (idx < 0) idx = 0;
  if (idx >= turns.length) idx = turns.length - 1;
  // Clear previous highlight
  view.querySelectorAll('.turn.active-turn').forEach(el => el.classList.remove('active-turn'));
  const el = turns[idx];
  if (!el) return;
  el.classList.add('active-turn');
  currentTurnIndex = idx;
  if (scroll) {
    el.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
}

function moveTurn(delta) {
  const view = document.getElementById('conv-view');
  if (!view) return;
  const turns = view.querySelectorAll('.turn');
  if (!turns.length) return;
  const start = currentTurnIndex < 0 ? (delta > 0 ? -1 : turns.length) : currentTurnIndex;
  setActiveTurn(start + delta);
}

document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown') return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  // Skip when typing in an input-ish element
  const t = ev.target;
  if (t) {
    const tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || t.isContentEditable) return;
  }
  const view = document.getElementById('conv-view');
  if (!view || view.style.display === 'none' || view.offsetParent === null) return;
  ev.preventDefault();
  moveTurn(ev.key === 'ArrowDown' ? 1 : -1);
});

// Delegated click handler for the reading pane. Handles two things:
//   1. Copy button inside a bubble → write the turn's pre-computed text to
//      clipboard and flash the button. Stops propagation so it doesn't also
//      trigger the click-to-activate path below.
//   2. Any other click inside a .turn → move the active-turn cursor there,
//      so subsequent ↑/↓ navigation continues from the spot the user picked.
document.getElementById('conv-view').addEventListener('click', (ev) => {
  const copyBtn = ev.target.closest && ev.target.closest('.copy-turn-btn');
  if (copyBtn) {
    copyTurnText(copyBtn);
    ev.stopPropagation();
    return;
  }
  const turnEl = ev.target.closest && ev.target.closest('.turn');
  if (!turnEl) return;
  const idx = parseInt(turnEl.dataset.turnIndex, 10);
  if (Number.isNaN(idx)) return;
  setActiveTurn(idx, {scroll: false});
});

// The JSONL `user` role is the Anthropic API's catch-all for "anything the
// assistant didn't produce." That includes the human's typed text, but also
// tool_result blocks (required by the API to live under a user message) and
// synthetic metadata blocks injected by the client (system reminders, image
// markers, /command messages). We classify the turn so the UI can label it
// honestly instead of pretending the human wrote all of it.
const META_TEXT_RE = /^\s*(?:\[Image:|<system-reminder>|<command-name>|<command-message>|<command-args>)/;
function isMetaTextBlock(b) {
  return b && b.type === 'text' && typeof b.text === 'string' && META_TEXT_RE.test(b.text);
}
function classifyTurn(turn) {
  if (turn.role !== 'user') return {kind: turn.role, label: '✦ Claude'};
  const blocks = turn.blocks || [];
  if (!blocks.length) return {kind: 'user', label: '👤 You'};
  const isToolResult = b => b.type === 'tool_result';
  if (blocks.every(isToolResult)) return {kind: 'tool-result', label: '📤 Tool result'};
  if (blocks.every(b => isToolResult(b) || isMetaTextBlock(b))) return {kind: 'system', label: '⚙️ System'};
  return {kind: 'user', label: '👤 You'};
}

// Build a plain-text copy payload for a turn. Keeps light separators so a
// thinking / tool-use / tool-result stays distinguishable when pasted.
function buildTurnCopyText(turn) {
  const parts = [];
  (turn.blocks || []).forEach(b => {
    if (!b) return;
    if (b.type === 'text')        parts.push(b.text || '');
    else if (b.type === 'thinking')    parts.push('🧠 Thinking\n' + (b.text || ''));
    else if (b.type === 'tool_use')    parts.push('🔧 ' + (b.name || 'tool') + '\n' + (b.input || ''));
    else if (b.type === 'tool_result') parts.push('📤 Result\n' + (b.text || ''));
  });
  return parts.join('\n\n').trim();
}

function flashCopyBtn(btn, ok) {
  const prev = btn.textContent;
  btn.textContent = ok ? '✓ Copied' : '✗ Failed';
  btn.classList.add('flash');
  setTimeout(() => {
    btn.textContent = prev;
    btn.classList.remove('flash');
  }, 1100);
}

function copyTurnText(btn) {
  const turnEl = btn.closest('.turn');
  if (!turnEl) return;
  const text = turnEl.dataset.copyText || '';
  try {
    const p = navigator.clipboard && navigator.clipboard.writeText(text);
    if (p && typeof p.then === 'function') {
      p.then(() => flashCopyBtn(btn, true)).catch(() => flashCopyBtn(btn, false));
    } else {
      // Legacy fallback — synchronous execCommand via a hidden textarea.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      flashCopyBtn(btn, !!ok);
    }
  } catch (e) {
    flashCopyBtn(btn, false);
  }
}

function renderConversation(turns, container) {
  container.innerHTML = '';
  turns.forEach((turn, idx) => {
    const {kind, label: labelText} = classifyTurn(turn);
    const div = document.createElement('div');
    div.className = `turn ${kind}`;
    div.dataset.turnIndex = String(idx);
    // Pre-compute the clean text payload so the copy button doesn't have to
    // re-parse the DOM (which would also pick up the button's own label).
    div.dataset.copyText = buildTurnCopyText(turn);

    const label = document.createElement('div');
    label.className = 'turn-label';
    label.textContent = labelText;
    // Per-turn token badge. The backend attaches tokens_in / tokens_out to
    // every assistant turn (user turns don't have a usage dict). We render
    // a small inline badge so the reader can see which single reply was
    // the expensive one. Tooltip spells out the full counts.
    if (kind === 'assistant' && (typeof turn.tokens_in === 'number' || typeof turn.tokens_out === 'number')) {
      const tok = document.createElement('span');
      tok.className = 'turn-tokens';
      tok.textContent = `${formatTokens(turn.tokens_in || 0)} in / ${formatTokens(turn.tokens_out || 0)} out`;
      tok.title =
        `Input: ${(turn.tokens_in || 0).toLocaleString()} tokens\n` +
        `Output: ${(turn.tokens_out || 0).toLocaleString()} tokens\n\n` +
        `Per-turn usage reported by the API for this single reply.`;
      label.appendChild(document.createTextNode(' '));
      label.appendChild(tok);
    }
    div.appendChild(label);

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'copy-turn-btn';
    copyBtn.title = 'Copy this message to clipboard';
    copyBtn.setAttribute('aria-label', 'Copy message');
    copyBtn.textContent = '📋 Copy';
    bubble.appendChild(copyBtn);

    (turn.blocks || []).forEach(block => {
      const bd = document.createElement('div');
      bd.className = 'block';
      if (block.type === 'text') {
        // Inside a regular user turn, a single metadata line (image marker,
        // system-reminder) gets muted styling instead of being rendered as
        // the user's speech — keeps the real typed text visually dominant.
        if (kind === 'user' && isMetaTextBlock(block)) {
          bd.className += ' block-meta';
          bd.textContent = block.text;
        } else {
          bd.className += ' block-text';
          bd.textContent = block.text;
        }
      } else if (block.type === 'thinking') {
        bd.className += ' block-thinking';
        bd.innerHTML = `<details><summary>🧠 Thinking</summary><div class="think-body">${esc(block.text)}</div></details>`;
      } else if (block.type === 'tool_use') {
        bd.className += ' block-tool';
        bd.innerHTML = `<div class="tool-name">🔧 ${esc(block.name)}</div><pre>${esc(block.input)}</pre>`;
      } else if (block.type === 'tool_result') {
        bd.className += ' block-result';
        bd.innerHTML = `<div class="result-label">📤 Result</div><pre>${esc(block.text)}</pre>`;
      }
      bubble.appendChild(bd);
    });

    div.appendChild(bubble);
    container.appendChild(div);
  });
  container.scrollTop = 0;

  // Apply active filters so newly rendered turns/blocks respect any chips the
  // user has toggled off. Call before setActiveTurn so we skip hidden turns.
  applyFilters();

  // Reset the active-turn cursor to the first VISIBLE turn (if any). No scroll
  // here — the reader is already at the top; the keyboard handler will scroll
  // on move.
  const firstVisible = Array.from(container.querySelectorAll('.turn'))
    .findIndex(t => t.style.display !== 'none');
  currentTurnIndex = firstVisible >= 0 ? firstVisible : -1;
  setActiveTurn(currentTurnIndex, {scroll: false});
}

// ── Download selected as Markdown ────────────────────────────────────────────
document.getElementById('download-btn').addEventListener('click', async () => {
  if (!selected.size) return;
  const btn = document.getElementById('download-btn');
  const originalText = btn.textContent;
  btn.textContent = 'Preparing…';
  btn.disabled = true;

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ids: [...selected]}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({error: 'Download failed'}));
      alert(err.error || 'Download failed');
      return;
    }
    const blob = await res.blob();
    const dispo = res.headers.get('Content-Disposition') || '';
    const m = dispo.match(/filename="([^"]+)"/);
    const filename = m ? m[1] : 'claude-history.md';

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } finally {
    btn.textContent = originalText;
    btn.disabled = selected.size === 0;
  }
});

// ── Copy selected as Markdown (to clipboard) ─────────────────────────────────
//
// Copying from a button is awkward in Safari: once we `await fetch()`, the
// user-gesture required by `navigator.clipboard.writeText` is consumed and
// both `writeText` and the legacy `execCommand('copy')` silently fail.
//
// The fix is the `ClipboardItem` + Promise pattern: `clipboard.write([item])`
// is invoked synchronously inside the click handler, while the Blob it
// contains resolves asynchronously. Safari/WebKit explicitly supports this.
// Chrome / Firefox / Edge also support it.
//
// If that still fails (very old browser, permission denied, etc.), we fall
// through to legacy methods and finally to a modal with a pre-selected
// textarea so the user can always Cmd/Ctrl+C manually.

async function fetchExportMarkdown(ids) {
  const res = await fetch('/api/copy', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids}),
  });
  if (!res.ok) {
    let msg = 'Copy failed';
    try { msg = (await res.json()).error || msg; } catch (_) {}
    throw new Error(msg);
  }
  const data = await res.json();
  return data.markdown || '';
}

function legacyCopyFallback(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch (_) {
    return false;
  }
}

// Modal fallback: if both clipboard APIs refuse, show the text with the
// textarea already focused and selected so the user can just hit Cmd/Ctrl+C.
function ensureManualCopyModal() {
  let bd = document.getElementById('manual-copy-backdrop');
  if (bd) return bd;
  bd = document.createElement('div');
  bd.id = 'manual-copy-backdrop';
  bd.setAttribute('role', 'dialog');
  bd.setAttribute('aria-modal', 'true');
  bd.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,0.55);display:none;' +
    'align-items:center;justify-content:center;z-index:110;';
  bd.innerHTML = `
    <div style="background:var(--surface);border:1px solid var(--border);
                border-radius:12px;max-width:720px;width:calc(100% - 32px);
                max-height:80vh;padding:20px 22px;color:var(--text);
                display:flex;flex-direction:column;gap:10px;
                box-shadow:0 12px 48px rgba(0,0,0,0.5);">
      <div style="font-size:15px;font-weight:600;color:var(--accent);">
        Copy Markdown manually
      </div>
      <div style="font-size:12px;color:var(--text2);line-height:1.5;">
        Your browser blocked the clipboard API for this action. The text is
        selected below — press <kbd>⌘C</kbd> (Mac) or <kbd>Ctrl+C</kbd>
        (Windows/Linux) to copy, then close this window.
      </div>
      <textarea id="manual-copy-textarea" readonly
        style="flex:1;min-height:260px;background:var(--bg);
               color:var(--text);border:1px solid var(--border);
               border-radius:6px;padding:10px 12px;font-family:ui-monospace,
               SFMono-Regular,Menlo,monospace;font-size:12px;resize:vertical;
               white-space:pre;"></textarea>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button id="manual-copy-try" type="button"
          style="background:var(--accent2);color:#0f1117;border:0;
                 border-radius:6px;padding:6px 14px;cursor:pointer;
                 font-weight:600;font-size:13px;">Try copy again</button>
        <button id="manual-copy-close" type="button"
          style="background:var(--accent);color:#0f1117;border:0;
                 border-radius:6px;padding:6px 14px;cursor:pointer;
                 font-weight:600;font-size:13px;">Close</button>
      </div>
    </div>`;
  document.body.appendChild(bd);

  const close = () => { bd.style.display = 'none'; };
  bd.addEventListener('click', (e) => { if (e.target === bd) close(); });
  bd.querySelector('#manual-copy-close').addEventListener('click', close);
  bd.querySelector('#manual-copy-try').addEventListener('click', () => {
    const ta = bd.querySelector('#manual-copy-textarea');
    ta.focus();
    ta.select();
    try {
      const ok = document.execCommand('copy');
      if (ok) close();
    } catch (_) { /* user can still Cmd/Ctrl+C */ }
  });
  return bd;
}

function showManualCopyModal(text) {
  const bd = ensureManualCopyModal();
  const ta = bd.querySelector('#manual-copy-textarea');
  ta.value = text;
  bd.style.display = 'flex';
  // Wait a tick so the textarea is visible before selecting.
  setTimeout(() => {
    ta.focus();
    ta.select();
    try { ta.setSelectionRange(0, text.length); } catch (_) {}
  }, 30);
}

document.getElementById('copy-btn').addEventListener('click', () => {
  if (!selected.size) return;
  const btn = document.getElementById('copy-btn');
  const n = selected.size;
  const ids = [...selected];

  btn.textContent = 'Preparing…';
  btn.disabled = true;

  const flash = () => {
    btn.classList.add('copied');
    btn.textContent = `✓ Copied ${n}!`;
    setTimeout(() => {
      btn.classList.remove('copied');
      updateDownloadBtn();
    }, 1600);
  };
  const resetIdle = () => {
    btn.classList.remove('copied');
    btn.disabled = selected.size === 0;
    updateDownloadBtn();
  };

  // ── Pattern 1: Safari-safe ClipboardItem + Promise ────────────────────────
  // We MUST call navigator.clipboard.write synchronously inside the click
  // handler. The Blob inside ClipboardItem can be a Promise.
  if (
    window.isSecureContext &&
    navigator.clipboard &&
    typeof navigator.clipboard.write === 'function' &&
    typeof window.ClipboardItem === 'function'
  ) {
    let cachedMd = '';
    const blobPromise = fetchExportMarkdown(ids).then((md) => {
      cachedMd = md;
      return new Blob([md], {type: 'text/plain'});
    });

    let item;
    try {
      item = new ClipboardItem({'text/plain': blobPromise});
    } catch (_) {
      item = null;
    }

    if (item) {
      navigator.clipboard.write([item])
        .then(flash)
        .catch(async () => {
          // Promise-based write was rejected. Try the fetched text via
          // writeText / execCommand / manual-copy modal.
          let md = cachedMd;
          if (!md) {
            try { md = await fetchExportMarkdown(ids); }
            catch (e) { alert(e.message || 'Copy failed'); resetIdle(); return; }
          }
          if (navigator.clipboard && navigator.clipboard.writeText) {
            try { await navigator.clipboard.writeText(md); flash(); return; }
            catch (_) { /* continue */ }
          }
          if (legacyCopyFallback(md)) { flash(); return; }
          showManualCopyModal(md);
          resetIdle();
        });
      return;
    }
  }

  // ── Pattern 2: Legacy path (no ClipboardItem support) ─────────────────────
  (async () => {
    let md = '';
    try {
      md = await fetchExportMarkdown(ids);
    } catch (e) {
      alert(e.message || 'Copy failed');
      resetIdle();
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(md); flash(); return; }
      catch (_) { /* fall through */ }
    }
    if (legacyCopyFallback(md)) { flash(); return; }
    showManualCopyModal(md);
    resetIdle();
  })();
});

// ── Back-up the whole history folder ────────────────────────────────────────
//
// Unlike Download / Copy, which act on the *selected* conversations, Back-up
// copies the ENTIRE history folder tree to a user-chosen destination. The
// goal is to shield the user's conversations from a system cleanup or from
// Claude app maintenance/update routines that might delete or overwrite
// local history files.
//
// The user picks the destination folder either via a native Finder dialog
// (macOS) or by typing/pasting the full path. The server then creates a
// timestamped subfolder there (so repeated backups to the same location
// coexist instead of overwriting each other) and recursively copies the
// history into it.
function showBackupResult(info) {
  document.getElementById('backup-dest').textContent = info.destination || '—';
  document.getElementById('backup-files').textContent =
    (info.files_copied != null ? info.files_copied : '—') + ' file(s)';
  document.getElementById('backup-size').textContent = info.bytes_human || '—';

  const wrap = document.getElementById('backup-errors-wrap');
  const list = document.getElementById('backup-errors');
  const count = document.getElementById('backup-errors-count');
  const errs = info.errors || [];
  if (errs.length) {
    wrap.style.display = 'block';
    count.textContent = info.error_count != null ? info.error_count : errs.length;
    list.textContent = errs.slice(0, 50).join('\n');
  } else {
    wrap.style.display = 'none';
  }

  document.getElementById('backup-backdrop').classList.add('open');
}

function closeBackupModal() {
  document.getElementById('backup-backdrop').classList.remove('open');
}

document.getElementById('backup-close').addEventListener('click', closeBackupModal);
document.getElementById('backup-backdrop').addEventListener('click', (e) => {
  if (e.target.id === 'backup-backdrop') closeBackupModal();
});

document.getElementById('backup-btn').addEventListener('click', async () => {
  const btn = document.getElementById('backup-btn');

  // Ask the user how they want to choose the destination. The same two-mode
  // pattern is used by the "Change folder" button for consistency.
  const choice = prompt(
    'Back up your Claude history folder to another location so it\'s not\n' +
    'wiped by a system cleanup or by a Claude app maintenance/update routine.\n\n' +
    'How would you like to pick the destination folder?\n\n' +
    '  1 = open a Finder window to pick it\n' +
    '  2 = type or paste the full folder path\n\n' +
    'Enter 1 or 2:',
    '1'
  );
  if (choice === null) return;

  let body;
  if (choice.trim() === '2') {
    const pasted = prompt(
      'Paste the full path to the folder where the backup should be saved\n' +
      '(a timestamped subfolder will be created inside it):'
    );
    if (!pasted || !pasted.trim()) return;
    body = {mode: 'path', path: pasted};
  } else {
    body = {mode: 'finder'};
  }

  const originalText = btn.textContent;
  btn.textContent = 'Backing up…';
  btn.disabled = true;

  try {
    const res = await fetch('/api/backup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let msg = 'Backup failed';
      try { msg = (await res.json()).error || msg; } catch (_) {}
      alert(msg);
      return;
    }
    const info = await res.json();

    // Transient "✓ Backed up" flash on the button, then settle back to idle.
    btn.classList.add('backed-up');
    btn.textContent = '✓ Backed up';
    setTimeout(() => {
      btn.classList.remove('backed-up');
      btn.textContent = originalText;
      btn.disabled = false;
    }, 1800);

    showBackupResult(info);
  } catch (e) {
    alert((e && e.message) || 'Backup failed');
    btn.textContent = originalText;
    btn.disabled = false;
  } finally {
    // Safety: make sure the button is re-enabled even if the flash callback
    // above didn't run (e.g. error path).
    if (!btn.classList.contains('backed-up')) {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  }
});

// ── About dialog ─────────────────────────────────────────────────────────────
let aboutLoaded = false;
async function openAbout() {
  const bd = document.getElementById('about-backdrop');
  if (!aboutLoaded) {
    try {
      const res = await fetch('/api/about');
      const info = await res.json();
      document.getElementById('about-title').textContent = info.name || 'Claude History Browser';
      document.getElementById('about-version').textContent = 'v' + (info.version || '—');
      document.getElementById('about-author').textContent = info.author || '—';
      document.getElementById('about-license').textContent = (info.license || '—') + ' License';
      const repoA = document.getElementById('about-repo');
      if (info.repo) {
        repoA.href = info.repo;
        repoA.textContent = info.repo;
      }
      document.getElementById('about-copyright').textContent = info.copyright || '';
      aboutLoaded = true;
    } catch (_) { /* show whatever we have */ }
  }
  bd.classList.add('open');
}
function closeAbout() {
  document.getElementById('about-backdrop').classList.remove('open');
}
document.getElementById('app-title').addEventListener('click', openAbout);
document.getElementById('about-close').addEventListener('click', closeAbout);
document.getElementById('about-backdrop').addEventListener('click', (e) => {
  if (e.target.id === 'about-backdrop') closeAbout();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeAbout(); closeBackupModal(); }
});

// ── Search ───────────────────────────────────────────────────────────────────
document.getElementById('search-global').addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim();
  if (!q) { showConvPanel(); return; }
  await runSearch(q);
});

async function runSearch(q) {
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('conv-view').style.display = 'none';
  document.getElementById('conv-header').style.display = 'none';
  const tb = document.getElementById('conv-toolbar');
  if (tb) tb.style.display = 'none';
  const sr = document.getElementById('search-results');
  sr.style.display = 'block';
  sr.innerHTML = '<p style="color:var(--text3)">Searching…</p>';

  const res = await fetch('/api/search?q=' + encodeURIComponent(q));
  const results = await res.json();

  if (!results.length) {
    sr.innerHTML = '<p style="color:var(--text3)">No results found.</p>';
    return;
  }
  sr.innerHTML = `<p style="color:var(--text3);margin-bottom:12px">${results.length} conversations matched</p>`;

  results.forEach(r => {
    const div = document.createElement('div');
    div.className = 'sr-item';
    const date = r.last_ts ? new Date(r.last_ts).toLocaleDateString() : '';
    const excerpts = (r.excerpts || []).map(ex => {
      const highlighted = ex.snippet.replace(
        new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'),
        m => `<em>${esc(m)}</em>`
      );
      return `<div class="sr-snippet">[${ex.role}] ${highlighted}</div>`;
    }).join('');
    div.innerHTML = `<div class="sr-title">${esc(r.title)}</div>
      <div class="sr-meta">${esc(r.project)}  ·  ${date}  ·  ${r.user_count} messages</div>
      ${excerpts}`;
    div.addEventListener('click', () => openConversation(r));
    sr.appendChild(div);
  });
}

function showConvPanel() {
  document.getElementById('search-results').style.display = 'none';
  if (allConversations.length) {
    document.getElementById('welcome').style.display = 'none';
  } else {
    document.getElementById('welcome').style.display = 'flex';
  }
}

// ── Change folder ────────────────────────────────────────────────────────────
document.getElementById('path-btn').addEventListener('click', async () => {
  const choice = prompt(
    'How would you like to set the history folder?\n\n' +
    '  1 = open a Finder window to pick it\n' +
    '  2 = type or paste the full folder path\n\n' +
    'Enter 1 or 2:',
    '1'
  );
  if (choice === null) return;

  let body;
  if (choice.trim() === '2') {
    const pasted = prompt('Paste the full path to your history folder:');
    if (!pasted || !pasted.trim()) return;
    body = {mode: 'path', path: pasted};
  } else {
    body = {mode: 'finder'};
  }

  const res = await fetch('/api/config/change', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const cfg = await res.json();
    alert('Folder changed to:\n' + cfg.history_path);
    location.reload();
  } else {
    let msg = 'Could not change folder.';
    try { msg = (await res.json()).error || msg; } catch (_) {}
    alert(msg);
  }
});

// ── Utils ─────────────────────────────────────────────────────────────────────
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Format a raw token count into a compact human-readable string, e.g.:
//   null/undefined/0 → "0"
//   842              → "842"
//   12_340           → "12.3K"
//   1_250_000        → "1.25M"
// Kept short so the reader-pane header stays scannable; the full count with
// commas is shown in the tooltip by the caller.
function formatTokens(n) {
  const v = Number(n || 0);
  if (!isFinite(v) || v <= 0) return '0';
  if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 1 : 2).replace(/\.?0+$/, '') + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(v >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'K';
  return String(v);
}

init();
</script>
</body>
</html>
"""


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    global HISTORY_PATH
    HISTORY_PATH = resolve_history_path()

    port = 5757
    url = f"http://127.0.0.1:{port}"
    print(f"\n🚀 Starting Claude History Browser at {url}")
    print("   Press Ctrl+C to stop.\n")

    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
