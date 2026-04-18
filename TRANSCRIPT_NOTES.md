# Transcript notes — things that may look odd in the reader

Claude writes conversation transcripts as `.jsonl` files — one JSON record per line. The browser parses those records and renders them as a chat view. Most of it is straightforward, but a handful of quirks in the underlying format can make the reader look weird, wrong, or broken when it's actually showing you exactly what's on disk. This document catalogs the ones that matter.

If something in the reader surprises you, check here before assuming it's a bug.

---

## The two different `type` fields

Every `.jsonl` record carries a top-level `type`. And inside each message, the `content` array carries blocks that *also* have a `type`. These are separate fields with separate vocabularies.

### Top-level `type` — what kind of record is this line?

Counts come from a real 962-record sample of the author's own history, so you can see how common each is in practice.

| `type` | Share | What it is | Does the reader show it? |
|--------|-------|-----------|--------------------------|
| `user` | ~31% | A user-role message. Holds **what you typed** — or, confusingly, a tool-result the client sent back to Claude. (The API protocol requires tool-results to travel as `user` messages.) | Yes — the reader labels them **👤 You**, **📤 Tool result**, or **⚙️ System** depending on content. |
| `assistant` | ~46% | Claude's reply. Contains text, thinking, and any tool calls Claude made. | Yes — labeled **✦ Claude**. |
| `attachment` | ~5% | A file-upload envelope — metadata accompanying an image, PDF, etc. | No — ignored. |
| `last-prompt` | ~6% | A snapshot Claude Code writes of the prompt that produced the next reply. Used internally for caching/diff. | No — ignored. |
| `queue-operation` | ~4% | Scheduling/queue bookkeeping from Cowork (agent queued, agent resumed). | No — ignored. |
| `system` | <1% | System-level config or environment records. | No — ignored. |
| `ai-title` | <1% | The auto-generated title for the conversation. | Used for the conversation title in the sidebar; not rendered as a message. |

The reader's message area only renders `user` and `assistant` top-level records. The others exist in the file, but they're infrastructure, not conversation.

### Content-block `type` — what kind of block is inside a message?

Each `user` or `assistant` record has a `message.content` field that is **an array of blocks**. Every block has its own `type`:

| block `type` | What it is | How the reader renders it | Filter chip |
|--------------|-----------|---------------------------|-------------|
| `text` | Plain prose — the actual text of what was said. | Plain text in the message bubble. | 👤 **You** (in user turns) / ✦ **Claude** (in assistant turns) |
| `tool_use` | Claude asking a tool to run, with its name and JSON input. Always in assistant messages. | 🔧 **ToolName** label + the `input` as a `<pre>` block. | 🔧 **Tool** |
| `tool_result` | The tool's response coming back. **Always stored inside a user-role message** (protocol quirk). | 📤 **Result** box with the output. | 📤 **Result** |
| `thinking` | Claude's internal reasoning, stored as `{type: "thinking", thinking: "…", signature: "…"}`. Always in assistant messages. | 🧠 **Thinking** collapsible block. | 🧠 **Thinking** |
| `image` | An image block — uploaded by you or produced by a tool. | Currently passed through in the data but not rendered inline (known gap). | — |

---

## Misunderstanding #1: "YOU" doesn't always mean you typed it

The Anthropic API protocol requires that when a tool finishes running, its output travels back to Claude **inside a `user`-role message** — even though *you* didn't produce it. Technically the "user" in that protocol means "the party talking to Claude," which is the client software, not the human.

So a raw JSONL `user` record can contain any of:

1. **Real text you typed** — what you probably think of as "you."
2. **A tool_result block** sent back by the client (Claude Code, Cowork, the API).
3. **Client-injected metadata** like `[Image: …]` markers, `<system-reminder>` tags, or `<command-name>` instructions.

The reader disambiguates this at display time:

- A user turn with real typed text → **👤 You** (purple).
- A user turn whose only content is a `tool_result` block → **📤 Tool result** (muted).
- A user turn whose only content is injected metadata → **⚙️ System** (muted).
- A mixed user turn (typed text plus a metadata line) still shows as **👤 You**, but the metadata line is rendered in a dim "this came from the client, not you" style.

This is why, if you glance at the raw JSONL, you'll see lots of `{"type": "user", ...}` records that aren't things you typed. The reader's labeling is more honest than the file's `type` field.

---

## Misunderstanding #2: Many thinking blocks are empty

