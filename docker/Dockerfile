# A sandbox image a confined Locus can actually build in.
#
# Why this exists, measured: the default sandbox image carries `pwsh` and coreutils and NOTHING else.
# A confined agent can therefore write files and run shell scripts, and cannot run python, git, node,
# or install anything -- and with `--network none` it cannot fetch them either. Verified by probing the
# container directly: python3, git, node, npm, curl, wget and jq were all absent.
#
# The base is Microsoft's PowerShell image on purpose: `_sandboxed_shell_argv` invokes `pwsh`, so
# keeping it means command syntax stays identical whether or not the sandbox is on. An agent does not
# have to know which world it is in, and a command that worked unsandboxed does not start failing.
#
# The network stays OFF. Everything here is baked in at build time, which is the point: an agent that
# can install packages at runtime can also install something malicious, and `--network none` is the
# control that stops exfiltration. Build time is where a dependency gets added; run time is not.
#
#   docker build -t myriaxon-sandbox:latest docker/
#   set MYRIAXON_SANDBOX_IMAGE=myriaxon-sandbox:latest      (cmd)
#   $env:MYRIAXON_SANDBOX_IMAGE="myriaxon-sandbox:latest"  (powershell)
#
# Build it from inside WSL when Docker is hosted there, since a Linux engine cannot build from a
# Windows path: `wsl -d Ubuntu -- docker build -t myriaxon-sandbox:latest /mnt/c/.../docker`

FROM mcr.microsoft.com/powershell:latest

# Debian-based, so apt. `--no-install-recommends` and the cache cleanup keep the image small, which
# matters because it is pulled on first use and a sandbox that takes minutes to appear does not get
# used.
#
# The package list is driven by a measured capability map (`docs/CAPABILITY-MAP.md`), which probed
# this image and found 29 of 51 host programs absent. Everything added here is a build-time install
# so the RUN-time network stays off; the isolation is unchanged. The named additions are the ones
# that unblock whole role categories rather than the ones that merely look useful:
#
#   sqlite3          the CLI, alongside the Python module -- DB work without writing a script
#   zip, unzip       archive handling, which the probe found missing and nothing else provides
#   rsync            file synchronisation inside the workspace
#   file, bc         identification and arithmetic for shell pipelines
#   graphviz (dot)   renders .dot to SVG/PNG -- turns hand-written diagrams into real images
#   imagemagick      raster conversion and resizing: SVG -> PNG at last
#   vim, nano        an editor, so the agent can inspect a file interactively when that helps
#   patch, diffutils already partly present; `patch` makes unified diffs applicable
#   less, procps     paging and process inspection
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      git \
      curl \
      wget \
      jq \
      ca-certificates \
      build-essential \
      sqlite3 \
      zip \
      unzip \
      rsync \
      file \
      bc \
      graphviz \
      imagemagick \
      librsvg2-bin \
      vim \
      nano \
      patch \
      diffutils \
      less \
      procps \
      pkg-config \
      pandoc \
      gnuplot \
 && rm -rf /var/lib/apt/lists/*

# The Python packages the capability map named as the single largest gap: measured 0 of 34
# third-party packages present, and with no run-time network they can never be added later. These
# four move Data & analysis and Visual & media the furthest, per that document:
#
#   numpy, pandas        real dataframes -- ETL, cross-tabs, statistics beyond `statistics`
#   matplotlib           chart rendering: CSV in, PNG out
#   Pillow               raster image work: resize, convert, compose, read metadata
#
# Pinned to a minimum, not an exact version: Debian's wheels are already a coherent set, and pinning
# exactly would break the build the first time a mirror drops a specific release.
#
# No `--break-system-packages`: measured, this image's pip is older than that flag ("no such option"),
# and it is not needed either -- that flag exists to override PEP 668 on distros that mark the system
# Python externally managed, and this image does not.
RUN pip3 install --no-cache-dir \
      numpy \
      pandas \
      matplotlib \
      Pillow \
 && rm -rf /root/.cache/pip

# Node from the distribution rather than a curl|bash installer: a pinned distro package is
# reproducible, and a piped remote script at build time is exactly the supply-chain shape this
# sandbox exists to contain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm \
 && rm -rf /var/lib/apt/lists/*

# A non-root user for the work. `docker run` defaults to root, which means anything the agent writes
# into the mounted workspace is owned by root on the host -- an ownership mess the user has to clean up
# by hand, and a privilege the agent does not need.
#
# UID 1000 matches the default first user in a WSL distribution, so files written here are owned by
# that user on the host rather than by root:
ARG SANDBOX_UID=1000
ARG SANDBOX_GID=1000
RUN groupadd --gid ${SANDBOX_GID} sandbox 2>/dev/null || true \
 && useradd --uid ${SANDBOX_UID} --gid ${SANDBOX_GID} --create-home --shell /bin/bash sandbox \
      2>/dev/null || true

# git needs an identity before it will commit; a placeholder is better than an error that reads like a
# broken tool. The agent should set a real one if it commits anything it cares about.
RUN git config --system user.email "agent@myriaxon.local" \
 && git config --system user.name "Myriaxon Agent" \
 && git config --system --add safe.directory /workspace

# /workspace MUST EXIST AND BE OWNED BY THE SANDBOX USER, and until this line was added it was not.
#
# Measured: `docker run --rm myriaxon-sandbox:latest touch /workspace/x` failed with
# `Permission denied` -- with no mount at all, on the image's OWN workspace. The cause is that
# `WORKDIR /workspace` is a convenience instruction: Docker CREATES the directory when it does not
# exist, as root, and `WORKDIR` runs AFTER `USER sandbox` below. So the one directory every confined
# Locus writes to was root-owned and read-only to the user meant to work in it.
#
# A bind-mounted workspace was unaffected, because the mount replaces the directory -- which is exactly
# why this hid: the common case worked, and the image's own default workspace did not. Anything that
# ran without a mount (a plain `docker run ... bash`, a diagnostic, a test) hit it instead.
RUN mkdir -p /workspace && chown -R sandbox:sandbox /workspace

WORKDIR /workspace
USER sandbox

# No entrypoint: `_sandboxed_shell_argv` passes `pwsh -NoProfile -NonInteractive -Command ...`
# explicitly, and an inherited ENTRYPOINT would be prepended to it and break the invocation.
