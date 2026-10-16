# Myriaxon

**Ten thousand paths. One mind.**
An advanced agentic harness for the terminal and the browser.

Myriaxon is a coding agent that runs against the provider you already pay for — Anthropic, any
OpenAI-compatible endpoint, OpenRouter, DeepSeek, Netra, or Gemini/Vertex AI. It ships as a plain
Python package: no Node.js, no sign-in flow, no build step, and a web dashboard that uses nothing but
the standard library.

It also ships its own evaluation standard, **IQB-14**, so the same agent you use can be measured
rather than merely described.

```powershell
myriaxon                          # interactive terminal REPL
myriaxon -p "explain main.py"     # one-shot, non-interactive
myriaxon web                      # local dashboard at http://127.0.0.1:8765
python -m myriaxon.bench lint     # validate the IQB-14 task suite (free, no API calls)
```

---

## Highlights

| | |
|---|---|
| **Multi-provider** | Anthropic, OpenAI-compatible (any endpoint), OpenRouter, DeepSeek, Netra, Gemini + Vertex AI — six built-in providers plus unlimited custom endpoints, switchable mid-conversation |
| **37 tools** | read/write/edit, shell with background jobs, grep/glob, git status/diff, notebooks, web search/fetch, todos, memory search, skills, checkpoints, scheduling, persistent agents, structured questions |
| **Persistent agents** | *loci* — durable identities with a role, standing instructions and objectives that survive restarts, act on their own schedule, and log everything they do |
| **Sub-agents** | `task`, `send_to_subagent` and `parallel_tasks`, capped at **3 concurrent sub-agents**, with no recursive delegation |
| **Skills** | `SKILL.md` folders at user and project level, listed in the system prompt and loaded on demand |
| **Hooks** | shell hooks on `PreToolUse` / `PostToolUse` / `UserPromptSubmit` — a non-zero exit blocks the call |
| **Plugins** | in-process Python plugins that add tools and observe five hook events, without a subprocess per call |
| **MCP** | stdio **and** remote HTTP servers (streamable HTTP, then SSE), with bearer-token or custom-header auth, registry search and an 18-server catalog |
| **Checkpoints / rewind** | automatic file snapshots before every overwrite, plus a whole-project shadow git history for `/rewind` |
| **Memory** | cross-project full-text search over past session transcripts (SQLite FTS5) |
| **Layered permission policy** | `allow` / `ask` / `deny` rules, argument-aware (`run_bash:git *`), layered user → project → system |
| **Model adaptation** | `small` / `balanced` / `large` profiles that change prompt, tool-result caps, compaction thresholds and delegation per model |
| **IQB-14** | a 14-parameter benchmark with a composite AXS score, pass@k / pass^k, Wilson intervals and reproducible scorecards |
| **Two front ends** | a terminal REPL and a local zero-dependency web dashboard over the same agent |
| **Mission control** | the dashboard's landing view: connection health for every provider and integration, usage and token accounting, runs with elapsed time, decisions waiting on you, scheduled work, a live trace, model routing, memory and skills — every figure read from the machine, never illustrative |

---

## Install

Requires **Python 3.10 or newer**. Pick the line that matches what you have.

### From GitHub

The distribution is `myriaxon-harness`; the import package is `myriaxon`. `pip install` normalises the name, so
either spelling works.

```bash
pip install "myriaxon-harness[all] @ git+https://github.com/matchu-id/myriaxon-harness.git@v0.0.1"
```

Or from a clone, which is the route to take if you intend to change anything:

```bash
git clone https://github.com/matchu-id/myriaxon-harness.git
cd myriaxon-harness
pip install ".[all]"
```

### Easiest — install a prebuilt wheel

If you have the folder this project ships in, `dist/` contains a built wheel. That is the fastest and most
predictable route: one file, no build step, dependencies resolved by pip.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install (Get-ChildItem dist\myriaxon_harness-*.whl | Select-Object -First 1).FullName
myriaxon --version
```

```bash
# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate
pip install dist/myriaxon_harness-*.whl
myriaxon --version
```

The filename is a glob rather than a literal on purpose. It was written as `myriaxon-1.2.0-...` and broke on
the first public release, because the distribution gained a `-harness` suffix and the version changed — so
anyone following the instructions got "no such file" instead of a diagnosis.

Add `[all]` for every provider, MCP and the OS keychain:

```powershell
pip install "dist\myriaxon_harness-0.0.1-py3-none-any.whl[all]"
```

> **It is not usable until you add a credential.** `myriaxon --version` working only proves the
> install. To actually run the agent, see **§5 Provider setup** in [`INSTALL.md`](INSTALL.md) — one
> API key, or a local Ollama model with no key at all.

### From a checkout — the guided installers

Both scripts create a private virtualenv **inside the folder**, install into it, and write nothing
to `Program Files`, the registry, or a system Python. Neither needs administrator rights.

```powershell
# Windows
.\install.ps1                 # add -Extras all for every provider SDK
.\install.ps1 -Verify         # ...and run the offline test suite afterwards
```

```bash
# macOS / Linux
./install.sh                  # add --extras all for every provider SDK
./install.sh --verify         # ...and run the offline test suite afterwards
```

If Windows refuses to run the script, do not change any system policy — bypass it for this one
invocation:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### From a checkout — plain pip

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install .                 # installs the package; `-e .` instead if you are editing it
```

The base install is five dependencies — `anthropic`, `rich`, `pygments`, `prompt_toolkit` and
`httpx` (the default transport for every OpenAI-compatible provider, and required by the MCP
registry search) — and covers the Anthropic provider. Everything else is an optional extra:

| Extra | Installs | For |
|---|---|---|
| `openai` | `openai>=1.50` | the OpenAI SDK, as an alternative to the built-in `httpx` client |
| `gemini` | `google-genai>=2.0` | Gemini and Vertex AI |
| `mcp` | `mcp>=1.0` | MCP servers, both transports |
| `poster` | `pillow>=10.0` | PNG poster output from `design_poster` (SVG needs nothing) |
| `keychain` | `keyring>=24.0` | storing API keys in the OS credential store |
| `build` | `pyinstaller>=6.0` | the single-file binary build |
| `all` | the five runtime extras | every provider, MCP, poster output and the OS keychain |
| `dev` | `pytest`, `pytest-timeout` | running the test suites |

```powershell
pip install -e ".[all]"      # everything at runtime
pip install -e ".[dev]"      # what the tests need
```

### Building the wheel and sdist yourself

```bash
python -m pip install build
python -m build               # writes dist/myriaxon-<version>-py3-none-any.whl and .tar.gz
```

`python -m build` also needs the `wheel` package and stops with `Unmet dependencies ... wheel`
rather than falling back. Either install it, or call the backend directly — which is all the build
frontend does, needs nothing beyond `setuptools`, and takes about a second here:

