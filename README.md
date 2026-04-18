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
- **Displays** a selected conversation in a clean chat-like view, with styled blocks for plain text, thinking blocks (collapsible), tool calls, and tool results. Each turn is clearly labeled: **👤 You**, **✦ Claude**, **📤 Tool result**, or **⚙️ System**.
- **Reader toolbar** under the conversation header lets you isolate parts of a thread with one click:
  - **Category chips** — **👤 You / ✦ Claude / 🔧 Tool / 🧠 Thinking / 📤 Result** — toggle each independently to filter the transcript (e.g., hide tool chatter to read only the human/Claude conversation).
  - **🗜 Compact tool blocks** — clips long tool inputs and tool results at ~240px with an inner scrollbar so you can scan big transcripts faster.
  - Your filter/compact preferences persist across browser sessions.
- **Keyboard navigation** — **↑ / ↓** arrow keys step through turns in the open conversation. Click anywhere in a turn to set the active position, and arrows continue from there.
- **Per-turn Copy button** — every message has a **📋 Copy** button in its top-right corner that copies a clean text payload (no button labels, no DOM noise) to your clipboard.
- **Per-turn token badge** — each Claude reply shows a small `N in / M out` badge next to its label, so you can see which single response was the expensive one. Hover for full counts.
- **Conversation-level token totals** — the header shows cumulative input/output for the whole thread, with a tooltip breaking out cache-read and cache-write so prompt-caching savings are visible at a glance.
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

### Tested on

I developed and use this app on **macOS (Apple Silicon)** with **Safari**. Everything below was written and debugged in that environment. On **Chrome / Firefox / Edge** it should still work — the frontend is plain HTML + vanilla JS with no Safari-specific APIs — but I haven't verified every small behavior (clipboard permissions, smooth-scroll easing, scrollbar styling, minor CSS rendering) on those browsers. On **Windows / Linux** the folder picker falls back to a paste-the-path prompt (see the *Linux / Windows tip* below) but the rest of the app is the same cross-platform Flask. If you spot a browser-specific or OS-specific glitch, please open an issue.

### Where Claude history lives

| Tool | Default history path |
|------|----------------------|
| Claude Code (CLI) | `~/.claude/projects/` |
| Cowork (desktop) | inside the workspace folder(s) you selected |
| Claude desktop coding sessions | typically under `~/Library/Application Support/Claude/` or similar — point the app at the parent folder and it will recurse |

Each subfolder becomes a "project" in the UI. Each `.jsonl` becomes a conversation.

> ⚠️ **Claude Code auto-deletes local history after 30 days by default.** This browser can only show what's still on disk, so if you care about long-term scrollback, take a minute to raise `cleanupPeriodDays` in `~/.claude/settings.json` — or archive the folder elsewhere. See **[HISTORY_RETENTION.md](HISTORY_RETENTION.md)** for a full explanation, the one config tweak that matters, and a ready-to-use archive recipe.

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
6. **Navigate inside a conversation**:
   - **↑ / ↓** arrow keys step through turns; the active turn is highlighted and smooth-scrolled into view.
   - **Click** anywhere inside a turn to set it as the active position — arrows continue from there.
   - **Category chips** (👤 / ✦ / 🔧 / 🧠 / 📤) in the toolbar isolate the parts you want to see.
   - **🗜 Compact tool blocks** clips long tool dumps so you can skim; toggle it off to see everything in full.
   - **📋 Copy** on any turn copies just that message to your clipboard.
   - Watch the **token badge** next to "✦ Claude" labels to spot expensive replies.
7. **Export**: tick the checkboxes for the conversations you want, then click **⬇︎ Download (N)**. You'll get a single `.md` file like `claude-history-20260417-173411.md` containing all the selected threads, cleanly formatted.

### How the filter chips work

The five chips in the reader toolbar each target **one type of content**, not whole turns. A message bubble stays visible as long as **at least one** of its blocks is visible — so you can, for example, turn CLAUDE off and TOOL on and still see Claude's tool-call turns (just without the prose).

| Chip | What it shows / hides |
|------|-----------------------|
| **👤 You** | The text you typed, plus `[Image:…]` and `<system-reminder>` metadata that came from your side. |
| **✦ Claude** | Claude's **prose** replies only. Does **not** touch tool calls, thinking, or results — those have their own chips. |
| **🔧 Tool** | The 🔧 tool-call blocks inside Claude's turns (what Claude asked a tool to do). |
| **🧠 Thinking** | The 🧠 internal reasoning blocks inside Claude's turns. |
| **📤 Result** | 📤 tool outputs and ⚙️ system-injected turns that sit between tool calls and Claude's next reply. |

All chips start **ON** (everything shown). Click one to turn it off. Useful combinations:

- **You + Claude** → a clean human/Claude conversation, with all the tool chatter, thinking, and results collapsed out.
- **Only Tool** → every Claude turn that made a tool call, showing just the 🔧 blocks. Handy for spotting what tools ran and with what inputs.
- **Only Thinking** → Claude's reasoning path end-to-end, without the work itself.
- **Tool + Result** → the execution log: what Claude asked for, what came back, nothing else.
- **Claude + Result** → Claude's replies plus the tool outputs that informed them, without the intermediate tool-call plumbing.

