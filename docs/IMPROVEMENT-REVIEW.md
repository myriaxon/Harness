# Improvement review: what a full end-to-end pass found

**Date:** 2026-10-16 · **Commit tested:** `60ab275` · **Method:** ran the dashboard on the built code, drove
every API the UI calls, gave it real tasks, ran a Locus, read the log, and assessed the outcomes.

This is a **review**, not a wish list. Each item says how it is known and what was measured. Items marked
**FIXED** were fixed in the same pass; the rest are open with a recommended approach.

---

## What was tested, and the result

| Area | Method | Result |
|---|---|---|
| Dashboard API sweep | every GET route the UI calls, plus the POST-only ones | **PASS** (see note 1) |
| Task: write a file + read it back | real turn through `/api/chat`, file checked on disk | **PASS** — 8.0s, file created with exact content, 4 transparency events at layers 3 and 4 |
| Task: reason with no tools | real turn | **PASS** — 2.0s, `PONG` |
| Transparency feed | observed live during real turns | **PASS** — layers 3 and 4 populated, no secrets |
| Locus: create + run | `/api/loci` create, then run, transcript polled | **FAIL** — see item 1 |
| Log review | `~/.myriaxon/logs/myriaxon.log`, 154 KB | **1 real defect** — see item 2 |

**Note 1 — the 404s were mine, not the server's.** `/api/mcp`, `/api/rules`, `/api/plugins`, `/api/messaging`
and others are **POST-only** routes (`_save_mcp`, `_save_rules`, `reload_plugins`); their panels read from
`/api/config`, which returns **41 keys** including `mcp`, `plugins`, `rules`, `messaging` and `settings`.
No defect. Recorded because a reviewer who stops at the 404 will report five fake bugs.

---

## FIXED in this pass

### 1. A Locus run reported success and then did nothing — **FIXED**

**Severity: high.** The caller was told the run started; it never did.

Reproduced, then traced to the exact call:

```
POST /api/loci {action: run}   ->  {'accepted': True, 'reason': ''}
locus record                   ->  running=True, session_id=None, open_goals=1 (unchanged)
transcript                     ->  1 turn: the user prompt only. No assistant turn ever.
locus activity                 ->  [note] run refused: this locus is already running (pid 3456)
log                            ->  nothing at all
```

**Root cause.** The run lease was consulted **only inside the turn's worker thread**, by
`Locus.run_scope` (`loci.py:1864`). `run_locus` had already returned `accepted: True` by then, so the
refusal had nowhere to go but the locus's own activity log and a log line nobody reads.

**Why that is worse than a plain failure.** There was no error to act on. The panel showed "working now"
forever while the goal never advanced, and `session_id` stayed `None` — so the caller could not even tell
which of the two states it was in.

**Fix.** `run_locus` now asks `read_run_lease(locus)` **before scheduling anything** and returns
`accepted: False` with the holder's description. Because `read_run_lease` already returns `None` for a lease
whose owner is gone, this does **not** refuse a run because of a dead process — `acquire_run_lease` reclaims
those.

**Verified:** with the slot poisoned, `accepted` went from `True` to `False`.

### 2. The same stale lease was logged 84 times — **FIXED**

**Severity: low, and real.** Seven distinct dead pids produced **84 identical INFO lines** over three days:

```
INFO Reclaiming the run lease for 2508c6d7: its owner (pid 14092) is gone    x 40
INFO Reclaiming the run lease for 2508c6d7: its owner (pid 17980) is gone    x 15
```

**Root cause.** `_lease_from_path` logs whenever `_pid_alive()` is false. `read_run_lease` is called from
`Locus.is_running()`, which the **dashboard polls** to decide whether to show "working now" — so one dead
owner was logged on every poll, for up to the 30-minute stale window.

**Why it matters.** Every line was true, and the repetition made all of them worthless. This repository has
already recorded the same failure twice for other diagnostics: *a message nobody reads is a message that is
not there.*

