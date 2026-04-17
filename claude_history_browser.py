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

# ── Try to import Flask, install if missing ─────────────────────────────────
try:
    from flask import Flask, jsonify, request, render_template_string
except ImportError:
    print("📦 Installing Flask...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--quiet"])
    from flask import Flask, jsonify, request, render_template_string

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


def project_key(filepath: Path) -> str:
    """Return the project identifier for a .jsonl file.

    This is the path of the file's parent directory relative to HISTORY_PATH,
    so nested subfolders produce distinct project names (e.g. "foo/bar").
    Files directly in HISTORY_PATH get the project name "(root)".
    """
    try:
        rel = filepath.parent.relative_to(HISTORY_PATH)
    except Exception:
        return filepath.parent.name
    s = str(rel)
    if s in ("", "."):
        return "(root)"
    # Normalize to forward slashes for display
    return s.replace(os.sep, "/")


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


# ── HTML / CSS / JS template ──────────────────────────────────────────────────
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude History Browser</title>
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
    --sidebar-w: 320px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; height: 100vh; display: flex; flex-direction: column; }

  /* ── Header ── */
  header { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--surface); border-bottom: 1px solid var(--border); flex-shrink: 0; }
  header h1 { font-size: 16px; font-weight: 600; color: var(--accent); white-space: nowrap; }
  header h1 span { color: var(--text2); font-weight: 400; }
  #search-global { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text); font-size: 13px; outline: none; }
  #search-global:focus { border-color: var(--accent); }
  #path-btn { background: var(--surface2); border: 1px solid var(--border); color: var(--text2); border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; white-space: nowrap; }
  #path-btn:hover { color: var(--accent); border-color: var(--accent); }

  /* ── Layout ── */
  .body { display: flex; flex: 1; overflow: hidden; }

  /* ── Sidebar ── */
  aside { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  .sidebar-top { padding: 10px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  #project-select { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; color: var(--text); font-size: 13px; cursor: pointer; }
  #conv-list { flex: 1; overflow-y: auto; }
  .conv-item { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.15s; }
  .conv-item:hover { background: var(--surface2); }
  .conv-item.active { background: var(--surface2); border-left: 3px solid var(--accent); }
  .conv-title { font-size: 13px; font-weight: 500; line-height: 1.4; color: var(--text); margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .conv-meta { font-size: 11px; color: var(--text3); display: flex; gap: 8px; }
  .conv-preview { font-size: 12px; color: var(--text2); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #conv-count { padding: 6px 14px; font-size: 11px; color: var(--text3); border-bottom: 1px solid var(--border); flex-shrink: 0; }

  /* ── Main panel ── */
  main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  #welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--text3); }
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

  /* ── Loader ── */
  #loader { display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%); color: var(--text3); }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<header>
  <h1>Claude <span>History</span></h1>
  <input id="search-global" type="search" placeholder="Search all conversations... (press Enter)" />
  <button id="path-btn" title="Change history folder">📂 Change folder</button>
</header>

<div class="body">
  <aside>
    <div class="sidebar-top">
      <select id="project-select"><option value="">All projects</option></select>
    </div>
    <div id="conv-count">Loading…</div>
    <div id="conv-list"></div>
  </aside>

  <main>
    <div id="welcome">
      <h2>Claude History Browser</h2>
      <p>Select a conversation from the left, or search above.</p>
    </div>
    <div id="conv-header">
      <h2 id="ch-title"></h2>
      <div class="meta" id="ch-meta"></div>
    </div>
    <div id="conv-view"></div>
    <div id="search-results"></div>
  </main>
</div>

<div id="loader">Loading…</div>

<script>
let allConversations = [];
let currentProject = '';
let searchTimer = null;

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadProjects();
  await loadConversations();
}

async function loadProjects() {
  const res = await fetch('/api/projects');
  const projects = await res.json();
  const sel = document.getElementById('project-select');
  projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p.replace(/^-/, '').replace(/-/g, '/');
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
  renderList(allConversations);
}

function renderList(convs) {
  const list = document.getElementById('conv-list');
  const count = document.getElementById('conv-count');
  count.textContent = convs.length + ' conversation' + (convs.length !== 1 ? 's' : '');
  list.innerHTML = '';
  convs.forEach(c => {
    const div = document.createElement('div');
    div.className = 'conv-item';
    div.dataset.id = c.id;
    const date = c.last_ts ? new Date(c.last_ts).toLocaleDateString('en-US', {month:'short',day:'numeric',year:'numeric'}) : '';
    div.innerHTML = `
      <div class="conv-title">${esc(c.title)}</div>
      <div class="conv-meta"><span>${date}</span><span>${c.user_count} msgs</span><span>${c.model || ''}</span></div>
      <div class="conv-preview">${esc(c.preview)}</div>`;
    div.addEventListener('click', () => openConversation(c));
    list.appendChild(div);
  });
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
  if (choice === null) return; // cancelled

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
  if (!s) return '';
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