Your chip preferences persist across browser sessions, so once you pick a view you like for reading old transcripts you won't have to set it up again.

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

> ⚠️ **Full disclosure:** I use this app on **macOS (Apple Silicon)** with **Safari**, and that's the only combination I've actually tested. I have no idea whether any of the Windows instructions anywhere in this repo actually work — I've been a Mac user for so long I cannot remember my last Windows version, so anything Windows-specific here was proposed by Claude and has never been tested by me on a real Windows machine. Same caveat for **Chrome / Firefox / Edge** on any platform: the UI is plain HTML + vanilla JS so it *should* just work, but small things (clipboard permissions, smooth-scroll, scrollbar appearance) may differ. If you run into trouble on Windows or in a non-Safari browser, please open an issue — or better yet, a PR with a version that actually works.

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

## Ideas for improvement — come help this thing thrive

This app does the boring-but-useful stuff: open the files, list them, search them, export them. There is a lot of room to make it genuinely smart. If any of the ideas below sound fun, please fork it, prototype it, and open a PR — however rough. I'd rather merge a scrappy working idea than wait for a polished one that never ships.

### AI-powered ideas

- **Conversation memory / recap (Claude API).** Point the app at a conversation (or a whole batch), send the transcript to the Claude API, and get back a crisp recap: what the user was trying to do, what was tried, what worked, what was left open, and key decisions. Store the recap as a sidecar file (e.g. `<conversation-id>.recap.md`) so it's cached and re-openable without hitting the API again. Bonus: a "**rolling memory**" view that stitches recaps across many conversations into a living summary of what you've been working on lately.
- **Smart search with skills.** Today search is plain string matching. With a small set of **skills** (Claude-style specialized prompts), the app could route queries intelligently — e.g. a `code-finder` skill for "find the bit where I debugged the Flask route", a `decision-tracker` skill for "when did I decide to use SQLite?", a `people-and-projects` skill for "what did I discuss with the legal team last month?". Each skill would know how to re-rank, summarize, and present results for its kind of question.
- **Semantic search / embeddings.** Index every conversation with an embedding model so you can ask fuzzy questions ("that time I was fighting with CORS") without remembering exact words. Local embeddings are fine — no cloud needed.
- **Auto-tagging and topic clustering.** Let the model read each conversation once and suggest tags (`#flask`, `#cowork`, `#bug-hunt`, `#refactor`), then cluster the sidebar by topic instead of just by project.
- **Ask-your-history chat.** A small chat box that answers questions *about* your history — grounded in the actual conversations, with citations back to the source `.jsonl` files.
- **Auto-detect resumable threads.** Flag conversations that ended mid-task so you can pick them back up, maybe with a one-click "continue this in Claude Code" button.

### Plain-old-software ideas

- Cross-platform folder picker (tkinter fallback, or PyWebview).
- Tests — there are none yet. See *[About the author](#about-the-author)* for why.
- Better sorting / advanced filters (date range, model, message count, conversation length).
- Export to HTML or PDF, not just Markdown.
- Virtualized list so people with thousands of conversations don't melt the browser.
- Split the single-file app into modules (Flask blueprints, templates extracted from the `HTML_TEMPLATE` string, static assets as real files).
- A proper package install (`pip install claude-history-browser`) with a console entry point.
- Dark/light theme toggle.
- More keyboard shortcuts for power users (`j`/`k` to move through the conversation list, `/` to focus search, `c` to copy the active turn, etc. — arrow-key navigation *within* a conversation already works).

## Contributing

Issues and PRs welcome. If any of the ideas above grab you, just go. If you're adding an AI feature, please keep it **opt-in** and **local-first** — the whole point of this app is that nothing leaves your machine by default. An AI recap that calls the Claude API is great, but it should be a clearly labeled choice, not a surprise.

If you're going to touch the HTML template, it lives inside `claude_history_browser.py` as a single triple-quoted `HTML_TEMPLATE` string — not ideal, but it keeps the whole thing a single file. Extracting it is a fine PR if you want a proper structure.

---

## About the author

IMPORTANT: I AM NO CS GUY AND HAVE NO REAL CS BACKGROUND. I MADE THAT FOR MY PERSONAL USE. HOPE YOU UNDERSTAND AND LIKE.

I'm [@jamaia1971](https://github.com/jamaia1971), a seasoned lawyer. I dropped engineering school after two years and ten math courses, but I've loved computers for 40+ years — BASIC on an Apple II Plus as a kid, a little assembly, some Pascal at university. The 2023 LLM boom pulled me back into reading and running some coding after decades away, and this history browser is one of the first things I've shipped since — vibe-coded with Claude at the wheel.

---

## License

Released under the [MIT License](LICENSE) — copyright © 2026 [@jamaia1971](https://github.com/jamaia1971). In short: you can use, copy, modify, merge, and redistribute the code freely, as long as the copyright notice and the MIT license text travel with it. The software is provided "as is", with no warranty of any kind.

This is a personal tool, not a product. I'm not shipping a packaged version, I have no roadmap, and I don't see any commercial use for it — it's here because it's useful to me and might be useful to someone else. If you want to fork it, rework it, or build something completely different on top of it, go ahead; that's exactly what MIT is for.

---

Made with a lot of help from [Claude](https://claude.ai). The irony of a Claude-built tool for browsing Claude's own conversation history is not lost on me.
