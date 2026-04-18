# Claude context windows — chat, Code, and Cowork

A short field guide to how much "working memory" Claude actually has in the three surfaces most people use day-to-day: the **chat** product at claude.ai, the **Claude Code** CLI, and **Cowork** in the Claude desktop app.

> **Why this lives in this repo.** Claude History Browser now shows a per-conversation token tally in the reader header. Those totals are *cumulative across the thread* — they are **not** a snapshot of the current context window. This doc explains the difference, so the number in the header doesn't get confused with what Claude can actually "see" at any one moment.

---

## 1. Context window in one paragraph

The **context window** is everything the model can reference when generating a reply — the system prompt, every prior message in the conversation, every tool call result, any loaded files or skills, and the output it's currently producing. It is *working memory*, not long-term memory. When a conversation gets long enough to press against the window, something has to give: the product either drops old turns (rolling eviction), summarizes them (compaction), or refuses new input (hard error). Bigger windows are useful, but research on "context rot" shows accuracy and recall degrade as the window fills — so the question is never just "how big?", it's "how big, and how is it managed?". [^apicontext]

---

## 2. Chat — claude.ai

| Plan | Context window |
|---|---|
| Free | ~200K tokens |
| Pro ($20/mo) | 200K tokens |
| Max | 200K tokens |
| Team | 200K tokens |
| Enterprise | 500K tokens (on supported models) |

A few practical notes specific to the chat product:

- **Rolling eviction is in play.** For chat interfaces, the window can behave like a FIFO queue — very old turns are dropped from what Claude sees, even though they still appear in the chat history you scroll through. The Anthropic context-window docs call this out explicitly for chat UIs. [^apicontext]
- **Automatic summarization is available on paid plans with code execution enabled.** As a conversation approaches the limit, earlier messages are condensed to free room for new ones, which is what lets long paid-plan conversations keep going "indefinitely" without a hard wall. [^helpplans]
- **The 1M-token option does not apply to claude.ai chat.** 1M is an API / Claude Code feature, not a chat product one (see §3).
- **Usage caps are a separate thing.** A Pro user typically gets on the order of ~45 messages per 5-hour window — that's a *rate* limit, not a context limit, and is tracked per-plan rather than per-conversation. [^aionx]

**Rule of thumb for chat users:** treat 200K as "plenty for one long document or a dense conversation, but not unlimited." If you're pasting entire books, splitting across threads or switching to the API is usually the answer.

---

## 3. Claude Code (CLI)

Claude Code is the engine under the terminal CLI and — importantly — under Cowork's file/shell work too. Its context story is the most mechanical of the three:

| Tier | Context window |
|---|---|
| Default | **200K tokens** |
| With Pro "extra usage" or Enterprise, using Opus 4.7 / 4.6 or Sonnet 4.6 | **1M tokens** |

### What gets loaded automatically at session start

Every Claude Code session begins by auto-loading a handful of things into the window before you type anything. Approximate typical sizes, from Anthropic's own context-window explorer: [^codectx]

| Item | Approx. tokens |
|---|---|
| System prompt | ~4,200 |
| Auto memory (`MEMORY.md`, first 200 lines / 25KB) | ~680 |
| Environment info (cwd, platform, git) | ~280 |
| MCP tool names (schemas deferred) | ~120 |
| Skill descriptions (one-liners) | ~450 |
| Global `~/.claude/CLAUDE.md` | ~320 |
| Project `CLAUDE.md` | ~1,800 |
| **Typical startup subtotal** | **~8K tokens** |

Everything else — file reads, tool outputs, thinking blocks, large skill bodies, sub-agent transcripts — is added *as you go*, and that's where a session's window really fills up.

### Auto-compact — when Claude Code summarizes behind your back

When a session gets close to the ceiling, Claude Code runs an auto-compaction pass: it generates a structured summary of older turns and replaces them with that summary, so the conversation can keep going. Key details:

- **Default trigger: ~83–83.5% of the window.** The older "95%" threshold that circulates in blog posts is out of date; the current default is around 83%. [^autocompact] [^override]
- **`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` can only *lower* the threshold**, not raise it. Power users who want more aggressive compaction set it to 70 or 75; attempts to raise it to 90 or 95 get clamped. [^override]
- **Auto-compact is reactive, not proactive.** By the time it fires you've already paid full token cost for the content being summarized, and detail gets lost in the summarization. Anthropic and most experienced users recommend running `/compact` manually around 60% capacity, before the automatic one kicks in. [^mindstudio]
- **Not everything survives compaction.** Skill *descriptions* (the index listing) are not re-injected after compaction — only skills you've actually invoked are preserved. Project `CLAUDE.md` and the system prompt do survive. [^codectx]
- **Hooks fire around compaction.** The `PreCompact` hook runs before every compaction pass (manual or automatic), which is what blog posts describing "context backups" hook into. [^precompact]

