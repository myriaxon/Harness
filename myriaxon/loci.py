"""Loci: persistent, always-on agent identities.

A Locus is not a session and not a sub-agent. A session is a conversation that ends when you
close the terminal; a sub-agent is a helper that exists for the duration of one tool call and
is then forgotten. A Locus is an *identity* that persists: it has a name, a role, standing
instructions, a set of goals it is working toward, its own working directory, and a log of
everything it has done — and it resumes that state every time it runs.

Why this exists
---------------
The two failure modes of a chat-shaped agent are that it forgets, and that it waits. It forgets
because context is per-session, so every launch starts from zero. It waits because it only ever
acts when prompted, so nothing happens between prompts even when the next step is obvious.

A Locus addresses both with durable state rather than a longer prompt:

* **It remembers.** Role, instructions, goals, notes and history live in ``loci.json`` and on
  disk, so a Locus working on a goal today continues that goal tomorrow without being re-briefed.
* **It acts.** With proactive mode enabled, the scheduler delivers a Locus's due goals as ordinary
  turns, so objectives advance on their own. Everything it does is appended to its activity log,
  and every write tool it calls still passes through the same permission layer as an interactive
  turn — a Locus is autonomous, not privileged.
* **It is inspectable.** Everything a Locus knows or has done can be printed or shown in the
  dashboard: its objectives, its notes, its log, its workspace. Autonomy without visibility is
  just a black box that spends money.

Relationship to the rest of the harness
---------------------------------------
A Locus owns nothing new. It composes what is already here: the scheduler fires its turns, the
memory store indexes what it did, skills capture what it learned, checkpoints make its edits
reversible, and the permission policy gates its writes. This module is the identity and the
goal-tracking layer on top — the part that was missing.

Reliability
-----------
Unattended work multiplies the cost of every failure a single turn can have, and a failure nobody
sees is the worst version of it: an agent that quietly stops looks exactly like an agent with
nothing to do. The rules that prevent that are enforced here, in the layer both surfaces go
through, rather than left to each caller:

* **A run is bounded, and only worth retrying when it is.** A provider timeout, a dropped stream,
  a 429 or a 5xx is retried with exponential backoff; a bad model name, a revoked key or a
  malformed request is not. See :func:`classify_error` and :func:`run_with_retry`.
* **A goal cannot spin.** A goal handed to the model ``MAX_GOAL_ATTEMPTS`` times without being
  finished is marked ``blocked`` with the reason written into it — a question for a person, which
  is what stops an infinite loop against a paid API. A permanent failure blocks it on the first
  failure rather than the eighth, because waiting does not fix a revoked key.
* **Every outcome is written down.** Success, recovery after retries, exhaustion and permanent
  failure all append an activity entry with the real reason, and the goal carries ``last_error``
  so a surface can show why it failed without reading the log.
* **A run is visible and exclusive.** ``Locus.running`` plus a lease file in the locus's workspace let
  the dashboard say "running now" and stop the terminal and the dashboard from running the same
  locus at the same time. The lease expires on time alone, so a process that dies mid-run cannot
  lock its locus out.
* **Reflection is invited, not fabricated.** A completed objective produces a prompt asking
  whether anything reusable was learned; a failed or trivial run produces none.

Honest scope
------------
A Locus runs while a Myriaxon process is open: the terminal REPL or the web dashboard. It does
not spawn a detached daemon that outlives the process, because a background process that keeps
editing files and spending tokens after the user has closed the window is not a feature, it is
a surprise. "Always on" here means *it resumes by itself and does not need to be prompted* —
not *it runs when nothing is running*. Making it truly continuous is a deployment concern
(a service, a container, a cron entry) and :meth:`LocusRegistry.next_due` is the hook for it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from .atomic_io import atomic_write_text
from .constants import CONFIG_DIR, TRANSIENT_ERROR_BACKOFF_SECONDS, TRANSIENT_ERROR_RETRIES
from .logging_setup import logger

LOCI_FILE = CONFIG_DIR / "loci.json"
LOCI_WORKSPACE_DIR = CONFIG_DIR / "loci"
LOCUS_LOG_CHAR_CAP = 40_000
LOCUS_ACTIVITY_KEEP = 200

# What this concept was called before the rename, and where its state lives.
#
# ## These three literals must NOT be updated by any future rename
#
# They hold the OLD name on purpose: that is their entire function. Real user state is at `~/.myriaxon/dots.json`
# -- measured, 24 KB with five agents in it on this machine -- and at `~/.myriaxon/dots/<id>/` for each agent's
# workspace. The reader looks there when the new name does not exist yet, so nobody's agents disappear.
#
# Measured defect, and the reason for this warning: the bulk rename that created this module also rewrote these
# VALUES, turning `LEGACY_LOCI_FILENAME` into `"loci.json"` and `LEGACY_LOCI_KEY` into `"loci"`. The compatibility
# shim became a copy of the thing it was meant to be compatible with, so the registry silently loaded **0** loci
# instead of 5. A rename script cannot tell a name from a reference to a name, and these are references.
#
# `tools/verify_migration.py` asserts all three, because a value that silently degrades the product to an empty
# state is exactly what a verifier is for.
LEGACY_LOCI_FILENAME = "dots.json"
LEGACY_LOCI_WORKSPACE_DIRNAME = "dots"
# The top-level JSON key the old writer used. The reader accepts either, so it does not matter which wrote the file.
LEGACY_LOCI_KEY = "dots"

# Bumped when the payload shape changes. 1 was the Locus era; 2 records the rename. Nothing gates on this yet -- the
# reader is double-shaped instead, because a version gate would refuse a file it can perfectly well read.
LOCI_PAYLOAD_VERSION = 2

# How many times one goal may be handed to the model before the locus stops trying and asks a person
# instead. The exact number is a judgement call; having one at all is not. Without a ceiling a goal
# the locus cannot make progress on is retried on every wake-up forever: it burns tokens every
# interval, and because each attempt looks like normal work, nothing in the log says "this has
# failed eight times" -- the loop is invisible until someone reads the whole activity list.
# How many times a goal may be handed to the model before the harness gives up on it and blocks it,
# so a goal the locus cannot make progress on is not retried on every wake-up forever.
#
# This interacts with the step budget in a way that was not obvious and was found by DRIVING the loop
# rather than reading it: a continuation step inside a multi-step run calls `_claim_goal` too, so each
# step spends an attempt. With 8, a self-directed locus on a single objective ran EIGHT steps and then
# had its goal blocked mid-objective -- measured: `assert 8 == 12`. The 12-step budget could therefore
# never be used by the commonest case, one objective, and the failure mode was the worst kind: the
# locus stopped with the objective auto-blocked and reported as "gave up after 8 attempts", which
# reads as the model failing rather than as a ceiling nobody had connected to the step budget.
#
# 40 rather than a number near 12, deliberately: the ceiling exists to bound SEPARATE wakes (a goal
# retried on every interval for days), not to bound one run, and 40 leaves room for several multi-step
# runs on the same objective before it concludes the work is not progressing. `step_budget()` is what
# bounds a single run, and it does that already.
MAX_GOAL_ATTEMPTS = 40

# Multi-step runs are opt-in. One step per wake-up was the historical behaviour and the safe default:
# a locus that keeps asking for "the next step" has no natural stopping point, and its cost is a
# function of how long it is left alone.
DEFAULT_MAX_STEPS_PER_RUN = 1

# The ceiling, applied even when the stored value is absurd or hand-edited.
#
# It was 20, on the reasoning that "a locus configured with 500 steps is not a feature request, it is
# a runaway bill waiting for its first wake-up". The owner of this installation was shown exactly that
# argument and chose no ceiling: a self-directed agent that stops after twenty steps cannot finish
# anything, and a bound that makes the feature useless is not a safety feature.
#
# The value is a SENTINEL rather than a round number, deliberately. A test that asserts "a request of
# 10,000 is clamped to the ceiling" cannot distinguish a working clamp from no clamp when the ceiling
# IS 10,000 -- measured: the existing clamp test passed 9,999 and got 9,999 back, which is correct and
# proved nothing. 10,001 keeps the clamp observable at the top end.
MAX_STEPS_PER_RUN_CEILING = 10_001

# How much of its own direction a locus has. The two modes differ in ONE thing that matters: whether
# the locus may invent objectives. Everything else -- role, standing instructions, workspace,
# confinement -- is identical, because "autonomous" must not quietly mean "a different agent".
AUTONOMY_ASSISTED = "assisted"            # advances the objectives it was given, and only those
AUTONOMY_SELF_DIRECTED = "self_directed"  # may also write and pursue its own objectives
AUTONOMY_MODES = (AUTONOMY_ASSISTED, AUTONOMY_SELF_DIRECTED)

# What a self-directed locus gets when nobody chose a number. Twelve is enough to plan, act, check
# the result and correct it a few times -- the shape of a real task -- while staying far enough below
# the ceiling that a runaway is bounded by the model's judgement rather than by a number nobody set.
DEFAULT_SELF_DIRECTED_STEPS = 12

# === The consecutive-failure ledger =================================================================
#
# A locus that fails on every wake-up is the most expensive failure this feature can have: it spends a run's
# worth of tokens on each interval, forever, and only the *goal* attempt ceiling (8) stands in the way -- so a
# locus with five open goals could burn forty failed runs before anything stopped it. Worse, each individual
# failure is logged, so the activity log fills with errors while the locus keeps waking: the log looks busy and
# the situation looks like work.
#
# OpenClaw's answer is to auto-disable a recurring job after 10 consecutive execution failures and record
# `autoDisabled.reason`. That is the right shape and the numbers are borrowed deliberately rather than invented.
#
# The trap it warns about in the same breath is worth repeating, because this mechanism can create it: a job
# left disabled and invisible "will never fire or explain itself -- a silent non-outcome, which is a worse
# failure than a job that runs and visibly complains." So an auto-disabled locus is *never* silent here: it stays
# visible in `loci --status`, it says in words why it stopped and what to do, and it does not return to the
# wake-up candidate list. `loci --reset <name>` is the one-command way back.
CONSECUTIVE_FAILURES_BEFORE_DISABLE = 10

# Backoff between attempts while a locus is failing but not yet disabled. Without this, a locus failing for a
# transient reason retries at its normal interval, which for a 60-second locus is 10 failures in ten minutes.
# Capped so a locus never effectively stops dead before the disable threshold is reached -- the cap must be
# shorter than the threshold times the interval, or the ledger would never fill.
FAILURE_BACKOFF_CAP_SECONDS = 3600.0

# The cross-process run guard. A file in the locus's own workspace, because that is the one directory
# a locus owns and the natural place for "who is working here right now".
RUN_LEASE_FILENAME = "run.lease"
# How long a lease may go untouched before it is treated as abandoned. Long enough for a real
# multi-minute turn; short enough that a process killed mid-run does not lock its locus out for the
# rest of the day. A run expected to outlast this calls renew_run_lease() to re-touch the file.
RUN_LEASE_STALE_SECONDS = 1800

# How often a live run re-touches its lease. A quarter of the staleness window, so two beats can be
# missed -- a long tool call, a stalled scheduler -- before the lease is wrongly considered dead.
LEASE_HEARTBEAT_SECONDS = RUN_LEASE_STALE_SECONDS / 4

# Backoff cap. The cap matters more than the growth: TRANSIENT_ERROR_BACKOFF_SECONDS doubling
# unclamped passes a minute by the sixth attempt, and a locus waiting four minutes to retry a
# dropped connection is indistinguishable from a hung one.
TRANSIENT_BACKOFF_CAP_SECONDS = 60.0

# The reflection invitation appended to a locus's own prompt. Kept word-for-word in step with the one
# tool_registry._spawn_subagent_inner adds to a sub-agent's prompt, so "did you learn something
# reusable?" reads the same however the work was delegated -- and so both say plainly that finding
# nothing worth keeping is a normal outcome, which is what stops a model inventing a lesson.
REFLECTION_CLAUSE = (
    "Before concluding, consider: did you discover a genuinely reusable approach here? "
    "If so, call save_skill to preserve it for future tasks. If nothing here is "
    "generalizable, don't call it -- that's a normal, expected outcome."
)

# Goal lifecycle. Deliberately small: a goal is something to be done, something being done,
# something waiting on a person, or finished. A richer taxonomy mostly produces goals nobody
# bothers to move between states.
GOAL_PENDING = "pending"
GOAL_ACTIVE = "active"
GOAL_BLOCKED = "blocked"
GOAL_DONE = "done"
# A goal the agent decided is no longer worth doing. Level 5 requirement 5.3.
#
# Deliberately a TERMINAL STATE WITH A REASON rather than a deletion. An agent that can delete objectives can
# destroy its owner's instructions, and "why did this stop being pursued" is a question a person asks and a
# deletion cannot answer. The goal stops being selected and stays in the record.
GOAL_OBSOLETE = "obsolete"
GOAL_STATES = (GOAL_PENDING, GOAL_ACTIVE, GOAL_BLOCKED, GOAL_DONE, GOAL_OBSOLETE)

# Who wrote an objective. The distinction decides whether the agent may retire it (5.3).
OWNER_GOAL_AUTHOR = "owner"
LOCUS_GOAL_AUTHOR = "locus"

# How deep a decomposition tree may go. Requirements 5.1 and the reason it needs a cap.
#
# An agent told to "break this into smaller pieces" will do so indefinitely: each level looks like progress,
# and nothing in the prompt says when to stop. Three levels is enough to turn a broad objective into
# concrete work -- goal, sub-goal, task -- and a fourth adds cost without adding information. The number is
# a judgement rather than a measurement, and it is stated here so a reader can disagree with a number
# instead of discovering an unbounded process.
MAX_GOAL_DEPTH = 3

# How often a proactive Locus should wake up when its owner has not said otherwise. Short enough
# that "always on" is observable, long enough that it is not a busy loop against a paid API.
DEFAULT_PROACTIVE_INTERVAL_SECONDS = 900


# ---------------------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------------------
# Which failures are worth retrying is the difference between an agent that survives a flaky
# upstream and one that spends three times as much to be told the same thing. The knowledge of
# which provider exceptions mean which already exists -- cli.py's
# _auth_errors/_rate_limit_errors/_connection_errors/_status_errors build the SDK type tuples, and
# constants.TRANSIENT_ERROR_RETRIES/_BACKOFF_SECONDS hold the policy -- so this reuses those
# constants and the same shapes instead of inventing a second scheme that would drift from it.
ERROR_TRANSIENT = "transient"
ERROR_PERMANENT = "permanent"

# Statuses that mean "the request was fine, the world was not". 529 is Anthropic's "overloaded";
# 520/522/524 are Cloudflare's equivalents in front of several providers.
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})

# Matched against every class name in the exception's MRO, lowercased, because the SDKs nest their
# errors (anthropic.APITimeoutError is an APIConnectionError; google.genai's compat layer mirrors
# the same shape) and only the leaf name is visible at the except site.
_TRANSIENT_TYPE_MARKERS = (
    "timeout", "connection", "ratelimit", "overloaded", "internalserver", "serviceunavailable",
    "remoteprotocol", "protocolerror", "incompleteread", "brokenpipe", "temporarilyunavailable",
)
_PERMANENT_TYPE_MARKERS = (
    "authentication", "permissiondenied", "permissionerror", "unauthorized", "notfound",
    "badrequest", "unprocessable", "invalidrequest", "invalidargument", "modelnotfound",
    "apikeymissing",
)

# Checked against the lowercased exception message, and deliberately checked permanent-first: a
# message like "invalid api key (401)" must not be read as retryable because it also mentions a
# status the table calls transient.
_PERMANENT_TEXT_MARKERS = (
    "invalid api key", "incorrect api key", "invalid x-api-key", "no api key", "missing api key",
    "api key not", "authentication", "unauthorized", "permission denied", "invalid model",
    "model not found", "unknown model", "no such model", "does not exist", "not found",
    "invalid_request", "invalid request", "bad request", "malformed", "unprocessable",
    "unsupported", "credit balance", "insufficient", "quota exceeded", "billing",
    "context length", "maximum context", "too many tokens", "exceeds",
)
_TRANSIENT_TEXT_MARKERS = (
    "timeout", "timed out", "deadline exceeded", "connection", "broken pipe",
    "peer closed connection", "incomplete message body", "remote protocol error",
    "connection reset", "temporarily unavailable", "try again", "overloaded", "rate limit",
    "rate_limit", "too many requests", "server error", "internal server error",
    "service unavailable", "bad gateway", "gateway timeout", "upstream", "stream error",
)
# Only reached when there is no typed status code and no marker matched. A loose "\b500\b" here is
# a deliberate trade: this path is a fallback for prose-only errors, and a wrong "transient" costs
# one bounded extra attempt while a wrong "permanent" loses the task the locus was built to finish.
_STATUS_IN_TEXT = re.compile(r"\b(?:429|5\d\d)\b")


def _status_code_of(exc: BaseException) -> int | None:
    """The HTTP status on an SDK exception, wherever the provider happens to put it.

    anthropic/openai attach ``.status_code``; google.genai's error types use ``.code``; wrappers
    around either sometimes keep only ``.status``. All of them are checked because a status this
    function fails to find turns a 503 into an unclassified error -- and unclassified errors are
    permanent here, so the miss would disable retrying on exactly the failure retrying fixes.
    """
    for attr in ("status_code", "status", "code", "http_status"):
        raw = getattr(exc, attr, None)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
    return None


def classify_error(exc: BaseException) -> str:
    """Whether retrying this failure could plausibly succeed: ``transient`` or ``permanent``.

    Order is deliberate, strongest evidence first: the exception's own type, then an explicit
    status code, then the message text. A type or a status is something the SDK knows; message
    matching is guesswork and is only consulted when the first two say nothing.

    The default is ``permanent``. An error nobody classified is far more likely to be a bug, a
    malformed request or a programming mistake than a flaky upstream, and retrying those three
    times costs three requests to arrive at the same answer. The failure is still recorded either
    way -- being wrong here costs attempts, never information.
    """
    type_names = " ".join(cls.__name__.lower() for cls in type(exc).__mro__)
    for marker in _PERMANENT_TYPE_MARKERS:
        if marker in type_names:
            return ERROR_PERMANENT
    for marker in _TRANSIENT_TYPE_MARKERS:
        if marker in type_names:
            return ERROR_TRANSIENT

    status = _status_code_of(exc)
    if status is not None:
        if status in _TRANSIENT_STATUS or 500 <= status < 600:
            return ERROR_TRANSIENT
        if 400 <= status < 500:
            return ERROR_PERMANENT

    text = str(exc).lower()
    for marker in _PERMANENT_TEXT_MARKERS:
        if marker in text:
            return ERROR_PERMANENT
    for marker in _TRANSIENT_TEXT_MARKERS:
        if marker in text:
            return ERROR_TRANSIENT
    if _STATUS_IN_TEXT.search(text):
        return ERROR_TRANSIENT
    return ERROR_PERMANENT


def is_transient_error(exc: BaseException) -> bool:
    """Reads better than an equality check at the call site."""
    return classify_error(exc) == ERROR_TRANSIENT


def retry_backoff_seconds(attempt: int) -> float:
    """Seconds to wait before retrying, given the attempt that just failed.

    Exponential from ``TRANSIENT_ERROR_BACKOFF_SECONDS`` and capped -- see
    ``TRANSIENT_BACKOFF_CAP_SECONDS`` for why the cap is the load-bearing half.
    """
    exponent = max(0, int(attempt) - 1)
    return min(TRANSIENT_ERROR_BACKOFF_SECONDS * (2 ** exponent), TRANSIENT_BACKOFF_CAP_SECONDS)


def max_run_attempts() -> int:
    """One first try plus ``TRANSIENT_ERROR_RETRIES`` retries, read live from constants so a
    project-wide change to the retry budget takes effect without editing this module."""
    return max(1, int(TRANSIENT_ERROR_RETRIES) + 1)


# ---------------------------------------------------------------------------------------
# Run outcomes
# ---------------------------------------------------------------------------------------
# The names a run can end under. Kept as strings in a field rather than an enum so they survive the
# JSON round trip the registry already does and stay readable in loci.json.
OUTCOME_SUCCESS = "success"
OUTCOME_RECOVERED = "recovered"
OUTCOME_TRANSIENT = "transient-failure"
OUTCOME_EXHAUSTED = "transient-exhausted"
OUTCOME_PERMANENT = "permanent-failure"


@dataclass
class RunOutcome:
    """What actually happened during a run, in a form the locus can record and a caller can act on.

    Every field exists because some surface needs it: ``ok``/``kind`` for the caller deciding
    whether to continue, ``attempts`` for the log line that distinguishes a clean run from one
    that survived two timeouts, ``error`` for the goal's ``last_error``, and ``exception`` for a
    caller that wants to re-raise instead of report.
    """

    ok: bool
    kind: str = OUTCOME_SUCCESS
    attempts: int = 0
    error: str = ""
    error_kind: str = ""
    result: Any = None
    exception: BaseException | None = None

    def describe(self) -> str:
        """One truthful sentence, for the activity log and for the user-facing surface."""
        if self.ok:
            if self.attempts <= 1:
                return "run completed"
            return (
                f"run completed after {self.attempts} attempts "
                "(recovered from a transient error)"
            )
        reason = self.error or "no reason recorded"
        if self.kind == OUTCOME_EXHAUSTED:
            plural = "" if self.attempts == 1 else "s"
            return f"gave up after {self.attempts} attempt{plural}: {reason}"
        if self.kind == OUTCOME_TRANSIENT:
            return f"transient failure: {reason}"
        return f"failed permanently: {reason}"


def normalize_outcome(outcome: "RunOutcome | BaseException | None") -> RunOutcome:
    """Turn whatever a caller has to hand into the same report shape.

    Three shapes reach :meth:`Locus.end_run`: a full RunOutcome from :func:`run_with_retry`, the bare
    exception a caller caught itself, and ``None`` for "it finished". Normalizing here is what lets
    a caller that only kept the exception still record the real reason and still get the
    transient/permanent decision applied to its goal.
    """
    if isinstance(outcome, RunOutcome):
        return outcome
    if isinstance(outcome, BaseException):
        message = str(outcome).strip() or type(outcome).__name__
        kind = classify_error(outcome)
        return RunOutcome(
            ok=False,
            # OUTCOME_TRANSIENT, not OUTCOME_EXHAUSTED: nothing was retried here, and reporting
            # "gave up after N attempts" for a caller that caught the error itself would put a
            # fiction in the activity log -- the one record a person uses to reconstruct a run.
            kind=OUTCOME_TRANSIENT if kind == ERROR_TRANSIENT else OUTCOME_PERMANENT,
            attempts=1,
            error=message,
            error_kind=kind,
            exception=outcome,
        )
    return RunOutcome(ok=True, kind=OUTCOME_SUCCESS, attempts=1)


def record_failure(locus: "Locus | None", goal: "Goal | None", outcome: RunOutcome) -> None:
    """Write a failed run down where a person will find it: the activity log, the locus, the goal.

    A *permanent* failure also blocks the goal it belongs to. A revoked key or a model name that
    does not exist cannot be fixed by running again, so leaving the goal active would spend a
    run's worth of tokens on every wake-up until the attempt ceiling eventually stopped it -- and
    the person would learn nothing they could act on until then. Blocking on the first failure
    instead puts the real reason in front of them immediately, with the note explaining how to
    resume once the cause is fixed. The goal is not lost; it becomes a question.

    A transient failure that exhausted its retries does *not* block: the next wake-up is a
    reasonable thing to try, and the attempt ceiling is the bound that stops that loop.
    """
    message = outcome.error or "no reason recorded"
    if locus is not None:
        locus.last_error = message
        locus.log("error", outcome.describe())
        # Counted BEFORE the goal attribution below, which returns early when no goal can be attributed.
        # The ledger is about the *locus* failing, so it must not depend on a goal being identifiable -- the
        # first version of this called it after that early return, so a locus whose failure could not be tied to
        # a goal failed silently and forever, which is the exact outcome the ledger exists to prevent.
        record_consecutive_failure(locus, outcome)
        if goal is None:
            goal = locus.goal_for_last_attempt()
    if goal is None:
        return
    goal.last_error = message
    goal.updated_at = time.time()
    if outcome.error_kind == ERROR_PERMANENT and goal.status != GOAL_DONE:
        goal.status = GOAL_BLOCKED
        goal.notes.append(
            f"blocked after a permanent failure: {message}. Fix the cause, then set this objective "
            "back to pending to resume."
        )
        if locus is not None:
            locus.log("error", f"[{goal.id}] {goal.title} -> blocked: {message}")


def record_success(locus: "Locus") -> None:
    """Clear the consecutive-failure ledger after a run that worked.

    Called on success only. Deliberately not called on `recovered`: a run that needed four retries did not
    fail, but it did not sail through either, and zeroing the ledger on it would let a locus that fails once per
    run and recovers forever stay enabled indefinitely. Only a clean success resets the count.
    """
    if locus.consecutive_failures:
        prior = locus.consecutive_failures
        locus.consecutive_failures = 0
        locus.last_failure_kind = ""
        locus.log("note", f"recovered after {prior} consecutive failure(s); failure budget reset")


def reset_failure_ledger(locus: "Locus") -> str:
    """Clear a Locus's failure ledger and re-enable it. Returns a one-line description of what changed.

    The counterpart to `record_consecutive_failure`, and the reason auto-disabling is acceptable at all: a Locus
    that stops itself must be one command away from starting again, or the mechanism would be a trap rather
    than a guard.

    Deliberately does not touch goals. A locus disabled itself because *its runs* kept failing, which says nothing
    about whether its objectives are still worth doing -- that is the owner's call, and the goals are left
    exactly as they were found.
    """
    was_disabled = not locus.enabled
    prior = locus.consecutive_failures
    locus.consecutive_failures = 0
    locus.last_failure_kind = ""
    was_auto = bool(locus.auto_disabled_at)
    locus.auto_disabled_at = 0.0
    locus.auto_disabled_reason = ""
    locus.enabled = True
    locus.updated_at = time.time()

    detail = []
    if was_auto:
        detail.append("cleared its self-disable")
    if was_disabled:
        detail.append("re-enabled")
    detail.append(f"failure ledger reset (was {prior})")
    summary = "; ".join(detail)
    locus.log("note", f"failure ledger reset by hand: {summary}")
    return summary


def record_consecutive_failure(locus: "Locus", outcome: RunOutcome) -> None:
    """Count a failed run against the locus, and disable the locus when the budget is spent.

    This is the bound that stops a broken locus from spending a run's worth of tokens on every wake-up forever.
    The goal attempt ceiling does not cover it: a locus with several open goals can fail its way through all of
    them, and a locus that keeps acquiring new ones never trips it at all.

    Disabling is the last resort, so everything cheaper is tried first -- the per-goal ceiling, permanent-failure
    blocking, and the backoff in `seconds_until_due` all act before this. What remains at the threshold is a locus
    failing repeatedly *for reasons none of those caught*, which is exactly when a person needs to be asked.

    Never silent. The reason is written to the locus, to its activity log, and is surfaced by `loci --status`;
    the goal is left as it was rather than blocked, because the failure was the locus's, not the objective's.
    """
    locus.consecutive_failures += 1
    locus.last_failure_kind = outcome.error_kind or "unknown"

    if locus.consecutive_failures < CONSECUTIVE_FAILURES_BEFORE_DISABLE:
        return

    locus.enabled = False
    locus.auto_disabled_at = time.time()
    locus.auto_disabled_reason = (
        f"disabled itself after {locus.consecutive_failures} consecutive failed runs "
        f"(last: {locus.last_failure_kind}: {outcome.error or 'no reason recorded'})"
    )
    locus.log(
        "error",
        f"{locus.auto_disabled_reason}. It will not wake again until someone runs "
        f"`myriaxon loci --reset {locus.name}`. Its goals were left untouched.",
    )


def run_with_retry(
    operation: Callable[[], Any],
    *,
    locus: "Locus | None" = None,
    goal: "Goal | None" = None,
    max_attempts: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RunOutcome:
    """Run one bounded unit of work, retrying only the failures that retrying can fix.

    ``sleep`` is injectable so tests can prove the backoff schedule without living through it; a
    suite that really waited out three retries would cost more wall-clock than the rest of the run
    and would be deleted for being slow long before it caught a regression.

    The outcome is *returned*, never swallowed: a caller that wants the exception back has it in
    ``RunOutcome.exception``, and the activity log has the reason regardless. ``KeyboardInterrupt``
    and every other ``BaseException`` propagate untouched -- a user stopping a run is not a
    transient provider failure, and retrying it would make ^C look like an API problem. The
    caller's ``finally`` still clears the running flag.
    """
    total = max(1, int(max_attempts if max_attempts is not None else max_run_attempts()))
    attempt = 0
    while True:
        attempt += 1
        try:
            result = operation()
        except Exception as exc:  # noqa: BLE001 -- every failure must leave a record
            kind = classify_error(exc)
            message = str(exc).strip() or type(exc).__name__
            if kind == ERROR_TRANSIENT and attempt < total:
                delay = retry_backoff_seconds(attempt)
                if locus is not None:
                    locus.log(
                        "retry",
                        f"transient failure on attempt {attempt}/{total}: {message} "
                        f"-- retrying in {delay:.0f}s",
                    )
                sleep(delay)
                continue
            outcome = RunOutcome(
                ok=False,
                kind=OUTCOME_EXHAUSTED if kind == ERROR_TRANSIENT else OUTCOME_PERMANENT,
                attempts=attempt,
                error=message,
                error_kind=kind,
                exception=exc,
            )
            record_failure(locus, goal, outcome)
            return outcome

        outcome = RunOutcome(
            ok=True,
            kind=OUTCOME_SUCCESS if attempt == 1 else OUTCOME_RECOVERED,
            attempts=attempt,
            result=result,
        )
        if locus is not None:
            locus.log("turn", outcome.describe())
            # A clean success clears the failure ledger. A *recovered* run does not: it needed retries, and
            # treating that as healthy would let a locus that fails once per run and recovers forever stay
            # enabled. See record_success.
            if outcome.kind == OUTCOME_SUCCESS:
                record_success(locus)
        return outcome


# ---------------------------------------------------------------------------------------
# The cross-process run guard
# ---------------------------------------------------------------------------------------
def locus_workspace_dir(locus: "Locus") -> Path:
    """Where a locus's files live, without creating anything.

    Separate from :meth:`Locus.workspace_path` because the lease guard reads this path: a check that
    creates a directory as a side effect turns "is anyone running this locus?" into a write, and the
    read happens on paths (``is_due``) that must stay cheap.
    """
    return Path(locus.workspace) if locus.workspace else LOCI_WORKSPACE_DIR / locus.id


# Words in an objective that mean "you must actually execute something to satisfy this".
#
# Deliberately narrow and action-shaped. A broad list would fire on objectives that merely mention
# testing in passing, and a check that cries wolf gets ignored -- which is worse than no check, because
# it teaches the reader to skip the warning.
_EXECUTION_VERBS = (
    "run ", "runs ", "running ", "execute", "executing",
    "prove it", "test it", "run the test", "run check", "compile", "build and run",
)

# Tools that count as "actually executed something", as opposed to reading or writing a file.
_EXECUTION_TOOLS = ("run_bash", "bash_output", "kill_bash")


def requires_execution(goal_text: str) -> bool:
    """Whether satisfying this objective needs a command to be run, not merely read about."""
    lowered = (goal_text or "").lower()
    return any(verb in lowered for verb in _EXECUTION_VERBS)


def execution_was_attempted(tools_called) -> bool:
    """Whether any executing tool was called this turn."""
    try:
        return bool(set(tools_called or ()) & set(_EXECUTION_TOOLS))
    except TypeError:
        return False


def unverified_execution_note(goal_text: str, tools_called) -> str:
    """The line to record when an objective demanded execution and none was attempted.

    Empty when the objective did not demand it, or when a command was actually run.

    This exists because four separate attempts to fix the behaviour by TELLING the agent failed. The
    briefing said it, the environment manifest said it, and the `run_bash` description said it twice --
    and across seven benchmark runs the agent still reported "the shell is blocked" without calling the
    tool once, while the tool was present, permitted and working (verified directly: proceed=True,
    failed=False, output SHELL-ALIVE).

    Since describing the environment does not change what the agent does, the harness stops relying on
    the description and records the FACT instead: an objective that said "run check.py" and a turn that
    ran nothing is an INCOMPLETE attempt, and it is recorded as one rather than reported as finished.
    The note goes into the goal's own history, so the next wake-up sees it.
    """
    if not requires_execution(goal_text):
        return ""
    if execution_was_attempted(tools_called):
        return ""
    return (
        "this objective asks for something to be RUN, and no command was executed this turn. "
        "Running it is how the objective is satisfied; reading the code is not the same thing."
    )


def run_lease_path(locus: "Locus") -> Path:
    return locus_workspace_dir(locus) / RUN_LEASE_FILENAME


# ---------------------------------------------------------------------------------------
# Self-scheduling: making a Locus run without a human present
# ---------------------------------------------------------------------------------------
#
# Measured, and it is the gap that kept this out of conditional autonomy: with a Locus enabled,
# proactive, due, an objective waiting and a 30-second interval, ninety seconds of doing nothing
# produced no run at all. `proactive`, `interval_seconds` and `is_due()` describe WHEN a Locus should
# run; nothing in the codebase made it happen. The only triggers were `--run`, `--watch` and a button
# -- every one of which needs a person.
#
# Conditional autonomy is defined by human involvement becoming EXCEPTION-based. An agent you must
# start is one you are routinely involved with, whatever its other properties.
#
# The fix is deliberately the smallest one that works: hand the clock to the operating system's own
# scheduler. No daemon to supervise, nothing resident to leak, and it survives a reboot because the OS
# remembers it rather than this process. `--watch` remains for a foreground session.

# ---------------------------------------------------------------------------------------
# Self-scheduling
# ---------------------------------------------------------------------------------------
#
# MEASURED, and it is the requirement that kept Loci out of conditional autonomy: with a Locus
# enabled, proactive, DUE and holding an objective, ninety seconds of doing nothing produced no run
# at all. `proactive`, `interval_seconds` and `is_due()` describe WHEN a Locus should run; nothing in
# the codebase made it happen, and every trigger was a person.
#
# The clock lives in the harness, in PYTHON, deliberately. An operating-system scheduler was tried
# first and REMOVED, for three reasons:
#
#   1. It is a second moving part outside the harness -- something to find, install, explain and
#      remove, and something that can be left behind on a machine after the tool is gone.
#   2. It is platform-specific by construction. `schtasks` works only on Windows, so the feature would
#      have existed for one user on one operating system and silently not existed for everyone else.
#   3. Its failure mode is invisible. Measured: the first version made the user's WSL window pop up
#      every five minutes, and the only reason anyone noticed was that Windows showed them.
#
# Everything here is pure Python and behaves identically on Windows, macOS and Linux. The single
# optional platform detail -- how to start a process without a console window appearing -- is isolated
# in `launcher_command` so nothing else needs a branch.

SUPERVISOR_ENV_INTERVAL = "MYRIAXON_SUPERVISOR_SECONDS"
SUPERVISOR_ENV_DISABLE = "MYRIAXON_NO_SUPERVISOR"
DEFAULT_SUPERVISOR_INTERVAL = 60.0


def supervisor_interval() -> float:
    """How often the in-harness supervisor checks for due Loci. Never below 5 seconds.

    Floored rather than trusted: a zero or negative interval would spin a thread against the registry
    as fast as the CPU allows, and the person who typed it would be debugging a hot laptop rather than
    a scheduler.
    """
    import os

    try:
        return max(5.0, float(os.environ.get(SUPERVISOR_ENV_INTERVAL) or ""))
    except (TypeError, ValueError):
        return DEFAULT_SUPERVISOR_INTERVAL


def supervisor_enabled() -> bool:
    """Whether the in-harness supervisor should run. Off only when explicitly disabled."""
    import os

    return not (os.environ.get(SUPERVISOR_ENV_DISABLE) or "").strip()


def launcher_command(module_args: list[str]) -> list[str]:
    """The argv that runs Myriaxon without opening a console window, where that is possible.

    The ONE platform-specific decision in the whole scheduling path, kept here so nothing else has to
    branch. A background agent that flashes a black box is an agent the user disables -- and then it
    stops working for a reason nobody connects to this line.

    Windows ships a windowless interpreter (`pythonw.exe`) beside the normal one. POSIX has no window
    to suppress, so the interpreter is used unchanged. If the windowless binary is missing, the normal
    interpreter is still correct -- just visible.
    """
    import platform as _platform
    import sys as _sys
    from pathlib import Path as _Path

    interpreter = _sys.executable
    if _platform.system() == "Windows":
        windowless = _Path(interpreter).with_name("pythonw.exe")
        if windowless.exists():
            interpreter = str(windowless)
    return [interpreter, "-m", *module_args]


def supervisor_argv() -> list[str]:
    """What a supervisor process runs: advance whatever is due, once, and exit.

    `--run` rather than `--watch`, because the caller owns the loop. A resident watcher started
    repeatedly would overlap with itself, and while the per-Locus lease would refuse the second run,
    spawning processes that immediately do nothing is waste dressed as diligence.
    """
    return launcher_command(["myriaxon", "loci", "--run"])


def run_due_once(*, console: Any = None) -> tuple[int, int]:
    """Advance every due Locus exactly once. Returns `(runs, failures)`.

    The headless entry point, callable from anything -- a supervisor thread, a test, a platform's own
    scheduler if a user wants one, or `python -m myriaxon.loci`. Nothing about it is Windows-specific
    or process-specific, which is the point: the work should be reachable from Python regardless of
    who owns the clock.
    """
    from argparse import Namespace

    from .cli import _build_agent_for_command, _run_one_dot
    from .config import resolve_config
    from .theme import get_console

    registry = get_registry()
    due = registry.due()
    if not due:
        return 0, 0

    console = console or get_console(quiet=True)
    config = resolve_config(console, model="")
    if config is None:
        return 0, 0

    args = Namespace(
        model="", yolo=True, no_sandbox=False, thinking=False, effort=None, mode="auto_edit",
        no_compact=False, profile=None, agent_mode="single", json=True, sandbox=True,
    )
    agent = _build_agent_for_command(config, console, args)
    if agent is None or agent.tool_context is None:
        return 0, 0

    runs = failures = 0
    for locus in due:
        ran, failed = _run_one_dot(locus, agent, console, args)
        runs += int(ran)
        failures += int(failed)
    return runs, failures


class RunInProgress(RuntimeError):
    """Raised by :meth:`Locus.run_scope` when another run already holds this locus.

    Carries the holder when it could be read, because "already running" without knowing since when
    or by which process is the kind of message that sends someone hunting through log files.
    """

    def __init__(self, locus: "Locus", lease: "RunLease | None" = None) -> None:
        self.locus = locus
        self.lease = lease
        since = f" (held by {lease.describe()})" if lease is not None else ""
        super().__init__(
            f"{locus.name} is already running{since}. Wait for that run to finish, or clear the lease "
            "in its workspace if the process that held it is gone."
        )


@dataclass
class RunLease:
    """An exclusive claim on running one locus, held for as long as the run lasts.

    A file rather than an in-process lock, because the two surfaces that run loci -- the terminal
    and the dashboard -- are separate processes sharing one ``loci.json``; an in-process lock
    would happily let both of them work the same locus in the same workspace at the same time.

    Expiry is a function of time alone, not of whether the owning process is alive. On Windows
    ``os.kill(pid, 0)`` does not test for existence, it terminates the process, so a liveness probe
    is not portable enough to put in the one code path that must never misfire. Time-based expiry
    has the property the guard actually needs: a process that dies holding the lease cannot hold
    it forever. ``enforced=False`` marks a lease that could not be written at all (an unwritable
    workspace) -- the run proceeds, because refusing to work over a lock file is the worse failure.
    """

    locus_id: str
    path: Path | None
    pid: int
    acquired_at: float
    token: str
    enforced: bool = True

    def describe(self) -> str:
        when = time.strftime("%H:%M:%S", time.localtime(self.acquired_at))
        return f"pid {self.pid}, started {when}"

    def release(self) -> None:
        """Drop the lease, if it is still ours.

        The token check is what stops a stale owner from deleting the claim of whoever took over
        after it: without it, a run that finally unwinds half an hour late would unlock a locus that
        another process is actively working on, and the next wake-up would start a second run
        beside the first -- the exact collision this file exists to prevent.

        A lease that cannot be *read* is never deleted. Leaving a claim in place costs a retry once
        it goes stale; removing a claim that might belong to somebody else costs two agents in one
        workspace, so the two mistakes are not equally bad and this picks the cheap one.
        """
        if self.path is None:
            return
        held = _read_lease_file(self.path)
        if held is None:
            return
        if held.get("token") not in (None, "", self.token):
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_lease_file(path: Path) -> dict | None:
    """Parse a lease file. ``None`` means "could not be read"; ``{}`` means "present but empty".

    The distinction is load-bearing rather than pedantic. A caller deciding whether a claim is
    *its own* must not read "I could not open the file" as "the file is mine" -- that is how one
    process deletes another's lock. A caller deciding whether *anyone* holds the locus must treat
    both as held, because the file's existence is itself evidence that somebody claimed it.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process on this machine.

    Unknown is reported as ALIVE, deliberately. A pid of 0 means the lease file could not be read,
    and the safe reading of an unreadable claim is that somebody holds it -- the same direction
    `_lease_from_path` already takes. Treating "cannot tell" as dead would let two runs of one locus
    start at once, which is the collision the lease exists to prevent.
    """
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes

        # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION, which is enough to ask about a process we do
        # not own and cannot open for anything else.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # 5 = ERROR_ACCESS_DENIED: the process exists, it just is not ours to inspect. 87 =
        # ERROR_INVALID_PARAMETER, which is what a pid that no longer exists returns.
        return ctypes.windll.kernel32.GetLastError() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


# Which stale leases have already been announced, so a DEAD owner is reported ONCE rather than on every
# poll. Keyed by (lease path, pid), because the same locus can leave several stale leases over a day with
# different owners, and each of those is genuinely new information.
_ANNOUNCED_STALE_LEASES: set[tuple[str, int]] = set()


def _announce_reclaimed_lease(path: Path, locus_id: str, pid: int) -> None:
    """Say once that a lease's owner is gone. The file is NOT deleted here.

    WHY THIS EXISTS. Measured in the real log on this machine:

        INFO Reclaiming the run lease for 2508c6d7: its owner (pid 14092) is gone   x 40
        INFO Reclaiming the run lease for 2508c6d7: its owner (pid 17980) is gone   x 15
        ... 84 lines in total, for SEVEN distinct dead pids

    Every one of those lines was true, and the repetition made them worthless. `read_run_lease` is called
    from `Locus.is_running()`, which the dashboard polls to decide whether to show "working now", so a
    single dead owner was logged on every poll for as long as the lease file survived -- up to the
    30-minute stale window. 84 identical INFO lines train a reader to ignore the log, which is the same
    failure this repository has already recorded twice for other diagnostics: **a message nobody reads is
    a message that is not there.**

    It is logged at INFO and not WARNING deliberately. Reclaiming is the system working: the owner died and
    the next run takes the slot. A warning would be for the case where a stale lease actually PREVENTS
    something, which it does not -- `acquire_run_lease` unlinks it and proceeds.

    Deliberately does NOT unlink. This function runs on a READ path, and deleting a file because it looks
    stale is how a read becomes a mutation: two processes polling the same stale lease would race to
    unlink, and a lease created between the `_pid_alive` check and the unlink would be destroyed by a
    reader. Reclamation belongs to the acquirer, which already does it under `O_EXCL`.
    """
    key = (str(path), int(pid))
    if key in _ANNOUNCED_STALE_LEASES:
        return
    _ANNOUNCED_STALE_LEASES.add(key)
    logger.info(
        "Reclaiming the run lease for %s: its owner (pid %s) is gone. "
        "Said once per stale lease -- the file is left for the next acquire to take over.",
        locus_id, pid,
    )


def _lease_from_path(
    path: Path, locus_id: str, *, now: float, stale_after: float
) -> "RunLease | None":
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if now - mtime > stale_after:
        return None
    # An unreadable file still proves somebody created a claim, so it counts as held. See
    # _read_lease_file for why that is the safe direction here and the unsafe one in release().
    info = _read_lease_file(path) or {}
    pid = int(info.get("pid") or 0)
    # The mtime test above is not enough on its own, and the gap it leaves is not hypothetical.
    # Measured: a dashboard process holding a lease was killed, the file kept a fresh mtime, and
    # that locus then reported `running` -- refused every new run, showed "working now" forever --
    # for the full stale window even though the owning process was gone. The mtime only bounds how
    # long a *forgotten* lease can live; it cannot see that the owner died a second ago.
    if not _pid_alive(pid):
        _announce_reclaimed_lease(path, locus_id, pid)
        return None
    return RunLease(
        locus_id=locus_id,
        path=path,
        pid=pid,
        acquired_at=float(info.get("acquired_at") or mtime),
        token=str(info.get("token") or ""),
    )


def read_run_lease(
    locus: "Locus", *, now: float | None = None, stale_after: float = RUN_LEASE_STALE_SECONDS
) -> "RunLease | None":
    """The live lease on this locus, or None when nothing holds it (or it went stale)."""
    return _lease_from_path(
        run_lease_path(locus), locus.id, now=time.time() if now is None else now, stale_after=stale_after
    )


def acquire_run_lease(
    locus: "Locus", *, now: float | None = None, stale_after: float = RUN_LEASE_STALE_SECONDS
) -> "RunLease | None":
    """Try to claim the run slot for ``locus``. ``None`` means somebody else has it.

    The claim is created with ``O_EXCL``, the one filesystem operation that is atomic on both
    Windows and POSIX. A read-then-write ("no lease? write one") would let the terminal and the
    dashboard both see an empty slot and both start the same locus -- the guard would exist, pass its
    tests, and still fail at the only moment it matters.

    A lease whose mtime is older than ``stale_after`` is taken over, because a live run re-touches
    it (see :func:`renew_run_lease`). That is what keeps a crashed process from locking its locus out
    permanently.
    """
    path = run_lease_path(locus)
    now = time.time() if now is None else now
    token = uuid.uuid4().hex

    def unguarded(reason: str) -> RunLease:
        logger.warning("Running %s without a lease: %s", locus.name, reason)
        return RunLease(
            locus_id=locus.id, path=None, pid=os.getpid(), acquired_at=now, token=token, enforced=False
        )

    try:
        # A locus's workspace is created by the first run that needs it; the lease cannot be the one
        # thing that refuses to create it.
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return unguarded(f"its workspace is not writable ({exc})")

    for attempt in (1, 2, 3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _lease_from_path(path, locus.id, now=now, stale_after=stale_after) is not None:
                return None  # held by a live run
            if attempt == 3:
                return None  # a racing process keeps recreating it; it wins
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Windows refuses to delete a file that still has an open handle, and the stale
                # owner's handle can outlive its process by a few milliseconds. Pausing briefly
                # beats both alternatives: giving up here would silently drop the wake-up, and
                # overwriting in place would break the atomicity the whole guard rests on.
                time.sleep(0.05)
                continue
            continue
        except OSError as exc:
            return unguarded(str(exc))
        payload = json.dumps(
            {"locus": locus.id, "pid": os.getpid(), "acquired_at": now, "token": token}
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError:
            pass
        return RunLease(
            locus_id=locus.id, path=path, pid=os.getpid(), acquired_at=now, token=token
        )
    return None


def renew_run_lease(lease: "RunLease | None", *, now: float | None = None) -> bool:
    """Push a lease's expiry out by re-touching it. False when it is no longer ours.

    The heartbeat for a run that legitimately outlasts ``RUN_LEASE_STALE_SECONDS``. It re-checks
    the token first, so a run that was already taken over stops claiming to own the slot instead
    of extending a lease that now belongs to somebody else.
    """
    if lease is None or lease.path is None:
        return False
    held = _read_lease_file(lease.path)
    if held is None or held.get("token") not in (None, "", lease.token):
        return False
    try:
        os.utime(lease.path, None)
        return True
    except OSError:
        return False


class _LeaseHeartbeat:
    """A background thread that keeps one run's lease fresh until stopped.

    A daemon thread rather than a timer loop in the caller: the run blocks inside a model turn for
    minutes at a time, so anything that only renewed between steps would let the lease expire during
    exactly the long runs it is meant to protect.

    Stopping is idempotent and always happens in a `finally`, so a run that raises does not leave a
    thread touching a lease file for a locus somebody else now owns. The thread also stops itself the
    moment `renew_run_lease` reports the lease is no longer ours -- a run that was taken over must
    stop claiming the slot rather than fighting for it.
    """

    def __init__(self, lease: "RunLease | None") -> None:
        self.lease = lease
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "_LeaseHeartbeat":
        if self.lease is None or self.lease.path is None:
            return self
        self._thread = threading.Thread(
            target=self._beat, name=f"myriaxon-lease-{self.lease.locus_id}", daemon=True,
        )
        self._thread.start()
        return self

    def _beat(self) -> None:
        while not self._stop.wait(LEASE_HEARTBEAT_SECONDS):
            if not renew_run_lease(self.lease):
                return

    def stop(self) -> None:
        self._stop.set()


def _start_lease_heartbeat(lease: "RunLease | None") -> _LeaseHeartbeat:
    return _LeaseHeartbeat(lease).start()


def _stop_lease_heartbeat(beat: "_LeaseHeartbeat | None") -> None:
    if beat is not None:
        beat.stop()


def release_run_lease(locus: "Locus") -> bool:
    """Release whatever lease is currently recorded for ``locus``. For a caller that has only the locus."""
    lease = read_run_lease(locus)
    if lease is None:
        return False
    lease.release()
    return True


@dataclass
class Goal:
    """One objective, with enough state to survive a restart mid-way through."""

    id: str
    title: str
    detail: str = ""
    status: str = GOAL_PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
    # Why this goal last failed, kept on the goal itself rather than only in the activity log:
    # the log is a stream to be read in order, while this is the one fact a surface needs to show
    # next to a stuck objective ("why is this not moving?").
    last_error: str = ""
    # --- Level 5: self-directed goal formation ------------------------------------------------
    #
    # The parent objective this one was decomposed from, or "" for a goal a person or the agent created
    # directly. Requirement 5.1: an agent that can only work a flat list of objectives is following
    # instructions, not setting its own sub-goals.
    parent: str = ""
    # How deep in the decomposition tree this sits. 0 for a top-level objective.
    #
    # CAPPED, and the cap is load-bearing rather than tidy: unbounded decomposition is a fork bomb with a
    # token budget. An agent asked to "break this into smaller pieces" will do so indefinitely, and each
    # level multiplies the work without adding information. See `MAX_GOAL_DEPTH`.
    depth: int = 0
    # The agent's own judgement of how much this matters, 0.0 to 1.0. Requirement 5.2.
    #
    # Recorded rather than merely used, which is the whole point: the agent will sometimes value what is
    # EASIEST rather than what matters, and a stored number is the only thing that makes that drift
    # reviewable. A formula would not fix the judgement; visibility is what catches it.
    value: float = 0.5
    # Who wrote this objective: "owner" for a person, "locus" for the agent itself. Requirement 5.3 turns on
    # this -- an agent may retire its OWN objectives and never its owner's.
    author: str = "owner"
    # Why it was retired. Kept beside the state so "why did this stop" has an answer.
    retired_reason: str = ""

    def is_open(self) -> bool:
        return self.status in (GOAL_PENDING, GOAL_ACTIVE, GOAL_BLOCKED)

    # ---- Level 5: the agent's own judgement about its objectives ------------------------------

    def is_retirable_by_agent(self) -> bool:
        """Whether the agent may retire this objective itself.

        Only its own. An agent that can retire an objective its owner wrote has been given a delete button for
        its instructions, and the failure is silent: the objective simply stops being pursued and nobody is
        told. Requirement 5.3 permits self-authored retirement and nothing else.
        """
        return self.author == LOCUS_GOAL_AUTHOR and self.is_open()

    def exhausted(self) -> bool:
        """Whether this goal has used up its attempts and is due to be blocked."""
        return self.attempts >= MAX_GOAL_ATTEMPTS

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Goal":
        """Rebuild from stored JSON, ignoring keys this build does not know about.

        The forward-compatibility half of the rule :meth:`Locus.from_dict` already follows. Without
        it, one unknown key -- a field written by a newer build, a hand edit -- makes ``Goal(**data)``
        raise, and the registry's per-entry guard then drops the whole locus that owned it. Losing a
        locus because one of its objectives has an extra key is a data-loss bug wearing validation's
        clothes.
        """
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ActivityEntry:
    """One thing a Locus did. The log is the answer to "what has it been doing?"."""

    at: float
    kind: str          # "turn" | "goal" | "note" | "error" | "retry" | "created"
    summary: str

    def render(self) -> str:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.at))
        return f"[{when}] {self.kind:<8} {self.summary}"


@dataclass
class Locus:
    """A persistent agent identity."""

    id: str
    name: str
    role: str = "generalist"
    instructions: str = ""
    workspace: str = ""
    provider: str = ""
    model: str = ""
    proactive: bool = False
    interval_seconds: int = DEFAULT_PROACTIVE_INTERVAL_SECONDS
    # What makes this locus wake. `None` means the interval decides, which is the historical behaviour.
    #
    # With a condition, a long-running maintenance agent wakes because the thing it maintains changed rather than
    # because a clock ticked -- so a quiet night costs nothing instead of one paid call per interval. The
    # condition is evaluated before the turn starts, so a tick that is not warranted never becomes a model call.
    condition: dict | None = None
    # The last time the condition was evaluated, whether or not a turn ran. Advanced on every tick so a quiet
    # condition does not accumulate catch-up wakes, and used as the `since` for time-based conditions.
    condition_checked_at: float = 0.0
    # The last evaluation's verdict, for `loci --status`: "holds", "quiet", or "ERROR: ...".
    last_condition_state: str = ""
    # What the condition remembers between evaluations: the last observed value and its revision.
    #
    # Persisted because `is_due` rebuilds the `Condition` from a dict every tick, so a `Condition` object cannot
    # carry state -- it is discarded before the next evaluation. Held here so it survives a process restart, which
    # is what makes "wake me when this CHANGED" expressible at all.
    trigger_state: dict = field(default_factory=dict)
    # When the condition last FIRED (as opposed to when it was last evaluated). Used by the `changed` kind to tell
    # "the value moved" from "the value moved and I already acted on it".
    condition_fired_at: float = 0.0
    # Set by `is_due`, committed by `commit_trigger_state` only for a run that finished. Not persisted: a staged
    # update belongs to the tick that produced it, and a process that died mid-tick should re-evaluate rather than
    # believe a commit it never made.
    _pending_trigger_state: Any = field(default=None, repr=False, compare=False)
    _pending_condition: Any = field(default=None, repr=False, compare=False)
    # The standing watchlist this locus follows on every unprompted wake, and what it last decided to report.
    #
    # Without a watchlist an always-on agent invents work from whatever is in its context. With one, "I checked
    # and there is nothing to report" becomes a real outcome rather than a wasted turn -- which is what lets it
    # run unattended without either spamming or going quiet for the wrong reason.
    scratch: str = ""
    # The most recent heartbeat verdict: "alert", "silent", "remembered" or "deferred".
    last_heartbeat_verdict: str = ""
    # Bounded internal context from a `notify: false` heartbeat, carried to the next user turn. The LATEST
    # outcome, not a history: an unbounded replay queue is a memory leak with extra steps.
    heartbeat_note: str = ""
    # Opt-in multi-step runs. 1 is the historical behaviour: one wake-up, one turn.
    max_steps_per_run: int = DEFAULT_MAX_STEPS_PER_RUN
    # How much of its own direction this locus is allowed. See AUTONOMY_MODES.
    #
    # "assisted" is the historical behaviour and stays the default, deliberately: every locus that
    # already exists must keep behaving exactly as it did, and an upgrade that silently turned
    # confined agents loose would be the worst kind of change. "self_directed" is opt-in per locus.
    autonomy: str = AUTONOMY_ASSISTED
    # Objectives this locus wrote for itself, in the order it intends to work them. Kept apart from
    # `goals` so "what my owner asked for" and "what I decided to do" stay distinguishable: the owner
    # asked for that distinction by asking for self-direction WITHOUT giving up oversight of the
    # objective list they wrote.
    self_set_goals: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_run_at: float = 0.0
    # Set while a run is in flight, and cleared in end_run's first statement. Two fields rather
    # than one because the timestamp is what makes the flag self-healing: a flag with no age can
    # only ever say "busy", including for a process that died an hour ago.
    running: bool = False
    run_started_at: float = 0.0
    # The last failure recorded for this locus, whether or not it belonged to a goal.
    last_error: str = ""
    # The goal this locus most recently handed to the model, so a failure reported by a caller that
    # does not know which goal it was working on is still attributed to the right objective.
    last_goal_id: str = ""
    # The conversation this locus is having, once it has had one.
    #
    # A locus used to get a brand-new session per run, which made every exchange a Q&A: it could not
    # refer to what you asked a minute ago, and "so make it portrait instead" had no antecedent.
    # A persistent agent that forgets the conversation between messages is not persistent in the way
    # that matters. Held here so the conversation belongs to the *locus*, not to whichever browser
    # happened to start it -- which is also what lets the terminal and the dashboard continue the
    # same discussion rather than each starting their own.
    session_id: str = ""
    # ---- the consecutive-failure ledger. See CONSECUTIVE_FAILURES_BEFORE_DISABLE for why it exists.
    #
    # `consecutive_failures` counts runs that failed, in a row, and is reset by any success. It is separate
    # from `Goal.attempts` on purpose: attempts count *this objective*, while these count *this locus*, which is
    # the thing that has to stop when nothing is working -- a locus that keeps changing goals and failing each
    # one never trips a per-goal ceiling.
    consecutive_failures: int = 0
    # Which class of failure the last one was, so `loci --status` can distinguish "the key is revoked" from
    # "the network blipped" without reading the activity log.
    last_failure_kind: str = ""
    # Set when the ledgers trip. Non-zero means this locus disabled *itself*, as opposed to being turned off by
    # a person, and that distinction is the whole point: a self-disabled locus must explain itself and must not
    # look like a deliberate choice someone made.
    auto_disabled_at: float = 0.0
    auto_disabled_reason: str = ""
    goals: list[Goal] = field(default_factory=list)
    activity: list[ActivityEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Deliberately not dataclass fields: these describe *this process's* view of the current
        # run, and asdict() must not carry them into loci.json. Annotating them would make them
        # fields and silently add two more things to persist.
        self._lease: RunLease | None = None
        self._completed_goals_at_start = {g.id for g in self.goals if g.status == GOAL_DONE}
        self._reflection_used = False
        # How many consecutive steps have FAILED, and the last reason. Read by `_replan_note`, which puts a
        # re-plan instruction into the next continuation prompt. Defaulted here rather than only set on
        # failure, so `continuation_prompt` can ask without a getattr dance.
        self._step_failures = 0
        self._last_step_failure = ""
    def open_goals(self) -> list[Goal]:
        return [g for g in self.goals if g.is_open()]

    def runnable_goals(self) -> list[Goal]:
        """Open goals this locus could still make progress on: pending or active, not blocked.

        A goal that has used up its attempts is deliberately *included*: it is the wake-up itself
        that turns "spent" into ``blocked`` with the reason attached, so filtering it out here
        would leave a used-up objective sitting active forever with nothing left to resolve it.
        A blocked goal is excluded, which is what stops a locus whose only objective needs a person
        from being woken on every interval to be told the same thing.
        """
        return [g for g in self.goals if g.status in (GOAL_ACTIVE, GOAL_PENDING)]

    def next_goal(self) -> Goal | None:
        """The one goal a proactive run should advance.

        Scans by *status*, not by position: any active goal wins over every pending one,
        regardless of the order they were added. Returning the first goal that happened to be
        either active or pending meant that adding a new objective silently starved whatever was
        already in progress -- progress stopped on work half-done and moved to work not started.

        A blocked goal is never returned. Blocked means a person owes an answer, so retrying it
        spends tokens to be told the same thing on every wake-up.
        """
        for status in (GOAL_ACTIVE, GOAL_PENDING):
            # Within a status tier, the agent's own value judgement decides -- requirement 5.2, and the
            # tiebreaker is deliberately INSIDE the tier rather than across it.
            #
            # Ordering all goals by value would undo a measured fix: an active goal must beat a pending one
            # regardless of value, because returning the first goal that was active-or-pending meant that
            # adding a new objective silently starved whatever was already half-done. Value decides which of
            # several equally-eligible objectives to take, not whether to abandon work in progress.
            #
            # Ties fall back to creation order, so an agent that values everything equally behaves exactly as
            # it did before this existed -- which makes the change invisible until it is actually used.
            tier = [g for g in self.goals if g.status == status]
            if tier:
                return max(tier, key=lambda g: (float(getattr(g, "value", 0.5) or 0.0), -g.created_at))
        return None

    def workspace_path(self) -> Path:
        path = locus_workspace_dir(self)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def goal_for_last_attempt(self) -> Goal | None:
        """The objective this locus last handed to the model, if it is still unfinished.

        Used to attribute a failure to the right goal when the caller reporting it only has the
        exception: without this, a failed run would leave ``last_error`` on the locus and nothing on
        the objective that actually failed, which is the one place a person looks.
        """
        if not self.last_goal_id:
            return None
        goal = self.find_goal(self.last_goal_id)
        if goal is None or goal.status == GOAL_DONE:
            return None
        return goal

    def goals_completed_this_run(self) -> list[Goal]:
        """Goals that reached ``done`` since this run began.

        The comparison is against a snapshot taken in :meth:`begin_run`, so a goal completed in an
        earlier session is not reported as this run's achievement -- which is what keeps the
        reflection prompt honest about what was just learned.
        """
        return [
            g for g in self.goals if g.status == GOAL_DONE and g.id not in self._completed_goals_at_start
        ]

    def is_self_directed(self) -> bool:
        """Whether this locus may write and pursue its own objectives.

        One predicate rather than a string comparison in six places: the brief, the run path, the
        self-set-goal tool and both surfaces all ask this question, and a mode check repeated six
        times is a mode check that eventually disagrees with itself -- the mistake this codebase has
        already made once with the provider switch.
        """
        return str(getattr(self, "autonomy", AUTONOMY_ASSISTED)).strip().lower() == AUTONOMY_SELF_DIRECTED

    def step_budget(self) -> int:
        """How many model turns one run of this locus may take, clamped to the ceiling.

        Clamped rather than trusted: ``max_steps_per_run`` is persisted JSON that a person can edit
        and a stale schema can carry. A value below 1 (or garbage) falls back to the single-step
        default, which stays the default for a locus nobody has configured -- an upgrade must not
        silently turn a one-step locus into an unbounded one.

        A self-directed locus gets a large budget rather than one step, because the two settings are
        not independent: a locus that decides its own work and is then cut off after a single tool
        call has not been given autonomy, it has been given a longer leash on the same post. The
        default changes with the mode; an explicit `max_steps_per_run` still wins either way.
        """
        try:
            requested = int(self.max_steps_per_run)
        except (TypeError, ValueError):
            requested = DEFAULT_MAX_STEPS_PER_RUN
        if requested <= DEFAULT_MAX_STEPS_PER_RUN and self.is_self_directed():
            # Nobody chose this number, so the mode decides: enough steps to plan, act and verify.
            requested = DEFAULT_SELF_DIRECTED_STEPS
        return max(1, min(requested, MAX_STEPS_PER_RUN_CEILING))

    def is_running(self, now: float | None = None) -> bool:
        """Whether a run is in flight for this locus right now -- here or in another process.

        Two sources, because each alone is wrong. The in-memory flag is what a surface in *this*
        process sets and can read back instantly; the lease file is what the other process left
        behind. The flag is bounded by the same stale timeout as the lease so that a process killed
        mid-run cannot leave a locus looking permanently busy -- a guard that can deadlock is worse
        than no guard, because it stops work silently.

        The two checks read different clocks on purpose. The in-memory flag is this process's own
        live state and is always judged against the wall clock, so a caller asking "would this be
        due in an hour?" still cannot schedule a run that is happening right now. The lease is on
        disk and is judged against ``now``, which is what makes expiry testable without waiting
        half an hour for it.
        """
        if self.running:
            started = self.run_started_at or time.time()
            if (time.time() - started) <= RUN_LEASE_STALE_SECONDS:
                return True
        read_at = time.time() if now is None else now
        return read_run_lease(self, now=read_at) is not None

    def heartbeat_prompt(self) -> str:
        """The turn text for a standing-check wake-up.

        Distinct from `proactive_prompt()`: that one advances a *goal*, while this one follows the locus's watchlist
        and is allowed to conclude that nothing needs doing. A locus with a watchlist and no runnable goal is exactly
        the maintenance case -- "keep an eye on this" with nothing to build -- and it needs this path to run at all.
        """
        from . import heartbeat

        scratch = heartbeat.Scratch(notes=self.scratch)
        return heartbeat.heartbeat_prompt(scratch, extra=self.briefing(include_activity=False))

    def record_heartbeat(self, verdict: str, text: str = "", note: str = "") -> None:
        """Record what a heartbeat turn decided, so the next wake and the status line both know."""
        from . import heartbeat

        self.last_heartbeat_verdict = verdict
        if verdict == heartbeat.REMEMBERED and note:
            # The LATEST note replaces the previous one. Their rule: this is the latest outcome for the session,
            # "not an alert history or exact-delivery replay queue".
            self.heartbeat_note = note[:2000]
        self.log("heartbeat", f"{verdict}" + (f": {text[:400]}" if text else ""))

    def is_due(self, now: float | None = None) -> bool:
        """Whether this locus should wake up and advance its own work.

        A locus that has never run is due immediately -- waiting a full interval before a
        brand-new locus does anything would make it look broken. That is expressed explicitly
        rather than left to the arithmetic: `last_run_at` defaults to 0.0, so an epoch-based
        comparison treats every newly created locus as having been idle for fifty-six years, which
        is the right answer for the wrong reason and would break the moment the default changed.

        A locus that is already running is not due. Both surfaces schedule from this method, and
        without the check a run in progress would be started a second time on the next tick.

        The gate is a *runnable* goal, not merely an open one. A locus whose every objective is
        blocked has nothing it is allowed to work on, so waking it spends a turn to be told what
        the last wake-up already said -- the loop is silent, because each individual run looks
        like an ordinary attempt.

        **With a condition, the interval becomes a ceiling rather than the trigger.** The condition is
        evaluated only once the interval has elapsed, so the clock still bounds how often the agent may run and
        the condition decides whether it needs to. A condition that does not hold means no turn, which is the
        whole point: a quiet night costs nothing.

        Evaluation has a side effect by design -- `condition_checked_at` and `last_condition_state` advance even
        when the answer is "quiet" -- because a tick that did not happen must still count as having been
        considered, or a quiet condition would accumulate catch-up wakes.
        """
        if not (self.enabled and self.proactive):
            return False
        # A locus with a WATCHLIST or a CONDITION is a monitor, and a monitor's job may be "check and confirm
        # nothing is wrong" rather than "advance an objective". Gating that on a runnable goal made maintenance
        # impossible: measured, a locus created with a condition and a watchlist and no goals returned `is_due:
        # False` forever and never ran. The goal gate still applies to a locus with neither.
        monitoring = bool(self.scratch.strip() or self.condition)
        if not self.runnable_goals() and not monitoring:
            return False
        if self.is_running(now):
            return False
        moment = time.time() if now is None else now
        if self.last_run_at and (moment - self.last_run_at) < self.effective_interval_seconds():
            return False

        if not self.condition:
            return True

        from . import conditions as conditions_module

        condition = conditions_module.Condition(**self.condition)
        # The state is read from the Locus and the UPDATED state is parked on `_pending_trigger_state` rather than
        # written here. This method is a predicate that both scheduling surfaces call, sometimes speculatively, and
        # it must not make a durable change as a side effect of being asked a question. `end_run` commits it, and
        # only for a run that finished -- see `commit_trigger_state`.
        state = conditions_module.TriggerState.from_dict(self.trigger_state)
        holds, result, updated = conditions_module.should_run(
            condition, last_run_at=self.last_run_at, now=moment, state=state
        )
        self.condition_checked_at = moment
        self.last_condition_state = (
            f"ERROR: {result.detail}" if result.error else ("holds" if result.holds else "quiet")
        )
        if holds:
            self._pending_trigger_state = updated
            self._pending_condition = condition
        else:
            # A quiet evaluation has nothing to commit for a change-style condition, but for an observing one the
            # BASELINE must persist or every tick would look like the first. So a quiet observing evaluation still
            # stages its state; a quiet non-observing one stages nothing.
            if condition.kind in conditions_module.OBSERVING_KINDS:
                self._pending_trigger_state = updated
                self._pending_condition = condition
        if result.detail:
            self.log("condition", result.render())
        return holds

    def commit_trigger_state(self, *, succeeded: bool) -> bool:
        """Make a staged trigger-state update durable, or discard it. Returns whether anything was written.

        ## The rule, copied from OpenClaw and easy to get backwards

        Their documentation: *"If a fired payload run fails, the returned `state` is **not** persisted -- the next
        evaluation sees the previous state and can fire again."*

        That is the correct default. If a failed run persisted its state, the change that triggered the run would be
        recorded as handled by a run that accomplished nothing, and the watcher would go quiet at exactly the moment
        its work had failed. So a failure discards the staged state and the condition fires again next tick.

        A quiet evaluation still commits its baseline, which is why this is not simply "commit on success": for a
        `changed` condition the baseline is what makes the *next* comparison meaningful.
        """
        staged = getattr(self, "_pending_trigger_state", None)
        if staged is None:
            return False

        if not succeeded and self._pending_condition is not None:
            kind = self._pending_condition.kind
            from . import conditions as conditions_module

            if kind in conditions_module.OBSERVING_KINDS and staged.fires > 0:
                # A run that was meant to handle a change failed. Keep the OLD fingerprint so the change is still
                # visible next tick, and say so, because a watcher that fires twice looks like a bug otherwise.
                self.log(
                    "condition",
                    "run failed: keeping the previous observation so this change fires again",
                )
                return False

        self.trigger_state = staged.to_dict()
        self._pending_trigger_state = None
        self._pending_condition = None
        return True

    def condition_verdict(self, *, state: str = "") -> str:
        """Would this condition fire right now? Read-only, for `doctor` and for a status line.

        A dry run: `should_run(commit=False)` with the stored state, so asking never changes the answer for the next
        real tick. Returns `"quiet"`, `"holds"`, or `"ERROR: ..."`.
        """
        if not self.condition:
            return "no condition (the interval decides)"
        from . import conditions as conditions_module

        condition = conditions_module.Condition(**self.condition)
        problem = condition.validate()
        if problem:
            return f"ERROR: invalid condition: {problem}"
        stored = conditions_module.TriggerState.from_dict(self.trigger_state)
        _holds, result, _state = conditions_module.should_run(
            condition, last_run_at=self.last_run_at, state=stored, commit=False
        )
        if result.error:
            return f"ERROR: {result.detail}"
        return "holds" if result.holds else "quiet"

    def effective_interval_seconds(self) -> float:
        """The interval actually used for scheduling, which grows while the locus is failing.

        A locus failing for a transient reason should not retry at full cadence: a 60-second locus would spend ten
        failed runs inside ten minutes and hit the disable threshold before anyone could look at it. Backing off
        gives a transient cause time to clear and gives the ledger time to mean something.

        Exponential in the failure count, capped at `FAILURE_BACKOFF_CAP_SECONDS`. The cap matters: if it could
        grow without bound the locus would effectively stop before reaching the threshold, and the disable would
        never fire -- a silent stall instead of a stated one.
        """
        base = max(1, int(self.interval_seconds))
        if self.consecutive_failures <= 0:
            return float(base)
        grown = base * (2 ** min(self.consecutive_failures, 10))
        return float(min(grown, max(base, FAILURE_BACKOFF_CAP_SECONDS)))

    def seconds_until_due(self, now: float | None = None) -> int:
        if not self.last_run_at:
            return 0
        now = time.time() if now is None else now
        return max(0, round(self.effective_interval_seconds() - (now - self.last_run_at)))

    # ---- mutation ----------------------------------------------------------------------
    def log(self, kind: str, summary: str) -> None:
        summary = " ".join(str(summary).split())
        self.activity.append(ActivityEntry(time.time(), kind, summary[:2000]))
        if len(self.activity) > LOCUS_ACTIVITY_KEEP:
            del self.activity[: len(self.activity) - LOCUS_ACTIVITY_KEEP]

    def add_goal(self, title: str, detail: str = "", *, parent: str = "", value: float = 0.5,
                 author: str = OWNER_GOAL_AUTHOR) -> Goal:
        """Add an objective, optionally as a sub-goal of another. Level 5.1.

        The DEPTH CAP is enforced here rather than at the call site, and it is refused by FLATTENING rather
        than by raising. Raising would fail a run because the agent tried to decompose one level too far --
        a reasonable thing for it to try -- while flattening keeps the work and refuses only the tree. The
        returned goal's `depth` reports what actually happened, so a caller can see it was capped without
        having to catch anything.
        """
        depth = 0
        if parent:
            ancestor = self.find_goal(parent)
            if ancestor is not None:
                depth = min(int(getattr(ancestor, "depth", 0)) + 1, MAX_GOAL_DEPTH)
            else:
                # An unknown parent is treated as no parent rather than as an error: the objective is still
                # worth doing, and refusing it would lose the work over a bookkeeping mistake.
                parent = ""
        goal = Goal(
            id=uuid.uuid4().hex[:8],
            title=title.strip(),
            detail=detail.strip(),
            parent=parent if depth else "",
            depth=depth,
            value=max(0.0, min(1.0, float(value))),
            author=author if author in (OWNER_GOAL_AUTHOR, LOCUS_GOAL_AUTHOR) else OWNER_GOAL_AUTHOR,
        )
        self.goals.append(goal)
        self.log("goal", f"new objective: {goal.title}")
        return goal

    def retire_goal(self, ref: str, reason: str = "") -> tuple[Goal | None, str]:
        """Mark one of the AGENT'S OWN objectives obsolete. Level 5.3. Returns (goal, problem).

        A terminal state with a reason, never a deletion. Two separate reasons:

          * an agent that can delete objectives can destroy its owner's instructions, and the failure is
            SILENT -- the objective stops being pursued and nobody is told;
          * "why did this stop being pursued" is a question a person asks, and a deletion cannot answer it.

        So `retire_goal` refuses anything the owner wrote (`is_retirable_by_agent`), and what it does to the
        agent's own goals is set a status and record why. The goal stays in the record and stops being
        selected, which is exactly the behaviour wanted: the work stops, the history does not.
        """
        goal = self.find_goal(ref)
        if goal is None:
            return None, f"no objective matching {ref!r}"
        if not goal.is_retirable_by_agent():
            if goal.author != LOCUS_GOAL_AUTHOR:
                return None, (
                    f"[{goal.id}] was written by your owner, so only your owner can retire it. If it is "
                    "wrong or no longer applies, mark it blocked with a note explaining why -- do not try to "
                    "remove it."
                )
            return None, f"[{goal.id}] is already {goal.status}"
        goal.status = GOAL_OBSOLETE
        goal.retired_reason = " ".join((reason or "").split())[:400]
        goal.updated_at = time.time()
        self.log("goal", f"retired [{goal.id}] {goal.title}: {goal.retired_reason or 'no reason given'}")
        return goal, ""

    def find_goal(self, ref: str) -> Goal | None:
        """Resolve a goal by id or by unambiguous title match, so the CLI can accept either."""
        ref = (ref or "").strip()
        if not ref:
            return None
        for goal in self.goals:
            if goal.id == ref:
                return goal
        matches = [g for g in self.goals if g.title.lower() == ref.lower()]
        if len(matches) == 1:
            return matches[0]
        matches = [g for g in self.goals if ref.lower() in g.title.lower()]
        return matches[0] if len(matches) == 1 else None

    def set_goal_status(
        self, ref: str, status: str, note: str = "", *, source: str = "", admitted_round: str = ""
    ) -> Goal | None:
        """Set a goal's status. A transition to `done` requires completion authority.

        ## Why this is gated

        A Locus runs unattended. Without this check, the agent doing the work is also the party that declares the
        work finished -- and a model that has run out of ideas has a strong incentive to decide the objective is
        met. DeepSeek's harness closes the same hole in `goal/tool-goal/src/authority.ts`: completion needs either a
        direct human input in the root agent's open turn, or the turn to be *exactly* the goal's admitted round,
        matched on `(goalId, revision, round)`.

        ## The default is the least authoritative source

        `source=""` resolves to `system`, never to `human`. A caller must **supply** human authority rather than
        inherit it by leaving the argument out, which is the inversion that stops "unattended" quietly becoming
        "authorised". The 24/7 Locus path passes `source="locus"` and is therefore refused, as it should be.

        A refusal returns `None` and is written to the activity log. Returning the goal unchanged would look like
        success to the caller, and a refusal nobody can see is indistinguishable from a bug.
        """
        if status not in GOAL_STATES:
            return None
        goal = self.find_goal(ref)
        if goal is None:
            return None

        if status == GOAL_DONE:
            from . import goal_authority

            context = goal_authority.TurnContext(
                source=goal_authority.source_of(source),
                # Only an explicit human source carries human input. The field is set by the input path in a real
                # session; here it follows from the caller having named the human source deliberately.
                human_input=goal_authority.source_of(source) == goal_authority.SOURCE_HUMAN,
            )
            admitted = None
            if admitted_round:
                parts = admitted_round.split("@r")
                if len(parts) == 2 and "#" in parts[1]:
                    revision, _, round_number = parts[1].partition("#")
                    try:
                        admitted = goal_authority.RoundStamp(
                            goal_id=parts[0], revision=int(revision), round=int(round_number)
                        )
                    except ValueError:
                        admitted = None
            decision = goal_authority.may_complete(context, admitted=admitted)
            if not decision.allowed:
                self.log(
                    "note",
                    f"goal completion REFUSED for {goal.title}: {decision.reason}",
                )
                return None
            self.log(
                "goal",
                f"{goal.title} completion authorised by {decision.authority}"
                + (" (the model claimed it)" if decision.model_claimed else ""),
            )

        goal.status = status
        goal.updated_at = time.time()
        if note:
            goal.notes.append(note)
        self.log("goal", f"{goal.title} -> {status}" + (f" ({note})" if note else ""))
        return goal

    # ---- run lifecycle -----------------------------------------------------------------
    def begin_run(self) -> bool:
        """Claim this locus for one run. False means another process already has it.

        Both the in-memory flag and the on-disk lease are set, because they answer different
        questions: the flag is what a surface in this process renders as "running now" without
        touching the disk, and the lease is what stops the terminal and the dashboard from working
        the same locus at the same time. A refusal is written to the activity log rather than
        returned silently -- a run that did not happen for a reason nobody can see is
        indistinguishable from a bug, which is the failure this module exists to eliminate.
        """
        lease = acquire_run_lease(self)
        if lease is None:
            holder = read_run_lease(self)
            who = f" ({holder.describe()})" if holder is not None else ""
            self.log("note", f"run refused: this locus is already running{who}")
            return False
        self._lease = lease
        self.running = True
        self.run_started_at = time.time()
        self._completed_goals_at_start = {g.id for g in self.goals if g.status == GOAL_DONE}
        self._reflection_used = False
        # Per-RUN state, reset when a run begins rather than persisted. A failure streak belongs to the run
        # that is failing; carrying it across runs would make a fresh run's first step arrive with a re-plan
        # note about work that is already over.
        self._step_failures = 0
        self._last_step_failure = ""
        if not lease.enforced:
            self.log("note", "run started without a lease: its workspace is not writable")
        return True

    def end_run(self, outcome: "RunOutcome | BaseException | None" = None) -> RunOutcome:
        """Finish a run and write down what happened. Returns the normalized outcome.

        The running flag and the lease are cleared **first**, before anything that can fail. A locus
        left marked "running" is a locus nothing will schedule again, so the clearing is the one part
        of this method that must survive a logging or filesystem error; everything after it is
        bookkeeping that is allowed to be imperfect.
        """
        self.running = False
        self.run_started_at = 0.0
        lease, self._lease = self._lease, None
        if lease is not None:
            lease.release()

        report = normalize_outcome(outcome)
        if report.ok:
            self.last_error = ""
            self.log("turn", report.describe())
            completed = self.goals_completed_this_run()
            if completed:
                names = ", ".join(f"[{g.id}] {g.title}" for g in completed)
                self.log("note", f"completed {names}; ask what was reusable before moving on")
        else:
            record_failure(self, None, report)

        # The condition's memory advances only for a run that finished. A failed run deliberately leaves the
        # previous observation in place so the change that triggered it fires again -- see
        # `commit_trigger_state` for why, and note this must happen BEFORE `once` is evaluated: a `once` watcher
        # whose run failed must stay armed.
        self.commit_trigger_state(succeeded=report.ok)

        if report.ok and self.condition and self.condition.get("once"):
            # Their rule: `once` completes on a **successful fired payload**, not on a fire. So the watcher is
            # disabled here rather than when the condition held, and a failed first attempt leaves it armed to
            # retry -- which is what stops a one-shot watch from being dropped by one bad run.
            self.log(
                "condition",
                f"fired once and the run succeeded; disabling this watcher ({self.condition.get('description')})",
            )
            self.enabled = False

        self.last_run_at = time.time()
        self.updated_at = self.last_run_at
        return report

    @contextlib.contextmanager
    def run_scope(self) -> Iterator["Locus"]:
        """``begin_run``/``end_run`` around a block, clearing the flag even when the block raises.

        Offered because the ``finally`` is the guarantee and it is easy to forget: a run that dies
        mid-turn must not leave the locus looking busy, or the dashboard shows a phantom run and the
        scheduler skips real work. A caller that already called ``end_run`` with a real outcome
        inside the block is left alone -- ``running`` is already False.

        A refused slot *raises* rather than entering the block. Entering would be the one outcome
        the lease exists to prevent (two agents in one workspace), and a caller that has to handle
        the exception is a caller that knows a run did not happen. Callers that would rather skip
        quietly should use :meth:`begin_run`, which returns False instead.

        The lease is HEARTBEAT while the block runs. `renew_run_lease` was documented as the
        heartbeat and had no production caller, so a run longer than ``RUN_LEASE_STALE_SECONDS``
        silently stopped counting as a run: `is_running()` went False, `is_due()` went True, and a
        second surface could `begin_run` the same locus while the first was still working it -- two
        agents in one workspace, double token spend, interleaved edits. That is precisely what the
        lease exists to prevent, and 30 minutes is reachable by an ordinary 20-step run on a slow
        model. Starting the heartbeat here rather than at each call site is what makes it hold for
        every run, since every run goes through this scope.
        """
        if not self.begin_run():
            raise RunInProgress(self, read_run_lease(self))
        lease = read_run_lease(self)
        beat = _start_lease_heartbeat(lease)
        try:
            yield self
        except BaseException as exc:
            if self.running:
                self.end_run(exc)
            raise
        finally:
            _stop_lease_heartbeat(beat)
        if self.running:
            self.end_run(None)

    # ---- preflight ---------------------------------------------------------------------
    def preflight(self, for_message: bool = False) -> list[str]:
        """Everything already visible in this locus's own state that would make a run fail.

        The caller refuses on a non-empty list and tells the user why, so a doomed run costs no
        tokens and produces no mystery. Every check here is *static* -- no network, no credential,
        no model call -- because a preflight that can itself fail, hang or cost money is worse than
        none at all. Credentials are deliberately not checked: they belong to the provider
        configuration, not to the locus, and the provider layer reports them clearly on its own.

        `for_message=True` means the owner is giving the locus a direct instruction, and it drops the
        complaints about objectives. Those checks exist because a *proactive* wake-up with nothing
        to work on would burn a turn inventing something -- but that reasoning does not apply when a
        person has said what they want. Without this, a locus whose objectives were all finished or
        blocked could not be asked to do anything at all: `cowork` was unusable by message for
        exactly that reason, which is the opposite of what a persistent agent is for.
        """
        problems: list[str] = []

        if not self.enabled:
            problems.append("it is disabled, so nothing will run it (enable it first)")

        if not for_message:
            open_goals = self.open_goals()
            runnable = self.runnable_goals()
            if not open_goals:
                problems.append("it has no open objectives, so a run would have nothing to work on")
            elif not runnable:
                problems.append("every open objective is blocked, waiting on its owner's decision")
            elif all(g.exhausted() for g in runnable):
                problems.append(
                    f"every unblocked objective has already used its {MAX_GOAL_ATTEMPTS} attempts, "
                    "so the next run would mark them blocked instead of making progress"
                )

        # A locus with neither instructions nor objectives has nothing to answer from, whatever the
        # caller supplies -- a message gives it work, not a role.
        #
        # The `and not self.goals` half is load-bearing and was dropped once by mistake: a locus that
        # has objectives but no instructions is perfectly normal, and treating that as unready made
        # every such locus unrunnable.
        if not (self.instructions or "").strip() and not self.goals:
            problems.append(
                "it has neither standing instructions nor objectives, so a run would have nothing "
                "to go on"
            )

        workspace_problem = self._workspace_problem()
        if workspace_problem:
            problems.append(workspace_problem)

        # A locus overrides the machine's provider/model by setting either field, and half an
        # override is how a locus silently ends up running somewhere its owner did not choose.
        if bool((self.provider or "").strip()) != bool((self.model or "").strip()):
            problems.append(
                f"it overrides only half of its model configuration (provider="
                f"{self.provider!r}, model={self.model!r}); set both or neither, or the run uses "
                "a model its owner did not pick"
            )
        return problems

    def _workspace_problem(self) -> str:
        """A human-readable reason the workspace cannot be used, or "" when it can."""
        try:
            path = self.workspace_path()
        except OSError as exc:
            return f"its workspace cannot be created ({exc})"
        probe = path / ".myriaxon_dot_probe"
        try:
            probe.write_text("", encoding="utf-8")
        except OSError as exc:
            return f"its workspace {path} is not writable ({exc})"
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
        return ""

    # ---- prompts -----------------------------------------------------------------------
    def briefing(self, include_activity: bool = True, run_scope: str = "objective") -> str:
        """The standing brief handed to the model at the start of every turn with this Locus.

        This is the whole mechanism by which a Locus "remembers who it is". It is rebuilt from
        durable state each time rather than carried in a session, so it is identical whether the
        Locus ran five minutes ago in the terminal or yesterday in the dashboard.

        `run_scope` says what the turn is FOR, and it changes the last instruction rather than the
        identity: a locus is always "cowork" with its own role and instructions, but a turn that is
        answering its owner is not a turn that is advancing objectives.

        Measured defect this fixes: the brief ended with "Work the objectives above, then report..."
        unconditionally, so a greeting -- "hi" -- arrived at a model that had just been told to work
        objectives and report on them. The user watched "thinking" for minutes and asked, reasonably,
        why the locus was doing things nobody asked for. A question is not a work order, so
        `run_scope="message"` replaces the last paragraph and says so explicitly.
        """
        lines = [
            f'You are "{self.name}", a persistent Myriaxon agent (a "locus").',
            f"Role: {self.role}.",
        ]
        if self.instructions.strip():
            lines.append("")
            lines.append("Standing instructions from your owner:")
            lines.append(self.instructions.strip())

        workspace = self.workspace_path()
        lines.extend(
            [
                "",
                f"Your workspace is {workspace}. Keep work for these objectives inside it unless "
                "an objective says otherwise.",
            ]
        )

        open_goals = self.open_goals()
        if open_goals:
            lines.append("")
            lines.append("Your objectives, in the order you should work on them:")
            for goal in open_goals:
                marker = {"active": "in progress", "pending": "not started", "blocked": "blocked"}[goal.status]
                lines.append(f"  - [{goal.id}] ({marker}) {goal.title}")
                if goal.detail:
                    lines.append(f"      {goal.detail}")
                for note in goal.notes[-3:]:
                    lines.append(f"      note: {note}")
        else:
            lines.append("")
            if self.is_self_directed():
                lines.append(
                    "You have no open objectives. You are SELF-DIRECTED: decide what is worth doing "
                    "next and record it before you start, with `locus_goal_update` passing "
                    f'`locus: "{self.name}"` and `add: "<the objective>"`. Recording it first is the '
                    "point: it makes your reasoning visible to your owner, it survives a restart, and "
                    "it is what the next run picks up. Choose work that serves your role and standing "
                    "instructions. Do not invent busywork to look occupied -- if nothing is worth "
                    "doing, say so and stop."
                )
            else:
                lines.append(
                    "You have no open objectives. Do not invent work: report that you are idle and "
                    "what you would need in order to be useful, then stop."
                )

        if self.is_self_directed():
            lines.append("")
            lines.append(
                "You are self-directed: when you see work that serves your role, add it yourself with "
                f'`locus_goal_update` (`locus: "{self.name}"`, `add: "..."`). Objectives your owner '
                "wrote always take priority over ones you set yourself, and you cannot delete or "
                "rewrite your owner's."
            )
            # The completion gate refuses a locus's own unattended turn the right to mark a goal done
            # -- deliberately, because the party that did the work does not get to declare it finished.
            # Without this instruction the consequence was silent and expensive: the objective stayed
            # open and the locus redid the same work on every wake-up, forever, with nothing in the
            # transcript to say why. Blocked is the state that stops the retry, and a blocked goal is
            # already never selected (see `next_goal`), so this costs nothing and needs no new
            # authority -- it is a report to the owner, not a claim about the work.
            lines.append(
                "When you have genuinely finished an objective but cannot mark it done -- a run of your "
                "own is refused that authority -- mark it `blocked` with a note saying the work is "
                "finished and awaiting your owner's confirmation. Do not leave it open: an open "
                "objective is one you will be asked to do again, and you would redo finished work on "
                "every wake-up."
            )

        # Capability honesty, stated for EVERY locus and every run.
        #
        # Measured, from the first benchmark run: the locus was asked to fix a bug and prove it by
        # running `check.py`. It fixed the bug correctly, and then spent all six of its steps
        # announcing that it could not verify the fix because "shell execution is blocked in this
        # Locus (no sandbox)" -- while the sandbox was available and working. It never called
        # run_bash to find out. The work was right; the report was false; and it burned its entire
        # budget repeating the false report.
        #
        # The cost of that failure mode is worse than idleness: a false "I cannot" is indistinguishable
        # from a true one, so the owner is told to fix something that is not broken. Stating the rule
        # in the brief is the cheapest possible fix and it applies to every task, not just this one.
        lines.append("")
        lines.append(
            "Before you report that you cannot do something, TRY IT ONCE. A claim that a tool is "
            "unavailable, a sandbox is missing or a file cannot be read is a claim about the world, and "
            "it is wrong often enough that guessing costs more than testing. Call the tool and report "
            "what actually happened, including the error text.\n"
            "Never say you verified something you did not verify. If you checked code by reading it, "
            "say 'verified by reading', not 'verified'. If you could not run the check, say that "
            "plainly and still do the part you can.\n"
            "Do not spend a second step re-reporting what the first step already said. Each step is "
            "paid work: either make progress, or stop and report."
        )

        # The environment, stated as fact rather than left to inference.
        #
        # Everything below this line is instruction; this block is DESCRIPTION, and it exists because
        # an agent that does not know where it runs will reason about it instead of testing it.
        # Measured: six benchmark runs where a Locus refused to call `run_bash` at all, insisting the
        # shell was blocked, while the tool was present and working. Two attempted fixes -- a briefing
        # rule and a tool-description rewrite -- both failed, because the agent was not short of
        # permission, it was short of facts.
        try:
            from .tools import environment_manifest

            lines.append("")
            lines.append("Your execution environment:")
            for entry in environment_manifest().splitlines():
                lines.append(f"  {entry}" if entry.strip() else "")
        except Exception:  # noqa: BLE001 - a missing manifest must not break a run
            pass

        if include_activity and self.activity:
            lines.append("")
            lines.append("Your most recent work, so you do not repeat it:")
            for entry in self.activity[-8:]:
                lines.append(f"  {entry.render()}")

        lines.append("")
        if run_scope == "message":
            lines.extend(
                [
                    "This turn is a CONVERSATION: your owner has written to you and you are answering them.",
                    "Answer what they actually said, in a sentence or two, and then stop.",
                    "Do not start working on your objectives, and do not call tools, unless the message "
                    "explicitly asks you to do that work. If they ask a question, answer it; if they greet "
                    "you, greet them back; if they ask for work, do only that work.",
                ]
            )
        else:
            lines.extend(
                [
                    "Work the objectives above, then report in two or three sentences: what you did, "
                    "what you learned, and what (if anything) needs your owner's decision. If an "
                    "objective needs information only a person can give, mark it blocked rather than "
                    "guessing. Prefer finishing one objective over starting several.",
                ]
            )
        return "\n".join(lines)

    def take_run(self) -> tuple[Goal, str] | None:
        """Select the goal for an unprompted run and return it with its prompt, atomically.

        Prefer this over calling `next_goal()` and `proactive_prompt()` separately, which is what the REPL did.
        The reason is coherence, not a lost update: `proactive_prompt()` claims the goal and counts an attempt,
        and `_select_goal()` is called inside it, so the two separate calls could in principle disagree about
        which objective the run is for. Returning both together makes that unrepresentable.

        An earlier version of this docstring claimed the old pair *destroyed* the goal when called twice. That
        was checked and is false: re-selecting returns the same goal, deliberately, because `runnable_goals`
        includes `GOAL_ACTIVE` so that a goal stays selected until the attempt ceiling blocks it. Verified by
        calling both paths three times and comparing. The claim is corrected here rather than left in place,
        because a justification that overstates a bug is how a reader learns to distrust the comments.

        Returning `None` when there is nothing to run keeps the empty-prompt case out of the caller: it either
        has a goal *and* its prompt, or neither.
        """
        goal = self._select_goal()
        if goal is None:
            return None
        prompt = self.proactive_prompt()
        if not prompt:
            # _select_goal found a goal but no prompt could be built for it. Returning None rather than an
            # empty prompt keeps the caller from starting a turn with no instruction in it.
            return None
        return goal, prompt

    def proactive_prompt(self) -> str:
        """The turn text for an unprompted run.

        The goal is chosen first, so the brief and the instruction cannot disagree about what this
        run is for. Selection also enforces the attempt ceiling -- see :meth:`_select_goal` --
        which is the only thing standing between a goal the locus cannot finish and an unbounded
        retry loop against a paid API.

        **Calling this claims the goal and counts an attempt**, so it is not a pure getter: a second
        consecutive call returns "" because the goal is now active and no longer selectable. Use
        :meth:`take_run` unless the claim is the intended effect.

        The reflection clause is the same invitation the sub-agent path makes (see
        ``tool_registry._spawn_subagent_inner``), with the same explicit permission to find nothing
        worth keeping: a prompt that demands a lesson produces invented ones.
        """
        goal = self._select_goal()
        if goal is None:
            return ""
        self._claim_goal(goal)
        lines = [
            f"Continue your objective [{goal.id}] \"{goal.title}\".",
            "Take the next concrete step. Use your tools rather than only describing what you "
            "would do. When the objective is genuinely complete, call locus_goal_update with "
            'status "done" and say so. If you are blocked on something only your owner can '
            'decide, call locus_goal_update with status "blocked" and state exactly what you need.',
        ]
        steps = self.step_budget()
        if steps > 1:
            lines.append(
                f"This run may take up to {steps} steps. When you finish one objective, keep going "
                "on the next open one instead of stopping -- unless it needs a decision only your "
                "owner can make."
            )
        lines.append(REFLECTION_CLAUSE)
        return "\n\n".join(lines)

    def continuation_prompt(self, step: int = 2) -> str:
        """The prompt for step *step* of a multi-step run, or "" when the run must stop.

        Only reachable when ``max_steps_per_run`` was raised above its default of one, because
        unattended multi-step runs have no natural stopping point and their cost is a function of
        how long nobody is watching.

        A completion takes priority over starting the next objective: reflection is worth one step
        precisely when it is freshest, and it is the thing that makes a locus better at its second
        objective than its first.
        """
        try:
            step = int(step)
        except (TypeError, ValueError):
            return ""
        if step < 2 or step > self.step_budget():
            return ""
        if not self._reflection_used:
            reflection = self.reflection_prompt()
            if reflection:
                self._reflection_used = True
                return reflection
        goal = self._select_goal()
        if goal is None:
            return ""
        self._claim_goal(goal)
        # The closing instruction differs by mode, and it has to: this is the prompt a locus sees on
        # every step of a multi-step run, so it governs the commonest case. The briefing has told a
        # self-directed locus to park finished-but-unconfirmable work as `blocked`, but the STEP prompt
        # offered it only "blocked if you need a person" -- so on a step-by-step basis, which is where
        # the work actually happens, the instruction that stops the redo loop was absent. Two places
        # telling the same agent different things is how the redo loop would have survived the fix.
        closing = (
            "Use locus_goal_update to mark it done, or blocked if you need a person."
            if not self.is_self_directed()
            else (
                "Use locus_goal_update to mark it done, or blocked if you need a person. A run of "
                "your own cannot mark a goal done, so when the work is FINISHED, mark it blocked with "
                "a note that it is finished and awaiting your owner's confirmation -- do not leave it "
                "open, or you will be asked to do it again."
            )
        )
        return (
            f"Step {step} of {self.step_budget()}: continue your objective [{goal.id}] "
            f"\"{goal.title}\". Take the next concrete step. {closing}{self._replan_note()}"
        )

    def note_step_failure(self, reason: str = "") -> None:
        """Remember that a step failed, so the NEXT step is told to change approach.

        Requirement 4.13 (revise its own plans) and 4.14 (abandon a dead end and record why) both reduce to
        the same missing thing: a step that failed left no trace in the prompt that followed, so the next
        step was asked to "take the next concrete step" with no idea that the last one had not worked. The
        agent would rediscover the same wall and stop at it again -- which is the shape the benchmark showed,
        where a run spent every step announcing that the shell was blocked.

        The count matters rather than a boolean. One failure is worth a nudge; two identical failures mean the
        approach itself is wrong, and that is the point to say so plainly rather than let a third attempt
        spend another step on it.
        """
        self._step_failures = int(getattr(self, "_step_failures", 0)) + 1
        self._last_step_failure = " ".join((reason or "").split())[:400]

    def clear_step_failures(self) -> None:
        """Forget the failure streak once a step succeeds, so the note does not outlive the problem."""
        self._step_failures = 0
        self._last_step_failure = ""

    def _replan_note(self) -> str:
        """The re-plan instruction appended to a continuation prompt after a failure, or ""."""
        count = int(getattr(self, "_step_failures", 0))
        if count <= 0:
            return ""
        reason = getattr(self, "_last_step_failure", "")
        detail = f" The failure was: {reason}" if reason else ""
        if count == 1:
            return (
                f"\n\nNOTE: your previous step did not work.{detail} Do not repeat it unchanged -- either "
                "take a different approach, or if the objective cannot be done, mark it blocked with the "
                "reason."
            )
        return (
            f"\n\nSTOP AND RE-PLAN: your previous {count} steps have failed.{detail} Repeating the same "
            "approach a third time will fail the same way. Either take a genuinely different approach, or "
            "give up on THIS objective properly -- mark it blocked with a note saying what you tried and "
            "why it did not work. Abandoning an objective with a clear reason is a good outcome; grinding "
            "at a wall until the step budget runs out is not."
        )

    def reflection_prompt(self) -> str:
        """What to ask after an objective is genuinely complete, or "" when none was.

        Empty for a failed, trivial or incomplete run, and that emptiness is the point: a skill
        recorded after a run that achieved nothing would be a fabricated lesson, and the value of
        the skills store is that everything in it was earned. Whether the locus then calls
        ``save_skill`` stays its own decision -- the prompt says so explicitly.
        """
        completed = self.goals_completed_this_run()
        if not completed:
            return ""
        goal = completed[-1]
        others = f" ({len(completed) - 1} other objective(s) also finished)" if len(completed) > 1 else ""
        return (
            f'You have just finished the objective [{goal.id}] "{goal.title}"{others}.\n\n'
            "Before moving on, consider: did you discover a genuinely reusable approach here -- a "
            "procedure, a command sequence, a gotcha worth remembering? If so, call save_skill to "
            "preserve it for future tasks. If nothing here is generalizable, don't call it -- "
            "that's a normal, expected outcome."
        )

    def _select_goal(self) -> Goal | None:
        """``next_goal()``, blocking any goal that has spent its attempt ceiling and moving on.

        Blocking rather than skipping is deliberate. A goal that has been attempted
        ``MAX_GOAL_ATTEMPTS`` times without being finished is not going to be finished by the same
        approach a ninth time, and silently skipping it would leave the locus looking busy with a
        objective that never moves. Marking it blocked -- with the attempt count, the last error
        and the way back -- turns an invisible loop into a question a person can answer, and frees
        the locus to work on whatever else it has.
        """
        while True:
            goal = self.next_goal()
            if goal is None:
                return None
            if not goal.exhausted():
                return goal
            self._block_exhausted_goal(goal)

    def _block_exhausted_goal(self, goal: Goal) -> None:
        reason = goal.last_error or "no error was recorded"
        goal.status = GOAL_BLOCKED
        goal.updated_at = time.time()
        goal.notes.append(
            f"blocked by the harness after {goal.attempts} attempts without finishing "
            f"(last error: {reason}). Change the approach, the model or the objective itself, then "
            "set this back to pending to resume."
        )
        self.log(
            "error",
            f"[{goal.id}] {goal.title}: gave up after {goal.attempts} attempts (last error: {reason})"
            " -- blocked, needs a decision.",
        )

    def _claim_goal(self, goal: Goal) -> None:
        """Mark a goal as being worked on and count the attempt.

        ``attempts`` counts how many times the goal has been handed to the model, continuation
        steps included, because that is what the ceiling is a limit on. A multi-step run therefore
        spends attempts faster -- intentional: a step that did not finish the objective is evidence
        about the approach, and evidence is what the ceiling exists to collect.
        """
        if goal.status == GOAL_PENDING:
            goal.status = GOAL_ACTIVE
        goal.updated_at = time.time()
        goal.attempts += 1
        self.last_goal_id = goal.id

    # ---- persistence -------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        # Private fields are dropped. They hold a staged trigger-state update that belongs to the tick which
        # produced it: persisting it would let a process that died mid-tick resume believing it had committed a
        # change it never handled, which is precisely the state the failure rule exists to prevent. `asdict` would
        # also convert the staged dataclass into a plain dict, so a reload would hand `commit_trigger_state` a dict
        # where it expects a `TriggerState`.
        data = asdict(self)
        for name in [k for k in data if k.startswith("_")]:
            del data[name]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Locus":
        goals = [Goal.from_dict(g) for g in data.get("goals", [])]
        activity = [ActivityEntry(**{**a}) for a in data.get("activity", [])]
        # Private fields are excluded as well as dropped on write, so a file hand-edited to contain one cannot
        # inject a staged commit.
        known = {f for f in cls.__dataclass_fields__ if not f.startswith("_")}
        clean = {k: v for k, v in data.items() if k in known and k not in ("goals", "activity")}
        # A run in flight belongs to the process that started it, not to the file. Honouring a
        # persisted "running: true" is what would strand a locus after a crash: the flag would say
        # busy until its timestamp aged out, and the only way to clear it would be to wait or to
        # edit the JSON by hand. The lease file on disk is the cross-process truth, and
        # Locus.is_running() reads it.
        clean["running"] = False
        clean["run_started_at"] = 0.0
        return cls(goals=goals, activity=activity, **clean)


class LocusRegistry:
    """Every Locus on this machine, persisted to ``~/.myriaxon/loci.json``.

    Thread-safe: the dashboard runs turns on worker threads while the terminal fires scheduled
    prompts from the scheduler's daemon, so two threads can reach this at once.
    """

    def __init__(self, path: Path | None = None) -> None:
        # `path` overrides everything, so a caller pointing at a specific file (a test, the dashboard against a
        # project-local store) is never redirected by the migration below.
        self.path = path or LOCI_FILE
        self.explicit_path = path is not None
        self._lock = threading.RLock()
        # `_loci` rather than the pre-rename `_dots`. The rename script could not map it: `self._loci` is an
        # attribute access, and the word-boundary rule deliberately skips anything preceded by a locus so that
        # `foo.dot` in unrelated code is not touched. Renamed by hand, here. The old word is kept in THIS comment
        # on purpose: it is explaining the rule that skipped the attribute. `_loci` is the live name.
        self._loci: dict[str, Locus] = {}
        self.load()

    # ---- persistence -------------------------------------------------------------------
    #
    # ## The migration, and why it is not optional
    #
    # This concept was called a "Locus" and persisted to `~/.myriaxon/loci.json` under a top-level `"loci"` key. Real
    # state exists: measured, this machine holds 24 KB with five agents in it. Renaming the concept must not orphan
    # them -- "my agents are gone" is the one outcome a rename cannot be forgiven for.
    #
    # So the reader is deliberately DOUBLE-SHAPED rather than version-gated:
    #
    #   * it looks for `loci.json`, and falls back to `loci.json` when the new name does not exist yet;
    #   * it accepts `"loci"` or `"loci"` as the list key, so it does not care which wrote the file;
    #   * it reads the legacy file WITHOUT renaming or deleting it. The old file stays exactly as it was until the
    #     first save, which writes the new name. That ordering matters: renaming on read would mean a crash between
    #     the rename and the first successful save leaves neither file intact.
    #
    # The fallback is permanent rather than a one-release shim. It costs one `is_file()` call, and it means a user
    # who downgrades, or restores an old backup, is not silently handed an empty registry.

    @property
    def legacy_path(self) -> Path:
        """Where this registry lived before the rename, or `self.path` if there is nothing to fall back to."""
        if self.explicit_path:
            return self.path
        return self.path.with_name(LEGACY_LOCI_FILENAME)

    def _source_path(self) -> Path | None:
        """The file to read: the new one if it exists, else the legacy one, else None."""
        if self.path.is_file():
            return self.path
        legacy = self.legacy_path
        if legacy != self.path and legacy.is_file():
            return legacy
        return None

    def _read_locked(self) -> dict[str, Locus]:
        """Parse the file into a fresh dict. Caller holds the lock."""
        parsed: dict[str, Locus] = {}
        source = self._source_path()
        if source is None:
            return parsed
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt registry must not take the whole harness down with it. Rename it aside so
            # the user can recover it, and carry on with an empty set.
            logger.warning("Could not read %s (%s); starting with no loci.", source, exc)
            try:
                source.replace(source.with_suffix(".json.corrupt"))
            except OSError:
                pass
            return parsed

        # Both key spellings, NEW first, then the legacy one.
        #
        # Measured defect, and the second half of the same bug: the bulk rename rewrote the string literal in the
        # fallback branch too, producing
        #
        #     entries = raw.get("loci") if isinstance(raw.get("loci"), list) else raw.get("loci")
        #
        # -- both branches asking for the new key, so a legacy file yielded nothing. Combined with the rewritten
        # `LEGACY_LOCI_KEY`, the registry silently loaded 0 loci instead of 5. Two identical branches are exactly
        # what a reader skims past, which is why the key now comes from the named constant and the loop makes the
        # two cases visibly distinct.
        entries: object = None
        for key in ("loci", LEGACY_LOCI_KEY):
            candidate = raw.get(key)
            if isinstance(candidate, list):
                entries = candidate
                break
        if not isinstance(entries, list):
            logger.warning("%s has no readable locus list; leaving it untouched.", source)
            return parsed
        if source != self.path:
            logger.info(
                "Read %d loci from the pre-rename file %s; they will be written to %s on the next change.",
                len(entries), source.name, self.path.name,
            )

        for entry in entries:
            try:
                locus = Locus.from_dict(entry)
            except Exception:  # a single malformed locus must not lose the others
                logger.warning("Skipping an unreadable locus entry.")
                continue
            parsed[locus.id] = locus
        return parsed

    def load(self) -> None:
        with self._lock:
            self._loci = self._read_locked()

    def _reload_locked(self) -> None:
        """Re-read the file before a mutation, so a write cannot discard another process's work.

        Two long-lived Myriaxon processes share one ``loci.json`` -- the terminal and the
        dashboard are routinely open at the same time. Each holds its own registry, loaded once
        at startup, so without this the second process to save silently reverts every locus the
        first one created or completed. Re-reading immediately before a mutation narrows the
        window to the duration of the write itself; it is not free, and a file lock would be the
        fully correct answer, but silently losing a completed objective is the failure that
        actually happens in normal use.
        """
        self._loci = self._read_locked()

    def save(self) -> None:
        """Write the current set. Callers that mutate must reload first -- see _reload_locked."""
        with self._lock:
            payload = {"version": LOCI_PAYLOAD_VERSION, "loci": [entry.to_dict() for entry in self._loci.values()]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, json.dumps(payload, indent=2))
        except OSError as exc:
            logger.warning("Could not save loci: %s", exc)

    # ---- access ------------------------------------------------------------------------
    def all(self) -> list[Locus]:
        with self._lock:
            return list(self._loci.values())

    def get(self, ref: str) -> Locus | None:
        """Resolve by id, or by name case-insensitively. Names are what people type."""
        ref = (ref or "").strip()
        if not ref:
            return None
        with self._lock:
            if ref in self._loci:
                return self._loci[ref]
            lowered = ref.lower()
            for entry in self._loci.values():
                if entry.name.lower() == lowered:
                    return entry
            matches = [entry for entry in self._loci.values() if lowered in entry.name.lower()]
            return matches[0] if len(matches) == 1 else None

    def due(self, now: float | None = None) -> list[Locus]:
        return [d for d in self.all() if d.is_due(now)]

    def headless(self) -> list[Locus]:
        """Every Locus that should be working while nobody is watching.

        The prompt names supervised deployment as the intended way to make a Locus continuous, which left the
        loop itself passive: a due Locus fired only when the user happened to press Enter. This is the
        selection the REPL needs to stop waiting -- enabled, proactive, and with work it is allowed to do.
        """
        return [d for d in self.all() if d.enabled and d.proactive and d.runnable_goals()]

    def next_wakeup_seconds(self, now: float | None = None, idle_cap: float = 30.0) -> float:
        """How long the caller may sleep before something needs attention.

        Returns 0.0 when something is due *right now*, so a caller that sleeps for this long and re-checks
        never misses a wake-up by more than the resolution it chose.

        Capped rather than returning a huge number, and capped at a *bounded* value by default: a caller
        parked on a 900-second sleep would not notice a Locus created or enabled in the meantime, so an idle
        cap keeps the check responsive without polling hard. The cap is the caller's to choose because only
        the caller knows what else might change.
        """
        now = time.time() if now is None else now
        candidates = self.headless()
        if not candidates:
            return idle_cap
        soonest = min(d.seconds_until_due(now) for d in candidates)
        if soonest <= 0:
            return 0.0
        return float(min(soonest, idle_cap))

    def next_due(self, now: float | None = None) -> tuple[Locus, int] | None:
        """The soonest-due Locus and how many seconds away it is.

        This is the deployment hook: a supervisor (a scheduled task, a container, a cron entry)
        can call this to decide whether to wake Myriaxon at all, which is how a Locus becomes
        continuous without the harness itself owning a background daemon.
        """
        candidates = [d for d in self.all() if d.enabled and d.proactive and d.runnable_goals()]
        if not candidates:
            return None
        soonest = min(candidates, key=lambda d: d.seconds_until_due(now))
        return soonest, soonest.seconds_until_due(now)

    # ---- mutation ----------------------------------------------------------------------
    def create(
        self,
        name: str,
        *,
        role: str = "generalist",
        instructions: str = "",
        goals: list[str] | None = None,
        proactive: bool = False,
        interval_seconds: int = DEFAULT_PROACTIVE_INTERVAL_SECONDS,
        provider: str = "",
        model: str = "",
        workspace: str = "",
        max_steps_per_run: int = DEFAULT_MAX_STEPS_PER_RUN,
    ) -> Locus:
        with self._lock:
            self._reload_locked()
            existing = self.get(name)
            if existing is not None:
                raise ValueError(f"A locus named {existing.name!r} already exists.")
            locus = Locus(
                id=uuid.uuid4().hex[:8],
                name=name.strip(),
                role=role.strip() or "generalist",
                instructions=instructions.strip(),
                proactive=proactive,
                interval_seconds=max(30, int(interval_seconds)),
                # Clamped here as well as in step_budget(): a caller that passes a nonsensical
                # value gets a sane locus on disk, not one that only behaves once it is read back.
                max_steps_per_run=max(
                    DEFAULT_MAX_STEPS_PER_RUN,
                    min(int(max_steps_per_run or DEFAULT_MAX_STEPS_PER_RUN), MAX_STEPS_PER_RUN_CEILING),
                ),
                provider=provider,
                model=model,
                workspace=workspace,
            )
            for title in goals or []:
                if title.strip():
                    locus.add_goal(title.strip())
            locus.log("created", f"locus created with role {locus.role}")
            self._loci[locus.id] = locus
        self.save()
        return locus

    def delete(self, ref: str) -> bool:
        with self._lock:
            self._reload_locked()
            locus = self.get(ref)
            if locus is None:
                return False
            del self._loci[locus.id]
        self.save()
        return True

    def touch(self, locus: Locus) -> None:
        """Persist a locus the caller has mutated, without discarding that mutation.

        Reload-then-save is wrong here: the caller holds `locus` and has been changing it, so
        replacing the in-memory set with a fresh read would write a *different* object and the
        change would vanish. Instead the mutated locus is re-inserted over whatever the reload
        produced, which is the last-writer-wins resolution this needs -- and it is written down
        because the alternative (silently losing the turn that just happened) is far worse than
        a concurrent edit from another process being overwritten.
        """
        locus.last_run_at = time.time()
        locus.updated_at = time.time()
        self.persist(locus)

    def persist(self, locus: Locus) -> None:
        """Write one locus's current state, keeping every other locus that exists on disk.

        Used by the goal tools, which mutate a `Locus` they obtained from a previous read. The
        reload is what makes this safe against a second process: without it, saving would write
        back the whole set as this process last saw it and revert every locus the other process
        created or completed in the meantime.
        """
        with self._lock:
            self._reload_locked()
            self._loci[locus.id] = locus
        self.save()

    def reload(self) -> None:
        """Re-read from disk. Public so a long-lived surface (the dashboard) can refresh on
        demand rather than showing whatever it loaded at startup."""
        self.load()


# ---------------------------------------------------------------------------------------
# Process-wide registry
# ---------------------------------------------------------------------------------------
# One instance per process: the CLI and the dashboard both load it, and two registries writing
# the same file would silently clobber each other's goal updates.
_registry: LocusRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> LocusRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = LocusRegistry()
        return _registry


def reset_registry(path: Path | None = None) -> LocusRegistry:
    """Point the process at a different registry. For tests, and for the dashboard's project
    switcher when it needs to re-read state from disk."""
    global _registry
    with _registry_lock:
        _registry = LocusRegistry(path)
        return _registry


# ---------------------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------------------
LOCUS_LIST_TOOL_DEF = {
    "name": "locus_list",
    "description": (
        "List the persistent Myriaxon agents (loci) on this machine, with their role, status and "
        "open objectives. Use this before creating a locus, to avoid duplicating one that already "
        "exists. Read-only."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

LOCUS_CREATE_TOOL_DEF = {
    "name": "locus_create",
    "description": (
        "Create a persistent agent (a locus) that keeps its identity, instructions and objectives "
        "across sessions. Use this when the user describes recurring or long-running "
        "responsibility for something ('keep the dependencies current', 'watch the release "
        "notes'), not for a one-off task -- for a single task use `task` instead. Give it "
        "standing instructions and either at least one concrete objective, or a `watchlist` for "
        "monitoring work that has nothing to build.\n\n"
        "To make it check a CONDITION rather than run on a timer, pass `condition`: it is evaluated "
        "before each wake-up, so a quiet night costs nothing instead of one paid turn per interval."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short name, unique on this machine."},
            "role": {"type": "string", "description": "What kind of worker it is, e.g. 'reviewer'."},
            "instructions": {
                "type": "string",
                "description": "Standing instructions: standards, constraints, what to never do.",
            },
            "goals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more concrete objectives for it to work toward.",
            },
            "watchlist": {
                "type": "string",
                "description": (
                    "What to check on every unprompted wake-up, one item per line. Use this for "
                    "monitoring work that has nothing to build -- 'the health file exists', 'the "
                    "queue is under 100'. Without a watchlist a monitor invents work from whatever "
                    "is in its context."
                ),
            },
            "condition": {
                "type": "object",
                "description": (
                    "When to wake, instead of on every interval. Evaluated before the turn starts, so "
                    "a tick where it does not hold costs nothing."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["command", "file_newer_than", "file_missing", "path_exists", "always",
                                 "changed"],
                        "description": (
                            "command: exit 0 means wake. file_newer_than: wake when the path changed "
                            "since the last run. file_missing / path_exists: presence checks. "
                            "changed: wake when an `observe` command's OUTPUT differs from last time -- "
                            "use this for 'tell me when this changes' rather than 'while this is true'."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "What this checks, in words. Shown to the agent when it wakes.",
                    },
                    "command": {"type": "string", "description": "For kind 'command'."},
                    "observe": {
                        "type": "string",
                        "description": (
                            "For kind 'changed': the command whose output is the watched value. Keep it "
                            "short -- print a status word, a count or a hash, not a whole log. The output "
                            "is what gets compared, and it is capped at 16 KB."
                        ),
                    },
                    "path": {"type": "string", "description": "For the path-based kinds."},
                    "once": {
                        "type": "boolean",
                        "description": (
                            "Disable the locus after the first run this condition fires. A FAILED run does "
                            "not count, so a one-shot watch whose attempt failed stays armed."
                        ),
                    },
                    "min_seconds_between_runs": {
                        "type": "number",
                        "description": (
                            "Floor on how often this condition may cause a run, so a flapping "
                            "condition cannot drive an unbounded loop (default 60)."
                        ),
                    },
                },
                "required": ["kind", "description"],
            },
            "proactive": {
                "type": "boolean",
                "description": "Whether it should advance its objectives on its own, unprompted.",
            },
            "autonomy": {
                "type": "string",
                "enum": list(AUTONOMY_MODES),
                "description": (
                    "How much of its own direction the locus has. 'assisted' (the default) works only "
                    "the objectives you give it. 'self_directed' may also decide and record its own "
                    "objectives and gets a larger step budget per run. Either way it acts only inside "
                    "its own workspace folder -- self-directed is not unrestricted."
                ),
            },
            "max_steps_per_run": {
                "type": "integer",
                "description": (
                    "How many model turns one run may take. Omit to let the mode decide: 1 for "
                    "assisted, more for self-directed. An explicit value wins either way."
                ),
            },
            "interval_seconds": {
                "type": "integer",
                "description": (
                    "How often a proactive locus wakes up (default 900, minimum 30). With a condition, "
                    "this is a ceiling: the condition is only evaluated once the interval has elapsed."
                ),
            },
        },
        "required": ["name"],
    },
}


LOCUS_SCRATCH_TOOL_DEF = {
    "name": "locus_watchlist",
    "description": (
        "Read or update a locus's standing watchlist -- what it checks on every unprompted wake-up. "
        "Use `set` to replace it, `add` to append one item, or neither to read it.\n"
        "Keep it short: it is sent with every wake-up, so a long watchlist is a per-tick cost and stops "
        "being a checklist. Update it rather than letting it grow -- a monitor that checks the same "
        "resolved item forever is spending turns to learn nothing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "locus": {"type": "string", "description": "Locus name or id."},
            "set": {"type": "string", "description": "Replace the whole watchlist."},
            "add": {"type": "string", "description": "Append one item."},
            "clear": {"type": "boolean", "description": "Empty the watchlist."},
        },
        "required": ["locus"],
    },
}


HEARTBEAT_RESPOND_TOOL_DEF = {
    "name": "heartbeat_respond",
    "description": (
        "Report the outcome of a periodic check. Use this on a wake-up that was not a user message.\n"
        "- `notify=false` with text: nothing needs attention, but record the note for the next turn.\n"
        "- `notify=true` with text: something needs attention; the text is delivered.\n"
        "If you simply have nothing to say, reply NO_REPLY instead of calling this."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "notify": {
                "type": "boolean",
                "description": "True to raise an alert, false to stay silent but remember the note.",
            },
            "text": {
                "type": "string",
                "description": "The alert, or the note to remember. Required when notify is true.",
            },
        },
        "required": ["notify"],
    },
}

LOCUS_GOAL_TOOL_DEF = {
    "name": "locus_goal_update",
    "description": (
        "Add an objective to a locus, or move an existing one between pending/active/blocked/done. "
        "Use it to report that your own objective is finished, or that you are blocked and need a "
        "decision. Marking a goal done is what stops a proactive locus from redoing the work."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "locus": {"type": "string", "description": "Locus name or id."},
            "goal": {"type": "string", "description": "Goal id or title. Omit when adding one."},
            "add": {"type": "string", "description": "New objective to add."},
            "status": {"type": "string", "enum": list(GOAL_STATES)},
            "note": {"type": "string", "description": "What you did, or what you are blocked on."},
        },
        "required": ["locus"],
    },
}

LOCUS_RUN_TOOL_DEF = {
    "name": "locus_run",
    "description": (
        "Hand a task to a persistent locus and wait for its answer. Unlike `task`, the locus keeps "
        "its identity, instructions, objectives and history, so it can pick up where it left off. "
        "Use this for work that belongs to a locus's standing responsibility."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "locus": {"type": "string", "description": "Locus name or id."},
            "message": {"type": "string", "description": "What to ask it to do now."},
        },
        "required": ["locus", "message"],
    },
}


# ---------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------
def format_locus(locus: Locus, *, verbose: bool = False) -> str:
    from . import brand

    state = "proactive" if locus.proactive else "on demand"
    if not locus.enabled:
        state = "disabled"
    lines = [
        f"{brand.MARK_GLYPH_SMALL} {locus.name}  [{locus.id}]  {locus.role}  ({state})",
    ]
    if locus.model or locus.provider:
        lines.append(f"    runs on {locus.provider or 'default'}/{locus.model or 'default'}")
    if locus.proactive:
        lines.append(f"    wakes every {locus.interval_seconds}s; next in {locus.seconds_until_due()}s")

    # The condition is shown because without it a monitor is indistinguishable from a broken one.
    #
    # The failure this closes: a condition whose command does not exist exits non-zero, which is byte-identical to
    # "the condition is not met". Such a watcher is PERMANENTLY and SILENTLY quiet, and before this block the
    # status line said only "wakes every 900s" -- exactly what a healthy watcher says. The defect concealed itself.
    # So the description, the last verdict, and the time of that verdict are all rendered, and an ERROR verdict is
    # loud rather than one word among many.
    if locus.condition:
        condition = locus.condition
        kind = str(condition.get("kind") or "")
        description = str(condition.get("description") or kind or "condition")
        # `observe` is included: for a `changed` watcher it is the command that produces the watched value, and
        # omitting it left the status line saying "wakes on a condition: CI status changed" with no indication of
        # what was being watched.
        target = str(condition.get("command") or condition.get("observe") or condition.get("path") or "")
        lines.append(f"    wakes on a condition: {description}" + (f" [{kind}]" if kind else ""))
        if target:
            lines.append(f"      checks: {target}")
        verdict = (locus.last_condition_state or "").strip()
        if not verdict:
            lines.append("      last check: not evaluated yet")
        elif verdict.upper().startswith("ERROR"):
            # Loud on purpose: this is the state that means the watcher may be blind.
            lines.append(f"      !! last check FAILED TO RUN: {verdict[6:].strip() or 'see the activity log'}")
            lines.append("      !! a check that cannot run is not the same as a check that passed")
        else:
            when = ""
            if locus.condition_checked_at:
                when = f" ({_relative_age(locus.condition_checked_at)})"
            lines.append(f"      last check: {verdict}{when}")
        if condition.get("once"):
            lines.append("      fires once, then disables itself")
        if condition.get("min_seconds_between_runs"):
            lines.append(f"      at most once per {condition['min_seconds_between_runs']:.0f}s")

    if locus.scratch.strip():
        items = [l for l in locus.scratch.strip().splitlines() if l.strip()]
        lines.append(f"    watchlist: {len(items)} item(s)")
        for item in items[:6]:
            lines.append(f"      {item.strip()}")
        if len(items) > 6:
            lines.append(f"      ... and {len(items) - 6} more")
        if locus.last_heartbeat_verdict:
            lines.append(f"    last check verdict: {locus.last_heartbeat_verdict}")
        if locus.heartbeat_note:
            lines.append(f"    noting for next turn: {locus.heartbeat_note[:160]}")

    if locus.is_running():
        # Read from the lease as well as the flag, so a run started by the other Myriaxon process
        # is visible here rather than only in the dashboard.
        lines.append("    running now")
    elif locus.step_budget() > 1:
        lines.append(f"    may take up to {locus.step_budget()} steps per run")

    open_goals = locus.open_goals()
    done = [g for g in locus.goals if g.status == GOAL_DONE]
    if open_goals:
        lines.append(f"    {len(open_goals)} open objective(s):")
        for goal in open_goals:
            lines.append(
                f"      [{goal.id}] {goal.status:<8} {goal.title}  "
                f"(attempt {goal.attempts}/{MAX_GOAL_ATTEMPTS})"
            )
            if goal.last_error:
                lines.append(f"          last error: {goal.last_error}")
    else:
        lines.append("    no open objectives")
    if done:
        lines.append(f"    {len(done)} completed")
    if locus.last_error:
        lines.append(f"    last failure: {locus.last_error}")

    if verbose:
        # Preflight is verbose-only on purpose: it writes a probe file to prove the workspace is
        # writable, and a plain listing must not create directories as a side effect of looking.
        problems = locus.preflight()
        if problems:
            lines.append("    cannot run usefully right now:")
            for problem in problems:
                lines.append(f"      - {problem}")
        if locus.instructions:
            lines.append("    standing instructions:")
            for line in locus.instructions.strip().splitlines():
                lines.append(f"      {line}")
        lines.append(f"    workspace: {locus.workspace_path()}")
        if locus.activity:
            lines.append("    recent activity:")
            for entry in locus.activity[-10:]:
                lines.append(f"      {entry.render()}")
    return "\n".join(lines)


def _relative_age(when: float) -> str:
    """A short human age, for a status line.

    Deliberately coarse. The interesting question in `loci --status` is "how long since this was checked?", and the
    difference between 61 and 63 seconds is not part of the answer -- a precise figure would invite reading
    meaning into noise. A future timestamp renders as `just now` rather than a negative age, which is what a clock
    adjustment would otherwise produce.
    """
    if not when:
        return "never"
    delta = time.time() - when
    if delta < 0:
        return "just now"
    if delta < 90:
        return f"{int(delta)}s ago"
    if delta < 5400:
        return f"{int(delta // 60)}min ago"
    if delta < 172800:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def format_registry(loci: list[Locus]) -> str:
    if not loci:
        return (
            "No loci yet. A locus is a persistent agent: give it a role, standing instructions and "
            "objectives, and it keeps them across sessions.\n"
            "Create one with:  /loci create <name> --role <role> --goal \"<objective>\""
        )
    blocks = [format_locus(locus) for locus in loci]
    total_open = sum(len(d.open_goals()) for d in loci)
    header = f"{len(loci)} locus(s), {total_open} open objective(s)"
    return header + "\n\n" + "\n\n".join(blocks)


# ---------------------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------------------
def execute_locus_list(tool_input: dict) -> tuple[str, bool]:
    registry = get_registry()
    registry.load()  # show what is actually on disk, including another process's changes
    return format_registry(registry.all()), False


def _goal_titles(raw) -> list[str]:
    """Objectives as plain titles. A model that sends objects (`{"title": ...}`) plainly means the title."""
    titles: list[str] = []
    for item in raw or []:
        if isinstance(item, dict):
            item = item.get("title") or item.get("goal") or item.get("objective") or item.get("text") or item.get("description") or ""
        text = str(item).strip()
        if text:
            titles.append(text)
    return titles


def execute_locus_create(tool_input: dict) -> tuple[str, bool]:
    registry = get_registry()

    # Validate the condition BEFORE creating anything. A locus whose condition cannot be evaluated fails open --
    # it wakes every tick -- so a typo would turn a monitor into a per-interval cost rather than a quiet one.
    condition = tool_input.get("condition")
    if condition:
        from . import conditions as conditions_module

        try:
            problem = conditions_module.Condition(**condition).validate()
        except TypeError as exc:  # a key the condition does not have
            return f"The condition is not usable: {exc}", True
        if problem:
            return f"The condition is not usable: {problem}", True

    watchlist = str(tool_input.get("watchlist") or "").strip()
    if watchlist:
        from . import heartbeat

        ok, message = heartbeat.Scratch().set(watchlist)
        if not ok:
            return message, True

    goals = _goal_titles(tool_input.get("goals"))
    # Warn rather than refuse. Creating an empty locus and then adding objectives is a real flow -- `locus_goal_update`
    # exists for exactly that -- and the first version of this check refused it, which broke three existing tests
    # that do precisely that. The honest outcome is a locus that exists and does not run until it has work, with the
    # reason stated so it does not look broken.
    idle_note = ""
    if not goals and not watchlist and not condition:
        idle_note = (
            "\n\nNote: this locus has no objectives, no watchlist and no condition, so it will never run on its "
            "own. Give it work with locus_goal_update, a watchlist with locus_watchlist, or a condition to wake on."
        )

    try:
        locus = registry.create(
            tool_input["name"],
            role=tool_input.get("role", "generalist"),
            instructions=tool_input.get("instructions", ""),
            goals=goals,
            proactive=bool(tool_input.get("proactive", False)),
            interval_seconds=int(tool_input.get("interval_seconds") or DEFAULT_PROACTIVE_INTERVAL_SECONDS),
        )
    except ValueError as exc:
        return str(exc), True

    # Validated and applied AFTER creation rather than passed through `create`, because `create` has a
    # narrow signature and rejecting a bad mode must not leave a half-made locus behind. A refused
    # value here returns before anything is persisted, so the caller either gets a locus with the mode
    # it asked for or no locus at all.
    wanted_mode = str(tool_input.get("autonomy") or "").strip().lower()
    if wanted_mode:
        if wanted_mode not in AUTONOMY_MODES:
            registry.delete(locus.id)
            return (f"autonomy must be one of {', '.join(AUTONOMY_MODES)}, not {wanted_mode!r}. "
                    f"Nothing was created."), True
        locus.autonomy = wanted_mode
    if tool_input.get("max_steps_per_run"):
        try:
            locus.max_steps_per_run = max(1, min(int(tool_input["max_steps_per_run"]),
                                                 MAX_STEPS_PER_RUN_CEILING))
        except (TypeError, ValueError):
            registry.delete(locus.id)
            return "max_steps_per_run must be a whole number. Nothing was created.", True

    if condition:
        locus.condition = dict(condition)
    if watchlist:
        locus.scratch = watchlist
    # Persisted when ANY of these changed, not only when a condition or watchlist was set: the mode and
    # the budget above were written to the in-memory locus, and a locus that reports self-directed
    # until the process restarts is worse than one that never offered the setting.
    if condition or watchlist or wanted_mode or tool_input.get("max_steps_per_run"):
        registry.persist(locus)
    return f"Created.\n\n{format_locus(locus, verbose=True)}{idle_note}", False


def execute_locus_watchlist(tool_input: dict) -> tuple[str, bool]:
    """Read or update a locus's standing watchlist."""
    from . import heartbeat

    registry = get_registry()
    registry.load()
    locus = registry.get(tool_input["locus"])
    if locus is None:
        return f"No locus named {tool_input['locus']!r}. Use locus_list to see them.", True

    scratch = heartbeat.Scratch(notes=locus.scratch)

    if tool_input.get("clear"):
        locus.scratch = ""
        registry.persist(locus)
        return f"Cleared {locus.name}'s watchlist. It now reports only on its objectives.", False

    if tool_input.get("set") is not None:
        ok, message = scratch.set(str(tool_input["set"]))
        if not ok:
            return message, True
        locus.scratch = scratch.notes
        registry.persist(locus)
        return f"{locus.name}'s watchlist replaced.\n\n{locus.scratch or '(empty)'}", False

    if tool_input.get("add"):
        ok, message = scratch.append(str(tool_input["add"]))
        if not ok:
            return message, True
        locus.scratch = scratch.notes
        registry.persist(locus)
        return f"{locus.name}'s watchlist updated.\n\n{locus.scratch}", False

    if not locus.scratch.strip():
        return (
            f"{locus.name} has no watchlist. Without one it invents work from whatever is in its context on "
            "each wake-up, so add the things worth checking: pass `set` or `add`.",
            False,
        )
    return f"{locus.name}'s watchlist ({len(locus.scratch)} chars):\n\n{locus.scratch}", False


