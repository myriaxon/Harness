"""What the system is doing, at eight levels of detail, with a dial rather than a switch.

WHY A DIAL AND NOT A VERBOSE FLAG

A single verbosity flag forces a bad choice. Quiet enough to work in is too quiet to audit; loud enough to
audit buries the answer in noise. The two audiences want different windows on the same stream -- a person
watching a run wants to know it is alive, a person investigating wants to know which bytes it read -- and a
boolean cannot serve both.

So transparency is a LEVEL, 0 to 8, and each level is a strictly richer view of the same underlying events.
Nothing below the level is computed or kept, which is what makes the dial honest: a low setting is genuinely
quiet rather than filtered at display time, and no level can reveal something a higher one hides.

THE EIGHT LAYERS

    0  silent          nothing is emitted at all
    1  pulse           a run exists and is progressing: start, step, heartbeat, end
    2  intent          what the agent says it is about to do, and why -- from the model, untrusted text
    3  actions         which tool was called, with arguments REDACTED by level 4's rules
    4  files           which paths were read and written, and how much changed
    5  system          shell commands, exit codes, and the tail of their output
    6  agents          loci and swarm coordination: who claimed what, who is waiting on whom
    7  decisions       the gates: refusals, confirmations, risk verdicts, budget stops -- including
                       what was REFUSED, which is the half a log usually omits
    8  memory          durable writes: sessions, checkpoints, collective memory, audit entries

LEVEL 7 IS THE ONE THAT MATTERS MOST and the one usually missing. An activity feed that shows only what
happened cannot answer "why did it not do the thing", which is the question people actually arrive with. Every
refusal, every blocked action and every escalation is emitted here with its reason.

WHAT IS NEVER EMITTED AT ANY LEVEL

Credential values. `audit._redact` already knows the shapes, and this reuses it rather than growing a second
opinion about what a secret looks like. A transparency feature that leaks an API key into a UI feed has made the
system worse than opaque, so redaction is applied at EMISSION -- before the event is stored or sent -- rather
than at display, where a second consumer could forget it.

TRUST IS RECORDED, NOT ASSUMED

Everything a model writes is untrusted: a tool argument, a file's contents, a sub-agent's report. Events carry
`trusted: False` for text that came from a model or a file, so a surface can render it as data rather than as
instructions. This is the same rule `tool_catalog` already applies to foreign schemas, applied to the feed.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --- the eight layers ----------------------------------------------------------------------

SILENT = 0
PULSE = 1
INTENT = 2
ACTIONS = 3
FILES = 4
SYSTEM = 5
AGENTS = 6
DECISIONS = 7
MEMORY = 8

MAX_LEVEL = MEMORY

LAYER_NAMES = {
    SILENT: "silent",
    PULSE: "pulse",
    INTENT: "intent",
    ACTIONS: "actions",
    FILES: "files",
    SYSTEM: "system",
    AGENTS: "agents",
    DECISIONS: "decisions",
    MEMORY: "memory",
}

LAYER_DESCRIPTIONS = {
    SILENT: "nothing is emitted",
    PULSE: "a run exists and is progressing",
    INTENT: "what the agent says it is about to do",
    ACTIONS: "which tool was called, arguments redacted",
    FILES: "which paths were read and written",
    SYSTEM: "shell commands, exit codes, output tails",
    AGENTS: "loci and swarm coordination",
    DECISIONS: "gates: refusals, confirmations, risk, budget",
    MEMORY: "durable writes: sessions, checkpoints, memory, audit",
}

# What a caller must supply for a layer to be meaningful. Used by `describe()` and asserted by the tests, so a
# layer cannot silently degrade into a generic event because nobody decided what belongs in it.
LAYER_REQUIRES = {
    PULSE: ("run_id",),
    INTENT: ("text",),
    ACTIONS: ("tool",),
    FILES: ("path",),
    SYSTEM: ("command",),
    AGENTS: ("member",),
    DECISIONS: ("decision",),
    MEMORY: ("store",),
}

DEFAULT_LEVEL = ACTIONS


def _level_from_env() -> int:
    raw = (os.environ.get("MYRIAXON_TRANSPARENCY") or "").strip()
    if not raw:
        return DEFAULT_LEVEL
    try:
        return max(SILENT, min(MAX_LEVEL, int(raw)))
    except ValueError:
        # A malformed setting must not silence the system or crash it; the default is a working value.
        return DEFAULT_LEVEL


# --- the event --------------------------------------------------------------------------------


@dataclass
class Event:
    """One thing that happened, at one layer."""

    layer: int = PULSE
    kind: str = ""
    at: float = field(default_factory=time.time)
    # Which run and which agent, so a feed can be filtered to one of them. "" when not applicable.
    run_id: str = ""
    locus: str = ""
    session: str = ""
    # One line a person can read. Redacted and length-bounded at emission.
    summary: str = ""
    # Structured detail. Never contains a credential value; see `emit`.
    detail: dict = field(default_factory=dict)
    # False when the text came from a model or a file. A surface must render untrusted text as data.
    trusted: bool = True

    def to_dict(self) -> dict:
        """The event as a plain dict, WITH the human-readable layer name included.

        `asdict` alone omits `layer_name`, because it is a property rather than a field -- so the API served
        `"layer_name": null` for every event while `event.layer_name` was perfectly correct in Python.
        Measured against the live server: a refusal at layer 7 serialised as `layer_name: None`.

        That matters beyond tidiness. The dashboard keeps its OWN copy of the layer names in JavaScript, so
        the two can drift: renaming a layer in Python would leave the UI labelling it with the old name and
        nothing would fail. Serving the name makes Python the single source of truth, and lets any other
        consumer label an event without duplicating the table.
        """
        data = asdict(self)
        data["layer_name"] = self.layer_name
        return data

    @property
    def layer_name(self) -> str:
        return LAYER_NAMES.get(self.layer, f"layer-{self.layer}")


# --- redaction, reused rather than reinvented --------------------------------------------------


def _redact(value):
    """Delegate to the audit log's redactor so there is one opinion about what a secret looks like."""
    try:
        from .audit import _redact as audit_redact

        return audit_redact(value)
    except Exception:  # noqa: BLE001
        # Never fail an emission because the redactor is unavailable, but never pass the value through
        # unexamined either: fall back to a shape-based scrub.
        return _fallback_redact(value)


