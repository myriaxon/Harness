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

## FIXED in this pass, second round — all six open items built

### 3. A Locus run was invisible while it happened — **FIXED**

`Locus.end_run` now records `last_outcome` — `{ok, kind, attempts, summary, error, at}` — and the panel
renders it on the locus card with a "12s ago" age. The server serves it as `last_outcome`; the card shows
a green or red dot and, on failure, the error text.

**It has to reach the disk, and the first version did not.** `_loci_payload` reloads from `loci.json` on
every request, so an outcome held only in memory was discarded before it could be rendered: the field would
have existed, been correct, and never appeared. `end_run` now persists through `registry.persist`, which
reloads first and re-inserts THIS locus, so a concurrent edit from the terminal is not reverted.

### 4. Two places decided whether a run could start — **FIXED**

`Locus.may_run()` returns `(ok, reason, holder)` and is now the single answer. `run_locus` asks it at submit
time and `begin_run` formats its refusal at run time, so the two cannot disagree again. This is the same
shape as `tools.shell_may_run`, which closed two earlier bypasses for the same reason.

The refusal reason carries the holder's pid and start time, because "already running" without those is the
kind of message that sends somebody hunting through log files.

### 5. `is_running()` re-read and re-parsed the lease per UI request — **FIXED**

Cached for one second, invalidated by `_forget_running()` wherever THIS process changes the answer
(acquiring or releasing). A caller passing an explicit `now` is asking a hypothetical and always gets a
fresh read, which is what keeps the expiry behaviour testable without waiting out the stale window.

### 6. Nothing tested the caller's contract — **FIXED**

`tests/test_locus_run_contract.py` (6 tests) and `tests/test_locus_run_contract_extra.py` (12 tests) assert
what a surface depends on: `accepted: True` means the run started; a refusal is visible; the outcome is
served; a dead owner never refuses; and the cache cannot outlive the fact it caches.

**Two of these tests were wrong before they were right**, and both times the code was correct:
the lease fixture first poisoned with a DEAD pid and expected a refusal — but a dead owner is correctly
reclaimed, so the run proceeded. The pid is now explicit and the held case uses a live one.

### 7. `running: True` with `session_id: None` — **FIXED**

The payload now carries `has_session` explicitly, so a panel does not have to infer whether a transcript
exists from two fields that can disagree.

### 8. Refusals appeared only in the locus's activity log — **FIXED, and it was worse than reported**

The investigation found that `transparency.emit` had **exactly one call site in the entire codebase**, and
it was `set_level` announcing that the level had changed. The DECISIONS layer — described in the module as
"gates: refusals, confirmations, risk, budget" — **had never emitted anything at all.** A dial offering a
category of event the program never produces is not transparency; it is a panel that looks wired up.

Two changes:
* Locus run refusals now emit at DECISIONS with `detail.gate = "locus-run"`, so the feed says which gate
  refused.
* `emit(..., always=True)` bypasses the dial for **refusals only**. At the default level 3 the DECISIONS
  layer (level 7) is off entirely, so without this the fix would have been invisible at the very setting
  most people use. The dial exists to lower the volume on the ordinary traffic of a working agent; a
  refusal means something the owner asked for did not happen, and the owner is the one person who needs to
  know. Everything else stays gated — a dial that does not reduce anything is not a dial.

### Found while fixing item 8: `layer_name` was `null` in every served event

`Event.layer_name` is a `@property`, and `to_dict` used `asdict`, which only walks dataclass FIELDS. So the
API served `"layer_name": null` for every event while the attribute was perfectly correct in Python.
`to_dict` now includes it, which makes Python the single source of truth for layer names instead of the
dashboard's separate JavaScript copy that could silently drift.

---

## Verified live, after the changes

Against the running dashboard, over HTTP, the way the browser sees it:

```
dial set to 3 (the default where refusals used to vanish)
POST /api/loci {action: run}  ->  accepted: False
                                  "verify-37141 is already running (pid 40944, started 14:52:21)"
feed at level 3               ->  1 refusal, layer 7, gate 'locus-run', locus named
last_outcome served           ->  {ok: True, kind: success, attempts: 1, summary: 'run completed'}
has_session served            ->  present
```

---

## Still open, and deliberately not changed in this pass

### 9. `run_locus` schedules on a worker thread, so the outcome arrives asynchronously — **OPEN, by design**

`accepted: True` now means the run genuinely started, but not that it finished. A caller that wants the
result polls the transcript or reads `last_outcome`. That is the right shape for a long-running agent, and
changing it would mean blocking an HTTP request for minutes. Worth stating rather than fixing.

### 10. The `LAYERS` table exists in both Python and JavaScript — **IMPROVED, still duplicated**

`layer_name` is now served, so the JS copy is no longer load-bearing for labels. The JS map is still used
for colour tone. Removing it entirely would mean serving the tone as well, which is a UI concern that does
not belong in `transparency.py`.

### 11. Orphaned launcher processes after a dashboard restart — **OPEN, environment**

Six `myriaxon web` processes accumulated across restarts while only one held the port. Not a code defect:
the CLI launcher spawns a child and the parent is not reaped when the child is killed by a tool rather than
by the user. Worth a look in `cli.py`, but it does not affect a normal single-instance run.

---

## Method notes, recorded so the review can be repeated

Several of my own measurement errors are worth keeping, because every one produced a **confident wrong
answer**:

* **I reported a duplicated answer prefix as a bug.** `answer_delta` carries the **cumulative** answer and the
  UI does `innerHTML = md(text)` — it *replaces*. My script **joined** the deltas. `'TheThe file contains...'`
  was my harness, not the product.
* **I reported five 404s as broken panels.** They are POST-only routes; the panels read from `/api/config`.
* **I wrote an unconsumed return value** in a test (`loci.get_ref() if False else ...`) and it passed review
  of my own writing — a good argument for the verifier suite existing.
* **A patch landed in the wrong function.** `"open_goals"` occurs twice in `server.py`, and a substring
  splice takes the first, so `has_session` went into the refusal payload instead of the render dict. It
  looked successful. Anchors must be unique, or located by index.
* **I used a CSS variable that does not exist** (`--danger`). `tests/test_brand_consistency.py` failed the
  build and was right to.

The pattern in all five: verifying that a change *applied* is not the same as verifying it is *correct*.

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

# 5. the two improvements, live
python .bench-tmp/verify_live.py

# 6. the caller's contract
python -m pytest tests/test_locus_run_contract.py tests/test_locus_run_contract_extra.py -q

# 7. the log
grep -c "Reclaiming the run lease" ~/.myriaxon/logs/myriaxon.log    # 84 before the fix
```