def execute_locus_goal_update(tool_input: dict, ctx=None) -> tuple[str, bool]:
    """Update a Locus's goals. A transition to `done` needs completion authority.

    `ctx` is the ToolContext, and it is how the turn's provenance reaches the gate. Omitting it resolves to the
    least authoritative source, so an older caller that does not pass one cannot complete a goal -- which is the
    right default for a parameter that was added to close a hole.
    """
    registry = get_registry()
    # Reload first: this handler is typically called from inside a locus's own turn, in a process
    # that may have loaded the registry before another process (the dashboard) changed it. Without
    # the reload, writing the goal update would revert that other process's changes.
    registry.load()
    locus = registry.get(tool_input["locus"])
    if locus is None:
        return f"No locus named {tool_input['locus']!r}. Use locus_list to see them.", True

    if tool_input.get("add"):
        goal = locus.add_goal(tool_input["add"])
        registry.persist(locus)
        return f"Added [{goal.id}] {goal.title} to {locus.name}.", False

    ref = tool_input.get("goal") or ""
    status = tool_input.get("status") or ""
    if not ref or not status:
        return "Provide `goal` and `status`, or `add` a new objective.", True

    # The source of THIS turn, read from the context rather than assumed. A Locus's own wake-up sets
    # `locus_run_source`, so the handler that runs inside a Locus reports its own lack of authority.
    from . import goal_authority

    source = goal_authority.SOURCE_SYSTEM
    if ctx is not None:
        raw = str(getattr(ctx, "locus_run_source", "") or "")
        if raw:
            source = goal_authority.source_of(raw)

    before = locus.find_goal(ref)
    goal = locus.set_goal_status(ref, status, tool_input.get("note", ""), source=source)
    if goal is None:
        # Distinguish "no such goal" from "refused". Reporting a refusal as a missing goal would send the model
        # looking for a typo in a reference that was correct, which is the opposite of actionable.
        if before is not None and status == GOAL_DONE:
            return (
                f"Refused: a {source} turn cannot mark [{before.id}] {before.title} done.\n"
                "Only a direct human instruction in an open session turn, or the goal's own admitted round, may "
                "complete a goal -- the party that did the work does not get to declare it finished.\n"
                "If the objective is met, say so in your reply and let a person confirm it.",
                True,
            )
        return f"No goal matching {ref!r} on {locus.name}.", True
    registry.persist(locus)
    return f"{locus.name}: [{goal.id}] {goal.title} -> {goal.status}", False


