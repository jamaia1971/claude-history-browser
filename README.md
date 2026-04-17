# Claude History Browser

A local web app for browsing your Claude conversation history (`.jsonl` files) via a clean browser UI.

## What it does

- Scans your Claude history folder (e.g. `~/.claude/projects/`) for conversation files
- Displays conversations in a chat-like interface with tool calls, results, and thinking blocks
- Full-text search across all conversations
- Filters by project folder

## Requirements

- Python 3.8+
- macOS (the folder picker uses AppleScript; on Linux/Windows, set the path manually — see below)
- Flask (auto-installed on first run)

## Usage

```bash
python3 claude_history_browser.py
```

**First run:** a macOS Finder dialog opens so you can select your history folder.  
The default is `~/.claude/projects/` — select that (or wherever your `.jsonl` files live).  
The path is saved to `~/.claude_history_browser.json` and reused on future runs.

**Subsequent runs:** launches instantly at [http://localhost:5757](http://localhost:5757).

## Where Claude history lives

| Tool | Default history path |
|------|----------------------|
| Claude Code (CLI) | `~/.claude/projects/` |
| Cowork (desktop) | Inside the workspace folder you selected |

Each project is a subfolder; each conversation is a `.jsonl` file inside it.

## Changing the folder

Click **📂 Change folder** in the top-right of the UI, or delete `~/.claude_history_browser.json` and restart.

## Linux / Windows

Replace the `pick_folder_mac()` call with a `tkinter` dialog:

```python
import tkinter as tk
from tkinter import filedialog

def pick_folder():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title="Select Claude history folder")
```

## License

MIT