### Context awareness (new in the 4.5 / 4.6 generation)

Sonnet 4.6, Sonnet 4.5, and Haiku 4.5 now receive an explicit budget header and periodic usage updates during long tool-use loops: [^apicontext]

```xml
<budget:token_budget>200000</budget:token_budget>
...
<system_warning>Token usage: 35000/200000; 165000 remaining</system_warning>
```

That's why 4.5+ models handle long agentic tasks better — they're no longer "cooking without a clock." Note the Anthropic docs list Sonnet 4.6 / 4.5 / Haiku 4.5 explicitly; Opus 4.7's behavior here is worth confirming against current release notes if you're relying on the feature.

**Rule of thumb for Claude Code users:** assume 200K unless you've paid for 1M. Keep `CLAUDE.md` under ~200 lines. Run `/compact` yourself around 60%. Move reference content into skills so it only loads when you actually use it.

---

## 4. Cowork (desktop)

Cowork sits *on top of* Claude Code — the same engine, wrapped in a chat-style desktop UI with workspace folders. So its context mechanics inherit almost everything from §3, with a few product-level wrinkles:

- **Cowork can use the 1M-token window.** On Max 5x with Opus 4.6, Anthropic's announcement on **2026-03-13** put the 1M context window into general availability for Cowork alongside Claude Code. [^cowork1m]
- **There is an active "1M is missing" bug in Cowork on macOS.** Some Max 5x accounts see Cowork report just "Opus 4.6" instead of "Opus 4.6 (1M Context)", even while Claude Code on the same account correctly shows the 1M indicator. If you suspect you're stuck on 200K in Cowork, check the model label in the session picker against the GitHub issue. [^cowork1mbug]
- **"The folder is the context."** Cowork's mental model is that your selected workspace folder — plus whatever files you drop in and what Claude generates — is the substrate it works on. The live context window still behaves like Claude Code's (system prompt, memory, skills, file reads, tool outputs), but files in the workspace are loaded on-demand, not all at once.
- **Compaction and memory still happen.** Cowork sessions can last a long time and compact just like Claude Code sessions, which is why the auto-memory system exists: facts the model wants to remember across compactions (and across sessions) are written to `MEMORY.md` and re-loaded at the start of each new session. That's a separate persistence layer from the context window itself.

**Rule of thumb for Cowork users:** you're on the Claude Code engine, so the thresholds, hooks, and compaction mechanics above all apply. If you have Max 5x and want the 1M window, verify the label in the model picker and file a bug if it's missing.

---

## 5. Model-level reference table

Context windows by model, as of April 2026: [^apicontext] [^apimodels]

| Model | Input context window | Max output tokens |
|---|---|---|
| Claude Opus 4.7 | 1M | 128K |
| Claude Opus 4.6 | 1M | 128K |
| Claude Sonnet 4.6 | 1M (tier-gated on API) | 64K |
| Claude Sonnet 4.5 | 200K | 64K |
| Claude Haiku 4.5 | 200K | 64K |

On the API, the 1M window on Sonnet 4.6 is generally available but usage-tier-gated (historically Tier 4+ or custom rate limits). On Opus 4.7 and 4.6, the 1M window is the native ceiling. Chat (claude.ai) does not expose 1M today regardless of model — see §2.

---

## 6. How this relates to Claude History Browser

The token counts shown in this browser's conversation header come from summing the `usage` field on every assistant turn in the transcript: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. That means:

- **It is a running total across the whole conversation.** A thread that ran for hours and compacted twice can show "900K in / 300K out" even on a 200K model, because every turn's input count was billed against that 200K budget *separately*.
- **It is not what the model had in context at any one moment.** During the session, the actual live context window was being pruned by compaction and never exceeded the model's real limit (200K or 1M, per §5).
- **Cache-read tokens are usually the biggest number.** Prompt caching replays the same system prompt, memory, and early turns on every request; those re-reads show up as cache-read input tokens and are the reason a long session's cumulative input total can dwarf the model's actual context window. This is normal and billed at a fraction of fresh-input price.
- **It is still useful.** It's a good proxy for "how expensive was this thread to run?" and "how much did this conversation actually cost in raw work?" — just don't mistake it for "how full was the window?".

