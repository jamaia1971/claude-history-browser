# Claude History Browser

A tiny local web app for browsing, filtering, searching, and exporting your Claude conversation history — the `.jsonl` files Claude writes to your disk whenever you use Claude Code, Cowork, or the Claude desktop app's coding sessions.

![Badge: Python 3.8+](https://img.shields.io/badge/python-3.8+-blue) ![Badge: MIT](https://img.shields.io/badge/license-MIT-green) ![Badge: Vibe coded](https://img.shields.io/badge/made%20with-vibe%20coding-ff69b4)

> **Heads up — this repo was entirely vibe-coded.** See *[About the author](#about-the-author)* below. If you're a seasoned Python/Flask engineer you will probably spot things that could be done more elegantly; PRs and issues are very welcome.

---

## Why I built this

Claude writes every conversation you have with it to a local file on your machine — one `.jsonl` file per session, organized into project folders. That is a gold mine: your past reasoning, prior solutions, debugging trails, drafts, prompts that worked, prompts that didn't. But the raw files are not fun to read:

- `.jsonl` is one JSON object per line, so you can't just open them in a text editor and skim.
- They are buried in paths like `~/.claude/projects/<encoded-folder-name>/<uuid>.jsonl`.
- There is no built-in way to search across all of them, filter by date, or export a handful of conversations into one shareable document.

I kept opening these files by hand, using `jq` tricks, or asking Claude to parse them for me. It got old. So I asked Claude to help me build a small, private, zero-dependency-beyond-Flask browser for them, and this is the result.

If you use Claude Code or Cowork day-to-day, this little app may save you a lot of squinting.

---

## What it does

- **Scans** a folder (recursively) for `.jsonl` conversation files — works with Claude Code's `~/.claude/projects/` layout, Cowork sessions, or any folder you point it at.
- **Lists** every conversation in a sortable, filterable table with these columns: a **checkbox**, the **title + preview**, **date & hour**, and **project**. Click the date cell to filter to that day; click the project cell to filter to that project. Active filters show as pills you can clear with one click.
- **Displays** a selected conversation in a clean chat-like view, with styled blocks for plain text, thinking blocks (collapsible), tool calls, and tool results.
- **Full-text search** across every conversation in your history folder, with excerpts.
- **Exports** any subset of conversations to a single Markdown file: tick the checkboxes, click **⬇︎ Download (N)**, save the `.md`. Great for sharing a thread, feeding it back to Claude, or archiving.
- **Change folder at runtime** via a macOS Finder dialog or by pasting a path.
- **Remembers** your chosen folder in `~/.claude_history_browser.json` so subsequent runs launch instantly.

Everything runs on `http://localhost:5757`. Nothing leaves your machine.

---

## Screenshots

_(Run it and it'll open itself in your browser — the UI is a dark-themed sidebar + reader layout, with the columns described above.)_

---

## Quick start

```bash
git clone https://github.com/jamaia1971/claude-history-browser.git
cd claude-history-browser
python3 claude_history_browser.py
```

On first run it asks which folder to scan (Finder dialog on macOS, or you can paste a path). On subsequent runs it just launches at [http://localhost:5757](http://localhost:5757).

Flask is installed automatically on first run if you don't already have it.

### Requirements

- Python 3.8 or newer
- Flask (auto-installed if missing)
- macOS for the native Finder folder-picker. On Linux/Windows you can still use the app — just paste the path when prompted, or see *[Linux / Windows tip](#linux--windows-tip)* below.

### Where Claude history lives

| Tool | Default history path |
|------|----------------------|
| Claude Code (CLI) | `~/.claude/projects/` |
| Cowork (desktop) | inside the workspace folder(s) you selected |
| Claude desktop coding sessions | typically under `~/Library/Application Support/Claude/` or similar — point the app at the parent folder and it will recurse |

Each subfolder becomes a "project" in the UI. Each `.jsonl` becomes a conversation.

---

## How to use it

1. Launch the app. A browser tab opens.
2. **Browse**: the left column lists every conversation. The newest is at the top.
3. **Filter**:
   - Use the **project dropdown** to pick a single project, or
   - Click a **date cell** to filter to that day, or
   - Click a **project cell** to filter to that project.
   - Active filters appear as pills — click the `✕` to clear them.
4. **Search**: type into the search bar at the top and press Enter. The results panel shows matching conversations with snippets.
5. **Read**: click any conversation row (not the checkbox) to open it in the reader pane on the right.
6. **Export**: tick the checkboxes for the conversations you want, then click **⬇︎ Download (N)**. You'll get a single `.md` file like `claude-history-20260417-173411.md` containing all the selected threads, cleanly formatted.

---

## How it works (very short version)

- A single-file Flask app (`claude_history_browser.py`).
- Recursively walks the configured folder and parses each `.jsonl` line-by-line into JSON records.
- A small set of JSON API routes (`/api/projects`, `/api/conversations`, `/api/conversation/<id>`, `/api/search`, `/api/download`, `/api/config/change`) power the UI.
- The frontend is one HTML template embedded in the Python file — plain vanilla JS, no build step, no dependencies. The whole UI is a single string.
- Markdown export: `conversation_to_markdown()` walks the same block structure as the reader and emits a GitHub-flavored markdown doc with collapsible `<details>` blocks for Claude's thinking.
- Config (the chosen history folder) is cached in `~/.claude_history_browser.json`.

Everything is local. The server binds to `127.0.0.1` only. Nothing ever leaves your computer.

---

## Linux / Windows tip

The folder picker uses AppleScript (`osascript`) because I'm on macOS. On other platforms it will just fall back to asking you to paste a path, which works fine. If you want a native dialog anyway, swap `pick_folder_mac()` for a `tkinter` version:

```python
import tkinter as tk
from tkinter import filedialog

def pick_folder():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title="Select Claude history folder")
```

Pull requests to make the picker cross-platform by default are welcome.

---

## Privacy

- The server binds to `127.0.0.1:5757` — it is not reachable from anywhere else on the network.
- No telemetry. No outgoing requests. No third-party services.
- Nothing is uploaded; the exported Markdown file is generated locally and handed to your browser as a download.

If you deploy this somewhere that isn't localhost (please don't), add authentication — the app currently assumes it's the only user.

---

## Contributing

Issues and PRs welcome, especially:
- Cross-platform folder picker
- Tests (there are none yet — see *[About the author](#about-the-author)*)
- Better sorting / advanced filters (date range, model, length)
- An option to export as a single HTML or PDF file in addition to Markdown
- Virtualized list for folks with thousands of conversations

If you're going to touch the HTML template, it lives inside `claude_history_browser.py` as a single triple-quoted `HTML_TEMPLATE` string — not ideal, but it keeps the whole thing a single file. Extracting it is a fine PR if you want a proper structure.

---

## About the author

I'm [Joao](https://github.com/jamaia1971). I'm a **vibe coder**. My "real" programming background is embarrassingly ancient — I wrote a lot of **BASIC** on 8-bit machines as a kid and some **Turbo Pascal** in school, and then I did approximately nothing for a few decades. I'm not a software engineer. I don't know Python idioms, I never learned Flask properly, and I picked up HTML/CSS by osmosis.

What I *can* do is describe what I want, read code, poke at it, and iterate. So everything you see here — the layout, the columns, the Markdown export, the history-scrubbing `.gitignore`, this README — is the product of me thinking out loud with Claude (the model), letting it write, reviewing the diff, asking for changes, and testing the result until it felt right. It's vibe coding in the truest sense: I steer, Claude drives, and we argue about the details until something useful falls out.

If the code style feels inconsistent, if there are no tests, if error handling is thin, if something could clearly be 10× more elegant — that's why. I'm publishing this because *the thing works* and *the thing is useful to me*, and maybe it's useful to you too. If you're a real engineer and want to refactor it: please do, I'll happily merge.

---

## License

MIT. See [LICENSE](LICENSE) (add a LICENSE file if you fork — I intend to ship one).

---

Made with a lot of help from [Claude](https://claude.ai). The irony of a Claude-built tool for browsing Claude's own conversation history is not lost on me.
