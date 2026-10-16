# Myriaxon Harness — the APPLICATION image, so installation is one command.
#
# NOT TO BE CONFUSED WITH `docker/Dockerfile`, which is the opposite thing: the sandbox image a
# confined Locus runs INSIDE. That one has no entrypoint on purpose, because `_sandboxed_shell_argv`
# supplies its own command. This one is what you run Myriaxon FROM, and it has one.
#
#   docker build -t myriaxon-harness:latest .
#   docker run -it --rm -v ~/.myriaxon:/home/myriaxon/.myriaxon myriaxon-harness:latest
#
# or, with nothing to install at all:
#
#   docker run -it --rm -v ~/.myriaxon:/home/myriaxon/.myriaxon ghcr.io/myriaxon/harness:latest
#
# WHY A CONTAINER IS THE EASIEST INSTALL
#
# The README asks for Python 3.10+, a virtualenv, and pip resolving four dependencies -- and the
# single most common first failure in any Python CLI is a dependency or interpreter mismatch that
# produces a traceback rather than an explanation. A container removes the interpreter question
# entirely: the Python, the package and its dependencies are all decided at build time and travel
# together. `pip install` cannot half-finish in an image that was already built successfully.

# 3.11 rather than 3.13: `requires-python = ">=3.10"` is the contract, and 3.11 is the version every
# other verification path in this repository uses. Matching the tested interpreter is worth more than
# being on the newest one.
FROM python:3.11-slim-bookworm

# Build metadata, so `docker inspect` answers "which commit is this" the way the version resource
# answers it for the Windows launcher. Declared as ARGs because they are build-time facts.
ARG MYRIAXON_VERSION=0.0.1
ARG MYRIAXON_REVISION=unknown

LABEL org.opencontainers.image.title="Myriaxon Harness" \
      org.opencontainers.image.description="An advanced agentic harness for the terminal and the browser" \
      org.opencontainers.image.authors="Thariq Arian Khalfani <ariankhalfani@gmail.com>" \
      org.opencontainers.image.url="https://github.com/myriaxon/Harness" \
      org.opencontainers.image.source="https://github.com/myriaxon/Harness" \
      org.opencontainers.image.documentation="https://github.com/myriaxon/Harness/blob/main/docs/HOW-TO-USE.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${MYRIAXON_VERSION}" \
      org.opencontainers.image.revision="${MYRIAXON_REVISION}"