If you want a true snapshot of how full the window got, look for `context-warning` or compaction events in the transcript itself (reader pane), not at the header totals.

---

## 7. Caveats on the numbers

- **These figures move.** Context-window tiers, auto-compact thresholds, and 1M-window availability have all changed more than once in the last year. Before relying on a number here for a purchase decision, check the sources at the end.
- **Thresholds and auto-loaded sizes are approximate.** The ~8K "startup subtotal" in §3 is drawn from Anthropic's own explorer page and will vary with your memory file, `CLAUDE.md`, and MCP/skill setup.
- **Enterprise and custom-contract numbers vary.** The 500K Enterprise window and the 1M Cowork/Code tier can be different under bespoke contracts; the table above reflects the publicly documented defaults.
- **This document is not from Anthropic.** It's a practitioner's summary that stitches public docs together. Where this doc and Anthropic's current help pages disagree, believe the help pages.

---

## Sources

- [Context windows — Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/context-windows) — authoritative on per-model window sizes, context awareness, extended-thinking math.
- [How large is the context window on paid Claude plans? — Claude Help Center](https://support.claude.com/en/articles/8606394-how-large-is-the-context-window-on-paid-claude-plans) — chat product tiers, Enterprise 500K, code-execution summarization.
- [Explore the context window — Claude Code Docs](https://code.claude.com/docs/en/context-window) — interactive breakdown of what Claude Code auto-loads, compaction behavior, hook points.
- [Models overview — Claude API Docs](https://platform.claude.com/docs/en/about-claude/models/overview) — current per-model input/output limits.
- [CLAUDE_AUTOCOMPACT_PCT_OVERRIDE cannot raise threshold above default (~83%) — anthropics/claude-code #31806](https://github.com/anthropics/claude-code/issues/31806) — current default auto-compact threshold, clamping behavior.
- [Feature Request: Configurable Context Window Compaction Threshold — anthropics/claude-code #15719](https://github.com/anthropics/claude-code/issues/15719) — history of the 95% → 83% threshold change.
- [[BUG] Cowork 1M context window unavailable on Max 5x — anthropics/claude-code #37413](https://github.com/anthropics/claude-code/issues/37413) — Cowork 1M label regression on macOS.
- [How to Use the /compact Command in Claude Code to Prevent Context Rot — MindStudio](https://www.mindstudio.ai/blog/claude-code-compact-command-context-management) — practitioner guidance on manual `/compact` timing.
- [Claude Code Session Hooks: Auto-Load Context Every Time — claudefa.st](https://claudefa.st/blog/tools/hooks/session-lifecycle-hooks) — PreCompact / SessionStart hook details.
- [Claude AI Message Limit: Free vs Pro Caps — AIonX](https://aionx.co/claude-ai-reviews/claude-ai-message-limit/) — per-plan message-rate caps (context for §2).

[^apicontext]: Context windows — Claude API Docs. https://platform.claude.com/docs/en/build-with-claude/context-windows
[^helpplans]: How large is the context window on paid Claude plans? — Claude Help Center. https://support.claude.com/en/articles/8606394
[^aionx]: Claude AI Message Limit — AIonX. https://aionx.co/claude-ai-reviews/claude-ai-message-limit/
[^codectx]: Explore the context window — Claude Code Docs. https://code.claude.com/docs/en/context-window
[^autocompact]: Feature Request: Configurable Context Window Compaction Threshold — anthropics/claude-code #15719. https://github.com/anthropics/claude-code/issues/15719
[^override]: CLAUDE_AUTOCOMPACT_PCT_OVERRIDE cannot raise threshold above default — anthropics/claude-code #31806. https://github.com/anthropics/claude-code/issues/31806
[^mindstudio]: `/compact` command guidance — MindStudio. https://www.mindstudio.ai/blog/claude-code-compact-command-context-management
[^precompact]: Claude Code Session Hooks — claudefa.st. https://claudefa.st/blog/tools/hooks/session-lifecycle-hooks
[^cowork1m]: Claude's 1 Million Context Window: What Changed and When It's Worth Using (2026). https://karozieminski.substack.com/p/claude-1-million-context-window-guide-2026
[^cowork1mbug]: [BUG] Cowork 1M context window unavailable on Max 5x — anthropics/claude-code #37413. https://github.com/anthropics/claude-code/issues/37413
[^apimodels]: Models overview — Claude API Docs. https://platform.claude.com/docs/en/about-claude/models/overview
