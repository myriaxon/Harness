# Running Myriaxon in Docker

Two images, and they point in opposite directions. Confusing them is the first mistake.

| Image | Dockerfile | What it is |
|---|---|---|
| **`myriaxon-harness`** | `Dockerfile` (repo root) | **the application.** What you run Myriaxon *from*. |
| **`myriaxon-sandbox`** | `docker/Dockerfile` | **the jail.** The container a confined Locus runs *inside*. |

Neither is built `FROM` the other. The harness image can *drive* the sandbox image when both are present
— see [Nested sandbox](#nested-sandbox-the-locus-jail-inside-the-harness-container).

---

## Install in one command

```bash
docker run -it --rm \
  -v myriaxon-config:/home/myriaxon/.myriaxon \
  -v "$PWD:/workspace" \
  ghcr.io/myriaxon/harness:latest
```

No Python, no virtualenv, no pip, no dependency resolution. That is the entire point: **the single most
common first failure in any Python CLI is an interpreter or dependency mismatch that produces a traceback
instead of an explanation**, and a built image cannot half-install.

Pass a provider and key the way you would locally:

```bash
docker run -it --rm \
  -v myriaxon-config:/home/myriaxon/.myriaxon \
  -v "$PWD:/workspace" \
  -e MYRIAXON_PROVIDER=netra \
  -e NETRA_API_KEY=sk_live_... \
  ghcr.io/myriaxon/harness:latest
```

Or with the compose file, which is the same thing in a form you can edit:

```bash
docker compose run --rm myriaxon          # the terminal agent
docker compose up dashboard               # the dashboard on http://127.0.0.1:8765
```

### The dashboard needs `--host 0.0.0.0`

```bash
docker run -it --rm -p 127.0.0.1:8765:8765 \
  -v myriaxon-config:/home/myriaxon/.myriaxon \
  -v "$PWD:/workspace" \
  ghcr.io/myriaxon/harness:latest web --no-browser --host 0.0.0.0
```

**This is required, not a convenience.** The dashboard binds `127.0.0.1` by default, which inside a
container means the port is published and still unreachable. That default is deliberate — loopback is the
safe choice for a tool that can read your files — so the container does not quietly widen it.

---

## What is verified, and how

Every claim below was measured on Debian 13 under WSL2 with Docker 26.1.5, at commit `8c37203`.
Nothing here is asserted from reading the Dockerfile.

| Check | Result |
|---|---|
| `--version` prints the version | ✅ `Myriaxon 0.0.1` |
| `--help` exits 0 with no config | ✅ 100 lines |
| runs as **uid 1000**, not root | ✅ |
| the config directory is writable (the volume mount point) | ✅ |
| the distribution metadata is intact | ✅ `['myriaxon', 'myriaxon.__main__:main']` |
| built-in skills, roles, IQB-14 tasks, brand assets all shipped | ✅ 2 / 4 / 28 / 3 |
| `write_file` and `read_file` dispatch inside the container | ✅ |
| **confinement still refuses** a path outside the workspace | ✅ `WorkspaceEscape` |
| the sandbox has `pwsh`, python3, node, git | ✅ |
| the sandbox has numpy, pandas, matplotlib, Pillow | ✅ |
| the sandbox has sqlite3, jq, zip, rsync, graphviz, imagemagick, pandoc, gnuplot | ✅ |
| **the sandbox has no network at run time** | ✅ `--network none` verified live |
| a file written through a bind mount is owned by uid 1000, not root | ✅ |
| git can commit inside the sandbox | ✅ |

**Harness image: 12/12. Sandbox image: 25/26 (the one failure was the test's, see below).**

---

## Three real bugs the container work found

Recorded because each one was invisible from outside and each would have shipped.

### 1. You could not run any command in the container

`ENTRYPOINT ["python", "-m", "myriaxon"]` looks right and is not. Docker **appends** the command rather
than replacing it:

```
docker run --rm myriaxon-harness python -c "print(1)"
  -> python -m myriaxon python -c "print(1)"
  -> myriaxon: error: argument command: invalid choice: 'python'
```

The consequence is not cosmetic. It removes the ability to get a **shell** in the container — no
`docker run --rm image bash`, no `python -c` to inspect the install. **An image you cannot get a shell in
is an image you cannot diagnose**, and that is the first thing anyone reaches for when a container
misbehaves.

Fixed with `docker/entrypoint.py`, which decides at runtime: a bare flag or a Myriaxon subcommand runs the
agent, anything else is executed as a command. The subcommand list is read from the CLI's own parser, so it
cannot drift.

### 2. The sandbox's own `/workspace` was read-only

```bash
docker run --rm myriaxon-sandbox:latest touch /workspace/x
  -> Permission denied
```

`WORKDIR /workspace` is a convenience instruction: Docker **creates** the directory as root when it does
not exist, and `WORKDIR` ran *after* `USER sandbox`. So the one directory every confined Locus writes to
was root-owned and read-only to the user meant to work in it.

**A bind-mounted workspace hid it**, because the mount replaces the directory — so the common case worked
and the image's own default did not. Anything running without a mount hit it. Fixed with an explicit
`mkdir -p /workspace && chown sandbox:sandbox /workspace` before `USER`.

### 3. The harness image had no Docker client, so the Locus sandbox could never work

`tools.docker_prefix()` returned `None` inside the container even with the socket mounted, so
`shell_may_run()` refused every command to a confined Locus. The harness could run the agent but not use
its own isolation.

Fixed with an opt-in `--build-arg WITH_DOCKER_CLI=true`. See [Nested sandbox](#nested-sandbox-the-locus-jail-inside-the-harness-container).

---

## Nested sandbox: the Locus jail inside the harness container

```bash
docker build -t myriaxon-sandbox:latest docker/

DOCKER_GID=$(getent group docker | cut -d: -f3)
docker build \
  --build-arg WITH_DOCKER_CLI=true \
  --build-arg MYRIAXON_GID="$DOCKER_GID" \
  -t myriaxon-harness:latest .

docker run -it --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e MYRIAXON_SANDBOX_IMAGE=myriaxon-sandbox:latest \
  -v myriaxon-config:/home/myriaxon/.myriaxon \
  myriaxon-harness:latest
```

**The socket, not Docker-in-Docker.** Sandbox containers become **siblings on the host daemon**. DinD
would need `--privileged` and a second daemon inside the harness image, which grants strictly more
privilege for strictly less benefit: the sandbox is meant to be a boundary the harness *cannot* cross, and
a nested daemon the harness owns is a boundary it can.

### `MYRIAXON_GID` must match the host's docker group

The socket is `root:docker 0660`. A container user with GID 1000 is **not in that group** and gets
`permission denied while trying to connect to the docker API`. Measured on the test host: the docker group
is GID **102**, so the image is built with `--build-arg MYRIAXON_GID=102`.

This is the general rule for any container that needs a host group — build the container's user into the
**same GID** the host resource is owned by. The image exposes `MYRIAXON_GID` for exactly this.

### ⚠️ Known limitation: the workspace path must be a HOST path

**This is the one thing that does not work the obvious way, and it is architectural rather than a bug.**

The harness asks the **host** daemon for `-v <path>:/workspace`. Docker resolves that path **on the host**,
not inside the harness container. So a container-local path like `/workspace` does not exist on the host,
and Docker silently creates an **empty directory** instead — the agent loses its workspace with no error.

Measured, both directions:

```
A. pass the path as the HARNESS sees it   ->  '' rc 1        FAILS
B. pass a path that exists on the HOST    ->  'host-...' rc 0  WORKS
```

A host path works; a container path does not. Consequences:

* ✅ The nesting works when the sandbox's workspace is given as a host path.
* ❌ It does **not** work when the harness is itself confined to a container-local mount.
* The workspace mount in the failing case is **silently empty**, which is the worst shape — no error, just
  an agent that cannot see its files.

**A real fix would need the harness to translate container paths to host paths**, which means knowing the
host's mapping — in general unknowable from inside a container. The honest options are to pass host paths,
or to use a named volume that exists on both sides.

---

## Code signing, and what this image does about detections

See [FALSE-POSITIVE.md](FALSE-POSITIVE.md) for the full account of the pip launcher and why an antivirus
may flag it.

**The container sidesteps that entirely.** It runs Linux, and there is no `.exe` anywhere in it — the
Windows console-script launcher does not exist here. `python -m myriaxon` is the entrypoint, which is the
same program through the same entry point the launcher calls.

What the image cannot fix: it is **unsigned**, because signing a container image needs the same kind of
certificate as signing a binary. OCI image signing (`cosign`) is the equivalent practice and is not set up
here.

---

## Verifying your own copy

```bash
docker run --rm myriaxon-harness:latest --version
docker run --rm myriaxon-harness:latest --help > /dev/null && echo "help ok"
docker run --rm myriaxon-harness:latest id           # must NOT be uid 0
docker run --rm myriaxon-harness:latest doctor       # provider and key state
docker image inspect myriaxon-harness:latest --format '{{json .Config.Labels}}'
```

The last one prints the author, licence, source, version and revision, so an image can be traced to the
commit it was built from.

---

## Building it yourself

```bash
docker build -t myriaxon-harness:latest .

# with the sandbox client, for nested Locus jails
docker build --build-arg WITH_DOCKER_CLI=true \
             --build-arg MYRIAXON_GID="$(getent group docker | cut -d: -f3)" \
             -t myriaxon-harness:latest .
```

| Build argument | Default | Purpose |
|---|---|---|
| `MYRIAXON_VERSION` | `0.0.1` | the version in the image labels |
| `MYRIAXON_REVISION` | `unknown` | the commit, so an image traces to its source |
| `MYRIAXON_UID` / `MYRIAXON_GID` | `1000` | the container user; match the host for bind mounts |
| `WITH_DOCKER_CLI` | `false` | install the Docker client, for the nested Locus sandbox |
| `DOCKER_CE_CLI_VERSION` | `5:29.9.1-1~debian.12~bookworm` | pinned exactly |

`.dockerignore` is a **security control** here, not an optimisation: the build context is sent to the
daemon *before* any instruction runs, so a real `.env` in the context has already left the machine even if
no later step copies it. Both `.env` and `.myriaxon/` are excluded first, for that reason.

---

## Publishing

`.github/workflows/container.yml` builds and pushes to `ghcr.io/myriaxon/harness` on a `v*` tag, for
`linux/amd64` and `linux/arm64`. A published image that does not run is worse than no image, so the
workflow **runs the container it just built** and asserts it starts, answers, is not root, and can write
its config directory — before pushing.

A `workflow_dispatch` run builds without pushing, so the Dockerfile can be checked without publishing.
