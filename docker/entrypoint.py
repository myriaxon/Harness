#!/usr/bin/env python3
"""Decide whether the container's arguments are a Myriaxon invocation or a command to run.

WHY THIS FILE EXISTS -- a design flaw the first version of this image shipped with.

The Dockerfile used `ENTRYPOINT ["python", "-m", "myriaxon"]`, which looks right and is not:

    docker run --rm myriaxon-harness --version           -> python -m myriaxon --version        fine
    docker run --rm myriaxon-harness python -c "..."     -> python -m myriaxon python -c "..."  BROKEN

Docker appends the command to the entrypoint rather than replacing it, so every second `python` became
an argument to Myriaxon -- and the argparse error was `invalid choice: 'python'`. The consequence is
not cosmetic: it removes the ability to run ANY command in the container. No shell for debugging, no
`python -c` to inspect the installed package, no `myriaxon doctor`. An image you cannot get a shell in
is an image you cannot diagnose, and "docker exec -it ... bash" is the first thing anyone reaches for
when a container misbehaves.

THE FIX, and the choice it encodes. There is no way to satisfy both of these with a static ENTRYPOINT:

    docker run image --version          # bare flags should mean "the agent"
    docker run image bash               # a command should mean "run it"

So the decision is made at runtime, by inspecting argv[1]:

  * starts with `-`            -> a flag for Myriaxon        -> run the agent
  * is a Myriaxon SUBCOMMAND   -> run the agent              -> `web`, `loci`, `doctor`, ...
  * is anything else, no args  -> run the agent (interactive)
  * is anything else           -> an executable              -> run it verbatim

The subcommand list is read from the CLI itself where possible, so this cannot drift from what the
program actually accepts. When that import is unavailable -- a broken install, which is one of the
states this image has to be debuggable in -- it falls back to a hardcoded list rather than refusing,
because a diagnostic path that fails during a broken install is useless exactly when it is needed.
"""

from __future__ import annotations

import os
import sys

# Used only when the CLI cannot be imported. Kept in sync with the argparse subparsers in cli.py.
FALLBACK_SUBCOMMANDS = {
    "auth", "web", "bot", "search", "ollama", "audit", "verify", "bench",
    "loci", "instructions", "roles", "skills", "doctor", "branch", "export", "avatar",
}


def subcommands() -> set[str]:
    """What the CLI actually accepts, asked of the CLI rather than duplicated here."""
    try:
        from myriaxon import argparse_cli

        parser = argparse_cli.build_parser()
        for action in parser._actions:  # noqa: SLF001 - argparse exposes no public accessor
            if getattr(action, "choices", None) and action.dest == "command":
                return set(action.choices)
    except Exception:  # noqa: BLE001 - a broken install must not break this decision
        pass
    return FALLBACK_SUBCOMMANDS


def main() -> int:
    argv = sys.argv[1:]

    # No arguments: the interactive agent, which is the least surprising default for this image.
    if not argv:
        os.execvp("python", ["python", "-m", "myriaxon"])

    first = argv[0]

    # A bare flag belongs to Myriaxon. `--version` and `--help` must work, and they are also what the
    # image's own HEALTHCHECK runs.
    if first.startswith("-"):
        os.execvp("python", ["python", "-m", "myriaxon", *argv])

    # A subcommand belongs to Myriaxon: `web --host 0.0.0.0`, `doctor`, `loci --status`.
    if first in subcommands():
        os.execvp("python", ["python", "-m", "myriaxon", *argv])

    # Anything else is a command the caller wants to run. `execvp` so `bash`, `python`, `sh` and `git`
    # all resolve through PATH exactly as they would outside a container.
    try:
        os.execvp(first, argv)
    except FileNotFoundError:
        # Say which command and where we looked. "exec: not found" alone sends people looking at the
        # image when the real answer is usually a typo or a missing package.
        print(f"myriaxon-entrypoint: no such command: {first}", file=sys.stderr)
        print(f"  PATH={os.environ.get('PATH', '')}", file=sys.stderr)
        print("  a bare flag or a Myriaxon subcommand runs the agent; anything else must be installed",
              file=sys.stderr)
        return 127
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
