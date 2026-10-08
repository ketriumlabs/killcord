# Resume semantics

This is the part that makes killcord more than a kill switch. Read this
before relying on it in anything that spends real money.

## The lifecycle

```
Tripwire.check(action)
   │
   ├─ within limits → counters updated, persisted, return normally
   │
   └─ over limit → SnapshotStore.write_pending(action, reason)   [atomic write]
                    raise TripwireTripped(snapshot_id, reason, action)

killcord serve  (or CLI)
   │
   └─ human sees the exact pending action → decide(token, approved) [atomic write]

Tripwire.resume(token)
   │
   └─ SnapshotStore.resume(token):
        - consumed-marker exists?           → AlreadyConsumedError
        - no pending snapshot for token?    → NoPendingSnapshotError
        - decision not made yet?            → NoPendingSnapshotError
        - otherwise: atomically rename pending.json → pending.json.consumed-<token>
                     → return Decision(approved, action)
      if approved: counters updated as if check() had passed
      caller is responsible for actually performing the action
```

Only one trip may be pending in a store at a time. A later trip raises
`PendingSnapshotExistsError` until the existing trip is consumed; it cannot
silently replace the action awaiting review. Once a decision is recorded, it
is final: repeating the same verdict is safe, while requesting the opposite
verdict returns HTTP 409 from the pause server (and raises
`DecisionAlreadyRecordedError` through the store API).

## The three files on disk

Everything lives under the Tripwire's `store` directory (default
`~/.killcord/default`), as plain JSON — `cat` them any time.

- **`state.json`** — persistent counters (spent, action_count, rate_events).
  Written on every successful `check()` and every approved `resume()`. This
  is what makes caps survive a process restart (Design invariant 4).
- **`pending.json`** — the current tripped action, if any. Written atomically
  when a trip happens; updated (still atomically) when a human decides.
- **`pending.json.consumed-<token>`** — an empty marker file left behind by
  `resume()`. Its only job is to make a second `resume()` call for the same
  token fail loudly instead of silently re-permitting the action.

## Why atomic writes are the whole game

Every write to any of these three files goes through
`atomic_write_text()`/`atomic_rename()`
([`snapshot/atomic.py`](../src/killcord/snapshot/atomic.py)): write to a
temp file in the same directory, `fsync`, then `os.replace()` — which is
atomic on both POSIX and Windows. A process killed at any point during a
write leaves either the old file completely intact or the new file
completely written. There is no state where a reader sees a half-written
JSON file.

## The at-most-once guarantee, precisely

**Claim:** for a given trip token, `resume()` returns a real `Decision`
(approved or denied) to at most one caller, ever.

**Why it holds:** the linearization point is the `os.replace()` inside
`atomic_rename()` that moves `pending.json` to the consumed-marker path.
Renames on both POSIX and Windows are atomic — exactly one caller's rename
call can be the one that finds the source file present and succeeds; every
other caller (whether truly concurrent or arriving after a crash-and-restart)
either sees the consumed-marker already present, or has its own
`os.replace()` raise `FileNotFoundError` because the source is already gone.
Both cases are turned into `AlreadyConsumedError`.

**What this does NOT guarantee:** that the action itself executes exactly
once. killcord tells the caller *"you may proceed"* at most once — it does
not execute the action for you and cannot stop a caller from performing it
twice through some other bug. If the process crashes after consuming the
token but before actually performing the action, the action never executes
at all. This is the deliberately safe direction: **zero-or-one, never
two-or-more.** See [`tests/test_crash_injection.py`](../tests/test_crash_injection.py)
for the tests that pin this down, including a simulated crash injected
*between* the rename committing and the Decision being returned.

## What "review-and-resume" looks like end to end

1. `tw.check(action)` raises `TripwireTripped`, snapshot written to disk.
2. Push notification fires (if `notify=` configured) with the resume command.
3. Human opens `killcord serve`, sees the exact tool/target/spend that
   tripped it, clicks Approve or Deny.
4. Your code calls `tw.resume(snapshot_id)` (typically: catch
   `TripwireTripped`, block on human input via whatever mechanism fits your
   app — polling the CLI, waiting on the pause server, a Slack bot, anything
   that eventually calls `resume()`), gets back a `Decision`.
5. If `decision.approved`, perform the action yourself and continue your
   loop. If not, skip it and continue (or stop, your call).

killcord deliberately does not "replay" the action for you — it doesn't
know how. It answers exactly one question: *is this specific action, that
tripped for this specific reason, permitted to proceed?*
