# History retention — what this browser can actually see

This document explains how long Claude keeps your conversation history on disk, what controls that, and how it affects Claude History Browser. It's worth reading once — a five-minute tweak to one config file can be the difference between a month of scrollback and a year.

> **TL;DR —** Claude Code auto-deletes your local `.jsonl` transcripts after **30 days** by default. This browser can only show what's still on disk. Change `cleanupPeriodDays` in `~/.claude/settings.json` to extend that window, or copy the folder elsewhere for a permanent archive.

---

## 1. The local 30-day clock is the one that matters here

Claude History Browser can only surf what is sitting on disk. Claude Code (and the desktop app / Cowork sessions that wrap it) writes every conversation as a JSONL transcript under:

```
~/.claude/projects/<project-hash>/<session-id>.jsonl
```

Every time Claude Code starts up, it runs a housekeeping pass and deletes transcript files whose last-modified time is older than `cleanupPeriodDays`. The default is **30**, so anything you haven't touched in the last month quietly disappears on the next launch. There is no prompt, no Trash, no undo — once it's swept, this browser has nothing left to index.

**Implication for this app:** the effective history horizon of Claude History Browser equals `cleanupPeriodDays` on the machine running it. No more, no less.

---

## 2. `cleanupPeriodDays` is the single knob you care about

The setting lives in `~/.claude/settings.json` (create the file if it's missing) as a top-level integer. For example:

```json
{
  "cleanupPeriodDays": 365
}
```

- Set it to `365` to get a year of scrollback.
- Set it to `3650` to effectively opt out of cleanup.
- Set it to a smaller number (e.g. `7`) if you *want* aggressive cleanup.

A few things worth knowing:

- **Per-machine, per-user.** The setting isn't synced anywhere. Each computer you use Claude on needs its own value.
- **Based on mtime, not creation time.** Opening an old session in this browser does not "refresh" it unless something writes to the file (this browser doesn't).
- **Do it now, not later.** Raising `cleanupPeriodDays` after a sweep has already happened won't bring deleted files back. Set it *before* you lose anything.

### Quick recipe

```bash
# macOS / Linux
mkdir -p ~/.claude
python3 -c "import json, os, pathlib; \
p = pathlib.Path.home() / '.claude' / 'settings.json'; \
d = json.loads(p.read_text()) if p.exists() else {}; \
d['cleanupPeriodDays'] = 365; \
p.write_text(json.dumps(d, indent=2))"
```

On Windows (PowerShell):

```powershell
$path = "$env:USERPROFILE\.claude\settings.json"
if (-not (Test-Path $path)) { New-Item -ItemType File -Force -Path $path | Out-Null; Set-Content $path '{}' }
$json = Get-Content $path -Raw | ConvertFrom-Json
$json | Add-Member -NotePropertyName cleanupPeriodDays -NotePropertyValue 365 -Force
$json | ConvertTo-Json | Set-Content $path
```

---

## 3. There is no cloud copy of the local `.jsonl` files

This is the point most people get wrong. The `.jsonl` transcripts under `~/.claude/` are produced **locally** by the CLI, desktop app, and Cowork sessions, and stored **only locally**. If the cleanup sweep eats them, they're gone — Anthropic doesn't have them to give back, and this browser can't recover them.

The retention numbers you'll see quoted in articles about "Claude data retention" apply to a different thing entirely: conversations you had in the web product at **claude.ai**. They do not apply to your local `.jsonl` files, and they are not queryable by this app.

For reference, here are the three cloud-side numbers that often get confused with the local one:

- **Normal chats on claude.ai.** Removed from your chat history in the UI the moment you delete them, and scrubbed from Anthropic's backend within **30 days**. Cloud-only. Not accessible to this browser.
- **Chats flagged by trust & safety classifiers.** Inputs/outputs retained up to **2 years**; classifier scores up to **7 years**. Cloud-only.
- **Opt-in "Help improve Claude".** De-identified copies may live in training pipelines for up to **5 years**. Cloud-only.

None of these govern what this browser can show you. Only `cleanupPeriodDays` does.

---

## 4. Practical recommendations for users of this browser

1. **Raise `cleanupPeriodDays` today.** Before you forget. A year (`365`) is a sensible default; power users who want to treat their history as a personal knowledge base often go higher.
2. **Archive somewhere outside `~/.claude/`.** If you want hard, long-term browsable history that is immune to the cleanup sweep, periodically copy the `~/.claude/projects/` tree into a separate folder (e.g. `~/ClaudeArchive/`). Once the `.jsonl` files live outside `~/.claude/`, the cleanup doesn't touch them. Point Claude History Browser at the archive folder and you can scroll back as far as you like.
3. **Automate the archive.** A simple cron / launchd / Task Scheduler job works:

   ```bash
   # macOS / Linux — daily mirror at 3am
   0 3 * * * rsync -a --delete ~/.claude/projects/ ~/ClaudeArchive/
   ```

   `rsync -a` preserves timestamps so the archive stays browsable chronologically. Drop `--delete` if you prefer an ever-growing copy.
4. **Treat the archive like sensitive workspace data.** Transcripts include absolute file paths, tool calls, and pasted content. Store the archive on an encrypted disk, keep it out of public cloud-sync folders, and add it to your backup routine alongside anything else private.
5. **Point the browser at whichever folder you want at runtime.** The UI lets you change the scanned folder — you can keep a "live" view of `~/.claude/projects/` and a separate "archive" view of `~/ClaudeArchive/` and switch between them.

---

## 5. TL;DR again, because this is the whole point

- Claude History Browser's horizon = whatever `cleanupPeriodDays` lets live in `~/.claude/projects/`.
- Default is **30 days**. Raise it. Ideally now.
- For permanent history, copy the folder somewhere else and point the browser there.
- Cloud-side retention (claude.ai) is a separate thing and does not affect what this app can see.

---

## Sources

- [How long do you store my data? — Anthropic Privacy Center](https://privacy.claude.com/en/articles/10023548-how-long-do-you-store-my-data)
- [How long do you store my organization's data? — Anthropic Privacy Center](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- [How Claude Code Manages Local Storage — Milvus Blog](https://milvus.io/blog/why-claude-code-feels-so-stable-a-developers-deep-dive-into-its-local-storage-design.md)
- [Does Claude Code store my data? — ClaudeLog](https://claudelog.com/faqs/does-claude-code-store-my-data/)
