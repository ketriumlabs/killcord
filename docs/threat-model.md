# Threat model

## What killcord protects against

- An agent loop that keeps spending/acting past a limit you set, because
  nothing in the loop itself checks — `Tripwire.check()` is an explicit,
  synchronous gate you insert.
- Losing track of *why* something got blocked — the pending snapshot always
  carries the tool, target, spend, and the specific reason it tripped.
- A tripped action executing twice because of a naive retry — see
  [resume-semantics.md](resume-semantics.md) for the at-most-once guarantee.
- Losing your caps on a crash/restart — counters are persisted, not
  in-memory only.

## What killcord does NOT protect against

- **Code that bypasses `tw.check()` entirely.** killcord is a library you
  call, not a sandbox. If part of your agent's tool surface doesn't route
  through a guarded call (or an adapter), killcord never sees it. The
  OpenAI/Anthropic adapters intercept at the httpx transport layer
  specifically to close this gap for those two SDKs — but only for traffic
  that actually goes through the wrapped client.
- **Exact spend accounting.** Adapter spend estimates come from published
  per-token pricing tables hardcoded in this repo (`adapters/openai.py`,
  `adapters/anthropic.py`). These drift as providers change prices and
  release new models. Treat `max_spend` as a strong safety margin, not a
  billing-accurate ledger. For exact accounting, call `record_spend()`
  yourself from your own cost calculation.
- **A single request's own cost.** The Tripwire is checked *before* a
  request goes out, using spend accrued *so far* — a request's own cost
  isn't known until its response comes back, so a single expensive call can
  push spend over the cap; the *next* call is what trips. See
  `adapters/_httpx_transport.py`'s docstring.
- **A compromised or malicious agent that specifically targets killcord's
  files.** Anyone with write access to the `store` directory can edit
  `state.json` to reset counters, or fabricate an "approved" decision in
  `pending.json`. This is a local trust boundary, same as any file-based
  tool — protect the directory with normal filesystem permissions.
- **The pause server has no authentication in v0.1.** It binds to
  `127.0.0.1` by default (opting into `--host 0.0.0.0` is explicit and your
  choice, exposing it to your network with no login). Don't expose it
  publicly without putting your own auth in front of it.
- **Multi-agent coordination.** One Tripwire, one store directory, one set
  of counters. Running multiple agents against the *same* store works
  (that's how state persists across restarts) but there's no per-agent
  breakdown — see plan.md's non-goals.

## Reporting a security issue

See [SECURITY.md](../SECURITY.md). Anything that breaks the at-most-once
resume guarantee is treated as HIGH severity by definition.
