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
import subprocess
import sys
import threading
import webbrowser
from collections import defaultdict
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
def pick_folder_mac():
    script = '''
    tell application "Finder"
        activate
    end tell
    try
        set chosen to choose folder with prompt "Select your Claude history folder (the folder containing project subfolders with .jsonl files):"
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


# Cache of per-folder "pretty" project names keyed by the parent directory,
# so we don't re-scan a jsonl file every time we need a display name.
_PROJECT_NAME_CACHE: dict[str, str] = {}


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


def project_display_name(filepath: Path) -> str:
    """Return a human-friendly project name for a .jsonl file.

    Order of preference:
      1. The basename of the `cwd` field recorded inside the .jsonl file
         (this is the actual project folder the user was working in).
      2. The decoded folder name on disk (best-effort, lossy).
      3. The raw folder name.
    Files directly in HISTORY_PATH get "(root)".
    """
    parent = filepath.parent
    parent_key = str(parent)
    cached = _PROJECT_NAME_CACHE.get(parent_key)
    if cached is not None:
        return cached

    # Files directly at the root
    try:
        rel = parent.relative_to(HISTORY_PATH)
        if str(rel) in ("", "."):
            _PROJECT_NAME_CACHE[parent_key] = "(root)"
            return "(root)"
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

    if cwd:
        # Use the last path segment — that's almost always what a user
        # thinks of as "the project".
        name = os.path.basename(cwd.rstrip("/\\")) or cwd
    else:
        # 2. Fall back to decoding the folder name.
        decoded = _decode_claude_folder_name(parent.name)
        name = os.path.basename(decoded.rstrip("/\\")) or parent.name

    _PROJECT_NAME_CACHE[parent_key] = name
    return name


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

    # Extra metadata pulled from the JSONL records themselves.
    # Claude Code / Cowork transcripts commonly carry these fields.
    session_id = _first_nonempty(messages, "sessionId")
    cwd = _first_nonempty(messages, "cwd")
    git_branch = _first_nonempty(messages, "gitBranch")
    cc_version = _first_nonempty(messages, "version")
    user_type = _first_nonempty(messages, "userType")

    return {
        "id": filepath.stem,
        "file": str(filepath),
        "project": project_key(filepath),
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
    }


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


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
        turns.append(
            {
                "role": t,
                "blocks": content_blocks(content),
                "timestamp": m.get("timestamp"),
                "uuid": m.get("uuid"),
                "model": m.get("message", {}).get("model"),
            }
        )
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


# ── HTML / CSS / JS template ──────────────────────────────────────────────────
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude History Browser</title>
<meta name="application-name" content="Claude History Browser">
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
  .col-header, .conv-item { display: grid; grid-template-columns: 28px 1fr 110px 150px; align-items: stretch; }
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

  /* ── Messages ── */
  .turn { margin-bottom: 18px; }
  .turn-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
  .turn.user .turn-label { color: var(--accent2); }
  .turn.assistant .turn-label { color: var(--accent); }
  .bubble { border-radius: var(--radius); padding: 12px 16px; font-size: 13px; line-height: 1.6; }
  .turn.user .bubble { background: var(--user-bg); }
  .turn.assistant .bubble { background: var(--asst-bg); }

  /* ── Content blocks ── */
  .block + .block { margin-top: 8px; }
  .block-text { white-space: pre-wrap; word-break: break-word; }
  .block-thinking { background: var(--think-bg); border: 1px solid #3a3e1a; border-radius: 6px; padding: 8px 12px; font-size: 12px; color: #9aaa60; }
  .block-thinking details summary { cursor: pointer; font-weight: 600; color: #b8c870; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .block-thinking .think-body { white-space: pre-wrap; margin-top: 6px; }
  .block-tool { background: var(--tool-bg); border: 1px solid #1e3020; border-radius: 6px; padding: 8px 12px; }
  .block-tool .tool-name { font-size: 11px; font-weight: 700; color: #6dcc88; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
  .block-tool pre { font-size: 11px; color: #8ecf9e; white-space: pre-wrap; word-break: break-all; overflow: hidden; max-height: 200px; }
  .block-result { background: var(--result-bg); border: 1px solid #1a2535; border-radius: 6px; padding: 8px 12px; }
  .block-result .result-label { font-size: 11px; font-weight: 600; color: var(--text3); margin-bottom: 4px; }
  .block-result pre { font-size: 11px; color: var(--text2); white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow: hidden; }

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

<div class="body">
  <aside>
    <div class="sidebar-top">
      <div class="row">
        <select id="project-select"><option value="">All projects</option></select>
      </div>
      <div class="action-row">
        <button id="download-btn" class="action-btn" disabled title="Download the selected conversations as a single .md file">⬇︎ Download (0)</button>
        <button id="copy-btn" class="action-btn" disabled title="Copy the selected conversations to the clipboard as Markdown">⧉ Copy (0)</button>
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
        <button class="filter-btn" data-project="${esc(c.project)}" title="Filter to this project">${esc(c.project)}</button>
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

  // Show header
  const header = document.getElementById('conv-header');
  header.style.display = 'block';
  document.getElementById('ch-title').textContent = c.title;
  const date = c.last_ts ? new Date(c.last_ts).toLocaleString() : '';
  document.getElementById('ch-meta').textContent = `${c.project}  ·  ${c.user_count} messages  ·  ${date}  ·  ${c.model || ''}`;

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

function renderConversation(turns, container) {
  container.innerHTML = '';
  turns.forEach(turn => {
    const div = document.createElement('div');
    div.className = `turn ${turn.role}`;

    const label = document.createElement('div');
    label.className = 'turn-label';
    label.textContent = turn.role === 'user' ? '👤 You' : '✦ Claude';
    div.appendChild(label);

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    (turn.blocks || []).forEach(block => {
      const bd = document.createElement('div');
      bd.className = 'block';
      if (block.type === 'text') {
        bd.className += ' block-text';
        bd.textContent = block.text;
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
  if (e.key === 'Escape') closeAbout();
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