Thinking blocks are stored like this:

```json
{"type": "thinking", "thinking": "...reasoning text...", "signature": "EtUCC..."}
```

The `signature` is an **encrypted cache key** the API uses internally. The `thinking` field holds the actual readable reasoning — *when it was persisted*. For many turns (in particular: shorter replies, replies where extended thinking didn't meaningfully engage, or responses from model configurations that don't retain thinking text), the `thinking` field comes back as an empty string and only the signature remains.

The reader used to render these as empty 🧠 **Thinking** boxes that expanded to show nothing. That was confusing — it looked like a rendering bug. The current behavior is to **drop thinking blocks with no readable text** at parse time, so they never appear. When thinking text *is* present, it renders normally.

So: if a conversation looks thinking-less, it's probably not that Claude didn't think — it's that the API didn't persist the thinking text to disk for those turns.

---

## Misunderstanding #3: Token counts are cumulative, not a context-window snapshot

The header shows things like `561 in / 305K out`, with a tooltip breaking out cache-read and cache-write. Those numbers are **summed across every assistant turn** in the conversation. They come from the `usage` dict the API stamps on each reply:

```json
"usage": {
  "input_tokens": 561,
  "output_tokens": 248,
  "cache_read_input_tokens": 14025,
  "cache_creation_input_tokens": 0
}
```

The reader sums `input_tokens`, `output_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` across every assistant turn and displays the totals.

### What can mislead you

- **A 30M cache-read number does not mean the context window is 30M tokens.** The context window at any one moment is the model's maximum (e.g. 200K for Claude). Each turn re-reads most of its context — and that re-read gets billed as cache-read. Over a long conversation, the same tokens get counted dozens of times in the running total.
- **"561 in" can look absurdly small next to a huge cache-read number**, but that's prompt caching doing its job: almost all of the input for each turn was served from the cache, so only a tiny slice counts as fresh input.
- **Per-turn badges on assistant replies** show *only* `input_tokens` + `output_tokens` for that single turn, to keep them compact. They do not include cache figures. If you need the full breakdown for a specific reply, the raw `usage` dict in the JSONL is the source of truth.

### Where to see which

- **Conversation header** — totals for the whole thread, with tooltip for the cache breakdown.
- **Per-turn badge** — just the input/output of one reply. Hover for the full count in commas.

---

## Misunderstanding #4: The conversation you see isn't always in chronological "conversation" order

Some records are not conversation turns (see the top-level `type` table above). They're infrastructure — attachments, queue operations, last-prompt snapshots — and the reader filters them out. So if you open the raw file and count lines, you'll see more lines than messages in the reader. That's expected.

Within the filtered `user` / `assistant` turns, order **is** preserved as written to disk. If turns look out of order, it's almost certainly that a Cowork session was resumed or branched — in which case the ordering on disk reflects the client's actual reconstruction of the thread, not a bug in the reader.

---

## Misunderstanding #5: Images aren't rendered inline (yet)

Image blocks appear in the data as `{"type": "image", ...}`. The reader currently doesn't render them inline in the conversation pane — they're tracked but skipped. If you need to see the image, open the `.jsonl` directly or check the attachment file referenced alongside it.

A fix for this is on the wish-list (see *Ideas for improvement* in the README).

---

## What the reader **doesn't** currently tell you

For completeness, here are things the JSONL knows that the reader doesn't yet surface:

- `sessionId` — the Claude Code / Cowork session nickname. Partially used for the "project (session)" label; not always shown.
- `cwd` — the working directory Claude Code was running in. Useful for remembering *which* codebase a conversation was about.
- `gitBranch` — the git branch at the time of the conversation.
- `version` — Claude Code version.
- `userType` — whether the user was acting as developer, admin, etc.

These are all available in `/api/conversations` responses and could be surfaced in the UI if useful to you. If one of them would genuinely help, open an issue.

---

## TL;DR

- Top-level `type` tells you what a JSONL *line* is. Most records are `user` or `assistant`; everything else is infrastructure the reader skips.
- Inside a message, a block's `type` tells you what *kind* of thing is in the message (text, thinking, tool call, tool result, image).
- A `user`-role message isn't always you — it might be a tool result, or client metadata. The reader relabels those as **📤 Tool result** or **⚙️ System**.
- Empty thinking blocks mean "Claude didn't persist readable reasoning for this turn" — not a bug.
- Token totals in the header are cumulative across turns, not the size of the context window.