# Nothing is interactive. Without this, apt and pip can stop on a prompt that a `docker build` never
# answers, and the build hangs rather than failing.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# The container's own tools. Deliberately short: everything here is something Myriaxon's own features
# invoke, not general convenience.
#   git         checkpoints, diffs, the file tools' history
#   ripgrep     grep_search is much faster with it, and falls back cleanly without it
#   curl        web_fetch has its own stdlib client, but hooks and plugins often shell out
#   openssh     a user's git+ssh remote, which a coding agent is routinely asked to work with
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git \
      ripgrep \
      curl \
      ca-certificates \
      openssh-client \
 && rm -rf /var/lib/apt/lists/*

# A NON-ROOT USER, and the reason is ownership rather than privilege alone. `docker run` defaults to
# root, so every file the agent writes into a mounted workspace arrives on the host owned by root --
# the user then has to `sudo chown` their own project. UID 1000 matches the first user on almost every
# Linux host and inside WSL, which is where a bind-mounted workspace usually comes from.
#
# `--create-home` matters: the config directory lives under it, so a named volume mounted there is
# owned by this user from the start rather than by root.
ARG MYRIAXON_UID=1000
ARG MYRIAXON_GID=1000
RUN groupadd --gid "${MYRIAXON_GID}" myriaxon 2>/dev/null || true \
 && useradd --uid "${MYRIAXON_UID}" --gid "${MYRIAXON_GID}" \
            --create-home --shell /bin/bash myriaxon \
 && mkdir -p /workspace /home/myriaxon/.myriaxon \
 && chown -R myriaxon:myriaxon /workspace /home/myriaxon

# ---------------------------------------------------------------------------------------------
# THE DOCKER CLIENT, OPT-IN, AND WHY IT IS OPT-IN
# ---------------------------------------------------------------------------------------------
# Measured: without this, a confined Locus INSIDE this container can never run a shell command --
# `tools.docker_prefix()` returns None, `shell_may_run()` refuses, and the sandbox feature is simply
# unavailable. The harness image could therefore run the agent but not use its own isolation.
#
# It is a build argument rather than unconditional because it only helps when the caller also mounts the
# Docker socket, and mounting that socket hands the container control of every container on the host.
# Making it unconditional would put a powerful client into every image for a feature most users cannot
# use, so the choice is explicit:
#
#     docker build --build-arg WITH_DOCKER_CLI=true .
#
# WHICH CLIENT, AND THE TWO ROUTES THAT WERE REJECTED.
#
# Debian's `docker.io` bundles the daemon -- containerd, runc and iptables, roughly 250MB of things that
# can never run here, because the daemon lives on the host. Debian 13 has a separate `docker-cli`
# package and bookworm, this image's base, does NOT (both measured).
#
# The static tarball was the first choice and is also rejected: **Docker publishes no checksum for it.**
# Measured -- `docker-29.9.1.tgz.sha256` and two other spellings all return 404, while the tarball itself
# is 86MB over 200. An 86MB download that cannot be verified is exactly the supply-chain shape the
# sandbox image's own comments refuse, so it is not used here either.
#
# What is used instead is `docker-ce-cli` from Docker's own apt repository, which is the canonical
# client, is a SINGLE package, drags in no daemon (measured: `Inst docker-ce-cli` alone), and is
# verified through the repository's GPG-signed Release file rather than a checksum fetched beside the
# payload. The version is pinned exactly, because a client that silently drifts from the daemon it talks
# to is a debugging problem nobody needs.
ARG WITH_DOCKER_CLI=false
ARG DOCKER_CE_CLI_VERSION=5:29.9.1-1~debian.12~bookworm
RUN if [ "${WITH_DOCKER_CLI}" = "true" ]; then \
      set -eux; \
      apt-get update; \
      apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
      install -m 0755 -d /etc/apt/keyrings; \
      curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
      chmod a+r /etc/apt/keyrings/docker.asc; \
      echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
           > /etc/apt/sources.list.d/docker.list; \
      apt-get update; \
      apt-get install -y --no-install-recommends "docker-ce-cli=${DOCKER_CE_CLI_VERSION}"; \
      # The key and its repository are removed after use. The CLIENT stays; the ability to apt-install
      # more from a third-party source does not, which keeps what can enter this image unchanged.
      rm -f /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.asc; \
      apt-get purge -y curl gnupg; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
      docker --version; \
    else \
      echo "docker CLI not installed; the Locus sandbox needs it -- see the WITH_DOCKER_CLI note above"; \
    fi

# WHERE CONFIG LIVES, set explicitly rather than left to the default. `~/.myriaxon` inside the
# container is `/home/myriaxon/.myriaxon`, and the README tells the user to mount a volume there --
# stating it here means the mount point does not depend on which user the image happens to run as.
ENV MYRIAXON_CONFIG_DIR=/home/myriaxon/.myriaxon \
    HOME=/home/myriaxon

# THE PACKAGE IS BUILT FROM THE COPY IN THE IMAGE, never downloaded from an index at build time.
# `COPY . .` then `pip install .` means the image contains exactly the commit it was built from, and
# it means this Dockerfile works on a machine with no network access to PyPI beyond the base layers.
#
# `[all]` is installed rather than the bare package: the whole point of the image is that the user does
# not have to think about extras, and an image missing `httpx` or the Gemini SDK would fail at the
# first provider call -- in a container, where the failure is harder to diagnose, not easier.
WORKDIR /build
COPY . .
RUN pip install --no-cache-dir ".[all]" \
 && rm -rf /build

# THE ENTRYPOINT IS A SCRIPT, NOT `["python", "-m", "myriaxon"]`.
#
# The obvious form is wrong, and it shipped here first before the tests caught it:
#
#     docker run --rm myriaxon-harness python -c "print(1)"
#     -> python -m myriaxon python -c "print(1)"
#     -> myriaxon: error: argument command: invalid choice: 'python'
#
# Docker APPENDS the command to the entrypoint rather than replacing it, so a static entrypoint makes it
# impossible to run any command in the container. No shell for debugging, no `python -c` to inspect the
# installed package -- and an image you cannot get a shell in is an image you cannot diagnose.
#
# `entrypoint.py` decides at runtime: a bare flag or a Myriaxon subcommand runs the agent, anything else
# is executed as a command. Both `docker run image --version` and `docker run image bash` then behave the
# way a person expects.
COPY docker/entrypoint.py /usr/local/bin/myriaxon-entrypoint.py
RUN chmod 0755 /usr/local/bin/myriaxon-entrypoint.py

USER myriaxon

# The workspace, and where a bind mount goes. `WORKDIR` also makes `myriaxon` treat this as the project
# root, which is what `_resolve` confines file tools to.
WORKDIR /workspace

# The dashboard's port. Declared rather than exposed automatically so `docker run -p` is a deliberate
# choice; binding it without publishing is what a `-P` user gets.
EXPOSE 8765

# A HONEST HEALTH CHECK, not a liveness theatre. `--version` answers from `argparse_cli` without
# importing the agent, so a slow model provider cannot make a healthy container look sick. It proves
# the interpreter, the package and the entry point all resolved.
#
# `python -m myriaxon` rather than the `myriaxon` launcher because the console script on Windows is a
# pip-generated .exe (see docs/FALSE-POSITIVE.md), while this image is Linux and the module path is the
# one thing that is identical on every platform.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-m", "myriaxon", "--version"]

# The interactive agent by default. `docker run -it` then behaves like running `myriaxon` locally,
# which is the least surprising thing an image called "harness" can do.
#
# The dashboard is one argument away and needs a published port:
#   docker run -it --rm -p 8765:8765 -v ~/.myriaxon:/home/myriaxon/.myriaxon \
#     ghcr.io/myriaxon/harness:latest web --no-browser --host 0.0.0.0
#
# `--host 0.0.0.0` is REQUIRED there and is not a convenience: the dashboard binds 127.0.0.1 by default,
# which inside a container means the port is published and still unreachable. That is deliberate in the
# server -- loopback by default is the safe choice for a tool that can read your files -- so the
# container cannot quietly widen it.
ENTRYPOINT ["python", "/usr/local/bin/myriaxon-entrypoint.py"]
CMD []
