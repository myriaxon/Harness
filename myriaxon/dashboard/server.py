"""HTTP server for the Myriaxon dashboard.

Standard library only: `http.server.ThreadingHTTPServer` plus server-sent events. No web framework,
no build step, no npm -- the whole UI is one HTML file served from memory, and every endpoint returns
JSON or an SSE stream.

Design notes:
  * ThreadingHTTPServer because an SSE stream occupies its thread for the length of a turn; a
    single-threaded server would freeze the UI while the agent worked.
  * Uploads are restricted to the session workspace. A browser page that can read any path on the
    machine is a real risk even locally, so paths are resolved and checked to stay inside the root.
  * Every handler is wrapped so an exception returns JSON with a message rather than killing the
    connection silently.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import posixpath
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .session import SessionManager
from .settings import SettingsStore
from .endpoints import CustomEndpointStore
from .paths import UploadStore, is_writable
from .policy import PermissionRules
from ..plugins import plugin_dirs as _plugin_dirs
from .. import git_view as from_git
from ..messaging import (
    MessagingClient,
    MessagingError,
    MessagingNotifier,
    format_turn_summary,
    is_allowed,
    load_messaging_config,
    parse_inbound,
    save_messaging_config,
)
from ..constants import ATTACHMENT_SIZE_CAP_BYTES, MESSAGING_FILE
from .ui import INDEX_HTML
from . import commands as commands_mod

# Upload cap. Matches the CLI's attachment cap so the same file works in both -- it used to
# be 12 MB while the terminal allowed 32 MB, so a 20 MB file was accepted in one front end and
# refused with a 413 in the other, and the comment claimed they matched.
MAX_UPLOAD_BYTES = ATTACHMENT_SIZE_CAP_BYTES


def _secret_matches(supplied: str, expected: str) -> bool:
    """Whether a supplied shared secret matches, in CONSTANT TIME.

    The check was `supplied != config.secret`, which compares byte by byte and returns as soon as two differ.
    That leaks the secret's PREFIX through response timing: an attacker who can measure the round trip learns
    how many leading characters were right, and recovers the value one character at a time instead of guessing
    the whole thing.

    Whether this endpoint is network-reachable decides how much that matters, and the honest position is that
    it should not depend on that: the webhook is the one path designed to accept a request from outside, the
    comparison costs nothing to make safe, and `hmac.compare_digest` is the standard tool for it.

    Both sides are encoded to bytes first, because `compare_digest` refuses `str` containing non-ASCII and
    would otherwise raise inside a request handler -- turning a rejected secret into a 500.
    """
    try:
        return hmac.compare_digest(str(supplied or "").encode("utf-8"),
                                   str(expected or "").encode("utf-8"))
    except (TypeError, ValueError):
        return False


class DashboardApp:
    """Holds the state the handlers need. One instance per server."""

    def __init__(self, workspace: Path, *, config: Any, mode: str = "auto_edit") -> None:
        self.workspace = workspace.resolve()
        self.config = config
        self.default_mode = mode

        from ..constants import CONFIG_DIR

        # Uploads live in the config directory, but it is not always writable. Measured crash:
        # starting the Harness with no arguments makes the workspace the home directory, and creating
        # ~/.myriaxon/uploads raised PermissionError during startup. UploadStore probes candidate
        # locations and falls back instead of raising, and resolves lazily so construction cannot fail
        # on a read-only config directory.
        self.uploads = UploadStore(CONFIG_DIR, self.workspace)
        self.settings = SettingsStore(self._settings_path())
        # User-defined endpoints keep their own store so both the CLI and the dashboard see the same
        # set, and a read-only config directory degrades instead of failing.
        self.endpoints = CustomEndpointStore(CONFIG_DIR / "custom_endpoints.json")
        # Permission-rule editing writes only the user settings file (see policy.py for why).
        from ..constants import USER_SETTINGS_FILE

        self.policy = PermissionRules(USER_SETTINGS_FILE, self.workspace)
        self.messaging = load_messaging_config(MESSAGING_FILE)
        # The notifier wants a console for its warnings, but the app never renders to one -- each
        # session owns its own EventConsole -- so a quiet one is created rather than reaching into a
        # session for it.
        from rich.console import Console as _RichConsole

        self._notifier_console = _RichConsole(quiet=True)
        self.notifier = MessagingNotifier(MessagingClient(self.messaging), self._notifier_console)
        self.sessions = SessionManager(self.workspace, self.settings, self.endpoints, application=self)
        # Saved conversations are restored by `serve()`, not here. A constructor that reaches out to
        # disk makes every test inherit the previous test's state, and "build me a fresh app" is a
        # reasonable thing to ask for.

        # Plugins are loaded once per process, before any agent is built, so their tools appear in
        # every session's tool list. Failures are recorded, not raised.
        try:
            from ..constants import CONFIG_DIR
            from ..plugins import load_plugins

            self.plugins = load_plugins(CONFIG_DIR, self.workspace)
        except Exception:  # noqa: BLE001
            self.plugins = None
        self.started_at = time.time()
        self._workspace_lock = threading.Lock()
        self.recent_workspaces: list[str] = []
        self._load_recents()

    @property
    def uploads_dir(self) -> Path:
        return self.uploads.path()

    def _settings_path(self) -> Path:
        from ..constants import CONFIG_DIR

        return CONFIG_DIR / "dashboard_settings.json"

    # -- workspace -----------------------------------------------------------------
    def _recents_path(self) -> Path:
        from ..constants import CONFIG_DIR

        return CONFIG_DIR / "dashboard_projects.json"

    def _load_recents(self) -> None:
        try:
            data = json.loads(self._recents_path().read_text(encoding="utf-8"))
            self.recent_workspaces = [p for p in data.get("recent", []) if isinstance(p, str)][:8]
        except (OSError, json.JSONDecodeError, AttributeError):
            self.recent_workspaces = []

    def _remember(self, path: Path) -> None:
        entry = str(path)
        self.recent_workspaces = [entry] + [p for p in self.recent_workspaces if p != entry]
        self.recent_workspaces = self.recent_workspaces[:8]
        try:
            self._recents_path().parent.mkdir(parents=True, exist_ok=True)
            self._recents_path().write_text(
                json.dumps({"recent": self.recent_workspaces}, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # recents are a convenience; never fatal

    def _plugins_payload(self) -> dict:
        """Loaded plugins, their tools and hooks, and any load failures."""
        if self.plugins is None:
            return {"plugins": [], "count": 0, "failed": [], "tools": [], "hooks": {}, "events": []}
        payload = self.plugins.summary()
        from ..constants import CONFIG_DIR

        payload["dirs"] = [str(d) for d in _plugin_dirs(CONFIG_DIR, self.workspace)]
        return payload

    def reload_plugins(self) -> dict:
        """Re-read the plugin directories, then invalidate agents so new tools take effect."""
        if self.plugins is None:
            return self._plugins_payload()
        from ..constants import CONFIG_DIR

        self.plugins.load(CONFIG_DIR, self.workspace, force=True)
        # Called on the app (we ARE the app here), not via the handler's convenience method.
        self.invalidate_agents()
        return self._plugins_payload()

    def _messaging_payload(self) -> dict:
        """Messaging settings, with credentials reduced to booleans."""
        payload = self.messaging.public()
        payload["stats"] = self.notifier.stats() if getattr(self, "notifier", None) else {"sent": 0, "failed": 0}
        return payload

    def save_messaging(self, body: dict) -> dict:
        """Persist messaging settings and rebuild the notifier."""
        updated = save_messaging_config(MESSAGING_FILE, body)
        self.messaging = updated
        # Reuses the console created at init rather than constructing one here, which referenced an
        # unimported name and turned every save into a 500.
        self.notifier = MessagingNotifier(MessagingClient(updated), self._notifier_console)
        return self._messaging_payload()

    def handle_inbound_message(
        self, payload: dict, headers: dict | None = None, deliver: bool = True
    ) -> dict:
        """Answer a provider webhook: authenticate, gate, run a turn, reply.

        Returns a small JSON object describing what happened, so the webhook always answers with 200
        and the provider does not retry a message that was deliberately refused.

        `deliver=False` runs everything except the outbound send. It exists for the self test, which
        must be able to prove the agent answers without messaging a real person: a test that always
        fires a real WhatsApp message is one nobody dares run.
        """
        config = self.messaging
        if not config.enabled:
            return {"ok": False, "reason": "messaging is disabled"}

        # A shared secret is optional but checked whenever one is configured: an open webhook is an
        # unauthenticated way to run an agent.
        if config.secret:
            supplied = ""
            if headers:
                # The pre-rebrand header name is accepted indefinitely: it is part of a deployed
                # webhook contract, and a live Twilio/Meta integration sending it would start
                # failing the moment it stopped being read. `x-iow-secret` is a typo that shipped
                # alongside it and is also kept, for the same reason -- silently dropping an alias
                # that some deployment may be using is not a safe way to tidy up.
                supplied = (
                    headers.get("X-Myriaxon-Secret")
                    or headers.get("x-myriaxon-secret")
                    or headers.get("X-Ioh-Secret")
                    or headers.get("x-iow-secret")
                    or headers.get("x-ioh-secret")
                    or ""
                )
            if not _secret_matches(supplied, config.secret):
                return {"ok": False, "reason": "bad or missing shared secret"}

        try:
            sender, text = parse_inbound(config, payload)
        except MessagingError as exc:
            # Delivery receipts and status callbacks land here. Not an error on our side.
            return {"ok": False, "reason": str(exc)}

        if not is_allowed(config, sender):
            return {
                "ok": False,
                "reason": (
                    f"sender {sender} is not on the allowlist. Add the number to `allow` in "
                    "whatsapp.json to permit it."
                ),
            }

        session = self.new_session()
        session.submit(text)

        client = MessagingClient(config)
        answer = ""
        deadline = time.time() + 600
        while time.time() < deadline:
            if not session.busy:
                break
            time.sleep(0.5)
        answer = self._last_assistant_text(session)

        if not deliver:
            return {
                "ok": True,
                "sender": sender,
                "replied": False,
                "send_skipped": True,
                "answer": answer,
                "session": session.id,
            }
        sent = client.send_safe(format_turn_summary(text, answer))
        return {
            "ok": True,
            "sender": sender,
            "replied": sent,
            "send_error": client.last_error,
            "answer": answer,
            "session": session.id,
        }

    @staticmethod
    def _last_assistant_text(session) -> str:
        try:
            for message in reversed(session.messages()):
                if message.get("role") == "assistant" and (message.get("text") or "").strip():
                    return str(message["text"])
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _mcp_payload(self) -> dict:
        """Configured MCP servers, plus the catalog of preconfigured ones.

        The catalog travels with the payload so the panel can show what is available and which entries
        are already installed, rather than making the user find a URL or a package name first.
        """
        try:
            from ..mcp_client import load_mcp_config

            config = load_mcp_config()
        except Exception as exc:  # noqa: BLE001
            return {"stdio_servers": [], "url_servers": [], "error": f"{type(exc).__name__}: {exc}"}
        server_file = ""
        try:
            from ..constants import MCP_SERVERS_FILE

            server_file = str(MCP_SERVERS_FILE)
        except Exception:  # noqa: BLE001
            pass

        stdio = config.get("stdio_servers") or []
        urls = config.get("url_servers") or []
        installed = {str(s.get("name")) for s in stdio} | {str(s.get("name")) for s in urls}

        from ..mcp_catalog import catalog_payload, categories

        catalog = []
        for entry in catalog_payload():
            item = dict(entry)
            item["installed"] = entry["key"] in installed
            catalog.append(item)

        try:
            from ..mcp_client import remote_transport_support

            transports = remote_transport_support()
        except Exception:  # noqa: BLE001
            transports = {}

        return {
            "stdio_servers": stdio,
            "url_servers": urls,
            "config_file": server_file,
            "catalog": catalog,
            "categories": categories(),
            "transports": transports,
        }

    def open_workspace(self, path: str) -> Path:
        """Point the whole server at a different project directory.

        The agent's file tools resolve relative paths against the process working directory, so this
        changes the process cwd rather than only recording a path. Sessions are discarded because a
        session's accumulated file context belongs to the project it was started in; keeping them
        would silently mix two projects. Serialized so two concurrent requests cannot race the chdir.
        """
        candidate = Path(path).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"no such directory: {candidate}")
        if not candidate.is_dir():
            raise NotADirectoryError(f"not a directory: {candidate}")
        # The agent writes into the workspace, so an unwritable one would fail on the first edit.
        # Refusing here gives a clear message instead of a later, more confusing one.
        if not is_writable(candidate):
            raise PermissionError(f"directory is not writable: {candidate}")

        with self._workspace_lock:
            os.chdir(candidate)
            self.workspace = candidate
            # Uploads may need to move now that the workspace (a fallback location) changed.
            self.uploads.rework(candidate)
            for session_id in [s["id"] for s in self.sessions.list()]:
                self.sessions.delete(session_id)
            self.sessions = SessionManager(candidate, self.settings, self.endpoints, application=self)
            self._remember(candidate)
        return candidate

    def new_session(self, mode: str | None = None):
        return self.sessions.create(self.config, mode=mode or self.default_mode)

    def start_supervisor(self, *, interval: float = 60.0) -> None:
        """Run due Loci on a timer, from inside the harness.

        This is what makes a Locus autonomous rather than merely capable of autonomy. Measured before
        it existed: with a Locus enabled, proactive, due, and an objective waiting, ninety seconds of
        doing nothing produced no run at all -- because `proactive`, `interval_seconds` and `is_due()`
        only DESCRIBE when a Locus should run, and every trigger for actually running one was a person
        (`loci --run`, `loci --watch`, or a button).

        A Python thread rather than an operating-system task, and the reason is the one the user gave
        when they asked for it: an OS task is a second moving part outside the harness that has to be
        found, installed, explained and removed, and the first attempt at it made the user's WSL pop
        up every five minutes. In-process, there is nothing to install, nothing to forget, and it stops
        when the harness stops.

        The trade, stated plainly: a Locus only runs while the dashboard is open. That is honest
        autonomy-within-a-session rather than always-on, and it is the correct default for a tool that
        should not leave a background process on someone's machine uninvited.
        """
        import threading

        if getattr(self, "_supervisor", None) is not None:
            return
        stop = threading.Event()
        # The last refusal per locus, so a permanently-unrunnable one is explained once instead of every
        # interval. Keyed by name and compared by reason, so a DIFFERENT problem is still reported.
        self._supervisor_refusals: dict[str, str] = {}

        def loop() -> None:
            # A first pass immediately, so opening the dashboard advances overdue work rather than
            # making the user wait a full interval to see whether the feature exists at all.
            while not stop.is_set():
                try:
                    from .. import loci as loci_module

                    registry = loci_module.get_registry()
                    for locus in registry.due():
                        # Each run is guarded by the Locus's own lease, so a supervisor pass racing a
                        # manual Run is refused rather than doubled -- the same protection a second
                        # process gets.
                        try:
                            outcome = self.run_locus(locus)
                        except Exception as exc:  # noqa: BLE001 - one bad locus must not stop the loop
                            # Printed rather than logged: this module has no logger, and a supervisor
                            # that silently swallows a failing locus is indistinguishable from one that
                            # is not running at all -- which is the exact confusion this whole change
                            # exists to remove.
                            print(f"  supervisor: could not run {locus.name}: {exc}")
                            continue

                        # A REFUSED RUN IS REPORTED, ONCE. `run_locus` returns `accepted: False` rather than
                        # raising, and this loop used to discard that -- so a locus that was due, enabled and
                        # proactive but had nothing to work on was retried every interval, refused every time,
                        # and said nothing. Measured: `anker` sat in that state for 26 minutes while
                        # `last_run_at` never advanced, because a refused run does not stamp it -- which
                        # means `is_due()` stays true forever and the locus is permanently due and
                        # permanently idle, with no output anywhere to explain it.
                        #
                        # Said ONCE per distinct reason, because the useful fact is "this one cannot run, and
                        # here is why". Repeating it every interval would turn a diagnosable state into a log
                        # nobody reads, which is the failure mode this reporting exists to avoid.
                        if isinstance(outcome, dict) and not outcome.get("accepted", True):
                            reason = str(outcome.get("reason") or "refused")
                            if self._supervisor_refusals.get(locus.name) != reason:
                                self._supervisor_refusals[locus.name] = reason
                                print(f"  supervisor: {locus.name} is due but cannot run -- {reason}")
                        else:
                            self._supervisor_refusals.pop(locus.name, None)
                except Exception as exc:  # noqa: BLE001
                    print(f"  supervisor: pass failed: {exc}")
                stop.wait(interval)

        thread = threading.Thread(target=loop, name="locus-supervisor", daemon=True)
        thread.start()
        self._supervisor = thread
        self._supervisor_stop = stop
        print(f"  supervisor: due Loci run automatically every {interval:.0f}s while this is open")

    def stop_supervisor(self) -> None:
        """Ask the supervisor to stop. Safe to call when it was never started."""
        stop = getattr(self, "_supervisor_stop", None)
        if stop is not None:
            stop.set()
        self._supervisor = None
        self._supervisor_stop = None

    def run_locus(self, locus, message: str = "") -> dict:
        """Give a locus a turn in a real session, so the browser watches it like any other turn.

        Deliberately not a turn executed inside the request handler. A dashboard turn can take
        minutes, and the browser's only way to follow one is the session's SSE stream -- running it
        here would block the request, show the user nothing until it finished, and bypass the busy
        flag, the transcript, the trajectory and the cancellation path that already exist.

        The locus keeps ONE conversation, reused across runs. It used to get a fresh session per run,
        which made every exchange a Q&A: "make it portrait instead" had no antecedent, and the locus
        could not refer to what you asked a minute earlier. A persistent agent that forgets between
        messages is not persistent in the way that matters.

        Reuse is safe against concurrent runs because the session carries the busy flag: a second
        run of the same locus while one is in flight is refused rather than interleaved into the same
        transcript. The session id lives on the locus, so the terminal and the browser continue the
        same discussion instead of each starting their own.
        """
        from .. import loci as loci_module
        from ..loci import get_registry

        # Preflight before anything is scheduled. It is static -- no network, no credential -- so
        # refusing here costs nothing and the caller learns exactly what to fix. The same two gates
        # the agent-facing `locus_run` tool applies; honouring them only in the tool path would make
        # the disable button a lie in the very panel that offers it.
        #
        # A message from the owner drops the objective checks: those exist so a proactive wake-up
        # with nothing to do does not invent work, and a person asking for something is not that.
        problems = locus.preflight(for_message=bool(message.strip()))
        if problems:
            return {
                "accepted": False,
                "reason": "; ".join(problems),
                "locus": locus.name,
            }

        # IS ANOTHER RUN ALREADY IN THE SLOT? Asked HERE, before anything is scheduled, because the
        # answer is only useful to the caller at submit time.
        #
        # Measured defect: the lease was consulted only inside the turn's worker thread, by `run_scope`,
        # so a run that could not possibly start still returned `accepted: True` -- and the refusal went
        # to the locus's ACTIVITY LOG, where a dashboard caller never looks. Reproduced:
        #
        #     run_locus -> {'accepted': True, 'reason': 'diag was claimed by another run...'}
        #     activity  -> [note] run refused: this locus is already running (pid 3456)
        #     result    -> running=True, session_id=None, open_goals unchanged, no assistant turn
        #
        # The client saw success and nothing happened. That is worse than a plain failure, because there
        # is no error to act on: the panel shows "working now" forever and the goal never advances.
        #
        # `read_run_lease` returns None when the holder is gone, so this does not refuse a run because of
        # a dead process -- `acquire_run_lease` reclaims those, and `_announce_reclaimed_lease` says so
        # once.
        holder = loci_module.read_run_lease(locus)
        if holder is not None:
            return {
                "accepted": False,
                "reason": f"{locus.name} is already running ({holder.describe()}). "
                          "Wait for that run to finish, or clear the lease in its workspace if the "
                          "process that held it is gone.",
                "locus": locus.name,
                "holder": holder.describe(),
            }

        session = None
        if locus.session_id:
            session = self.sessions.get(locus.session_id)
            if session is not None and getattr(session, "busy", False):
                return {
                    "accepted": False,
                    "reason": f"{locus.name} is already working on something. Wait for it to finish.",
                    "locus": locus.name,
                }
        if session is None:
            # Recreated under the SAME id when the process restarted: session ids live in memory,
            # so a restart would otherwise silently start a locus's conversation over. `create`
            # accepts an id for exactly this, and the continuation the user sees is then real.
            session = self.sessions.create(
                self.config, mode=self.default_mode,
                session_id=locus.session_id or None,
            )
            locus.session_id = session.id
        # The session records which locus it belongs to rather than encoding it in the title, so the
        # Mission control view can label a run without parsing a string.
        session.state.locus = locus.name
        session.state.title = f"{locus.name} Â· locus"

        # The locus's briefing becomes the session's IDENTITY, not a message.
        #
        # This is the fix for a defect the user hit directly: `/loci run analyst "are you analyst?"`
        # answered "Not by default -- I'm a coding agent". The briefing *was* being sent, but as a
        # user message, while the system prompt still asserted "You are Myriaxon, a terminal-based
        # coding agent" with `essential=True`. The model believed the system prompt, which is the
        # correct thing for it to do. A request cannot override an instruction that defines the same
        # agent, so the identity itself has to change.
        #
        # It replaces rather than appends, so exactly one section says who is speaking.
        #
        # The scope is decided by whether the owner wrote something. A message is a conversation --
        # answer it, do not start work -- while an empty message is the run this locus was made for,
        # advancing its own objectives. Without this distinction a greeting produced minutes of
        # "thinking" and tool calls, because the brief told the model to work its objectives whatever
        # had been asked of it.
        session.persona_identity = locus.briefing(run_scope="message" if message.strip() else "objective")
        # The agent is rebuilt when the model changed but reused otherwise, and `_ensure_agent` copies
        # the persona onto whatever it returns -- so setting it here is enough even for a session that
        # already has an agent built.
        if session.agent is not None:
            session.agent.persona_identity = session.persona_identity

        if message.strip():
            prompt = f"Message from your owner:\n{message.strip()}"
        else:
            # The same wording the terminal's proactive pass uses, so a locus's behaviour does not
            # depend on which surface woke it.
            prompt = locus.proactive_prompt() or "Take the next concrete step."

        locus.log("turn", f"run from the dashboard: {(message or 'advance next objective')[:200]}")
        try:
            # `touch`, not `persist`: touch is what records that the locus has *run*.
            #
            # It sets `last_run_at`, without which a proactive locus is due again the instant it
            # finishes -- `is_due()` compares against `last_run_at`, and 0.0 means "never ran". The
            # consequence was a locus that could be started over and over from the panel and would
            # wake on every proactive pass forever, because nothing had told the registry it had
            # ever been given a turn. Stamped at submit time rather than on completion: the run has
            # started, and an in-flight locus must not be considered due.
            get_registry().touch(locus)
        except Exception:  # noqa: BLE001
            pass

        accepted = session.submit(prompt)
        if accepted:
            # The run LEASE is taken here, for the duration of the turn.
            #
            # This path previously consulted no lease at all, so the terminal's proactive pass and a
            # browser click could work one locus in one workspace simultaneously -- two agents writing
            # the same files and spending tokens twice, which is the exact collision the lease was
            # built to prevent. `loci.py` promised it; only the terminal honoured it.
            #
            # The lease is held by the session rather than by a `with` block here, because the turn
            # runs on a worker thread and this call returns immediately. `_release_locus_lease` runs
            # from the turn's completion, and `begin_run`'s in-memory flag is what the panel reads.
            try:
                if locus.begin_run():
                    session._dot_lease = loci_module.read_run_lease(locus)
                    session._dot_lease_name = locus.name
                else:
                    # Lost a race with another surface between the preflight and here. The turn is
                    # already submitted, so the honest thing is to say so rather than pretend the
                    # run is exclusive.
                    return {
                        "accepted": True,
                        "reason": f"{locus.name} was claimed by another run at the same moment; "
                                  "this turn may interleave with it.",
                        "session": session.state.to_dict(),
                        "locus": locus.name,
                    }
            except Exception:  # noqa: BLE001
                pass
        return {
            "accepted": bool(accepted),
            "reason": "" if accepted else "the session is already running a turn",
            "session": session.state.to_dict(),
            "locus": locus.name,
        }

    def release_locus_lease(self, locus_name: str, locus=None) -> None:
        """End a locus run started by `run_locus`. Idempotent, and never raises.

        Called when the session's turn finishes. A failure here would leave the locus looking busy
        forever, so it is deliberately total rather than conditionally correct.
        """
        try:
            from .. import loci as loci_module

            target = locus
            if target is None:
                target = loci_module.get_registry().get(locus_name)
            if target is not None and target.running:
                target.end_run(None)
        except Exception:  # noqa: BLE001
            pass

    def set_vendor(self, provider: str, model: str = "") -> tuple[bool, str]:
        """Point this server at another gateway. Returns (ok, problem).

        On the APPLICATION rather than the request handler, and that is the fix for a reported bug
        rather than a preference: the vendor picker ran on a Handler, whose body read and wrote
        `self.config`. A handler is built per request and holds no configuration, so the write created
        a temporary attribute that vanished when the response was sent, and the read raised
        `'BoundHandler' object has no attribute 'config'` -- which the browser showed as
        "could not save: ...". Even had the read worked, the choice would have applied to one request
        and then been forgotten, while the running sessions kept clients for the old gateway.

        The switch itself goes through `config.switch_vendor`, the same function `/vendor` in the
        terminal uses, so the two surfaces cannot drift apart -- they already had once, over whether
        the environment's endpoint for another provider may be reused (it may not).
        """
        from ..config import save_config, switch_vendor

        new_config, problem = switch_vendor(self.config, provider, model)
        if new_config is None:
            return False, problem
        try:
            # Saved so a restart resumes on the chosen gateway. A failure here is reported to the
            # caller but does not undo a switch that is otherwise valid.
            save_config(new_config)
        except Exception as exc:  # noqa: BLE001 - an unwritable config is not a failed switch
            problem = f"switched, but the choice could not be saved ({type(exc).__name__})"
        self.config = new_config
        # The sessions hold clients built for the previous gateway; leaving them would send the new
        # provider's requests to the old host.
        self.invalidate_agents()
        return True, problem

    def invalidate_agents(self, keep_history: bool = True) -> int:
        """Drop built agents so a tool-list or policy change takes effect on the next message.

        Lives on the application, not the request handler. It was originally a Handler method, which
        meant any code path reaching it from the app (plugin reload, for one) raised AttributeError --
        the same class-confusion that produced an earlier 500 on /api/settings.
        """
        rebuilt = 0
        for info in self.sessions.list():
            session = self.sessions.get(info["id"])
            if session is None:
                continue
            if keep_history:
                session.capture_history()
            session.agent = None
            rebuilt += 1
        return rebuilt

    def _loci_payload(self, transcript_for: str = "", transcript_names: list[str] | None = None) -> dict:
        """Every persistent agent on this machine, with the state the panel renders.

        Reloaded from disk on each request rather than served from a cached copy: the terminal and
        the dashboard share one ``loci.json`` and are routinely open together, so a panel that
        showed whatever was loaded at startup would be wrong the moment anyone used `/loci`. The
        file is small, and being correct matters more here than saving a read.

        ``transcript_for`` names a locus whose own conversation should travel with the payload. It is
        what lets the Loci page show a locus's chat WITHOUT switching the Myriaxon session to that
        locus's session -- the coupling that used to put a locus's turns, and its raw
        ``[tool.name]â€¦`` console lines, into the middle of the user's own conversation. Read-only:
        ``messages()`` projects from the agent's message list, or from the transcript on disk when
        there is no agent yet, and never builds one (building starts MCP servers and loads plugins,
        which a GET must not do).
        """
        try:
            from ..loci import GOAL_STATES, get_registry

            registry = get_registry()
            registry.reload()
        except Exception as exc:  # noqa: BLE001
            return {"loci": [], "goal_states": [], "error": f"{type(exc).__name__}: {exc}"}

        def idle_reason(locus) -> str:
            """Why this locus is not doing anything on its own, in the user's words.

            Added because the honest answer to "why is my locus not autonomous?" is almost never a
            defect: it is one of three configuration facts the panel never stated. Measured on a real
            locus -- `enabled=False, proactive=False`, its single objective `done` -- every surface
            showed it as present and healthy while it did nothing, so the user read that as broken.

            Ordered by what to fix first, and empty when the locus genuinely would wake on its own.
            """
            if not locus.enabled:
                return "paused: it will not run, even on its interval. Press Enable."
            if not locus.open_goals():
                return "no open objectives: it has nothing to work on. Add one, or ask it for something."
            if not locus.proactive:
                return "on demand only: it never wakes on its own. Press Wake on interval."
            return ""

        def render(locus) -> dict:
            return {
                "id": locus.id,
                "name": locus.name,
                "role": locus.role,
                "instructions": locus.instructions,
                "workspace": str(locus.workspace_path()),
                "provider": locus.provider,
                "model": locus.model,
                "proactive": locus.proactive,
                "enabled": locus.enabled,
                "interval_seconds": locus.interval_seconds,
                # How much of its own direction this locus has, and what it therefore costs. Served
                # rather than derived in the browser so the panel and the CLI cannot disagree about
                # the same locus -- the rule already applied to `idle_reason` below.
                "autonomy": locus.autonomy,
                "self_directed": locus.is_self_directed(),
                "max_steps_per_run": locus.max_steps_per_run,
                "steps_this_run": locus.step_budget(),
                # The boundary, stated once and served. The owner chose full self-direction WITH
                # workspace confinement, so "autonomous" here must never read as "unrestricted": this
                # is the folder it can act in, and it is the same path `workspace` reports above,
                # named separately because the UI shows it as a limit rather than as a location.
                "confined_to": str(locus.workspace_path()),
                "seconds_until_due": locus.seconds_until_due(),
                "due_now": locus.is_due(),
                # Whether a run holds this locus right now. The panel could only style `due_now`, so a
                # locus mid-run from the terminal looked identical to an idle one -- there was no way to
                # tell "working" from "waiting" in the UI, and a user clicking Run on a busy locus got a
                # full turn interleaved with one already in flight.
                "running": locus.is_running(),
                # Why it is not working on its own, or "" when it would. Served rather than derived in
                # the browser so the CLI and the panel cannot disagree about the same locus.
                "idle_reason": idle_reason(locus),
                "run_started_at": getattr(locus, "run_started_at", 0.0) or 0.0,
                "goals": [
                    {
                        "id": g.id,
                        "title": g.title,
                        "detail": g.detail,
                        "status": g.status,
                        "attempts": g.attempts,
                        "notes": g.notes[-5:],
                    }
                    for g in locus.goals
                ],
                "open_goals": len(locus.open_goals()),
                # Most recent first: the panel answers "what has it been doing", and the newest
                # entry is the one that answers it.
                "activity": [
                    {"at": a.at, "kind": a.kind, "summary": a.summary} for a in reversed(locus.activity[-40:])
                ],
            }

        loci = [render(d) for d in registry.all()]
        existing = {d["name"] for d in loci}

        # The conversation of ONE locus, when the Loci page asked for it. Kept here rather than
        # behind a second endpoint so the page has one request to make and cannot render a roster
        # that disagrees with the transcript beside it.
        def _read_transcript(name: str) -> tuple[list[dict], str]:
            wanted = next((d for d in registry.all() if d.name == name), None)
            if wanted is None or not wanted.session_id:
                return [], ""
            session = self.sessions.get(wanted.session_id)
            if session is None:
                return [], wanted.session_id
            try:
                return [
                    {"role": str(m.get("role") or "assistant"), "text": str(m.get("text") or "")}
                    for m in session.messages()
                    if str(m.get("text") or "").strip()
                ], wanted.session_id
            except Exception:  # noqa: BLE001 - a broken transcript must not empty the roster
                return [], wanted.session_id

        transcript: list[dict] = []
        transcript_session = ""
        if transcript_for:
            transcript, transcript_session = _read_transcript(transcript_for)

        # SEVERAL conversations at once, for the pane wall. One request rather than one per pane, and that is
        # the whole reason it lives here instead of the page looping over the single-locus call: nine panes
        # polling independently would be nine requests on a timer, each re-reading `loci.json` and rebuilding
        # the roster -- so the cost of watching three agents work together would scale with how closely you
        # watched. Reading each session's message list is the only part that has to happen per pane.
        transcripts: dict[str, list[dict]] = {}
        for name in (transcript_names or ()):
            # Blank names are skipped HERE rather than only at the route, so the contract holds for every
            # caller: the route strips them, the tests call this directly, and a second caller would otherwise
            # have to remember. The alternative is an empty pane keyed by "" that nothing can draw.
            name = (name or "").strip()
            if name and name not in transcripts:
                transcripts[name], _ = _read_transcript(name)

        # The template gallery travels with the payload so the panel can offer a one-click bot.
        # `installed` is computed here rather than in the browser: the panel should not have to
        # re-derive which templates already exist, and doing it server-side keeps one answer.
        try:
            from ..bot_templates import TEMPLATES

            templates = []
            for template in TEMPLATES:
                entry = template.to_dict()
                entry["installed"] = template.name in existing
                templates.append(entry)
        except Exception:  # noqa: BLE001 - a broken template module must not empty the panel
            templates = []

        return {
            "loci": sorted(loci, key=lambda d: d["name"].lower()),
            "goal_states": list(GOAL_STATES),
            "file": str(registry.path),
            "templates": templates,
            "transcript": transcript,
            "transcript_session": transcript_session,
            "transcripts": transcripts,
        }

    def config_payload(self) -> dict:
        from ..constants import MODES

        config = self.config
        settings = None
        try:
            from ..settings import load_settings

            settings = load_settings()
        except Exception:  # noqa: BLE001
            settings = None
        return {
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            # Which of the two gateways this machine can actually use, and where the credential comes
            # from. Served so the composer can ask for a missing key the moment DeepSeek is chosen,
            # instead of letting the first turn fail with a 401. Booleans only -- this payload reaches
            # the browser on every page load, so the key itself must never travel in it.
            "vendor_keys": _vendor_key_state(config),
            "vertex_project": config.vertex_project,
            "vertex_location": config.vertex_location,
            "modes": list(MODES),
            "mode": self.default_mode,
            # The slash-command catalogue travels with the config so the composer can suggest
            # commands as they are typed. Built from the same table /help prints, so the menu and
            # the help text cannot disagree about what exists.
            "commands": _command_catalogue(),
            "models": _models_for(config, self.endpoints),
            "providers": _providers() + self.endpoints.names(),
            "custom_endpoints": self.endpoints.list(),
            "settings": self.settings.get().public(),
            "settings_schema": self.settings.schema(),
            "mcp": self._mcp_payload(),
            "plugins": self._plugins_payload(),
            "messaging": self._messaging_payload(),
            "loci": self._loci_payload(),
            "rules": self.policy.snapshot(),
            "workspace": str(self.workspace),
            "recent_workspaces": self.recent_workspaces,
            "enforced_mode": getattr(settings, "enforced_mode", None) if settings else None,
            "enforced_provider": getattr(settings, "enforced_provider", None) if settings else None,
        }

    def safe_path(self, relative: str) -> Path:
        """Resolve a client-supplied path, refusing anything outside the workspace."""
        cleaned = posixpath.normpath("/" + relative.replace("\\", "/")).lstrip("/")
        candidate = (self.workspace / cleaned).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise PermissionError(f"path is outside the workspace: {relative}")
        return candidate


class Handler(BaseHTTPRequestHandler):
    server_version = "Myriaxon"
    app: DashboardApp  # set on the server class

    def _ollama_payload(self, query: dict) -> dict:
        """Report local Ollama models for the composer's model picker.

        Lives on the handler rather than on `DashboardApp` because that is what the router calls
        `self` on. Placing it on the app produced
        `'BoundHandler' object has no attribute '_ollama_payload'` -- a 500 that names the attribute
        but not the mistake, which is why the body is read rather than the status.

        Ollama is the only provider with nothing to configure -- no key, no account -- so this reports
        what is on the machine and what each model can actually do. That matters because the advertised
        context window is not the one Ollama runs the model with: a model declares 262144 and Ollama gives
        it 4,096 unless its own settings say more (`myriaxon ollama --create` makes one that does), so both
        numbers travel and the panel shows which is budgeted against.

        Never raises. Ollama not being installed is the common case, and a panel that 500s because a
        user has not installed an optional local runtime would be a bug in the panel.
        """
        from .. import ollama

        quick = str((query.get("quick") or ["0"])[0]).lower() in ("1", "true", "yes")
        try:
            probe = ollama.detect(with_details=not quick)
        except Exception as exc:  # noqa: BLE001
            return {"reachable": False, "installed": False, "models": [], "message": str(exc)}

        models = []
        for model in probe.models:
            runs_with = ollama.runtime_context(model, probe.loaded.get(model.name, 0))
            models.append(
                {
                    "name": model.name,
                    "parameter_size": model.parameter_size,
                    "family": model.family,
                    "quantisation": model.quantisation,
                    "size_gb": round(model.size_gb, 2),
                    "context_declared": model.context_length,
                    "context_usable": runs_with,
                    "profile": ollama.profile_hint(runs_with),
                    "capabilities": model.capabilities,
                    "supports_tools": ollama.tool_capable(model),
                    "loaded": model.name in probe.loaded,
                }
            )

        active_provider = getattr(self.app.config, "provider", "")
        return {
            "reachable": probe.reachable,
            "installed": probe.installed,
            "base_url": probe.base_url,
            "message": probe.explain(),
            "models": models,
            "active": active_provider == "ollama",
            "active_model": getattr(self.app.config, "model", "") if active_provider == "ollama" else "",
            "minimum_for_agent": ollama.MIN_AGENT_CONTEXT,
        }

    # -- plumbing -----------------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        """Quiet by default; the dashboard shows activity, the console does not need to."""
        if os.environ.get("MYRIAXON_DASHBOARD_VERBOSE"):
            super().log_message(fmt, *args)

    def handle_one_request(self) -> None:
        """Swallow connection resets.

        Measured on Windows: a browser closing a keep-alive connection (or a page reload while an SSE
        stream is open) makes `readline` raise ConnectionAbortedError, and socketserver prints a full
        traceback to the console for what is entirely normal client behaviour. Silencing it here keeps
        the server's output readable so a real error is not lost in the noise.
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            pass

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _read_payload(self) -> dict:
        """Read a request body as either JSON or form-encoded data.

        Needed by the messaging webhook: Meta posts JSON, Twilio posts
        `application/x-www-form-urlencoded`. Reading only JSON made every Twilio message look like an
        empty payload, so the parse failed with "no inbound message" for a perfectly valid request.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        content_type = (self.headers.get("Content-Type") or "").lower()
        text = raw.decode("utf-8", errors="replace")
        if "json" in content_type or text.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {"_payload": parsed}
            except json.JSONDecodeError:
                return {"_raw": text}
        if "form" in content_type:
            return {key: values[0] for key, values in urllib.parse.parse_qs(text).items()}
        # Unknown content type: try JSON, then fall back to form parsing, so a mislabelled request from
        # a provider bridge still works.
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"_payload": parsed}
        except json.JSONDecodeError:
            return {key: values[0] for key, values in urllib.parse.parse_qs(text).items()}

    def _error(self, exc: BaseException, status: int = 500) -> None:
        self._send_json({"error": str(exc), "kind": type(exc).__name__}, status=status)

    # -- Vertex context cache: observability and control in one place ------------------
    #
    # Why this is in the dashboard at all: a cache is a BILLING RESOURCE with a lifetime. Enabling it
    # without a panel that says whether one exists, how big it is and when it expires leaves the operator
    # paying per hour with nothing to look at -- and the moment someone wants caching OFF is the moment
    # they are reacting to a cost they noticed elsewhere, so the kill switch has to be one click from the
    # same screen that reports the cost.
    #
    # GET reads live state from the API rather than from local memory, because a cache can be deleted
    # from anywhere: another process, the Cloud console, a colleague. A panel built from a local record
    # would show a cache that no longer exists and hide the ones that do.
    def _vertex_cache_get(self) -> None:
        from .. import vertex_cache

        vertex_cache.stats().enabled = vertex_cache.enabled()
        try:
            vertex_cache.list_caches()
        except Exception as exc:  # noqa: BLE001 - the panel must render an error, never a 500
            vertex_cache.stats().last_error = f"{type(exc).__name__}: {exc}"
        payload = vertex_cache.stats().to_dict()
        payload["ttl_seconds"] = vertex_cache.ttl_seconds()
        payload["min_tokens"] = vertex_cache.MIN_CACHE_TOKENS
        payload["available"] = self._vertex_cache_available()
        return self._send_json(payload)

    def _vertex_cache_available(self) -> bool:
        """Whether caching could work at all here.

        Reported separately from "enabled" so the panel can explain WHY an enabled cache has no effect:
        a Gemini-without-Vertex run, or a non-gemini provider, cannot use one no matter the switch.
        """
        try:
            from .. import vertex_auth

            return bool((os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
                        or vertex_auth.project())
        except Exception:  # noqa: BLE001
            return False

    def _vertex_cache_post(self) -> None:
        from .. import vertex_cache

        body = self._read_json()
        action = str(body.get("action") or "").strip().lower()

        if action == "purge":
            deleted, problems = vertex_cache.delete_all()
            return self._send_json({"ok": True, "deleted": deleted, "problems": problems})

        if action == "delete":
            ok, message = vertex_cache.delete(str(body.get("name") or ""))
            return self._send_json({"ok": ok, "message": message})

        if action == "create":
            # Built from what the SESSION would actually send, never from a placeholder: a cache made of
            # invented text would never be hit by a real request, and the panel would then report a cache
            # that costs money every hour and saves nothing.
            session = self.app.sessions.get(body.get("session") or "")
            model = str(body.get("model") or "")
            instruction = str(body.get("system") or "")
            if session is not None:
                model = model or getattr(session.state, "model", "")
                if not instruction:
                    try:
                        # `_ensure_agent()`, not `session.agent`: a session that has been created but
                        # has not run a turn yet holds `agent = None`, so reading the attribute directly
                        # returned "no system prompt is available" for every FRESH session -- which is
                        # exactly the session someone tries this from. Measured: the first live call of
                        # this endpoint failed that way, and the second failed on the wrong method name,
                        # so both mistakes are recorded here rather than left to be repeated.
                        instruction = session._ensure_agent()._system_prompt()
                    except Exception as exc:  # noqa: BLE001 - report it rather than cache nothing
                        return self._error(ValueError(
                            f"could not read this session's system prompt: {type(exc).__name__}: {exc}"
                        ), 400)
            if not model:
                model = self.app.config.model
            if not instruction:
                return self._error(
                    ValueError("nothing to cache: no system prompt is available for this session"), 400
                )
            cache, problem = vertex_cache.create(model, instruction, ttl=vertex_cache.ttl_seconds())
            if cache is None:
                return self._error(ValueError(problem or "cache creation failed"), 400)
            return self._send_json({"ok": True, "cache": cache.name, "tokens": cache.total_tokens})

        if action in ("enable", "disable"):
            # The process environment, so the agent picks it up on the next request without a restart.
            # The TTL and the switch are read per call rather than captured at construction, precisely so
            # a control in the UI can change behaviour immediately.
            os.environ["MYRIAXON_VERTEX_CACHE"] = "true" if action == "enable" else "false"
            vertex_cache.stats().enabled = action == "enable"
            return self._send_json({"ok": True, "enabled": action == "enable"})

        return self._error(ValueError(f"unknown cache action {action!r}"), 400)

    # -- routing ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                return self._send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
            if route == "/api/config":
                return self._send_json(self.app.config_payload())
            if route == "/api/sessions":
                return self._send_json({"sessions": self.app.sessions.list()})
            if route == "/api/avatar":
                # The avatar is generated from the SAME manifest the terminal renderer reads, rather than being a
                # second hand-maintained copy of the faces. Two tables is exactly how two surfaces drift apart.
                from .. import loci_character as _loci
                from .. import loci_svg as _loci_svg

                wanted = (query.get("expression", ["happy"]) or ["happy"])[0]
                # Section 8.6's deletion state, reachable from the dashboard too: the same face with the window
                # dark. A query parameter rather than a fifteenth expression, because section 4's fourteen faces are
                # the contract and "the window is dark" is not a different face.
                window_dark = (query.get("dark", ["0"]) or ["0"])[0] not in ("", "0", "false", "no")
                if wanted not in _loci.EXPRESSIONS:
                    # REFUSED rather than silently drawn as idle: a caller who asked for a face that does not exist
                    # should not be left believing they saw it.
                    self._send_json({"error": f"no expression named {wanted}"}, status=404)
                    return
                try:
                    size = int((query.get("size", ["34"]) or ["34"])[0])
                except (TypeError, ValueError):
                    size = 34
                svg = _loci_svg.render_svg(wanted, size=max(8, min(512, size)), window_dark=window_dark)
                body = svg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                # Immutable within a page life: one expression renders the same bytes every time, so the client can
                # cache it and never re-request a mood change it has already seen.
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
                return

            if route == "/api/health":
                return self._send_json(
                    {
                        "ok": True,
                        "uptime_s": round(time.time() - self.app.started_at, 1),
                        "workspace": str(self.app.workspace),
                        "sessions": len(self.app.sessions.list()),
                    }
                )
            if route == "/api/ollama":
                # Detection is best-effort and never raises, so this endpoint cannot fail the page.
                # `?quick=1` skips the per-model capability probe: that is one request per model, which
                # is fine for a panel the user opened and wasteful for a poll.
                return self._send_json(self._ollama_payload(query))
            if route == "/api/messages":
                session = self.app.sessions.get(query.get("session", [""])[0])
                if session is None:
                    return self._error(KeyError("unknown session"), 404)
                # Usage travels with the transcript so the status line can show it the moment a
                # session is opened. It used to arrive only on `turn_end`, so switching to a session
                # -- or reloading the page -- showed an empty status line for a conversation that had
                # plainly cost something.
                #
                # Deliberately NOT built here: `_ensure_agent()` starts MCP servers and loads
                # plugins, which is work a read-only GET must never trigger. The state carries the
                # last snapshot for exactly this case, and a session that has never run has nothing
                # to report anyway.
                return self._send_json({
                    "messages": session.messages(),
                    "trajectory": session.trajectory(),
                    "usage": session.usage(),
                    "state": session.state.to_dict(),
                })
            if route == "/api/endpoint":
                # The effective endpoint and credential state for a session. Exposed because the
                # failure mode this makes visible is silent: switching provider while keeping the
                # previous endpoint sends requests to the wrong host and surfaces as a 404 that looks
                # like a bad model name.
                session = self.app.sessions.get(query.get("session", [""])[0])
                if session is None:
                    return self._error(KeyError("unknown session"), 404)
                config = session.config
                return self._send_json(
                    {
                        "provider": config.provider,
                        "model": session.state.model,
                        "base_url": config.base_url,
                        "vertex_project": config.vertex_project,
                        "vertex_location": config.vertex_location,
                        "mode": session.mode,
                        "has_api_key": bool(config.api_key),
                        "agent_built": session.agent is not None,
                    }
                )
            if route == "/api/events":
                return self._stream_events(query.get("session", [""])[0])
            if route == "/api/transparency/stream":
                return self._stream_transparency()
            if route == "/api/loci":
                # Its own route as well as being folded into /api/config: this one re-reads the
                # registry on every call, so the panel can poll it while a locus is running without
                # pulling the whole config payload each time.
                #
                # `?transcript=<locus>` adds that locus's own conversation, which is how its chat
                # pane follows a run without the Myriaxon session being switched to it.
                #
                # `?transcripts=a,b,c` adds several at once, which is what the pane wall needs. Both are
                # accepted so the single-pane page and the wall share one endpoint and one roster, and so a
                # roster can never disagree with the transcripts beside it.
                wanted = [n.strip() for n in ",".join(query.get("transcripts", [])).split(",") if n.strip()]
                return self._send_json(self.app._loci_payload(
                    query.get("transcript", [""])[0], wanted[:12]))
            if route == "/api/files":
                return self._list_files(query.get("path", [""])[0])
            if route == "/api/file":
                return self._read_file(query.get("path", [""])[0])
            if route == "/api/download":
                return self._download(query.get("path", [""])[0])
            if route == "/api/git":
                # Changed-file list for the explorer's Source-control view. The workspace is often a
                # subdirectory of the repository, so the query is made at the repository root while
                # paths are reported relative to the workspace -- which is what the explorer lists.
                repo = from_git.display_root(self.app.workspace)
                return self._send_json(from_git.status(self.app.workspace, repo=repo))
            if route == "/api/git/diff":
                path = query.get("path", [""])[0]
                staged = (query.get("staged", ["0"])[0] or "0") not in ("0", "", "false")
                repo = from_git.display_root(self.app.workspace)
                payload = from_git.diff(self.app.workspace, path, staged=staged, repo=repo)
                # Parsed hunks travel with the raw diff so the browser can colour lines without
                # re-implementing a unified-diff parser.
                payload["hunks"] = from_git.parse_unified(payload.get("diff") or "")
                return self._send_json(payload)
            if route == "/api/vertex-cache":
                return self._vertex_cache_get()

            if route == "/api/transparency":
                # GET reports the dial and the recent feed. The feed rides along with the dial rather than
                # living on its own route because a surface always wants both: the level with no events is a
                # blank panel, and events with no level cannot say why they stopped.
                #
                # A failure degrades to an explained empty payload rather than a 500. This panel is the one a
                # person opens when something is going wrong, so it must not be the thing that breaks.
                from .. import transparency

                try:
                    payload = transparency.describe()
                    payload["feed"] = [e.to_dict() for e in transparency.get().recent(limit=120)]
                except Exception as exc:  # noqa: BLE001
                    payload = {"level": 0, "max": transparency.MAX_LEVEL, "layers": [], "feed": [],
                               "error": f"{type(exc).__name__}: {exc}"}
                return self._send_json(payload)

            if route == "/api/mission-control":
                # Assembled server-side, never in the browser: the view must show what the machine
                # actually reports, and a client that computed its own totals could disagree with
                # the API it is displaying.
                #
                # A failure here degrades to an explained empty snapshot rather than a 500. This
                # view is the landing page, so an exception would leave the user on a blank screen
                # with no way to reach the chat either.
                try:
                    from ..mission_control import snapshot

                    return self._send_json(snapshot(self.app))
                except Exception as exc:  # noqa: BLE001
                    from ..logging_setup import logger as _logger

                    _logger.exception("mission-control snapshot failed")
                    # The same key set the real snapshot returns. A degraded payload missing a key
                    # is not a graceful failure -- the renderer reads it and throws, which blanks
                    # the landing page for a reason unrelated to the original error.
                    return self._send_json(
                        {
                            "generated_at": time.time(),
                            "workspace": str(self.app.workspace),
                            "error": f"{type(exc).__name__}: {exc}",
                            "health": {
                                "overall": "error",
                                "summary": "state unavailable â€” see the log",
                                "items": [],
                            },
                            "usage": {}, "runs": [], "approvals": [], "trace": [],
                            "schedules": [], "memory": {}, "skills": [], "routing": [],
                            "counts": {},
                        }
                    )
            return self._error(KeyError(f"no route {route}"), 404)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            if route == "/api/sessions":
                body = self._read_json()
                session = self.app.new_session(body.get("mode"))
                return self._send_json({"session": session.state.to_dict(), "config": self.app.config_payload()})
            if route == "/api/chat":
                return self._chat()
            if route == "/api/vertex-cache":
                return self._vertex_cache_post()

            if route == "/api/transparency":
                # Moves the dial. The body carries the level; anything unparseable leaves the dial where it is
                # and says so, because a slider that silently ignores a movement teaches the user that the
                # control is broken rather than that the value was wrong.
                from .. import transparency

                body = self._read_json()
                if "level" not in body:
                    return self._send_json({"ok": False, "error": "send {\"level\": 0-8}"}, status=400)
                try:
                    wanted = int(body["level"])
                except (TypeError, ValueError):
                    return self._send_json({"ok": False, "error": "level must be an integer"}, status=400)
                applied = transparency.set_level(wanted)
                payload = transparency.describe()
                payload["ok"] = True
                payload["applied"] = applied
                payload["clamped"] = applied != wanted
                payload["feed"] = [e.to_dict() for e in transparency.get().recent(limit=120)]
                return self._send_json(payload)

            if route == "/api/cancel":
                body = self._read_json()
                session = self.app.sessions.get(body.get("session", ""))
                if session is None:
                    return self._error(KeyError("unknown session"), 404)
                session.cancel()
                # A locus asked to run works in ITS OWN session, so cancelling the Myriaxon session
                # left it running -- reported as "stop does not stop the agent". "Stop" means stop the
                # work this dashboard started, and a locus turn is that work, so any *busy* session that
                # belongs to a locus is cancelled too. Only busy ones: cancelling an idle locus session
                # would arm its cancel flag for a turn nobody asked for.
                also_stopped: list[str] = []
                try:
                    for info in self.app.sessions.list():
                        if info["id"] == session.id:
                            continue
                        other = self.app.sessions.get(info["id"])
                        if other is None or not other.busy:
                            continue
                        if not getattr(other.state, "locus", ""):
                            continue
                        other.cancel()
                        also_stopped.append(other.state.locus)
                except Exception:  # noqa: BLE001 - stopping the named session already succeeded
                    pass
                # The loci registry is told as well, because `is_running()` reads the on-disk lease as
                # well as this process's flag: a cancelled turn releases its lease when the turn ends,
                # and until then the panel would otherwise still show "working".
                return self._send_json({"cancelled": True, "loci": also_stopped})
            if route == "/api/upload":
                return self._upload()
            if route == "/api/workspace":
                return self._open_workspace()
            if route == "/api/settings":
                return self._update_settings()
            if route == "/api/rules":
                return self._save_rules()
            if route == "/api/plugins/reload":
                return self._send_json(self.app.reload_plugins())
            if route == "/api/messaging":
                return self._send_json(self.app.save_messaging(self._read_json()))
            if route == "/api/inbound":
                # The messaging webhook. Always answers 200 with a JSON body: a provider retries a
                # non-2xx response, and a deliberately refused message must not be retried forever.
                payload = self._read_payload()
                headers = {key: value for key, value in self.headers.items()}
                try:
                    result = self.app.handle_inbound_message(payload, headers)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
                return self._send_json(result)
            if route == "/api/mcp":
                return self._save_mcp()
            if route == "/api/mcp/search":
                return self._search_mcp()
            if route == "/api/loci":
                return self._manage_loci()
            if route == "/api/endpoints":
                return self._save_endpoint()
            if route == "/api/endpoints/probe":
                return self._probe_endpoint()
            if route == "/api/endpoints/test":
                return self._test_endpoint()
            if route == "/api/vendor":
                return self._save_vendor_key()
            if route == "/api/model":
                return self._set_model()
            if route == "/api/mode":
                return self._set_mode()
            return self._error(KeyError(f"no route {route}"), 404)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            if route.startswith("/api/sessions/"):
                session_id = route.rsplit("/", 1)[-1]
                return self._send_json({"deleted": self.app.sessions.delete(session_id)})
            if route.startswith("/api/endpoints/"):
                name = urllib.parse.unquote(route.rsplit("/", 1)[-1])
                return self._send_json({"deleted": self.app.endpoints.remove(name)})
            return self._error(KeyError(f"no route {route}"), 404)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    # -- chat ---------------------------------------------------------------------
    def _chat(self) -> None:
        body = self._read_json()
        text = (body.get("message") or "").strip()
        session_id = body.get("session") or ""
        if not text:
            return self._error(ValueError("message is empty"), 400)

        session = self.app.sessions.get(session_id)
        if session is None:
            session = self.app.new_session(body.get("mode"))
            session_id = session.id

        # Slash commands are handled immediately, without a model call or the busy flag: they are
        # local state operations, so making the user wait for an agent turn would be wrong. The
        # results are published on the same event stream the UI already listens to.
        if commands_mod.is_command(text):
            session.bus.publish("command", text=text)
            outcome = commands_mod.execute(session, text)
            if outcome["severity"] == "error":
                # A single unrecognised word after the slash is a change of mind about the slash, not
                # a mistyped command. Measured: "/hi" answered "unknown command /hi -- try /help", so a
                # message the user meant to send never reached the model -- and the reader is told to
                # look for a typo in a command they never intended to use.
                #
                # Only a bare word falls through, and only when the command is unrecognised: a real
                # command that FAILS still reports its error (an error severity from execution is
                # indistinguishable here, and swallowing those would hide broken commands), and a
                # multi-word line is left to the command table because "ls /var/log" as a message is
                # likelier than "/foo bar" as one. The user-visible text loses nothing: it is the same
                # line, minus the slash that turned out not to be a command.
                words = text.split()
                if len(words) == 1 and words[0][1:].isidentifier():
                    stripped = words[0][1:]
                    session.bus.publish(
                        "notice",
                        text=f"'{text}' is not a command, so it was sent to the agent as a message.",
                        severity="output",
                    )
                    text = stripped
                    # Falls through to the ordinary submit path below.
                else:
                    session.bus.publish(
                        "notice",
                        text=outcome["output"],
                        severity="output" if outcome["severity"] == "normal" else outcome["severity"],
                    )
                    session.bus.publish("command_result", result="error")
                    try:
                        self.app.sessions.save(session.id)
                    except Exception:  # noqa: BLE001 - a failed save is a lost transcript, not a failed command
                        pass
                    return self._send_json(
                        {
                            "accepted": True,
                            "command": True,
                            "output": outcome["output"],
                            "severity": outcome["severity"],
                            "session": session.state.to_dict(),
                        }
                    )
            else:
                session.bus.publish(
                    "notice",
                    text=outcome["output"],
                    severity="output" if outcome["severity"] == "normal" else outcome["severity"],
                )
                if outcome.get("rebuilt"):
                    session.bus.publish("status", text=f"{session.config.provider}:{session.state.model} ({session.mode})")
                session.bus.publish("command_result", result="ok")
                # Persisted here too, not only after a model turn. A command changes real state -- a
                # mode switch, a cleared conversation -- and without this a session that had only ever
                # run commands was never written to disk, so it vanished on restart. Found by asserting
                # a session file exists after `/help`, which is exactly the case that had none.
                try:
                    self.app.sessions.save(session.id)
                except Exception:  # noqa: BLE001 - a failed save is a lost transcript, not a failed command
                    pass
                return self._send_json(
                    {
                        "accepted": True,
                        "command": True,
                        "output": outcome["output"],
                        "severity": outcome["severity"],
                        "session": session.state.to_dict(),
                    }
                )

        attachments = body.get("attachments") or []
        if attachments:
            # The agent understands @path tokens; the UI sends real paths after uploading, so the
            # message is composed here rather than making the browser know the syntax.
            markers = " ".join(f'@"{path}"' for path in attachments)
            text = f"{markers}\n\n{text}"

        accepted = session.submit(text, model=body.get("model"), mode=body.get("mode"))
        if not accepted:
            return self._send_json({"accepted": False, "reason": "a turn is already running", "session": session.state.to_dict()}, 409)
        return self._send_json({"accepted": True, "session": session.state.to_dict()})

    def _open_workspace(self) -> None:
        body = self._read_json()
        target = (body.get("path") or "").strip()
        if not target:
            return self._error(ValueError("path is required"), 400)
        try:
            opened = self.app.open_workspace(target)
        except (FileNotFoundError, NotADirectoryError) as exc:
            return self._error(exc, 400)
        except OSError as exc:
            return self._error(exc, 400)
        return self._send_json({"workspace": str(opened), "config": self.app.config_payload()})

    def _update_settings(self) -> None:
        body = self._read_json()
        # `self` here is the HTTP handler, not the application -- state lives on `self.app`. Getting
        # this wrong surfaced as a 500 ("'BoundHandler' object has no attribute 'settings'").
        store = self.app.settings
        before = store.get().public()
        updated = store.update(body)
        after = updated.public()

        # A setting that changes how the agent is built must invalidate the built agents, or the
        # change would appear to do nothing until the session is recreated. Display-only settings
        # (theme, density) deliberately do not, since rebuilding an agent for a colour is waste.
        agent_affecting = {"workflow", "thinking", "effort", "max_tokens", "yolo", "auto_compact"}
        changed = {key for key in agent_affecting if before.get(key) != after.get(key)}
        rebuilt = 0
        if changed:
            for info in self.app.sessions.list():
                session = self.app.sessions.get(info["id"])
                if session is None:
                    continue
                session.capture_history()
                session.agent = None
                rebuilt += 1
        return self._send_json(
            {"settings": after, "rebuilt_sessions": rebuilt, "agent_affecting": sorted(changed)}
        )

    def _save_rules(self) -> None:
        """Replace the user layer's permission rules and reload the affected sessions."""
        body = self._read_json()
        rules = body.get("rules")
        if not isinstance(rules, dict):
            return self._error(ValueError("rules must be an object of {tool_or_tool:pattern: decision}"), 400)
        try:
            snapshot = self.app.policy.save(rules)
        except ValueError as exc:
            return self._error(exc, 400)
        # Rules are read from settings.json when an agent is built, so a live agent still holds the
        # old policy. Rebuilding keeps the transcript and makes the change take effect immediately.
        self._invalidate_agents()
        return self._send_json({"rules": snapshot, "rebuilt_sessions": len(self.app.sessions.list())})

    def _manage_loci(self) -> None:
        """Create, edit, run or delete a persistent agent from the panel.

        Every action goes through :mod:`myriaxon.loci`, the same module the CLI's `/loci` command
        and the agent's own tools use. Nothing about a locus behaves differently depending on which
        surface created it, which is the point: a locus is state, and the surfaces only render it.

        ``run`` is the one action that touches a session, and it deliberately routes through the
        ordinary chat path rather than running a turn in the request handler. A dashboard turn can
        take minutes; the browser's only way to watch one is the SSE stream, so doing the work here
        would block the request and show the user nothing until it finished.
        """
        from ..loci import GOAL_STATES, get_registry

        body = self._read_json()
        action = str(body.get("action") or "").strip()
        registry = get_registry()
        registry.reload()  # another process may have changed things since the last render

        if action == "template":
            # One-click bot from the gallery. The template carries the instructions, which is the
            # part that is actually hard to write; the panel should not have to send them back.
            key = str(body.get("template") or "").strip()
            try:
                from ..bot_templates import create as create_from_template
                from ..bot_templates import get as get_template
            except Exception as exc:  # noqa: BLE001
                return self._error(RuntimeError(f"bot templates unavailable: {exc}"), 500)
            template = get_template(key)
            if template is None:
                return self._error(KeyError(f"no bot template named {key!r}"), 404)
            try:
                locus, was_created = create_from_template(template)
            except ValueError as exc:
                return self._error(exc, 400)
            return self._send_json({
                "ok": True,
                "created": was_created,
                "locus": locus.name,
                "loci": self.app._loci_payload(),
            })

        if action == "create":
            name = str(body.get("name") or "").strip()
            if not name:
                return self._error(ValueError("a locus needs a name"), 400)
            # Validated before creation, like every other field here, so a bad mode does not leave a
            # locus behind that the caller then has to notice and delete.
            wanted_mode = str(body.get("autonomy") or "").strip().lower()
            if wanted_mode:
                from ..loci import AUTONOMY_MODES

                if wanted_mode not in AUTONOMY_MODES:
                    return self._error(
                        ValueError(f"autonomy must be one of {', '.join(AUTONOMY_MODES)}"), 400
                    )
            try:
                created = registry.create(
                    name,
                    role=str(body.get("role") or "generalist"),
                    instructions=str(body.get("instructions") or ""),
                    goals=[g for g in (body.get("goals") or []) if str(g).strip()],
                    proactive=bool(body.get("proactive")),
                    interval_seconds=int(body.get("interval_seconds") or 900),
                )
            except ValueError as exc:
                return self._error(exc, 400)
            # The mode is applied AFTER creation rather than passed through, because `Registry.create`
            # has a fixed signature and adding a parameter to it would make every existing caller
            # responsible for a field only this endpoint sets. Persisted immediately: a locus that
            # reports self-directed until the process restarts is worse than one that never offered it.
            if wanted_mode:
                created.autonomy = wanted_mode
                registry.persist(created)
            return self._send_json({"ok": True, "loci": self.app._loci_payload()})

        # Validated before the locus is looked up. Resolving the locus first meant a typo in `action`
        # on a misspelled locus name reported "no such locus", which sends the caller to fix the wrong
        # thing -- the action was the mistake, and that is what should be named.
        known = {"goal_add", "goal_status", "toggle", "delete", "run"}
        if action not in known:
            return self._error(
                ValueError(f"unknown loci action {action!r}; expected one of {', '.join(sorted(known))}"), 400
            )

        locus = registry.get(str(body.get("locus") or ""))
        if locus is None:
            return self._error(KeyError(f"no locus named {body.get('locus')!r}"), 404)

        if action == "goal_add":
            title = str(body.get("title") or "").strip()
            if not title:
                return self._error(ValueError("the objective needs a title"), 400)
            locus.add_goal(title, str(body.get("detail") or ""))
            registry.persist(locus)

        elif action == "goal_status":
            status = str(body.get("status") or "")
            if status not in GOAL_STATES:
                return self._error(ValueError(f"status must be one of {', '.join(GOAL_STATES)}"), 400)
            goal = locus.set_goal_status(str(body.get("goal") or ""), status, str(body.get("note") or ""))
            if goal is None:
                return self._error(KeyError(f"no objective matching {body.get('goal')!r}"), 404)
            registry.persist(locus)

        elif action == "toggle":
            # `enabled` gates whether it runs at all; `proactive` gates whether it runs unbidden.
            # Both are exposed because "stop it for now" and "stop it waking up on its own" are
            # different requests and conflating them makes one of the two impossible to express.
            #
            # `autonomy` is the third, and it is validated BEFORE anything is written: a rejected
            # value must not leave the other fields applied, or a refused request would change half
            # its intent. That is the same rule `set_goal_status` follows for completion authority.
            changes: list[str] = []
            if "autonomy" in body:
                from ..loci import AUTONOMY_MODES

                wanted = str(body["autonomy"] or "").strip().lower()
                if wanted not in AUTONOMY_MODES:
                    return self._error(
                        ValueError(f"autonomy must be one of {', '.join(AUTONOMY_MODES)}, not {wanted!r}"),
                        400,
                    )
                locus.autonomy = wanted
                changes.append(f"autonomy={wanted}")
            if "max_steps_per_run" in body:
                from ..loci import MAX_STEPS_PER_RUN_CEILING

                try:
                    steps = int(body["max_steps_per_run"])
                except (TypeError, ValueError):
                    return self._error(ValueError("max_steps_per_run must be a whole number"), 400)
                steps = max(1, min(steps, MAX_STEPS_PER_RUN_CEILING))
                locus.max_steps_per_run = steps
                changes.append(f"max_steps_per_run={steps}")
            for field_name in ("enabled", "proactive"):
                if field_name in body:
                    setattr(locus, field_name, bool(body[field_name]))
                    changes.append(f"{field_name}={getattr(locus, field_name)}")
            locus.log("note", ", ".join(changes) or "no change")
            registry.persist(locus)

        elif action == "delete":
            registry.delete(locus.id)

        elif action == "run":
            message = str(body.get("message") or "").strip()
            return self._send_json(self.app.run_locus(locus, message))

        return self._send_json({"ok": True, "loci": self.app._loci_payload()})

    def _save_mcp(self) -> None:
        """Add or remove an MCP server from the UI.

        Uses the same helpers the CLI's `/mcp add` uses, so a server added here is identical to one
        added in the terminal. A newly added server needs a session restarted before its tools exist,
        because the tool list is built when the agent is constructed -- that is reported rather than
        hidden, and the affected sessions are invalidated here so the next message picks it up.
        """
        from ..mcp_client import (
            add_stdio_server,
            add_url_server,
            load_mcp_config,
            remove_server,
            resolve_registry_stdio_spec,
            resolve_registry_url_spec,
        )

        body = self._read_json()
        action = (body.get("action") or "add").lower()

        if action == "remove":
            name = str(body.get("name") or "").strip()
            if not name:
                return self._error(ValueError("name is required"), 400)
            removed = remove_server(name)
            self._invalidate_agents()
            return self._send_json({"removed": removed, "config": load_mcp_config()})

        if action == "add":
            name = str(body.get("name") or "").strip()
            if not name:
                return self._error(ValueError("name is required"), 400)
            kind = str(body.get("kind") or "url").lower()
            error = None
            if kind == "stdio":
                command = str(body.get("command") or "").strip()
                if not command:
                    return self._error(ValueError("command is required for a stdio server"), 400)
                raw_args = body.get("args") or []
                if isinstance(raw_args, str):
                    raw_args = [a for a in raw_args.split() if a]
                error = add_stdio_server(name, command, [str(a) for a in raw_args], None)
            else:
                url = str(body.get("url") or "").strip()
                if not url:
                    return self._error(ValueError("url is required"), 400)
                if not url.startswith(("http://", "https://")):
                    return self._error(ValueError("url must start with http:// or https://"), 400)
                error = add_url_server(name, url, token=str(body.get("token") or "").strip())
            if error:
                return self._error(ValueError(error), 400)
            self._invalidate_agents()

            # Report an unusable configuration when it is created, rather than leaving the user to
            # wonder why their Figma or Microsoft 365 server contributes no tools. A warning, not an
            # error: the config is still saved and works once the SDK extra is installed.
            warning = ""
            if kind != "stdio":
                from ..mcp_client import remote_transport_support

                support = remote_transport_support()
                usable = [key for key, ok in support.items() if ok]
                if not usable:
                    warning = (
                        "no remote MCP transport is installed, so this server cannot connect yet -- "
                        "run: pip install -e .[mcp]"
                    )
                else:
                    warning = f"remote transports available: {', '.join(usable)}"
            return self._send_json(
                {"added": name, "config": load_mcp_config(), "restart_required": True,
                 "transport_warning": warning}
            )

        if action == "catalog_enable":
            return self._catalog_enable(body)
        if action == "catalog_disable":
            return self._catalog_disable(body)

        if action == "add_from_registry":
            entry = body.get("server") or {}
            if not isinstance(entry, dict):
                return self._error(ValueError("server entry is required"), 400)
            spec = resolve_registry_stdio_spec(entry)
            if spec:
                error = add_stdio_server(spec["name"], spec["command"], spec.get("args") or [], spec.get("env"))
            else:
                url_spec = resolve_registry_url_spec(entry)
                if not url_spec:
                    return self._error(
                        ValueError("that registry entry has no installable stdio or url spec"), 400
                    )
                error = add_url_server(url_spec["name"], url_spec["url"])
            if error:
                return self._error(ValueError(error), 400)
            self._invalidate_agents()
            return self._send_json({"config": load_mcp_config(), "restart_required": True})

        return self._error(ValueError(f"unknown action {action!r}"), 400)

    def _catalog_enable(self, body: dict) -> None:
        """Install a catalog entry, substituting whatever values the user supplied.

        This is the "turn it on and it works" path: for the seven entries that need nothing, the payload
        is just a key. For the rest, the required fields are named in the error rather than producing a
        server that fails to connect for reasons the user cannot see.
        """
        from ..mcp_catalog import by_key, resolve
        from ..mcp_client import add_stdio_server, add_url_server, load_mcp_config

        key = str(body.get("key") or "").strip()
        entry = by_key(key)
        if entry is None:
            return self._error(ValueError(f"no catalog entry named {key!r}"), 404)

        name = str(body.get("name") or entry.key).strip()
        try:
            server = resolve(entry, body.get("values") or {}, name=name)
        except ValueError as exc:
            return self._error(exc, 400)

        if entry.transport == "stdio":
            error = add_stdio_server(
                server["name"], server["command"], server.get("args") or [], server.get("env")
            )
        else:
            error = add_url_server(server["name"], server["url"], token=server.get("token", ""))
        if error:
            return self._error(ValueError(error), 400)

        self._invalidate_agents()
        payload = self.app._mcp_payload()
        payload["enabled"] = entry.key
        payload["restart_required"] = True
        return self._send_json(payload)

    def _catalog_disable(self, body: dict) -> None:
        """Remove an installed catalog entry."""
        from ..mcp_client import load_mcp_config, remove_server

        key = str(body.get("key") or "").strip()
        if not key:
            return self._error(ValueError("key is required"), 400)
        removed = remove_server(key)
        self._invalidate_agents()
        payload = self.app._mcp_payload()
        payload["disabled"] = key
        payload["removed"] = removed
        return self._send_json(payload)

    def _search_mcp(self) -> None:
        """Search the public MCP registry, so the UI can offer installable servers by name."""
        from ..mcp_client import search_registry

        body = self._read_json()
        query = str(body.get("query") or "").strip()
        if not query:
            return self._error(ValueError("query is required"), 400)
        limit = int(body.get("limit") or 10)
        try:
            results = search_registry(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "servers": []})
        # Only the fields the panel renders, so a large registry payload does not flood the browser.
        servers = [
            {
                "name": entry.get("name") or entry.get("id") or "",
                "description": (entry.get("description") or "")[:220],
                "url": entry.get("url") or entry.get("repository", {}).get("url", "") if isinstance(entry.get("repository"), dict) else entry.get("url", ""),
            }
            for entry in results
        ]
        return self._send_json({"ok": True, "servers": servers})

    def _invalidate_agents(self) -> None:
        """Handler-side convenience, delegating to the application's single implementation.

        The logic used to live here, which meant anything reached from DashboardApp itself (plugin
        reload, for one) raised AttributeError -- this `self` is the request handler, not the app.
        """
        self.app.invalidate_agents()

    def _save_endpoint(self) -> None:
        body = self._read_json()
        action = (body.get("action") or "upsert").lower()
        if action == "delete":
            name = str(body.get("name") or "").strip().lower()
            return self._send_json({"deleted": self.app.endpoints.remove(name),
                                    "endpoints": self.app.endpoints.list()})
        try:
            endpoint = self.app.endpoints.upsert(body)
        except ValueError as exc:
            return self._error(exc, 400)
        return self._send_json({"endpoint": endpoint.public(), "endpoints": self.app.endpoints.list()})

    def _probe_endpoint(self) -> None:
        """Ask an endpoint what models it serves, so the user can pick instead of typing ids.

        Deliberately a separate call from saving: a gateway may be unreachable at the moment it is
        configured, and the user should still be able to save it and try again later.
        """
        body = self._read_json()
        base_url = str(body.get("base_url") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        # An edit form never receives the stored key, so fall back to it by name.
        name = str(body.get("name") or "").strip().lower()
        if not api_key and name:
            existing = self.app.endpoints.get(name)
            if existing is not None:
                api_key = existing.api_key
        if not base_url:
            return self._error(ValueError("base_url is required"), 400)
        if not base_url.startswith(("http://", "https://")):
            return self._error(ValueError("base_url must start with http:// or https://"), 400)

        url = base_url.rstrip("/") + "/models"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            hint = ""
            if exc.code in (401, 403):
                hint = " -- the endpoint rejected the API key"
            return self._send_json({"ok": False, "status": exc.code,
                                    "error": f"HTTP {exc.code}{hint}", "models": []})
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}", "models": []})

        entries = payload.get("data") if isinstance(payload, dict) else None
        models: list[str] = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("id"):
                    models.append(str(entry["id"]))
                elif isinstance(entry, str):
                    models.append(entry)
        elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
            models = [str(m) for m in payload["models"]]
        return self._send_json({"ok": True, "models": sorted(models), "count": len(models)})

    def _test_endpoint(self) -> None:
        """Send one real message to an endpoint before the user commits to it.

        A probe that lists models proves the URL and key are valid; this proves the chat path works
        end to end, which is what the agent will actually use. Failures are reported as data rather
        than an HTTP error so the form can show why.
        """
        body = self._read_json()
        base_url = str(body.get("base_url") or "").strip()
        api_key = str(body.get("api_key") or "").strip()
        model = str(body.get("model") or "").strip()
        name = str(body.get("name") or "").strip().lower()
        if not api_key and name:
            existing = self.app.endpoints.get(name)
            if existing is not None:
                api_key = existing.api_key
        if not (base_url and model):
            return self._error(ValueError("base_url and model are required"), 400)

        try:
            from ..direct_http_client import DirectOpenAI

            client = DirectOpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=0)
            try:
                reply = ""
                for chunk in client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with exactly: ok"}],
                    max_tokens=20,
                    stream=True,
                ):
                    if chunk.choices:
                        reply += chunk.choices[0].delta.content or ""
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return self._send_json({"ok": True, "reply": reply.strip()[:200], "model": model})

    def _save_vendor_key(self) -> None:
        """Choose DeepSeek or Netra and, when the key is missing, take one typed in the browser.

        The key is checked against the provider before it is written, which is the whole reason this
        is a POST and not a settings field: a key that is stored unchecked surfaces as a 401 in the
        middle of the user's first real task, and the message names the HTTP status rather than the
        typo. One cheap request here turns that into "that key was refused" at the moment it was
        entered.

        It is written to the SAVED config, not to `.env`. `.env` is the user's file and belongs to
        them; a dashboard writing credentials into it would also make the choice impossible to change
        afterwards, because `.env` wins over everything.
        """
        from ..config import Config, load_config, save_config
        from ..constants import (
            DEEPSEEK_API_KEY_ENV_FALLBACK,
            DEFAULT_DEEPSEEK_BASE_URL,
            DEFAULT_DEEPSEEK_MODEL,
            DEFAULT_NETRA_BASE_URL,
            DEFAULT_NETRA_MODEL,
            ENV_PROVIDER,
            NETRA_API_KEY_ENV_FALLBACK,
            PROVIDER_DEEPSEEK,
            PROVIDER_NETRA,
            PROVIDER_OLLAMA,
        )

        body = self._read_json()
        provider = str(body.get("provider") or "").strip().lower()
        if provider not in (PROVIDER_DEEPSEEK, PROVIDER_NETRA, PROVIDER_OLLAMA):
            return self._error(
                ValueError(
                    f"provider must be {PROVIDER_DEEPSEEK!r}, {PROVIDER_NETRA!r} or {PROVIDER_OLLAMA!r}"
                ),
                400,
            )
        provided = str(body.get("api_key") or "").strip()
        state = _vendor_key_state(self.app.config)
        have = provided or (
            (self.app.config.api_key if self.app.config.provider == provider else "") or ""
        )
        if not have:
            key_env = (
                DEEPSEEK_API_KEY_ENV_FALLBACK if provider == PROVIDER_DEEPSEEK
                else NETRA_API_KEY_ENV_FALLBACK if provider == PROVIDER_NETRA
                else ""
            )
            # The per-provider variable first, then the generic one. Only the generic name was checked
            # before, so a key sitting in DEEPSEEK_API_KEY -- which is how a `.env` supplies it -- was
            # reported as missing while the picker showed "key ready".
            if key_env:
                have = (os.environ.get(key_env) or "").strip()
            have = have or (os.environ.get("MYRIAXON_API_KEY") or "").strip() or (
                "ollama" if provider == PROVIDER_OLLAMA else ""
            )

        if not have:
            return self._send_json(
                {"ok": False, "needs_key": True, "provider": provider,
                 "message": f"{provider} needs an API key before it can be used."}
            )

        if provided:
            # One request, no retries: the point is a fast, unambiguous answer, and a retry loop here
            # would make the button feel broken when the key is simply wrong.
            ok, detail = _check_vendor_key(provider, provided)
            if not ok:
                return self._send_json(
                    {"ok": False, "needs_key": True, "provider": provider, "message": detail}, 200
                )
            # The checked key IS the key: written through the app so the choice is durable and the
            # running sessions are rebuilt against it.
            try:
                from ..config import Config, save_config

                save_config(Config(
                    api_key=provided,
                    base_url=self.app.config.base_url if self.app.config.provider == provider
                    else (DEFAULT_DEEPSEEK_BASE_URL if provider == PROVIDER_DEEPSEEK
                          else DEFAULT_NETRA_BASE_URL),
                    model=self.app.config.model if self.app.config.provider == provider
                    else (DEFAULT_DEEPSEEK_MODEL if provider == PROVIDER_DEEPSEEK
                          else DEFAULT_NETRA_MODEL),
                    provider=provider,
                ))
            except Exception:  # noqa: BLE001 - the switch below still applies for this process
                pass

        # One implementation, on the application. See `set_vendor` for why this is not done here.
        ok, problem = self.app.set_vendor(provider)
        if not ok:
            return self._send_json(
                {"ok": False, "needs_key": True, "provider": provider, "message": problem}, 200
            )
        config = self.app.config
        # `self.app.config_payload()`, not `self.config_payload()`: `config_payload` is a method on
        # DashboardApp, and the handler does not inherit from it. This is the SECOND line of this
        # feature to make the same mistake -- the first was `self.config`, which the user reported as
        # "'BoundHandler' object has no attribute 'config'". The class boundary is easy to cross
        # because both objects are called `self` at their own definition site, so the rule is worth
        # stating: on a Handler, every piece of application state is one `.app` away.
        payload = self.app.config_payload()
        return self._send_json(
            {
                "ok": True,
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "from_env": bool(os.environ.get(ENV_PROVIDER)),
                "message": problem,
                "config": payload,
            }
        )

    def _set_model(self) -> None:
        body = self._read_json()
        session = self.app.sessions.get(body.get("session", ""))
        model = (body.get("model") or "").strip()
        if not model:
            return self._error(ValueError("model is empty"), 400)
        if session is None:
            return self._error(KeyError("unknown session"), 404)
        # Capture the transcript BEFORE discarding the agent, or the conversation goes with it.
        # The rebuilt agent is seeded from this, so switching model mid-session keeps its context.
        session.capture_history()
        session.config = _with_model(session.config, model)
        session.agent = None
        session.state.model = model
        return self._send_json({"model": model, "kept_history": len(session.history)})

    def _set_mode(self) -> None:
        body = self._read_json()
        session = self.app.sessions.get(body.get("session", ""))
        mode = (body.get("mode") or "").strip()
        if session is None:
            return self._error(KeyError("unknown session"), 404)
        from ..constants import MODES

        if mode not in MODES:
            return self._error(ValueError(f"unknown mode {mode!r}"), 400)
        session.capture_history()
        session.mode = mode
        session.state.mode = mode
        # Mode decides which tools the agent is given, so it is baked in at construction time.
        session.agent = None
        return self._send_json({"mode": mode, "kept_history": len(session.history)})

    # -- SSE ----------------------------------------------------------------------
    def _stream_transparency(self) -> None:
        """Live activity, one server-sent event per thing that happens.

        Same shape as `_stream_events` and for the same reasons: a heartbeat so an idle stream is not closed by
        a proxy, and a `finally` that unsubscribes so a browser tab closing does not leak a queue into the
        broadcaster for the life of the process.

        The dial is sent FIRST, before any event, so a surface that connects mid-run can label what it is about
        to receive. Without it the client knows events are arriving but not which ones are being withheld, and
        "nothing is happening" becomes indistinguishable from "the level is too low to show it".
        """
        from .. import transparency

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        broadcaster = transparency.get()
        subscriber = broadcaster.subscribe()
        try:
            # The dial, then whatever is already buffered, then live. A panel that opened after the interesting
            # part should still see it.
            if not self._write_raw(f"data: {json.dumps({'type': 'dial', **broadcaster.describe()}, default=str)}\n\n"):
                return
            for event in reversed(broadcaster.recent(limit=40)):
                if not self._write_raw(transparency.as_sse(event)):
                    return
            while True:
                try:
                    event = subscriber.popleft()
                except IndexError:
                    time.sleep(0.25)
                    if not self._write_raw(": ping\n\n"):
                        return
                    continue
                if not self._write_raw(transparency.as_sse(event)):
                    return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            broadcaster.unsubscribe(subscriber)

    def _stream_events(self, session_id: str) -> None:
        session = self.app.sessions.get(session_id)
        if session is None:
            return self._error(KeyError("unknown session"), 404)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        subscriber, replay = session.bus.subscribe()
        try:
            for event in replay:
                if not self._write_event(event):
                    return
            while True:
                try:
                    event = subscriber.get(timeout=15.0)
                except Exception:  # queue.Empty
                    # Heartbeat: keeps proxies and browsers from closing an idle stream.
                    if not self._write_raw(": ping\n\n"):
                        return
                    continue
                if event is None:
                    self._write_event({"type": "end", "seq": 0, "ts": time.time()})
                    return
                if not self._write_event(event):
                    return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            session.bus.unsubscribe(subscriber)

    def _write_event(self, event: dict) -> bool:
        payload = json.dumps(event, default=str)
        return self._write_raw(f"data: {payload}\n\n")

    def _write_raw(self, chunk: str) -> bool:
        try:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    # -- files --------------------------------------------------------------------
    def _list_files(self, relative: str) -> None:
        target = self.app.safe_path(relative)
        if not target.exists():
            return self._error(FileNotFoundError(str(relative)), 404)
        if target.is_file():
            return self._send_json({"files": [self._file_entry(target)]})
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if child.name in (".git", "__pycache__", ".venv", "node_modules"):
                continue
            entries.append(self._file_entry(child))
        return self._send_json({"path": relative, "files": entries})

    def _file_entry(self, path: Path) -> dict:
        try:
            stat = path.stat()
        except OSError:
            return {"name": path.name, "error": "unreadable"}
        return {
            "name": path.name,
            "path": str(path.relative_to(self.app.workspace)).replace("\\", "/") if self.app.workspace in path.parents or path == self.app.workspace else str(path),
            "is_dir": path.is_dir(),
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }

    def _read_file(self, relative: str) -> None:
        target = self.app.safe_path(relative)
        if not target.is_file():
            return self._error(FileNotFoundError(str(relative)), 404)
        if target.stat().st_size > 2 * 1024 * 1024:
            return self._send_json({"path": relative, "too_large": True, "size": target.stat().st_size})
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._error(exc)
        return self._send_json({"path": relative, "text": text})

    def _download(self, relative: str) -> None:
        target = self.app.safe_path(relative)
        if not target.is_file():
            return self._error(FileNotFoundError(str(relative)), 404)
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _upload(self) -> None:
        """Accept a raw upload with the filename in a header, so no multipart parser is needed."""
        filename = urllib.parse.unquote(self.headers.get("X-Filename") or "upload.bin")
        # Strip any directory component: the client must not choose where the file lands.
        filename = posixpath.basename(filename.replace("\\", "/")) or "upload.bin"
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._error(ValueError("empty upload"), 400)
        if length > MAX_UPLOAD_BYTES:
            return self._error(ValueError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes"), 413)

        data = self.rfile.read(length)
        # Resolved lazily and re-tried here: the directory may have been removed, or the config
        # directory may have become writable/unwritable between requests.
        target_dir = self.app.uploads_dir
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.app.uploads.rework(self.app.workspace)
            target_dir = self.app.uploads_dir
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return self._error(RuntimeError(f"no writable upload directory ({exc})"), 500)
        target = target_dir / f"{int(time.time())}_{filename}"
        try:
            target.write_bytes(data)
        except OSError as exc:
            return self._error(RuntimeError(f"could not store upload: {exc}"), 500)
        return self._send_json(
            {
                "path": str(target),
                "name": filename,
                "size": len(data),
                "is_image": target.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"),
            }
        )


def _providers() -> list[str]:
    """Every provider the dashboard can switch to, in a stable order.

    Listed from the constants the CLI resolves against, so the dropdown cannot offer a provider the
    CLI would reject or omit one it supports.
    """
    from ..constants import (
        PROVIDER_ANTHROPIC,
        PROVIDER_DEEPSEEK,
        PROVIDER_GEMINI,
        PROVIDER_NETRA,
        PROVIDER_OLLAMA,
        PROVIDER_OPENAI_COMPAT,
        PROVIDER_OPENROUTER,
    )

    return [
        PROVIDER_GEMINI,
        PROVIDER_NETRA,
        PROVIDER_DEEPSEEK,
        PROVIDER_OPENROUTER,
        PROVIDER_ANTHROPIC,
        PROVIDER_OPENAI_COMPAT,
        # Last because it is the only one that may not exist on this machine. It is still listed
        # unconditionally: a user who has Ollama should find it here without also discovering a
        # separate command, and a user who does not gets a dropdown entry that explains itself when
        # selected rather than a mystery absence.
        PROVIDER_OLLAMA,
    ]


def _command_catalogue() -> list[dict]:
    """The slash commands the composer may suggest. Degrades to an empty list, never raises.

    A missing suggestion menu is a smaller failure than a dashboard that will not load, and this is
    called on every config fetch.
    """
    try:
        from .commands import catalogue

        return catalogue()
    except Exception:  # noqa: BLE001
        return []


def _models_for(config: Any, endpoints: Any = None) -> list[str]:
    """Model choices for the active provider, from the same constants the CLI's wizard and
    /models command use. The configured model is always included, even if it is not in the
    curated shortlist, so a working setup is never made unselectable.

    A user-defined endpoint's own model list wins, since the built-in shortlists describe services
    this endpoint is not.
    """
    custom = _models_for_endpoint(endpoints, config.provider)
    if custom:
        models = list(custom)
        if config.model and config.model not in models:
            models = [config.model] + models
        return models

    from ..constants import (
        DEEPSEEK_MODELS,
        NETRA_MODELS,
        OPENROUTER_FAVORITE_MODELS,
        PROVIDER_DEEPSEEK,
        PROVIDER_GEMINI,
        PROVIDER_NETRA,
        PROVIDER_OPENROUTER,
    )

    by_provider = {
        PROVIDER_DEEPSEEK: list(DEEPSEEK_MODELS),
        PROVIDER_NETRA: list(NETRA_MODELS),
        PROVIDER_OPENROUTER: list(OPENROUTER_FAVORITE_MODELS),
        PROVIDER_GEMINI: [config.model],
    }
    models = by_provider.get(config.provider, [])
    if config.model and config.model not in models:
        models = [config.model] + models
    return models


def _models_for_endpoint(store: Any, name: str) -> list[str]:
    """Model choices for an endpoint name, whether built-in or user-defined."""
    endpoint = store.get(name) if store is not None else None
    if endpoint is not None:
        return list(endpoint.models) or ([endpoint.model] if endpoint.model else [])
    return []


def _check_vendor_key(provider: str, api_key: str) -> tuple[bool, str]:
    """One request to the provider to see whether this key works. Never raises.

    Returns (ok, message). This exists so a typed key is judged where it is typed: without it the key
    is stored unverified and the mistake surfaces as `401 missing or malformed key` in the middle of
    the user's first real task, which names an HTTP status instead of the thing they got wrong.

    A network failure is reported as "could not verify" and the key is still accepted -- the user's
    key is not this program's to refuse because a firewall was in the way. Only an explicit 401/403
    rejects it.
    """
    import json as _json
    import urllib.error
    import urllib.request

    from ..constants import (
        DEFAULT_DEEPSEEK_BASE_URL,
        DEFAULT_NETRA_BASE_URL,
        PROVIDER_DEEPSEEK,
    )

    base = DEFAULT_DEEPSEEK_BASE_URL if provider == PROVIDER_DEEPSEEK else DEFAULT_NETRA_BASE_URL
    request = urllib.request.Request(
        base.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            _json.loads(response.read().decode("utf-8", "replace") or "{}")
        return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, f"{provider} refused that key (HTTP {exc.code}). Check it and try again."
        return True, f"{provider} answered HTTP {exc.code}; the key was saved without being verified."
    except Exception as exc:  # noqa: BLE001 - unverifiable is not the same as wrong
        return True, f"could not reach {provider} to verify the key ({type(exc).__name__}); it was saved unverified."


def _vendor_key_state(config: Any) -> dict:
    """Which of the two DeepSeek gateways can be used right now, and where the key comes from.

    `deepseek` (DeepSeek's own API) and `netra` (the gateway that fronts the same weights) are the
    two the picker offers. A key counts as present when the environment has one -- which is how a
    `.env` file supplies it -- or when the saved configuration holds one for that provider, which is
    how a key typed into this dashboard is remembered.

    Booleans and a source label only. Never the key: this reaches the browser on every page load, and
    a payload that carries a credential is a credential in the browser's memory, its devtools and any
    HAR file someone saves while debugging.
    """
    from ..config import load_config
    from ..constants import (
        DEEPSEEK_API_KEY_ENV_FALLBACK,
        NETRA_API_KEY_ENV_FALLBACK,
        PROVIDER_DEEPSEEK,
        PROVIDER_NETRA,
    )

    stored = load_config()
    state: dict[str, dict] = {}
    for provider, env_name in (
        (PROVIDER_DEEPSEEK, DEEPSEEK_API_KEY_ENV_FALLBACK),
        (PROVIDER_NETRA, NETRA_API_KEY_ENV_FALLBACK),
    ):
        from_env = bool((os.environ.get(env_name) or "").strip())
        # `MYRIAXON_API_KEY` is the generic override and applies to whichever provider is active, so it
        # only counts for the provider currently in use.
        generic = bool((os.environ.get("MYRIAXON_API_KEY") or "").strip()) and config.provider == provider
        from_config = bool(
            stored is not None and stored.provider == provider and (stored.api_key or "").strip()
        )
        state[provider] = {
            "has_key": from_env or generic or from_config,
            "source": "environment" if (from_env or generic) else ("saved" if from_config else ""),
        }
    return state


def _env_names_provider(provider: str) -> bool:
    """Whether the environment's provider setting refers to the SAME provider we are switching to.

    True when `MYRIAXON_PROVIDER` names this provider, and when nothing names a provider at all --
    in the second case the base-url and model overrides are the only instruction available, which is
    the "point one command at another endpoint" case they exist for.

    False when the environment names a DIFFERENT provider, because then those overrides describe
    that other provider's host and model. This is the same rule `config.resolve_config` applies to
    the stored configuration ("when the environment names a DIFFERENT provider than the stored one,
    the stored provider-specific values must not be reused"); the dashboard's switch simply did not
    apply it to the environment.
    """
    from ..constants import ENV_PROVIDER

    named = (os.environ.get(ENV_PROVIDER) or "").strip().lower()
    if not named:
        return True
    return named == provider


def _switch_provider(config: Any, provider: str, endpoints: Any = None) -> Any:
    """Point a config at a different provider, remapping endpoint, model and credential.

    Changing only the provider name is actively harmful: the stored base_url belongs to the previous
    provider, so requests go to the wrong host and fail with a 404 that looks like a bad model name.
    The same applies to the model (a Gemini model id is a 404 on Netra) and the API key (the wrong
    key is a 401). Measured with the dashboard's /provider command, which previously left
    base_url=https://generativelanguage.googleapis.com/ while reporting provider=netra.

    A user-defined endpoint is checked first, so a custom name takes precedence over a built-in one
    with the same name rather than being silently ignored.

    Mirrors the resolution order used at startup: explicit environment override first, then the
    provider's own defaults.
    """
    if endpoints is not None:
        custom = endpoints.get(provider)
        if custom is not None:
            return custom.to_config(config)

    from ..config import load_config
    from ..constants import (
        DEFAULT_DEEPSEEK_BASE_URL,
        DEFAULT_DEEPSEEK_MODEL,
        DEFAULT_GEMINI_BASE_URL,
        DEFAULT_GEMINI_MODEL,
        DEFAULT_NETRA_BASE_URL,
        DEFAULT_NETRA_MODEL,
        DEFAULT_OLLAMA_BASE_URL,
        DEFAULT_OPENROUTER_BASE_URL,
        DEEPSEEK_API_KEY_ENV_FALLBACK,
        ENV_BASE_URL,
        ENV_MODEL,
        ENV_PROVIDER,
        GEMINI_API_KEY_ENV_FALLBACK,
        NETRA_API_KEY_ENV_FALLBACK,
        OLLAMA_PLACEHOLDER_KEY,
        OPENROUTER_API_KEY_ENV_FALLBACK,
        OPENROUTER_FAVORITE_MODELS,
        PROVIDER_DEEPSEEK,
        PROVIDER_GEMINI,
        PROVIDER_NETRA,
        PROVIDER_OLLAMA,
        PROVIDER_OPENROUTER,
    )

    table = {
        PROVIDER_NETRA: (DEFAULT_NETRA_BASE_URL, DEFAULT_NETRA_MODEL, NETRA_API_KEY_ENV_FALLBACK),
        PROVIDER_DEEPSEEK: (DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL, DEEPSEEK_API_KEY_ENV_FALLBACK),
        PROVIDER_OPENROUTER: (
            DEFAULT_OPENROUTER_BASE_URL,
            OPENROUTER_FAVORITE_MODELS[0],
            OPENROUTER_API_KEY_ENV_FALLBACK,
        ),
        PROVIDER_GEMINI: (DEFAULT_GEMINI_BASE_URL, DEFAULT_GEMINI_MODEL, GEMINI_API_KEY_ENV_FALLBACK),
        # Ollama has no key to look up, so the third slot carries a placeholder the protocol requires
        # and the server ignores. It was missing from this table entirely, which is why `/provider
        # ollama` answered `unknown provider 'ollama'` even though the dropdown offered it and the CLI
        # accepted it -- an omission that read as the feature not existing.
        PROVIDER_OLLAMA: (DEFAULT_OLLAMA_BASE_URL, "", ""),
    }
    if provider not in table:
        raise ValueError(f"unknown provider {provider!r}; choose from {', '.join(sorted(table))}")

    base_url, model, key_env = table[provider]
    # `MYRIAXON_BASE_URL` and `MYRIAXON_MODEL` are honoured ONLY when the environment is already
    # talking about the same provider. They are unconditional overrides meant for "run this one
    # command against that endpoint", and a `.env` file sets them for the provider it configures --
    # so reading them here regardless of target made an explicit vendor switch keep the previous
    # vendor's host. Measured: `/provider ollama` with a Netra `.env` produced
    #     provider set to ollama  endpoint https://api.netraruntime.com/v1  model myriaxon:latest
    # and the next turn failed `401 missing or malformed key`, because an ollama request was sent to
    # Netra with the ollama placeholder key. The docstring above already promised this could not
    # happen; it only guarded the stored config, not the environment.
    if _env_names_provider(provider):
        base_url = os.environ.get(ENV_BASE_URL) or base_url
        model = os.environ.get(ENV_MODEL) or model
    key = OLLAMA_PLACEHOLDER_KEY if provider == PROVIDER_OLLAMA else os.environ.get(key_env, "")
    if provider != PROVIDER_OLLAMA and not key:
        # A key typed into this dashboard is persisted to config.json (see `_save_vendor_key`), and
        # that is what is read here, so a stored DeepSeek key applies to DeepSeek and never leaks to
        # another provider -- the same rule the rest of this function follows for endpoint and model.
        stored = load_config()
        if stored is not None and stored.provider == provider:
            key = (stored.api_key or "").strip()
    if provider == PROVIDER_OLLAMA:
        # No model is chosen yet -- that is the whole point of the local-models panel. Asking Ollama
        # here would make switching vendor block on a network call, and the panel sets the model
        # immediately afterwards anyway.
        model = ""
        # But an empty model name is not a usable state: the next turn fails with Ollama's bare
        # `404 model not found`. So one is chosen from what is installed, preferring a model that can
        # call tools. Failure to reach Ollama is not an error here -- switching vendor should still
        # work, and the panel explains what is wrong.
        try:
            from .. import ollama as ollama_module

            probe = ollama_module.detect(with_details=True, timeout=3.0)
            made = probe.model(ollama_module.MYRIAXON_MODEL_NAME)
            # The model `myriaxon ollama --create` built, when there is one: it is the one with the full window.
            model = made.name if made is not None and ollama_module.tool_capable(made) else ollama_module.default_model(probe.models)
        except Exception:  # noqa: BLE001
            model = ""

    changes = {"provider": provider, "base_url": base_url, "model": model, "api_key": key}
    if provider != PROVIDER_GEMINI:
        # Vertex fields belong to Gemini; leaving them set would make a later Gemini run resume
        # against a stale project and confuse the endpoint reporting for other providers.
        changes["vertex_project"] = ""
        changes["vertex_location"] = ""
    return _replace_config(config, **changes)


def _replace_config(config: Any, **changes: Any):
    import dataclasses

    if dataclasses.is_dataclass(config):
        return dataclasses.replace(config, **changes)
    for key, value in changes.items():
        setattr(config, key, value)
    return config


def _with_model(config: Any, model: str):
    """Return a copy of the config with a different model, preserving everything else."""
    import dataclasses

    if dataclasses.is_dataclass(config):
        return dataclasses.replace(config, model=model)
    config.model = model
    return config


def serve(
    workspace: Path,
    *,
    config: Any,
    host: str = "127.0.0.1",
    port: int = 8765,
    mode: str = "auto_edit",
    open_browser: bool = True,
) -> None:
    app = DashboardApp(workspace, config=config, mode=mode)

    # Bring back the conversations a previous process saved. Done here, at the entry point to
    # actually serving, rather than in DashboardApp.__init__: constructing an app is what a test
    # does to get a clean, empty instance, and restoring inside the constructor meant every test
    # inherited whatever the previous test had written to disk. Production behaviour belongs at the
    # place production starts.
    try:
        restored = app.sessions.restore_all(config)
        if restored:
            print(f"  restored  : {restored} saved conversation(s)")
    except Exception as exc:  # noqa: BLE001 - never stop the server from starting
        print(f"  warning   : could not restore saved conversations ({exc})")

    # The workspace must become the process working directory, not just a path the dashboard knows
    # about. Measured failure without this: a turn asked to create `verify_dash.txt` reported
    # "Wrote 9 bytes to <repo>\verify_dash.txt" and the workspace stayed empty -- the agent's file
    # tools resolve relative paths against the process cwd, so --workspace only governed uploads and
    # the file browser while every edit landed in whatever directory the server was started from.
    # chdir before any agent exists, so there is no window where an agent holds the old cwd.
    previous_cwd = Path.cwd()
    try:
        os.chdir(app.workspace)
    except OSError as exc:
        print(f"warning: could not switch to the workspace ({exc}); file edits may land elsewhere")

    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True

    # NO model warm-up here, deliberately. It was tried and measured: with the model evicted, a first
    # turn took 17.2s without one and 22.5s with one. Ollama cancels an in-flight load as soon as the
    # client disconnects, so the load cannot be fired and forgotten -- any request that lives long
    # enough to finish it blocks the turn that follows. The load cost is the model's, not the
    # harness's, and the honest fix is a cloud vendor (`/vendor netra`) or a smaller local model.

    # Run due Loci on a timer while this server is open. Started AFTER the socket is bound, so a slow
    # first pass can never delay the page loading; on a daemon thread, so it dies with the server.
    if not os.environ.get("MYRIAXON_NO_SUPERVISOR"):
        try:
            app.start_supervisor(interval=float(os.environ.get("MYRIAXON_SUPERVISOR_SECONDS") or 60))
        except Exception:  # noqa: BLE001 - a broken supervisor must not stop the server
            print("  supervisor: could not start; Loci will only run when you ask")

    url = f"http://{host}:{port}/"
    print(f"Myriaxon running at {url}")
    print(f"  workspace : {app.workspace}")
    print(f"  uploads   : {app.uploads_dir}")
    print(f"  provider  : {config.provider}:{config.model}")
    for note in app.uploads.notes:
        print(f"  note      : {note}")
    if not is_writable(app.workspace):
        print(f"  warning   : the workspace is not writable; file edits will fail ({app.workspace})")
    print("  Ctrl+C to stop")

    if open_browser:
        def _open() -> None:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Timer(0.8, _open).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
        try:
            os.chdir(previous_cwd)
        except OSError:
            pass

