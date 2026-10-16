"""The contract a caller depends on: a run that says it started, started.

Item 1 of the improvement review was a run that reported `accepted: True` and did nothing, and it shipped
because no test asked the CALLER's question -- `tests/` covered the lease as a mechanism and never asserted
what an API consumer can rely on.

The invariants here are the ones a surface needs, not the ones the implementation happens to expose:

  1. `accepted: True` means the run started. Anything else is a lie the caller cannot detect.
  2. A refusal is VISIBLE -- in the transparency feed, at the DECISIONS layer, where a person looks.
  3. The outcome of the last run is on the record, so "did it work?" is answerable without the log.
  4. A refusal must never be caused by a lease whose owner is gone.

LOCUS NAMES ARE UNIQUE PER TEST, on purpose. `LocusRegistry` is a process-wide singleton and
`tests/conftest.py` already swaps `get_registry` per test, but the registry resolves its file from the
config directory at construction -- and fixture ORDER decides whether that happens before or after this
file's env changes. Naming the locus after the test that needs it removes the dependency on that order
instead of relying on it, which is what made the first version of this file fail with
"A locus named 'probe5' already exists".
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DEAD_PID = 999_999


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("MYRIAXON_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("MYRIAXON_SWARM_DIR", str(tmp_path / "swarm"))
    monkeypatch.setenv("MYRIAXON_NO_SUPERVISOR", "1")
    # The feed is a process-wide singleton. Clearing it stops one test's refusals from satisfying
    # another's assertion -- without this, "a refusal is visible" passes for the wrong reason. There is no
    # public reset, so the buffer is reached directly and the reason is written down here.
    from myriaxon import transparency

    transparency.get()._buffer.clear()
    return tmp_path


def make_locus(name: str | None = None, *, tag: str = ""):
    """Create a locus with a name nothing else in the process can be using."""
    from myriaxon import loci

    name = name or f"probe-{tag or uuid.uuid4().hex[:8]}"
    registry = loci.get_registry()
    registry.reload()
    existing = registry.get(name)
    if existing is not None:
        return existing
    registry.create(name=name, role="engineer", proactive=False, max_steps_per_run=2,
                    goals=["an objective worth running"])
    registry.reload()
    return registry.get(name)


def app_for(tmp_path):
    from myriaxon.config import Config
    from myriaxon.dashboard.server import DashboardApp

    return DashboardApp(tmp_path, config=Config(api_key="x", base_url="http://127.0.0.1:1",
                                               model="m", provider="openai_compat"))


def hold_lease(locus, pid: int) -> None:
    from myriaxon import loci

    path = loci.run_lease_path(locus)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "token": "held", "acquired_at": time.time()}),
                    encoding="utf-8")
    # The running answer is cached for a second; drop it so the test sees the lease it just wrote.
    loci._forget_running(locus.id)


class TestAcceptedMeansStarted:
    def test_a_refused_run_is_not_reported_as_accepted(self, scratch):
        from myriaxon import loci

        locus = make_locus(tag="accepted")
        hold_lease(locus, os.getpid())          # HELD by a live process

        outcome = app_for(scratch).run_locus(loci.get_registry().get(locus.name))
        assert outcome.get("accepted") is False, (
            "the caller must not be told a run started when it did not"
        )

    def test_the_refusal_names_the_gate(self, scratch):
        """The reason must be actionable: which locus, held by whom."""
        from myriaxon import loci

        locus = make_locus(tag="named")
        hold_lease(locus, os.getpid())
        outcome = app_for(scratch).run_locus(loci.get_registry().get(locus.name))

        reason = str(outcome.get("reason", ""))
        assert locus.name in reason, f"the reason should name the locus; got {reason!r}"
        assert str(os.getpid()) in reason or str(os.getpid()) in str(outcome.get("holder", "")), (
            f"and identify the holder; got {reason!r}"
        )


class TestARefusalIsVisible:
    """The refusal used to exist only in the locus's own activity log, which is not where a person looks."""

    def test_a_refusal_reaches_the_transparency_feed(self, scratch):
        from myriaxon import loci, transparency

        locus = make_locus(tag="feed")
        hold_lease(locus, os.getpid())
        app_for(scratch).run_locus(loci.get_registry().get(locus.name))

        events = transparency.get().recent(limit=50)
        refusals = [e for e in events if e.layer == transparency.DECISIONS and e.kind == "refused"]
        assert refusals, (
            "a refused run is exactly what the DECISIONS layer is for "
            f"(described as {transparency.LAYER_DESCRIPTIONS.get(transparency.DECISIONS)!r}); "
            f"got layers {sorted({e.layer for e in events})}"
        )
        assert locus.name in refusals[0].summary

    def test_the_refusal_records_which_gate(self, scratch):
        """'refused' without a gate is a fact with no address to fix."""
        from myriaxon import loci, transparency

        locus = make_locus(tag="gate")
        hold_lease(locus, os.getpid())
        app_for(scratch).run_locus(loci.get_registry().get(locus.name))

        refusals = [e for e in transparency.get().recent(limit=50)
                    if e.layer == transparency.DECISIONS and e.kind == "refused"]
        assert refusals and refusals[0].detail.get("gate") == "locus-run"