__all__ = [
    "Locus", "Goal", "ActivityEntry", "LocusRegistry", "get_registry", "reset_registry",
    "format_locus", "format_registry",
    "execute_locus_list", "execute_locus_create", "execute_locus_goal_update",
    "LOCUS_LIST_TOOL_DEF", "LOCUS_CREATE_TOOL_DEF", "LOCUS_GOAL_TOOL_DEF", "LOCUS_RUN_TOOL_DEF",
    "GOAL_STATES", "GOAL_PENDING", "GOAL_ACTIVE", "GOAL_BLOCKED", "GOAL_DONE",
    "DEFAULT_PROACTIVE_INTERVAL_SECONDS", "LOCI_FILE",
    # Reliability surface: failure classification, bounded retry, run outcomes, the cross-process
    # run lease, and the attempt ceiling. Exported so a caller (the dashboard's run route, the
    # terminal's proactive pass) can enforce the same rules this module enforces internally
    # instead of reimplementing them.
    "MAX_GOAL_ATTEMPTS", "DEFAULT_MAX_STEPS_PER_RUN", "MAX_STEPS_PER_RUN_CEILING",
    "RUN_LEASE_FILENAME", "RUN_LEASE_STALE_SECONDS", "TRANSIENT_BACKOFF_CAP_SECONDS",
    "REFLECTION_CLAUSE",
    "ERROR_TRANSIENT", "ERROR_PERMANENT", "classify_error", "is_transient_error",
    "retry_backoff_seconds", "max_run_attempts",
    "OUTCOME_SUCCESS", "OUTCOME_RECOVERED", "OUTCOME_TRANSIENT", "OUTCOME_EXHAUSTED",
    "OUTCOME_PERMANENT", "RunOutcome", "normalize_outcome", "record_failure", "run_with_retry",
    "RunLease", "RunInProgress", "locus_workspace_dir", "run_lease_path", "read_run_lease",
    "acquire_run_lease", "renew_run_lease", "release_run_lease",
]