```bash
python -c "from setuptools import build_meta as bm; print(bm.build_wheel('dist'))"
python -c "from setuptools import build_meta as bm; print(bm.build_sdist('dist'))"
```

### Installing `myriaxon` where you already have pip

There is no PyPI or git-URL install yet — the repository is **not published**, so
`pip install myriaxon` and `pip install git+https://github.com/...` both fail. The URLs in
`pyproject.toml` are placeholders for when it is. Until then the wheel above, the installers, or
`pip install .` from a checkout are the three routes that work.

### Verify the install

```powershell
myriaxon doctor          # environment, config, credential and dependency checks
myriaxon --version
```

`doctor` is the honest answer to "did this work?" — it reports what it checked and what it found,
rather than a bare success message.

The version is read from `myriaxon/constants.py` (`VERSION`). The distribution packages the whole
tree: the dashboard, the benchmark, the IQB-14 task files, the built-in skill and the brand SVGs are
all inside the wheel rather than left behind in the source tree.

Installing gives you the `myriaxon` console command; `python -m myriaxon` works identically without
it. Two Windows launchers wrap the common cases from any directory:

| Launcher | What it runs |
|---|---|
| `myriaxon.cmd` | the terminal agent — REPL, or one-shot with `-p` |
| `myriaxon-web.cmd` | the dashboard; defaults `--workspace` to the repository root |

They are separate commands on purpose: the CLI runs and exits, while the dashboard is a long-running
server. Two different lifecycles should not share one command.

---

## Quickstart

**New here?** Two documents cover everything, in order:

| | |
|---|---|
| **[docs/HOW-TO-USE.md](docs/HOW-TO-USE.md)** | install, first run, the dashboard, the transparency dial, loci, the swarm board, permissions, troubleshooting |
| **[docs/API-KEYS.md](docs/API-KEYS.md)** | putting in a **DeepSeek** or **Netra** key, Gemini through Vertex with no key at all, Ollama with no account, and which setting outranks which |

The shortest path:

```bash
myriaxon --reauth      # pick a provider, paste a key, done
myriaxon web           # the dashboard at http://127.0.0.1:8765
```

### 1. Configure a provider (once)

```powershell
myriaxon auth        # or: python -m myriaxon auth
```

The wizard asks for a **provider**, then an **endpoint** and a **model** pre-filled with that
provider's own defaults — the endpoint is not asked at all where it is fixed (DeepSeek, OpenRouter, Netra) —
and finally the **API key**. It saves the result to `~/.myriaxon/config.json`. There is no sign-in
flow and no OAuth. Only the generic `openai_compat` provider has no default endpoint or model, so
those two must be typed; picking Gemini additionally offers Vertex AI mode (a GCP project instead of
an endpoint).

A `.env` file in the current directory is loaded at startup (`KEY=value` per line, `#` comments
ignored); variables already set in your shell are never overridden. `GEMINI_API_KEY=…` in `.env` is
picked up automatically.

### 2. Terminal

```powershell
myriaxon                                   # interactive REPL
myriaxon -p "summarise the failing tests"  # one-shot, prints and exits
myriaxon --mode plan -p "propose a fix"    # read-only planning pass
myriaxon.cmd                               # the launcher, from anywhere
```

Useful flags:

| Flag | Effect |
|---|---|
| `-p`, `--print PROMPT` | run one prompt non-interactively and exit |
| `-y`, `--yolo` | skip confirmation for write/edit/bash/notebook tools |
| `--mode {manual,auto_edit,plan,auto}` | permission mode (default `manual`) |
| `--model NAME` | override the model |
| `--max-tokens N` | override the reply ceiling (default: the model's own real cap when fetchable) |
| `--effort {low,medium,high,xhigh,max}` | reasoning effort, where the provider supports it |
| `--thinking` | show the model's reasoning trace as it streams |
| `--profile {small,balanced,large}` | force a model-capability profile instead of auto-detecting |
| `--agent-mode {single,multi}` | `multi` additionally offers `task` / `parallel_tasks` |
| `--sandbox` | run `run_bash` in an isolated container/VM instead of directly on the host |
| `--no-compact` | disable automatic context compaction (Anthropic only) |
| `--no-resume` | don't offer to resume the session saved in this folder |
| `--output-format {text,json}` | structured output for `-p` runs |
| `--gemini-protocol {auto,generate,interactions}` | which Google protocol the Gemini provider speaks |
| `--reauth` | re-run provider setup |

### 3. Dashboard

```powershell
myriaxon web                                     # serve the current directory, open a browser
myriaxon web --workspace C:\path\to\project      # serve a specific project
myriaxon web --port 9000 --no-browser
myriaxon-web.cmd                                 # same, with the repository as the workspace

myriaxon bot                                     # guided setup for a bot you can message
myriaxon bot --list                              # the ready-made bots
myriaxon bot --template researcher --yes          # create one without questions
myriaxon bot --serve --tunnel                     # serve it and print a public webhook URL

myriaxon search                                  # which web-search backends are in use
myriaxon search --set brave:YOUR_KEY              # store a search API key
myriaxon search --test                            # run a real query and show what came back
```

`http://127.0.0.1:8765` by default, bound to loopback. The page is served from memory as one
self-contained string: no web framework, no build step, no static-file routes, no CDN, no external
request of any kind — so it runs wherever the CLI runs, including air-gapped machines.

| In the dashboard | Notes |
|---|---|
| Chat | streaming markdown — headings, lists, tables, code, links |
| Trajectory tab | every tool call with arguments, result, duration and error state |
| Files & changes | file explorer plus a colourised diff viewer, with a staged toggle |
| Sessions | create, switch, delete — each keeps its own agent and stream |
| Projects | open any directory at runtime; reads, writes and uploads follow it |
| Vendors + models | switch vendor mid-conversation; add, probe and test any OpenAI-compatible endpoint |
| Modes | manual / auto_edit / plan / auto, switchable live |
| Settings | workflow, reasoning, effort, reply cap, approval, compaction, theme, density |
| MCP servers | list, add (stdio or remote + token), remove, search the registry |
| Plugins | which plugins loaded, their tools and hooks, and a **Reload plugins** button |
| Permission rules | edit the same `allow` / `ask` / `deny` rules the CLI enforces |
| Messaging | WhatsApp via Twilio / Meta / generic webhook (see [docs/MESSAGING.md](docs/MESSAGING.md)) |
| Attachments | drag-drop, paste, or 📎 — images reach the model as real vision input |
| Theme | dark or light, following the OS preference, remembered per browser |

Notes that matter:

* **API keys never reach the browser.** The UI learns only whether a key is present (`has_api_key`).
  Editing an endpoint without retyping the key keeps the stored one.
* **Vendor switching carries conversation, not tool calls.** The transcript is snapshotted and
  re-seeded into the rebuilt agent, and the switch reports how many messages it carried. The tool
  exchange is dropped because the provider message formats are incompatible — OpenAI-compatible
  agents store `tool_calls`, while Gemini stores typed `function_call`/`function_result` parts and
  requires a `thought_signature` on replayed calls. The dropped calls remain visible in the
  Trajectory tab.
* **Automatic approval defaults to on in the dashboard**, because it has no terminal on which to ask.
  Turning it off makes tools that would need confirmation fail instead of prompting.
* **Opening a project changes the process working directory**, because the agent's file tools resolve
  relative paths against it. Reads, writes and uploads are confined to that directory.
* Commands that need a terminal (`/reauth`, `/rewind`, `/undo`, `/mcp`, `/sandbox`, …) say so
  explicitly in the dashboard instead of pretending to work.

---

## Providers

One provider is active at a time. Switching re-runs setup, or uses `/provider` for the session.

| Provider | Value | Client | Default endpoint | Default model | Key fallback |
|---|---|---|---|---|---|
| Anthropic | `anthropic` (default) | `anthropic` SDK (base dep) | `https://api.anthropic.com` | `claude-opus-5` | — |
| OpenAI-compatible | `openai_compat` | built-in `httpx` client | *asked at setup* | *asked at setup* | — |
| OpenRouter | `openrouter` | built-in `httpx` client | `https://openrouter.ai/api/v1` | *pre-filled from a curated shortlist* | `OPENROUTER_API_KEY` |
| DeepSeek | `deepseek` | built-in `httpx` client | `https://api.deepseek.com` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| Netra | `netra` | built-in `httpx` client | `https://api.netraruntime.com/v1` | `deepseek/deepseek-v4.1-flash` | `NETRA_API_KEY` |
| Gemini | `gemini` | `google-genai` (extra) | `https://generativelanguage.googleapis.com/` | `gemini-3.8-flash` | `GEMINI_API_KEY` |

The OpenAI-compatible providers talk to the endpoint over `httpx` directly; `MYRIAXON_OPENAI_SDK=1`
switches them to the `openai` SDK (`pip install -e ".[openai]"`) when you want its own retry and
transport behaviour.

What differs between them:

* **Anthropic** gets the full tool set, including the hosted `web_search` / `web_fetch` server tools
  that run on Anthropic's infrastructure, Anthropic's native auto-compaction, and the remote-MCP
  connector. Its tool block is sent with prompt caching enabled.
* **OpenAI-compatible** providers have no equivalent for the hosted server tools, so those two tools
  are simply not offered; everything else works the same, stdio MCP included. `--effort` maps to
  `extra_body.reasoning` (accepted by Netra, OpenRouter and other reasoning-capable gateways), and
  OpenRouter requests additionally carry its `web` plugin.
* **Gemini** is built on Google's step/event-based protocol for the 3.x line and `generateContent`
  for older models; the protocol is chosen per model automatically, and `--gemini-protocol` or
  `MYRIAXON_GEMINI_PROTOCOL` overrides it. **`--effort` and `--thinking` are not wired up for this
  provider** — the CLI says so, and Gemini models reason by default regardless.
* **Vertex AI** is not a separate provider: it is the same Gemini provider with the client built
  against a GCP project and location, optionally through workforce identity federation. See
  [docs/VERTEX-SETUP.md](docs/VERTEX-SETUP.md).

Switching provider mid-session starts a fresh conversation, because each provider's message format is
incompatible with the others. The previous conversation is still the one saved on disk.

---

## Configuration

Every field resolves in this order: **environment variable → stored config file → built-in default**.

| Field | Env var | Config key | Default |
|---|---|---|---|
| Provider | `MYRIAXON_PROVIDER` | `provider` | `anthropic` |
| API key | `MYRIAXON_API_KEY` | `api_key` | *required* — prompts if unset |
| Endpoint | `MYRIAXON_BASE_URL` | `base_url` | per provider (see above) |
| Model | `MYRIAXON_MODEL` | `model` | per provider (see above) |
| Fallback model | `MYRIAXON_FALLBACK_MODEL` | `fallback_model` | unset |

| Other env var | Effect |
|---|---|
| `MYRIAXON_CONFIG_DIR` | relocate the state directory (highest priority) |
| `MYRIAXON_USER_CONFIG_DIR` | relocate only the user settings layer (`settings.json`) |
| `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `NETRA_API_KEY` | provider-specific key fallbacks |
| `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex AI mode |
| `MYRIAXON_GEMINI_PROTOCOL` | `auto` / `generate` / `interactions` |
| `MYRIAXON_TIMING` | print a per-phase startup/turn timing table to stderr |
| `MYRIAXON_OPENAI_SDK` | use the `openai` SDK instead of the built-in direct HTTP client |
| `MYRIAXON_DASHBOARD_VERBOSE` | log every dashboard HTTP request |
| `MYRIAXON_TOOL_NAME`, `MYRIAXON_TOOL_IS_ERROR` | set for hook commands, not read from your shell |

The pre-rebrand `IOH_*` names are **not** read; the rename moved them to `MYRIAXON_*`.

### Where state lives

`~/.myriaxon` by default, with these contents:

| Path | Contents |
|---|---|
| `config.json` | provider, endpoint, model, API key |
| `settings.json` | the user policy layer: permission rules, theme, profiles, enforced settings |
| `mcp_servers.json` | MCP servers, both transports |
| `hooks.json` | user-level shell hooks |
| `skills/`, `commands/`, `agents/`, `plugins/` | user-level skills, custom slash commands, sub-agent types, plugins |
| `memory.db` | cross-session search (SQLite FTS5) |
| `audit.jsonl` | append-only governance audit trail of tool calls |
| `history/` | the per-project shadow git history used by `/rewind` |
| `logs/myriaxon.log` | errors and crashes, rotated at 2 MB with 3 backups |
| `prompt_history.txt` | REPL input history, persisted across launches |

Two fallbacks exist because the default is not universally writable:

1. A pre-rebrand `~/.iohcode` is **renamed** into `~/.myriaxon` on first run, so an existing
   installation keeps its keys, history, skills, MCP servers and memory database.
2. If `~/.myriaxon` cannot be written (a managed machine with restrictive ACLs), Myriaxon falls back
   to a `.myriaxon` directory next to the package and says which directory it is using.

Logging is entirely local; nothing is transmitted anywhere. Myriaxon never exits with a raw traceback
— it prints a themed message pointing at the log file.

---

## Slash commands

Type `/help` in the REPL for the annotated list. Every command below is implemented in the terminal;
the dashboard implements 19 of them and names the reason for the other 13.

| Command | Effect |
|---|---|
| `/help` | the command list |
| `/mode <manual\|auto-edit\|plan\|auto>` | switch permission mode without restarting |
| `/yolo` | toggle auto-accepting every confirmation |
| `/profile [name]` | apply a named mode+yolo bundle (built in: `fast`, `careful`) |
| `/effort [level\|none]` | show or set the reasoning effort |
| `/thinking` | toggle the reasoning-trace display |
| `/max-tokens [n]` | show or set the reply ceiling |
| `/model [name\|list]` | show or switch the model |
| `/models` | list models available for the active provider |
| `/provider [name]` | switch provider for this session |
| `/fallback-model [name\|none]` | set the model used after a quota or rate-limit failure |
| `/reauth` | re-enter credentials for this session (not saved) |
| `/clear` | reset the conversation and the todo list |
| `/compact` | summarise older turns and continue from the summary |
| `/context` | profile, live context meter, the action the harness would take, per-bucket breakdown |
| `/cost` | token usage and cost for this session |
| `/todos` | the current task checklist |
| `/export [path]` | export the transcript as Markdown |
| `/undo` | restore the most recent file checkpoint |
| `/rewind [id]` | list or restore whole-project checkpoints (shadow git) |
| `/diff` | unified diff of every file changed this session |
| `/retry` | re-send the last message as a fresh turn |
| `/trace` | toggle raw tool arguments and results |
| `/ground` | toggle the soft warning when a reply names files no tool call touched |
| `/policy` | the merged layered permission policy |
| `/sandbox [on\|off]` | toggle isolated `run_bash` execution |
| `/mcp [list\|list-available\|search\|install\|remove]` | manage MCP servers |
| `/plugins` | which plugins loaded, with their tools and hooks |
| `/memory search <query>` | full-text search past sessions, any project |
| `/commands` | list discovered custom slash commands |
| `/theme [default\|high-contrast\|mono]` | switch terminal colour theme (persisted) |
| `/vim` | toggle vi-style input-line editing (persisted) |
| `/shells` | background processes started by `run_bash` |
| `/doctor` | one-shot health check: provider, model, key presence, the active provider's SDK, sandbox and MCP status, active settings layers |
| `exit` / `quit` | leave the REPL |

**Custom commands.** A Markdown file with `name:` and `description:` frontmatter in
`~/.myriaxon/commands/` or `<project>/.myriaxon/commands/` becomes `/<name>`; its body is expanded
into the prompt. Built-in names are reserved, and a collision is reported rather than silently
ignored.

---

## Tools

**31 tools** are registered. Three of them (`task`, `send_to_subagent`, `parallel_tasks`) are offered
only in `--agent-mode multi`, so a default single-agent session sees 34.

| Tool | Confirmation | Notes |
|---|---|---|
| `read_file`, `glob_search`, `grep_search` | no | read-only |
| `write_file`, `edit_file`, `edit_notebook` | yes | shows a diff first |
| `run_bash` | yes | PowerShell on Windows, `sh` elsewhere; 120 s default timeout |
| `bash_output`, `kill_bash` | no | read from, or stop, a background shell |
| `git_status`, `git_diff` | no | structured repository state and diffs |
| `web_search`, `web_fetch` | no | hosted on Anthropic; every other provider gets local implementations of the same two tools (`myriaxon/web_tools.py`) |
| `todo_write` | no | the visible checklist |
| `ask_user_question` | no | a clarifying question with a fixed set of options |
| `use_skill`, `save_skill` | no | load a `SKILL.md` body; write a new skill |
| `search_memory` | no | full-text search across past sessions, any project |
| `checkpoint_list`, `checkpoint_restore` | restore confirms | list or roll a file back to a snapshot |
| `schedule_prompt`, `list_scheduled`, `cancel_scheduled` | no | session-scoped delayed prompts — **deferred** |
| `task`, `send_to_subagent`, `parallel_tasks` | inherited | sub-agent delegation (multi mode only) — **deferred** |
| `locus_list`, `locus_create`, `locus_goal_update`, `locus_run` | no | persistent agents — **deferred** |
| `design_poster` | no | compose a poster; writes SVG, PNG and a print-ready PDF — **deferred** |
| `mcp__<server>__<tool>` | from the server | any tool a configured MCP server exposes |

**Deferred tools.** Seven groups are withheld from the request until `request_tools` loads them — the
rows marked **deferred** above. Measured, they were 10,545 of the 18,698 characters of tool schema
sent on *every* request: **56% of the tool payload, about 2,636 tokens per request**, for capabilities
a coding turn rarely reaches for. `request_tools` ships in their place with a compact catalogue naming
every group, and an unknown group name is refused with the valid list, so a wrong guess costs one
correction rather than a dead end. Nothing is unreachable: with every group loaded, all 32 tools are
offered.

One caveat, stated because it is the model's decision: tools sit inside the provider's cached prefix,
so **loading a group mid-conversation costs one cache re-bill** — far more than the schemas
themselves. The tool's own description tells the model to load what it needs early and in one call.

Tool results are truncated at the boundary between the tool and the model, and the truncation is
**stated in the result** — head and tail are kept either side of a marker:

```
... [12,480 chars omitted -- re-run with a range if you need them.]
```

The marker is deliberately short: it is re-sent on every later request in the turn, once per
truncated result, so a paragraph of advice here is paid for repeatedly. The advice lives in the
`read_file` and `run_bash` descriptions instead, where it is charged once.

A silently truncated result makes a model assert things about data it never saw. The full text still
reaches the IQB-14 trace.

### Sub-agents

* `task` spawns a sub-agent with your tools minus the delegation tools themselves, and **no
  conversation history** — the prompt must carry its own context.
* `parallel_tasks` runs several at once, capped at **3 concurrent sub-agents**
  (`MAX_PARALLEL_SUBAGENTS`), enforced by a semaphore rather than by asking the model nicely.
* `send_to_subagent` continues a previously spawned sub-agent by id, keeping its history. The
  registry is in-memory, so it does not survive a session resume.
* Built-in sub-agent types are `general-purpose` and `explore` (read-only search and reading). Add
  your own as Markdown files with frontmatter in `~/.myriaxon/agents/` or
  `<project>/.myriaxon/agents/`.
* Delegation is **off by default**. A weak model delegating to a weaker model with a smaller window
  is worse than not delegating, so `--agent-mode multi` is an explicit choice.

### Persistent agents — loci

A sub-agent exists for one tool call and is then forgotten. A **locus** is an identity that persists:
a name, a role, standing instructions, objectives it is working toward, its own workspace, and a
log of everything it has done — all of which it resumes every time it runs.

The two failure modes of a chat-shaped agent are that it forgets and that it waits. A locus fixes
both with durable state rather than a longer prompt.

```text
/loci create release-notes --role "release manager" \
    --goal "Keep CHANGELOG.md current after every merge" \
    --instructions "Never invent an entry; only describe changes present in git log." \
    --proactive --every 3600
```

```text
/loci                          list every locus and its open objectives
/loci show release-notes       role, instructions, objectives, workspace, recent activity
/loci chat release-notes       talk to it continuously — everything you type goes to it
/loci off                      back to Myriaxon
/loci run release-notes        run one turn as that locus, now (a fresh agent each time)
/loci goal release-notes "…"   add an objective
/loci goal release-notes a1b2 --done --note "covered in 1.4.0"
/loci proactive release-notes on|off
/loci rm release-notes         delete it (confirmed, policy-gated)
```

`/loci chat` is the difference between a conversation and a series of questions. `run` builds a new
sub-agent per message, so each one starts from nothing; `chat` routes everything you type to that locus
and keeps one transcript, the way the dashboard does. The prompt changes to `release-notes>` so you
can see who is about to answer, and `/loci off` hands it back. `/loci off <name>` keeps its older
meaning of turning proactivity off for that locus — the two are told apart by whether a name follows.

The agent can do the same through four tools — `locus_list`, `locus_create`, `locus_goal_update`,
`locus_run` — so *"set up something to keep the dependencies current"* works as plain language.
Those four are **deferred**: withheld from the tool list until `request_tools` loads the `loci` group,
which is where 56% of the per-request tool payload went.

**How a locus remembers.** Its standing brief is rebuilt from `~/.myriaxon/loci.json` on every turn,
not carried in a session. That is why a locus working in the terminal and the same locus working in
the dashboard behave identically, and why nothing is lost when you close a window.

**How a locus acts.** A proactive locus runs when its interval has elapsed *and* it has open
objectives, at the top of the prompt in an open session. Its turns are ordinary turns: the same
permission mode, the same budget checks, the same audit log. Autonomy is not privilege — a locus in
`manual` mode still asks before it writes.

**What stops it running away.** A goal marked `blocked` is never retried, because blocked means a
person owes an answer and retrying spends tokens to learn the same thing. A locus with no open
objectives is never due and is told explicitly not to invent work. Everything it does is appended
to a bounded activity log you can read.

**Scope, stated plainly.** A locus runs while a Myriaxon process is open — terminal or dashboard. It
is not a detached daemon, deliberately: a background process that keeps editing files and spending
tokens after you close the window is a surprise, not a feature. `LocusRegistry.next_due()` is the
hook for a supervisor (a scheduled task, a container, cron) if you want it genuinely continuous.

---

## Permissions and safety

### One gate for every execution path

Myriaxon executes things for a model, so the restriction has to hold on **every** path that runs something —
not just the one the tool dispatcher guards. `tools.shell_may_run()` is the single answer to *"may a shell run
here"*, and both `confirm_action` (which `run_bash` goes through) and the Locus condition evaluator ask it.

That shared decision exists because two controls here once held on the path they were written for and not on
another path doing the same thing: `run_bash` refused a confined shell with no sandbox while a **condition**
executed freely, and the workspace confinement guarded the file tools while a "private" member directory sat
inside the tree it trusted. Both were a decision duplicated rather than shared. The audit that found them, with
the reproductions, is [docs/SECURITY-AUDIT.md](docs/SECURITY-AUDIT.md).

| Channel | Bound by |
|---|---|
| File tools | `_resolve` — the resolved path must sit inside the Locus workspace, or a granted shared directory |
| `run_bash` | `shell_may_run` — a confined Locus gets a shell only when a real sandbox is available |
| Locus conditions | `shell_may_run` — the same question, the same answer |
| `web_fetch` | `_refuse_reason` — loopback, RFC1918, link-local and metadata hosts are refused |
| Outbound messaging | a shared secret, compared with `hmac.compare_digest` |
| MCP / client schemas | never indexed for search — a hostile server cannot seed the catalogue |

### Modes

| Mode | `write_file` / `edit_file` / `edit_notebook` | `run_bash` |
|---|---|---|
| `manual` (default) | confirm | confirm |
| `auto_edit` | auto-approve | confirm |
| `plan` | **blocked** — the model must describe the plan in text | **blocked** |
| `auto` | auto-approve | auto-approve, *unless* the command matches the risky-command heuristic |

`--yolo` / `/yolo` is a separate, orthogonal override that skips every confirmation regardless of
mode — except in Plan mode, which blocks mutating tools even over `--yolo`, since the entire point of
Plan mode is that nothing happens until you switch out of it. The risky-command heuristic (`rm -rf`,
force-push, disk-formatting commands, …) is **best-effort, not a security boundary**.

### Permission rules

`settings.json` is read from three layers, later layers winning:

| Layer | Path | Represents |
|---|---|---|
| User | `~/.myriaxon/settings.json` (or `MYRIAXON_USER_CONFIG_DIR`) | the machine owner's policy |
| Project | `<project>/.myriaxon/settings.json` | the repository's policy — safe to commit |
| System | `%ProgramData%\Myriaxon\settings.json` | an admin / AI-governance override, final authority |

Within a layer the most specific rule wins — `"tool:pattern"`, then `"tool"`, then `"*"`:

```json
{
  "permissions": {
    "*": "ask",
    "read_file": "allow",
    "run_bash": "ask",
    "run_bash:git *": "allow",
    "run_bash:rm -rf *": "deny"
  },
  "enforced_mode": "manual",
  "allowed_write_paths": ["D:\\shared"]
}
```

Patterns match the tool's primary argument (`command` for bash, `path` for file tools), so "allow
git, ask for rm" is expressible. A pattern with no wildcard also matches a leading-word form —
`"git"` matches `git status` but **not** `gitleaks`. A `deny` rule survives auto-approval and
`--yolo`; rule keys are validated before they are stored, so a rule that can never match is reported
instead of silently doing nothing. `/policy` prints the merged result, and the dashboard has a rule
editor.

Other keys: `enforced_provider`, `enforced_mode`, `sandbox` (make container isolation mandatory),
`theme`, `vim_mode` and `profiles` (named mode+yolo bundles).

### Hooks

```json
{
  "PreToolUse": [
    { "matcher": "run_bash|write_file", "command": "python C:/hooks/gate.py" }
  ],
  "PostToolUse":  [ { "command": "python C:/hooks/audit.py" } ],
  "UserPromptSubmit": [ { "command": "python C:/hooks/context.py" } ]
}
```

User hooks live in `~/.myriaxon/hooks.json`, project hooks in `<project>/.myriaxon/hooks.json`, and
the two are merged by appending per event. `matcher` is a regular expression over the tool name. The
hook receives a JSON object on stdin and `MYRIAXON_TOOL_NAME` in its environment.

| Event | Behaviour |
|---|---|
| `PreToolUse` | a **non-zero exit blocks the call**, and its output is returned to the model. It runs before the interactive confirmation, so a hook can pre-empt even a prompt. |
| `PostToolUse` | observational; failures are logged, never raised into the turn |
| `UserPromptSubmit` | stdout is appended to the prompt as extra context |

Hooks time out after 30 seconds and **fail open**: a hung hook must never stall every tool call
forever.

### Isolation

`--sandbox` runs `run_bash` inside a network-isolated Docker container (PowerShell image,
`--network none`), and falls back to a disposable Windows Sandbox VM where Docker is unavailable.
Honest status: the Docker path is gated on `docker` being present and **has not been verified
end-to-end** in the environment it was written in; the Windows Sandbox path needs the optional
Windows feature enabled.

---

## Extending Myriaxon

### Skills

Drop `SKILL.md` (with `name:` / `description:` frontmatter) into `~/.myriaxon/skills/<name>/` or
`<project>/.myriaxon/skills/<name>/`; a project skill overrides a same-named user skill. Discovered
skills are listed in the system prompt, and the model loads one's full body with `use_skill`.
Myriaxon also ships built-in skills (for example `graphify`).

### Plugins

A plugin is a `.py` file or package directory in `~/.myriaxon/plugins/` or
`<project>/.myriaxon/plugins/`:

```python
PLUGIN = {"name": "acme", "version": "1.0", "description": "Demo plugin"}

def register(api):
    api.add_tool("acme_echo", "Echo the text back.", schema, handler, mutating=False)
    api.on("pre_tool_use", gate)      # return a string to block the call
```

`mutating=True` routes a plugin tool through the same confirmation and policy gate as `write_file`,
so a plugin cannot silently bypass a `deny` rule. A plugin **cannot** shadow a built-in tool — the
names are reserved before any plugin registers — a plugin that raises on import is recorded and
skipped rather than stopping the agent, and unknown hook events are refused at registration. Events:
`pre_tool_use`, `post_tool_use`, `user_prompt`, `agent_start`, `agent_stop`. Full reference:
[docs/PLUGINS.md](docs/PLUGINS.md).

### MCP servers

Myriaxon speaks every MCP transport — stdio, streamable HTTP, and the older HTTP+SSE — and a remote
server is tried over streamable HTTP first, then SSE, because implementations differ. Servers are
configured in `~/.myriaxon/mcp_servers.json`, added from `/mcp` in the terminal or the MCP panel in
the dashboard, or installed in one click from the 18-server catalog.

```json
{
  "stdio_servers": [
    { "name": "filesystem", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  ],
  "url_servers": [
    { "name": "figma", "url": "https://mcp.figma.com/mcp", "token": "figd_…" },
    { "name": "internal", "url": "https://mcp.example.com/mcp", "headers": { "X-Api-Key": "…" } }
  ]
}
```

A remote server's tools arrive namespaced as `mcp__<server>__<tool>`, so a server can never shadow a
built-in — the test fixtures deliberately expose a `read_file` tool to prove it. Re-saving a server
without retyping its token keeps the stored token. Requires `pip install -e ".[mcp]"`; without it, a
configured server contributes nothing and the panel says so. Full reference:
[docs/MCP-SETUP.md](docs/MCP-SETUP.md).

### Project instructions

`MYRIAXON.md` at the repository root (or `~/.myriaxon/MYRIAXON.md` for all projects) is injected into
the system prompt. `AGENTS.md` is read as well when present, and a pre-rebrand `IOH.md` still works as
a fallback. A line containing only `@relative/path` imports that file inline, up to five levels deep.

Search and content tools honour `.myriaxonignore` (gitignore-style patterns) in addition to
`.gitignore` and a built-in list (`.git`, `__pycache__`, `.venv`, `node_modules`, …). A pre-rebrand
`.iohignore` is still honoured.

---

## Memory, checkpoints and rewind

**Memory** is a SQLite FTS5 database at `~/.myriaxon/memory.db` holding the latest transcript of each
project ever used — one row per project, not one per turn, so it stays bounded. It is written
best-effort after a turn (a memory failure never blocks saving the session) and searched with the
`search_memory` tool or `/memory search <query>`, across every project on the machine.

**Checkpoints** are taken automatically before `write_file` / `edit_file` / `edit_notebook` overwrite
a file, and indexed under `<project>/.myriaxon/checkpoints/`. `/undo` restores the most recent one;
`checkpoint_list` and `checkpoint_restore` expose the same thing to the model, and a restore takes a
checkpoint of its own first so it can be undone.

**`/rewind`** works one level up: a whole-project shadow git repository kept outside the project (at
`~/.myriaxon/history/<hash of the project root>`), so it never collides with the project's own `.git`
and works in a directory that is not a repository at all. It requires `git` on PATH; when git is
missing or `init` fails, `/rewind` is simply unavailable and nothing else degrades.

---

## Context adaptation

Handing a 16k-window weak model the same prompt, the same tool results and the same delegation powers
as a frontier model is how a harness makes a weak model look worse than it is. `--profile
small|balanced|large` is auto-detected from the model id and the provider's real context window, and
each profile is a contract recorded in every benchmark manifest:

| | `small` | `balanced` (default) | `large` |
|---|---|---|---|
| Context window (nominal) | 16,000 | 64,000 | 200,000 |
| Reply ceiling | 2,048 | 8,192 | 32,000 |
| System-prompt budget | 2,400 chars | 6,000 chars | 12,000 chars |
| Tool results | ≤1,200 chars (hard cap 6,000) | ≤8,000 (40,000) | ≤24,000 (120,000) |
| Warn / prune / compact / refuse | 50 / 65 / 80 / 95% | 60 / 75 / 85 / 95% | 70 / 82 / 90 / 97% |
| Tools withheld | 5 | 1 | none |
| Argument coaching after a malformed call | on | off | off |
| Delegation | off | off | only with `--agent-mode multi` |

A resolved context window always beats the nominal one: the real number is what protects the user.
Tool *schemas* are charged on every request, and measurement against the real seed prompt found them
to be the single largest fixed cost — 2,163 of the 4,341 tokens a small-profile session spends before
its first word — which is why tool withholding exists alongside prompt trimming.

Before **every** request the harness measures the window — system prompt, tool schemas and reply
reserve included — and acts in graduated order: **warn**, **prune** stale tool results, **compact**
older turns, then **refuse with an explanation**. Pruning comes before compaction because it is free
and the model can re-read a file; compaction costs a model call and destroys detail.

Automatic compaction is provider-specific: Anthropic uses its native server-side compaction (on by
default, `--no-compact` disables it) and prints a dim notice when it fires; OpenAI-compatible and
Gemini sessions auto-compact locally past 92% of the window. Manual `/compact` works on every
provider and keeps the last few turns verbatim instead of flattening the whole conversation.

Measure any of it without spending tokens:

```powershell
python scripts/check_profile.py --compare      # fixed cost per profile
python scripts/check_budget.py gemma-2-2b      # where each action fires
python scripts/live_adapt_check.py             # real sessions, real token counts
```

---

## IQB-14 — the evaluation standard

Myriaxon ships its own agentic benchmark: **14 parameters** and a composite **AXS** score (0–100),
implemented in `myriaxon/bench/` with 14 seed tasks in `myriaxon/bench/tasks/`. It measures the
*shipped* agent loop — the same system prompt, tools and permission modes a human gets — not a
harness-only reimplementation.

What makes it a standard rather than a script:

* every task declares step, wall-clock and dollar budgets, **enforced inside the agent loop**;
* every tool call, argument, result, duration and token delta is written to a JSONL trace;
* `pass@k` **and** `pass^k` are always reported, with a Wilson 95% interval on every rate;
* `harness_error` and `env_error` instances are excluded from capability scoring and reported as
  harness reliability instead of being counted as model failures;
* a parameter is scored only from its own primary evidence — an unrun probe is reported as
  `incidental only` or `unmeasured`, never as a pass;
* `report` and `compare` are pure functions of the stored artifacts, so a disputed score is settled
  without spending another token.

```powershell
python -m myriaxon.bench lint                                    # validate task files (free)
python -m myriaxon.bench run --provider deepseek --model deepseek-v4-flash --dry-run
python -m myriaxon.bench run --out bench-out/run-1 --label "model-name" `
  --provider openrouter --model openai/gpt-oss-120b `
  --base-url https://openrouter.ai/api/v1 --api-key-env OPENROUTER_API_KEY
python -m myriaxon.bench report  --out bench-out/run-1 --print    # re-score from artifacts (free)
python -m myriaxon.bench compare bench-out/baseline bench-out/run-1
python -m myriaxon.bench export  --out bench-out/promptfoo.iqb.json   # adversarial subset
```

The full specification — parameter definitions, scoring formulas, the task-file schema, artifact
layout and the known limitations — is in [docs/IQB-14.md](docs/IQB-14.md). An LLM judge is available
(`--judge-model`, `--judge-mode {agent,api}`) but is quarantined: the seed suite does not use it, and
the share of judge-derived scoring is always reported.

---

## Project layout

```
myriaxon/
  cli.py                 terminal entry point, REPL, slash commands, banner
  argparse_cli.py        flags, kept free of provider SDKs so --help stays fast
  agent.py               Anthropic agent (Messages API, streaming, tool loop)
  openai_agent.py        OpenAI-compatible agent (OpenRouter, DeepSeek, Netra, custom)
  gemini_agent.py        Gemini / Vertex agent (both Google protocols)
  direct_http_client.py  SDK-free OpenAI-shaped client (measured 44-75s to import the SDK)
  config.py              provider / endpoint / model / key resolution and the setup wizard
  model_profiles.py      small / balanced / large contracts and detection
  model_adapt.py         per-model quirks; context_budget.py accounting; compaction.py
  tools.py               built-in tool implementations
  tool_registry.py       tool definitions, dispatch, schema index, sub-agents
  tool_context.py        the ToolContext passed to every tool
  settings.py            layered settings and argument-aware permission resolution
  policy.py              permission-rule key validation
  hooks.py               shell hooks     plugins.py   in-process plugin API
  skills.py              SKILL.md        subagents.py sub-agent types
  commands.py            custom slash commands
  checkpoints.py         file snapshots + shadow git       memory_store.py  FTS5 memory
  scheduler.py           delayed prompts  notebook.py  Jupyter cells  ask_user.py  questions
  mcp_client.py          stdio + streamable HTTP + SSE     mcp_catalog.py  18-server catalog
  messaging.py           WhatsApp (Twilio / Meta / generic webhook)
  git_view.py            structured git status and diffs for the UI
  audit.py               JSONL governance audit trail
  brand/                 the palette, type, mark and display copy (see docs/BRAND.md)
                         assets/ holds the SVGs shipped in the wheel
  banner.py theme.py completion.py system_prompt.py project_instructions.py …
  bench/                 IQB-14: parameters, scoring, runner, assertions, judge, guard, report
    tasks/               the 14 IQB-14 seed tasks, shipped inside the package
  dashboard/             zero-dependency web UI
    server.py            HTTP routes, SSE, the app object
    ui.py                the entire single-page UI, served from memory
    session.py           agent sessions   commands.py  dashboard slash commands
    settings.py policy.py endpoints.py console.py events.py paths.py
brand/                   generated distributable assets: 3 SVGs + PALETTE.md
tests/                   pytest suites (see below)
scripts/                 check scripts and benchmarks (see docs/HANDOVER.md)
tools/                   asset and migration utilities (export_brand_assets.py, rebrand.py)
```

---

## Testing

**470** offline suites — **470 tests************************, no network and no API key:

```powershell
pip install -e ".[dev]"
python -m pytest tests/ -q
```

* `tests/test_e2e_turn.py` — **a real agent turn** against a scripted local provider: streamed
  response, tool call, tool result fed back, final answer, persisted transcript, and the
  dashboard's separate agent builder. 31 checks. This is the one that matters most: every
  release-blocking defect in this codebase lived on that path and was invisible to unit tests.
* `tests/test_dots.py` — persistent agents: identity across restarts, objective lifecycle,
  proactive gating, cross-process registry safety, corrupt-state recovery
* `tests/test_brand_consistency.py` — the dashboard palette cannot drift from the brand tokens,
  and no CSS rule may reference a variable the page does not define
* `tests/test_model_adapt.py` — profiles, prompt tiers, pruning, budget thresholds
* `tests/test_bench_harness.py` — the IQB-14 harness: task loading, assertions, scoring, reporting

Standalone verification scripts live in `tools/`:

```powershell
python tools\e2e_check.py        # the turn path, with a readable per-check report
python tools\dots_check.py       # 60 checks over the persistent-agent layer
python tools\dashboard_smoke.py  # a real server, driven over real HTTP
```

`pyproject.toml` sets `testpaths = ["tests"]` and a `live` marker, so the default run stays offline;
anything needing network access or real credentials must be marked.

End-to-end checks live in `scripts/` as `check_*.py` (36 of them). 24 are wired into one runner:

```powershell
python scripts\run_dashboard_checks.py
```

That runner starts a real dashboard server and exercises UI markup, end-to-end turns, sessions,
settings, custom endpoints, MCP management, messaging, permission rules, the file explorer and diff
review, and the inline JavaScript. Two suites **skip** rather than fail in a confined sandbox — the
stdio MCP check needs piped child processes, and the browser check needs to launch Chrome. Both were
verified green with wider access. Individual checks run standalone:

```powershell
python scripts\check_files_ui.py
python scripts\check_permission_rules.py
python scripts\check_ui_visual.py     # real Chrome via CDP; skip when no browser is available
```

---

## Design principles

1. **Direct HTTP over SDKs where the SDK is slow.** `import openai` measured 44–75 s on a cold
   machine; `import httpx` is 1–4 s. The direct client exists for that reason, behind the
   `MYRIAXON_OPENAI_SDK` escape hatch.
2. **Zero third-party dependencies in the dashboard.** `ThreadingHTTPServer`, SSE, and one inline
   HTML string. No framework, no build step, no CDN, no external request.
3. **Single agent by default.** Multi-agent capability exists and is deliberately off; a weak model
   with less context in a sub-agent is not an improvement.
4. **Fail closed on anything security-shaped.** An empty messaging allowlist refuses everybody. A
   `deny` rule survives auto-approval. A plugin cannot shadow a built-in tool.
5. **Facts are verified by running something.** Comments in this codebase record measured numbers,
   including the ones that contradicted an earlier assumption.
6. **Unmeasured is not zero and not a pass.** A cost with no data is `null`; a probe that never ran is
   excluded from the score rather than counted as a success.
7. **State what was truncated, dropped or skipped.** Tool-result truncation is written into the
   result; a dashboard command that needs a terminal says so instead of pretending.
8. **No new dependencies without a reason that survives review.** Python's standard library carries
   most of this product.

---

## Documentation

| Document | Contents |
|---|---|
| [docs/HOW-TO-USE.md](docs/HOW-TO-USE.md) | **start here**: install, first run, dashboard, transparency dial, loci, troubleshooting |
| [docs/API-KEYS.md](docs/API-KEYS.md) | **DeepSeek, Netra, Vertex, Ollama keys**, precedence, and where a key is never written |
| [docs/FALSE-POSITIVE.md](docs/FALSE-POSITIVE.md) | **if an antivirus flags `myriaxon.exe`** — what the file is, how to verify it, and what cannot be fixed here |
| [docs/DOCKER.md](docs/DOCKER.md) | **running it in a container**: the two images, one-command install, nested Locus sandbox, known limits |
| [docs/BRAND.md](docs/BRAND.md) | the identity: mark geometry, palette, type, terminal glyphs, CLI themes |
| [docs/IQB-14.md](docs/IQB-14.md) | the evaluation standard, normative |
| [docs/MCP-SETUP.md](docs/MCP-SETUP.md) | connecting stdio and remote MCP servers |
| [docs/PLUGINS.md](docs/PLUGINS.md) | writing a plugin |
| [docs/MESSAGING.md](docs/MESSAGING.md) | WhatsApp / messaging integration |
| [docs/VERTEX-SETUP.md](docs/VERTEX-SETUP.md) | Gemini through a corporate Google account (WIF) |
| [docs/SECURITY-AUDIT.md](docs/SECURITY-AUDIT.md) | **the security audit**: what was found, how it was proved, and what is still open |
| [docs/Level4-5-STATUS.md](docs/Level4-5-STATUS.md) | every autonomy requirement with the commit that satisfies it |
| [docs/PlanToL5.md](docs/PlanToL5.md) | the gap inventory behind that status |
| [docs/GEMINI-MULTITOOL-STATUS.md](docs/GEMINI-MULTITOOL-STATUS.md) | a known Gemini 3.x limitation, with the measurements |
| [docs/GAP-ANALYSIS.md](docs/GAP-ANALYSIS.md) | capability parity vs other harnesses, and the prioritised gap list |
| [docs/HANDOVER.md](docs/HANDOVER.md) | full state of the project, test inventory and master roadmap |

The audit and status documents are in the repository deliberately. A capability claim with no evidence is a
wish, and a security claim with no reproduction is worse than none — so both are versioned next to the code
they describe rather than living in somebody's notes.

---

## Honest limits

* **Usage figures are per-process.** Mission control reports tokens, requests and turns for the
  running server, and a restart honestly reports zero. There is no persisted spending ledger in
  this codebase, so nothing is estimated or extrapolated — `started_at` says since when.
* **Approvals has two real sources**, not a general pending-ask register: objectives a locus marked
  blocked, and sessions that ended in an error. When neither exists the queue is empty and says so,
  rather than showing a plausible placeholder.
* **A locus running in another process is not a run row.** Mission control shows such a locus in
  Schedules and in the live trace (its activity carries its name), but not as a session with a
  turn counter — inventing "0 turns, 0s" for live work would be the exact kind of plausible lie
  the view is built to avoid.
* **Mid-stream cancel stops the turn, not the provider's billing instantly.** The Stop button requests
  cancellation through `cancellation.CancelToken`, and each agent's stream loop checks it between
  chunks, so tokens already generated are not consumed further and the provider response is closed.
* **A locus runs only while a Myriaxon process is open.** It resumes by itself and needs no prompting,
  but it is not a detached daemon — a background process that keeps editing files and spending
  tokens after you close the window would be a surprise, not a feature. `LocusRegistry.next_due()` is
  the hook for a supervisor if you want it genuinely continuous. A killed process's run lease
  blocks its locus for up to 30 minutes; `renew_run_lease()` is the heartbeat.
* **A turn does not self-prompt across turns.** The agent loops on tool calls within a turn and stops.
  A proactive locus is the supported way to get work that continues by itself.
* **Vendor switching carries conversational text only**, not the tool-call exchange (see the dashboard
  notes above).
* **`--sandbox` is unverified end-to-end** and the PyInstaller single-file build
  (`scripts/build_binary.py`) has not been run in this environment.
* **IQB-14's corpus is 14 seed tasks**, one per parameter. Scores over it are directionally useful and
  statistically thin, which is why confidence intervals and a coverage figure are always reported.
* **Only Netra has been used for live provider testing in this repository**, by project rule; the
  other providers' paths are wired and unit-tested but less exercised end to end.
* **The visual layout is verified by measurement, not by eye.** Chrome cannot be driven in this
  environment, so computed styles were not checked in a browser; the markup, the palette tokens and
  every CSS variable reference are asserted instead (see `tests/test_brand_consistency.py`).
* **Search is thin without an API key.** `web_search` works out of the box on key-free backends and
  says so in its own result: they cover reference material well and current events poorly. Measured
  on the machine this was built: DuckDuckGo is unreachable (the TLS certificate presented for it does
  not match the hostname, so the connection is being intercepted) and Mojeek answers with a captcha,
  which leaves Wikipedia and one scraper. Set `BRAVE_API_KEY`, `TAVILY_API_KEY` or `SERPER_API_KEY` —
  or run `myriaxon search --set brave:YOUR_KEY` — for a real index, and `myriaxon search --test` to
  see what actually comes back.
* **The bot is reachable only while a server runs**, and the webhook holds the connection open for
  the whole turn (up to ten minutes). A provider that times out sooner will retry, and the retry
  starts a second turn; a queue with an immediate acknowledgement is the fix and is not implemented.
* **Provider-specific gaps:** the *hosted* `web_search` / `web_fetch` tools are Anthropic-only —
  every other provider gets local implementations of the same two tools instead — and `--effort` /
  `--thinking` do nothing on the Gemini provider.

Myriaxon deliberately implements its own agent loop against the raw provider APIs rather than using
the Claude Agent SDK, because that SDK shells out to the closed-source `claude` binary — which would
have made "no Node.js, no sign-in" impossible to deliver honestly. The three provider agents are
independent implementations sharing one tool-execution and safety-confirmation core; only the wire
format differs.

---

Written by **Thariq Arian Khalfani**.