class TestTheLastOutcomeIsRecorded:
    def test_end_run_records_what_happened(self, scratch):
        from myriaxon import loci

        locus = make_locus(tag="outcome")
        locus.end_run(loci.RunOutcome(ok=True, kind=loci.OUTCOME_SUCCESS, attempts=1))

        assert locus.last_outcome, "a finished run must leave an answer to 'did it work?'"
        assert locus.last_outcome["ok"] is True
        assert locus.last_outcome["summary"], "and a sentence a surface can render"
        assert locus.last_outcome["at"] > 0, "and when, so a panel can say '12s ago'"

    def test_a_failed_run_records_the_error(self, scratch):
        from myriaxon import loci

        locus = make_locus(tag="failed")
        locus.end_run(loci.RunOutcome(ok=False, kind="error", attempts=2, error="the provider refused"))

        assert locus.last_outcome["ok"] is False
        assert "provider refused" in locus.last_outcome["error"]
        assert locus.last_outcome["attempts"] == 2

    def test_the_outcome_is_served_to_the_panel(self, scratch):
        """A field the server does not serialise is invisible no matter how well it is recorded.

        The locus is fetched through `get_registry()` immediately before `end_run`, because the registry is
        a singleton swapped per test (see conftest): mutating an instance obtained earlier can mutate an
        object the payload builder will never look at, and the assertion would then fail for a reason that
        has nothing to do with serialisation.
        """
        from myriaxon import loci

        created = make_locus(tag="served")
        app = app_for(scratch)
        target = loci.get_registry().get(created.name)
        target.end_run(loci.RunOutcome(ok=True, attempts=1))

        payload = app._loci_payload(lambda name: ([], ""), None)
        rendered = next((l for l in payload["loci"] if l["name"] == created.name), None)
        assert rendered is not None, "the locus should be in the payload"
        assert rendered.get("last_outcome"), "the panel record must carry the outcome"
        assert rendered["last_outcome"]["ok"] is True
        assert rendered["last_outcome"]["summary"], "and a sentence the card can render"

    def test_a_newer_run_replaces_the_older_answer(self, scratch):
        """A stale outcome must not be presented as current while a newer run has finished."""
        from myriaxon import loci

        locus = make_locus(tag="newer")
        locus.end_run(loci.RunOutcome(ok=True, attempts=1))
        first_at = locus.last_outcome["at"]
        time.sleep(0.02)
        locus.end_run(loci.RunOutcome(ok=False, kind="error", error="a later run failed"))
        assert locus.last_outcome["at"] > first_at, "the newer run must replace the older answer"
        assert locus.last_outcome["ok"] is False


class TestADeadOwnerNeverRefuses:
    """The counterpart to item 1's fix, and the one that would turn a fix into a deadlock."""

    def test_a_dead_owner_does_not_block_a_run(self, scratch):
        from myriaxon import loci

        locus = make_locus(tag="deadowner")
        hold_lease(locus, DEAD_PID)
        ok, reason, holder = loci.get_registry().get(locus.name).may_run()

        assert ok is True, f"a lease whose owner is gone is not a holder; got {reason!r}"
        assert holder is None

    def test_may_run_agrees_with_the_lease(self, scratch):
        """One decision: `may_run` must say exactly what `acquire_run_lease` will do."""
        from myriaxon import loci

        locus = make_locus(tag="agrees")
        ok, _, _ = loci.get_registry().get(locus.name).may_run()
        assert ok is True
        assert loci.acquire_run_lease(loci.get_registry().get(locus.name)) is not None

        ok2, _reason2, holder2 = loci.get_registry().get(locus.name).may_run()
        assert ok2 is False and holder2 is not None, "after acquiring, may_run must refuse"


class TestTheRunningCacheIsHonest:
    """The cache exists so a panel stops re-reading the lease per locus per poll. A cache that outlives the
    fact it caches is how a panel shows 'working now' for a run that has finished."""

    def test_acquiring_invalidates_the_cache(self, scratch):
        from myriaxon import loci

        locus = make_locus(tag="cache")
        target = loci.get_registry().get(locus.name)
        assert target.is_running() is False            # fills the cache with False
        loci.acquire_run_lease(target)
        loci._forget_running(target.id)                # what begin_run does
        assert loci.get_registry().get(locus.name).is_running() is True

    def test_an_explicit_now_is_never_cached(self, scratch):
        """A caller asking a hypothetical must get a real answer, which is what keeps expiry testable."""
        from myriaxon import loci

        locus = make_locus(tag="now")
        target = loci.get_registry().get(locus.name)
        target.is_running()                            # cache False
        far_future = time.time() + loci.RUN_LEASE_STALE_SECONDS + 60
        assert target.is_running(now=far_future) is False