**Fix.** `_announce_reclaimed_lease` deduplicates by `(lease path, pid)` and says it once. It deliberately
does **not** unlink the file: it runs on a read path, and deleting on read would let two pollers race to
unlink a lease that a third process created between the check and the delete. Reclamation stays with
`acquire_run_lease`, which does it under `O_EXCL`.

**Verified:** 12 reads → **1** log line (was 12). Acquisition after a dead owner still succeeds, so this was
log spam and never a deadlock.

---

## OPEN — recommended improvements, in priority order

### 3. A Locus run is invisible while it happens — **OPEN, medium**

The transcript for a running Locus contained **only the user prompt** for the entire run. A person watching
the panel cannot tell whether it is thinking, stuck, or dead — and item 1 shows that all three looked
identical.

**Recommend:** surface the worker's `RunOutcome` on the locus record so the panel can show the last step's
result, not just "working now". `locus.activity` already records `turn` entries; the *outcome* of the last
one is what is missing.

### 4. `run_locus` and `run_scope` disagree about who decides — **OPEN, medium**

Item 1 is a symptom of a layering problem: **two places decide whether a run may start**, one at submit time
and one inside the worker, and only the inner one is authoritative. That is the same shape as the two
execution gates this project already unified behind `shell_may_run`.

**Recommend:** add `Locus.may_run()` returning `(ok, reason)` and have **both** callers ask it, so the submit
path cannot report a success the worker will refuse.

### 5. `Locus.is_running()` polls the filesystem on every UI request — **OPEN, low**

It reads and parses `run.lease` per call, and the dashboard calls it per locus per poll.

**Recommend:** cache with a short TTL (1–2s). The lease already carries `acquired_at` and a heartbeat, so a
stale cache is bounded by the same window the lease itself uses.

### 6. No automated coverage for the failure that items 1 and 2 share — **OPEN, high value**

`tests/` covers the lease in isolation. **Nothing covered "the API says accepted and nothing happens"**, which
is why it shipped.

**Recommend:** a test that asserts the invariant directly — *if `run_locus` returns `accepted: True`, then
either the transcript grows or the locus's activity records a refusal*. Written against a poisoned lease, so
it fails on the pre-fix code.

### 7. `session_id: None` while `running: True` is a state no caller can use — **OPEN, low**

The two fields contradict each other. After item 1's fix the contradiction is harder to reach, but the
record can still hold it.

**Recommend:** treat `running` as derived (`is_running()`) rather than stored, or assert the pair cannot
disagree.

### 8. The activity log is the only place some refusals appear — **OPEN, low**

Item 1's refusal existed **only** as `[note] run refused: ...` in the locus's activity. A dashboard caller
sees nothing, and it is not in `myriaxon.log` either.

**Recommend:** route refusals through the transparency feed at the DECISIONS layer, which already exists for
exactly this ("the half a log usually omits") and is already streamed to the UI.

---

## Method notes, recorded so the review can be repeated

Two of my own measurement errors are worth keeping, because both produced **confident wrong answers**:

* **I reported a duplicated answer prefix as a bug.** `answer_delta` carries the **cumulative** answer and the
  UI does `innerHTML = md(text)` — it *replaces*. My script **joined** the deltas, which concatenates the same
  prefix repeatedly. `'TheThe file contains...'` was my harness, not the product.
* **I reported five 404s as broken panels.** They are POST-only routes; the panels read from `/api/config`.

Both are the same mistake: reading a result as a defect before checking how the consumer uses it. The
correction in each case cost one query.

## How to re-run this review

```bash
# 1. the dashboard on the built code
python -m myriaxon web --no-browser --port 8765 --workspace <repo>

# 2. every API the UI calls
python .bench-tmp/dashboard_sweep.py

# 3. real tasks, assessed on the outcome
python .bench-tmp/e2e_tasks.py

# 4. a locus, end to end
python .bench-tmp/e2e_locus.py

# 5. the log
grep -c "Reclaiming the run lease" ~/.myriaxon/logs/myriaxon.log    # 84 before the fix
```