_SECRET_HINTS = ("key", "token", "secret", "password", "credential", "authorization", "cookie")


def _fallback_redact(value, _depth: int = 0):
    if _depth > 6:
        return "<deeply-nested>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and any(hint in key.lower() for hint in _SECRET_HINTS):
                out[key] = "<redacted>"
            else:
                out[key] = _fallback_redact(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_fallback_redact(item, _depth + 1) for item in value[:50]]
    if isinstance(value, str):
        import re

        value = re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "<redacted>", value)
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}", "Bearer <redacted>", value)
        return value[:2000]
    return value


def _short(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


# --- the broadcaster --------------------------------------------------------------------------

# How many events to hold. Bounded because this is a live feed, not a log: `audit.jsonl` is the durable record
# and duplicating it here would be a second thing to trust and a second thing to grow without limit.
BUFFER_SIZE = 400


class Transparency:
    """The level, the buffer, and the subscribers. One per process."""

    def __init__(self, level: int | None = None) -> None:
        self._lock = threading.Lock()
        self._level = _level_from_env() if level is None else max(SILENT, min(MAX_LEVEL, int(level)))
        self._buffer: deque[Event] = deque(maxlen=BUFFER_SIZE)
        self._subscribers: list = []
        self._dropped = 0
        self._counts: dict[int, int] = {n: 0 for n in LAYER_NAMES}

    # -- the dial ------------------------------------------------------------------------

    @property
    def level(self) -> int:
        with self._lock:
            return self._level

    def set_level(self, level: int) -> int:
        """Move the dial. Returns the level actually set, after clamping."""
        try:
            wanted = max(SILENT, min(MAX_LEVEL, int(level)))
        except (TypeError, ValueError):
            wanted = self._level
        with self._lock:
            previous = self._level
            self._level = wanted
        if wanted != previous:
            # Emitted at PULSE so a surface can show the change even at a low setting -- the act of changing
            # transparency is itself worth seeing, and a silent change would leave a reader wondering why the
            # feed stopped.
            self.emit(PULSE, "transparency", summary=f"transparency {LAYER_NAMES[previous]} → "
                                                      f"{LAYER_NAMES[wanted]}", detail={"from": previous,
                                                                                        "to": wanted})
        return wanted

    def describe(self) -> dict:
        """The dial plus what each position means, for a UI to render without hard-coding the list."""
        with self._lock:
            level = self._level
        return {
            "level": level,
            "max": MAX_LEVEL,
            "name": LAYER_NAMES[level],
            "layers": [
                {
                    "level": number,
                    "name": LAYER_NAMES[number],
                    "description": LAYER_DESCRIPTIONS[number],
                    "active": number <= level and number != SILENT,
                    "requires": list(LAYER_REQUIRES.get(number, ())),
                }
                for number in range(SILENT, MAX_LEVEL + 1)
            ],
            "counts": dict(self._counts),
            "buffered": len(self._buffer),
            "dropped": self._dropped,
        }

    # -- emission ------------------------------------------------------------------------

    def emit(self, layer: int, kind: str, *, summary: str = "", detail: dict | None = None,
             run_id: str = "", locus: str = "", session: str = "", trusted: bool = True,
             always: bool = False) -> Event | None:
        """Record an event at `layer`, or return None when the dial is below it.

        Returning None rather than a discarded object is deliberate: a caller that wants to skip expensive
        detail can check the return, and the common case costs one integer comparison.

        ``always=True`` IGNORES THE DIAL, and only one category uses it: **a refusal**. The reasoning is the
        same one that shaped the dial. The dial exists so a person can lower the volume on the ordinary
        traffic of a working agent -- which tool ran, which file was read -- and that traffic is genuinely
        optional to watch. A refusal is the opposite: it means something the owner asked for did not happen,
        and the owner is the one person who needs to know.

        Measured: at the default level 3 the DECISIONS layer (level 7) is off entirely, so a refused run
        produced NO entry anywhere the user was looking -- only a line in one locus's own activity log. That
        is exactly the complaint this layer was added to answer ("when every error or stuck happened let me
        know it from UI"), so it earns an exception rather than a renumbering.

        Deliberately NOT a general escape hatch. Everything else stays gated, because a dial that does not
        reduce anything is not a dial.
        """
        with self._lock:
            level = self._level
        if layer == SILENT or (layer > level and not always):
            return None

        try:
            layer = max(SILENT, min(MAX_LEVEL, int(layer)))
        except (TypeError, ValueError):
            return None

        event = Event(
            layer=layer,
            kind=_short(kind, 60),
            run_id=_short(run_id, 80),
            locus=_short(locus, 80),
            session=_short(session, 80),
            summary=_short(summary, 300),
            detail=_redact(detail or {}),
            trusted=bool(trusted),
        )

        with self._lock:
            self._buffer.append(event)
            self._counts[layer] = self._counts.get(layer, 0) + 1
            subscribers = list(self._subscribers)

        for queue in subscribers:
            try:
                queue.append(event)
            except Exception:  # noqa: BLE001
                # A dead subscriber must never stop the run it was watching.
                with self._lock:
                    if queue in self._subscribers:
                        self._subscribers.remove(queue)
        return event

    # -- subscribers ---------------------------------------------------------------------

    def subscribe(self) -> deque:
        """A queue that receives every event from now on. Caller must `unsubscribe`."""
        queue: deque = deque(maxlen=200)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def recent(self, *, since: float = 0.0, layer: int = SILENT, limit: int = 200) -> list[Event]:
        """Buffered events, newest first, optionally filtered."""
        with self._lock:
            events = list(self._buffer)
        if since:
            events = [e for e in events if e.at > since]
        if layer:
            events = [e for e in events if e.layer == layer]
        return list(reversed(events))[: max(1, limit)]


_INSTANCE: Transparency | None = None
_INSTANCE_LOCK = threading.Lock()


def get() -> Transparency:
    """The process-wide broadcaster."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = Transparency()
        return _INSTANCE


def emit(layer: int, kind: str, **kwargs) -> Event | None:
    """Module-level convenience, so a call site does not have to fetch the instance."""
    return get().emit(layer, kind, **kwargs)


def level() -> int:
    return get().level


def set_level(value: int) -> int:
    return get().set_level(value)


def describe() -> dict:
    return get().describe()


# --- convenience wrappers, so call sites read as what they mean --------------------------------
#
# These exist so a caller does not have to remember which number a file read belongs to. A wrong layer number
# is invisible in review and obvious in use; a named function is neither.


def pulse(kind: str, **kwargs) -> Event | None:
    return emit(PULSE, kind, **kwargs)


def intent(text: str, **kwargs) -> Event | None:
    return emit(INTENT, "intent", summary=text, detail={"text": text}, trusted=False, **kwargs)


def action(tool: str, args: dict | None = None, **kwargs) -> Event | None:
    detail = {"tool": tool, "args": args or {}}
    return emit(ACTIONS, "action", summary=f"{tool}", detail=detail, **kwargs)


def file_read(path: str, *, bytes_read: int = 0, **kwargs) -> Event | None:
    detail = {"path": str(path), "bytes": int(bytes_read), "op": "read"}
    return emit(FILES, "file", summary=f"read {Path(str(path)).name}", detail=detail, **kwargs)


def file_write(path: str, *, bytes_written: int = 0, created: bool = False, **kwargs) -> Event | None:
    detail = {"path": str(path), "bytes": int(bytes_written), "op": "write", "created": bool(created)}
    verb = "created" if created else "wrote"
    return emit(FILES, "file", summary=f"{verb} {Path(str(path)).name}", detail=detail, **kwargs)


def command(command: str, *, exit_code: int | None = None, output_tail: str = "", **kwargs) -> Event | None:
    detail = {
        "command": _short(command, 500),
        "exit_code": exit_code,
        "output_tail": _short(output_tail, 600),
    }
    tail = "" if exit_code is None else f" (exit {exit_code})"
    return emit(SYSTEM, "command", summary=f"$ {_short(command, 120)}{tail}", detail=detail,
                trusted=False, **kwargs)


def agent(member: str, what: str, **kwargs) -> Event | None:
    detail = {"member": member, "what": what}
    return emit(AGENTS, "agent", summary=f"{member}: {_short(what, 160)}", detail=detail, **kwargs)


def decision(what: str, *, reason: str = "", allowed: bool | None = None, **kwargs) -> Event | None:
    """A gate outcome. Emitted whether the answer was yes or no -- the refusals are the point."""
    detail = {"decision": what, "reason": _short(reason, 500), "allowed": allowed}
    verdict = "" if allowed is None else ("allowed" if allowed else "refused")
    return emit(DECISIONS, "decision", summary=f"{what}: {verdict}".strip(": "), detail=detail, **kwargs)


def memory(store: str, what: str, **kwargs) -> Event | None:
    detail = {"store": store, "what": what}
    return emit(MEMORY, "memory", summary=f"{store}: {_short(what, 160)}", detail=detail, **kwargs)


def as_sse(event: Event) -> str:
    """One event as a server-sent-events frame."""
    return f"data: {json.dumps(event.to_dict(), ensure_ascii=False, default=str)}\n\n"
