"""A run that reports success must have actually started, and a stale lease must not spam the log.

Both defects were found by driving the real dashboard, and neither had any test. That is the whole reason
they shipped: `tests/` covered the lease as a MECHANISM and never asked the question a CALLER depends on.

  * `run_locus` returned `accepted: True` for a run that could not start, because the lease was consulted
    only inside the worker thread. The caller saw success, the panel showed "working now" forever, and the
    refusal existed only in the locus's own activity log.
  * `_lease_from_path` logged the same dead owner on every poll -- 84 identical lines for 7 dead pids.

THE PID IN A LEASE DECIDES WHAT THE TEST PROVES, and getting that wrong is how the first version of this
file was wrong. A lease whose owner is DEAD is correctly reclaimed: `read_run_lease` returns None and
`acquire_run_lease` takes it over. So poisoning with a dead pid proves nothing about a run being refused.
A lease that should BLOCK must be held by a process that is genuinely alive, and this test process is the
only one guaranteed to be. Both cases are therefore explicit below.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# A pid that cannot exist on a normal machine, used only where the point is an owner that is GONE.
DEAD_PID = 999_999


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("MYRIAXON_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("MYRIAXON_SWARM_DIR", str(tmp_path / "swarm"))
    monkeypatch.setenv("MYRIAXON_NO_SUPERVISOR", "1")
    return tmp_path


def make_locus(name: str = "probe"):
    from myriaxon import loci

    registry = loci.get_registry()
    registry.reload()
    registry.create(name=name, role="engineer", proactive=False, max_steps_per_run=2,
                    goals=["an objective worth running"])
    registry.reload()
    return registry.get(name)


def poison(lease_path: Path, pid: int) -> None:
    """Write a lease held by `pid`. See the module docstring for why the pid is never defaulted."""
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(json.dumps({"pid": pid, "token": "held", "acquired_at": time.time()}),
                          encoding="utf-8")


def app_for(tmp_path):
    from myriaxon.config import Config
    from myriaxon.dashboard.server import DashboardApp

    return DashboardApp(tmp_path, config=Config(api_key="x", base_url="http://127.0.0.1:1",
                                               model="m", provider="openai_compat"))


class TestARefusedRunDoesNotClaimSuccess:
    """The invariant: `accepted: True` must mean the run started.

    These fail on the pre-fix code, where `run_locus` returned success and the refusal went to the activity
    log instead of the caller.
    """

    def test_a_held_lease_is_reported_to_the_caller(self, scratch):
        from myriaxon import loci

        locus = make_locus()
        poison(loci.run_lease_path(locus), os.getpid())   # HELD by a live process

        outcome = app_for(scratch).run_locus(loci.get_registry().get("probe"))

        assert outcome.get("accepted") is False, (
            "a run whose slot is held must not report success -- the caller has nothing to act on. "
            f"Got {outcome.get('accepted')!r} with reason {outcome.get('reason')!r}"
        )
        assert "already" in str(outcome.get("reason", "")).lower(), (
            f"and the reason must say so; got {outcome.get('reason')!r}"
        )

    def test_the_reason_names_the_holder(self, scratch):
        """'Already running' without saying since when or by which pid sends someone hunting the log."""
        from myriaxon import loci

        locus = make_locus("probe2")
        poison(loci.run_lease_path(locus), os.getpid())

        outcome = app_for(scratch).run_locus(loci.get_registry().get("probe2"))
        combined = f"{outcome.get('reason', '')} {outcome.get('holder', '')}"
        assert str(os.getpid()) in combined, (
            f"the holder should be identifiable; got holder={outcome.get('holder')!r} "
            f"reason={outcome.get('reason')!r}"
        )

    def test_a_dead_owner_does_NOT_refuse_a_run(self, scratch):
        """The counterpart, and the one that would be easy to break.

        A lease from a process that is gone must not block anything -- `read_run_lease` returns None for it
        and `acquire_run_lease` reclaims it. Refusing here would turn log spam into a permanent deadlock,
        which is strictly worse than the bug being fixed. This is also the assertion that caught the first
        version of this file poisoning with a dead pid and expecting a refusal.
        """
        from myriaxon import loci

        locus = make_locus("probe3")
        poison(loci.run_lease_path(locus), DEAD_PID)
        loci.get_registry().reload()
        fresh = loci.get_registry().get("probe3")

        assert loci.read_run_lease(fresh) is None, "a lease whose owner is gone is not a holder"
        assert loci.acquire_run_lease(fresh) is not None, "a dead owner must never block the next run"


class TestAStaleLeaseIsAnnouncedOnce:
    """84 identical lines for 7 dead pids is a message nobody reads."""

    def test_many_reads_produce_one_line(self, scratch, caplog):
        from myriaxon import loci

        locus = make_locus("probe4")
        poison(loci.run_lease_path(locus), DEAD_PID)

        with caplog.at_level(logging.INFO, logger=loci.logger.name):
            for _ in range(12):
                loci.read_run_lease(loci.get_registry().get("probe4"))

        lines = [r for r in caplog.records if "Reclaiming the run lease" in r.getMessage()]
        assert len(lines) == 1, (
            f"12 reads should say it once, not {len(lines)} times -- the dashboard polls this per locus"
        )

    def test_a_DIFFERENT_dead_owner_is_still_reported(self, scratch, caplog):
        """Deduplicating by message text alone would hide a new problem behind an old one."""
        from myriaxon import loci

        locus = make_locus("probe5")
        path = loci.run_lease_path(locus)
        poison(path, DEAD_PID)

        with caplog.at_level(logging.INFO, logger=loci.logger.name):
            loci.read_run_lease(loci.get_registry().get("probe5"))
            poison(path, DEAD_PID + 1)
            loci.read_run_lease(loci.get_registry().get("probe5"))

        lines = [r for r in caplog.records if "Reclaiming the run lease" in r.getMessage()]
        assert len(lines) == 2, "two different dead owners are two facts, not one repeated"

    def test_the_file_is_left_for_the_acquirer(self, scratch):
        """A read path must not delete. Two pollers would otherwise race to unlink a lease that a third
        process created between the liveness check and the delete.
        """
        from myriaxon import loci

        locus = make_locus("probe6")
        path = loci.run_lease_path(locus)
        poison(path, DEAD_PID)

        loci.read_run_lease(loci.get_registry().get("probe6"))
        assert path.is_file(), "reading must not remove the lease"
