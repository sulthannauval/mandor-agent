# mandor-agent

[![CI](https://github.com/sulthannauval/mandor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sulthannauval/mandor-agent/actions/workflows/ci.yml)

A planner and executor workflow for coding agents. One Claude Code session plans and reviews. An executor, running in opencode or in Claude Code, ships the plans one pull request at a time through four subagents: scout, coder, fixer and reviewer.

*Mandor* is Indonesian for the foreman who splits the work among the crew and checks it before it is handed over.

## How it works

```
 PLANNER (Claude Code)                  EXECUTOR (opencode or Claude Code)
 writes plans + one prompt  ───────▶    per plan:
                                          scout     reads the source, checks the plan's premises
                                          coder     test first, then the change, then a mutation check
                                          fixer     formatting, lint, changelog, merge conflicts
                                          reviewer  approves or rejects before the PR is opened
                                        PR ─▶ CI green ─▶ merge ─▶ main green ─▶ next plan
 reviews every merged PR    ◀───────    final report (you relay it)
```

| Role | Does | Never does |
|---|---|---|
| planner | writes plans and the execution prompt, reviews every merged PR, handles blockers | codes during a batch |
| executor | orders the work, delegates, commits, opens and merges PRs, writes the report | edits code itself |
| scout | reads source, CI logs and call sites, reports with `file:line` | edits, builds, tests |
| coder | implements a plan step test-first, proves the test with a mutation | commits, pushes, opens PRs |
| fixer | makes mechanical fixes that keep behavior the same | changes behavior |
| reviewer | checks the diff against the plan and a checklist | edits or fixes |

The protocols are two files. [`core/WORKFLOW.md`](core/WORKFLOW.md) is the executor's: the loop, the hard rules, commit messages, blockers and the report. [`core/PLANNER.md`](core/PLANNER.md) is the planner's: writing a batch, tiered review, blockers and the two runtimes.

### Two executor runtimes

| | opencode (default) | Claude Code (occasional) |
|---|---|---|
| Start | `opencode-executor` | `claude-executor` |
| Models | combos in your router, one per role | Anthropic models on your Claude subscription: reviewer Opus, executor and coder Sonnet, fixer and scout Haiku |
| Rules enforced by | per-agent permissions in the agent files and `opencode.jsonc` | a guard hook that knows which agent is calling ([`claude/guard.py`](claude/guard.py)) |
| Reviewer independence | a different model family from the coder | a different tier and a fresh context |

You can switch runtimes between batches or in the middle of one. Plans and prompts never depend on the runtime.

### Skills

The planner and the agents use one plugin and three skills, and `install.sh` installs all of them.

| Skill | From | Used by |
|---|---|---|
| `tdd` | plugin `mattpocock-skills` | coder |
| `diagnosing-bugs` | plugin `mattpocock-skills` | coder |
| `codebase-design` | plugin `mattpocock-skills` | coder, reviewer |
| `code-review` | plugin `mattpocock-skills` | reviewer |
| `resolving-merge-conflicts` | plugin `mattpocock-skills` | fixer |
| `grilling`, `research`, `writing-for-agents` | plugin `mattpocock-skills` | planner |
| `/grill-with-docs`, `/handoff` | plugin `mattpocock-skills` | you, when the planner suggests them |
| `karpathy-guidelines` | `szkocot/andrej-karpathy-skills` | coder |
| `security-review` | `getsentry/skills` | executor, reviewer |
| `unslop` | `cursor/plugins` | executor, fixer |

The scout uses none. It only reads and reports, and a loaded skill adds tokens to every turn it takes.

## Requirements

- Linux. The scripts use GNU `find` and `realpath` options that stock macOS lacks.
- `git`, `python3`, and the GitHub CLI `gh`, logged in to the account that opens the PRs.
- [Claude Code](https://claude.com/claude-code) for the planner and the Claude Code executor.
- [opencode](https://opencode.ai) for the opencode executor, plus a router that serves both an OpenAI-style and an Anthropic-style (`/v1/messages`) endpoint. [9router](https://github.com/decolua/9router) is the one this was built on.
- `npx` to install the third-party skills.

## Install on a device

```bash
git clone https://github.com/sulthannauval/mandor-agent ~/project/mandor-agent
cd ~/project/mandor-agent
./install.sh
$EDITOR ~/.config/mandor/router-url ~/.config/mandor/router-key   # only if you use opencode
```

`install.sh` is safe to run again. It:

- links the protocols, the Claude Code and opencode agents, the guard and the launchers from this clone into `~/.config/mandor/`, `~/.claude/agents/`, `~/.config/opencode/agents/` and `~/.local/bin/`,
- renders `~/.config/opencode/opencode.jsonc` from [`opencode/opencode.jsonc.template`](opencode/opencode.jsonc.template), leaving a config it did not write alone unless you pass `--force`,
- creates `~/.config/mandor/router-url` and `router-key` once, with mode 600, for the router's base URL and API key; `opencode.jsonc` reads them with `{file:...}`, so every opencode session finds them,
- installs the Claude Code plugin `mattpocock-skills` and links its engineering skills for opencode,
- installs the skills in [`skills.txt`](skills.txt) with `npx skills add`,
- if an RTK hook is set up in Claude Code, makes it honour `RTK_HOOK_OFF`, so executor sessions read diffs and test output whole.

Options: `--force` replaces files that are not mandor links, `--no-skills` skips the plugin and skill installs, `--uninstall` removes every link that points into the clone.

Log in on each device: `claude` (your Claude subscription), `gh auth login`, and opencode if you use it.

## Set up the router combos (opencode runtime)

Create five combos in your router with exactly these names, using the **Fallback** strategy: `executor-agent`, `coder-agent`, `scout-agent`, `fixer-agent`, `reviewer-agent`. The names are fixed by role, so you can change the models behind them any time without touching opencode.

How to choose the models:

- **executor-agent**: your strongest model. It makes every decision in the batch.
- **coder-agent**: a capable coding model on your largest quota. It sends about half of all requests.
- **reviewer-agent**: a model from a **different family** than the coder, so it does not share the coder's blind spots.
- **scout-agent**: a cheap model with a long context. It reads a lot and judges little.
- **fixer-agent**: a fast model. Its tasks are short.

Give each combo a second and third model from other providers, so an exhausted quota falls back instead of stopping the batch.

Router settings that matter:

- Use **Fallback**, not Round Robin (it switches models mid-task and throws away the prompt cache) or Fusion (it pays for every model on every step).
- Turn **off** any tool-output compression, such as 9router's "Compress tool output (RTK)". It replaces diff bodies with a placeholder, so the reviewer would approve a diff it never saw.
- The template points opencode at the router's Anthropic-style endpoint (provider `9router-agent`, package `@ai-sdk/anthropic`). Through the OpenAI-style endpoint, some models (MiniMax M3, for one) write their reasoning into the answer text, which is then resent on every turn.

## Set up a project

```bash
cd /path/to/your/project
mandor-init
```

`mandor-init` creates `plans/` and `.mandor/`, keeps both and `CLAUDE.local.md` out of git through `.git/info/exclude`, and adds the planner import plus a project-layer skeleton to `CLAUDE.local.md`. Then fill in two files:

- **`CLAUDE.local.md`**: the project's build, test and lint commands, the local gate that matches CI, machine limits, high-risk paths, and changelog rules. Both runtimes read it.
- **`.mandor/env.sh`**: what isolates the executor from your live install. List paths no agent may touch in `MANDOR_PROTECTED_PATHS`, and point your app's config and data directories at throwaway ones. Both launchers source it.

## Daily use

1. **Plan.** Open Claude Code in the project. That session is the planner. Ask it for the plans and one execution prompt. Plans are files in `plans/`.
2. **Execute.** From the project, start `opencode-executor` (or `claude-executor`) and paste the prompt. The executor works plan by plan and merges each PR once CI is green.
3. **Relay.** Paste the executor's final report into the planner session. It reviews every merged PR and writes the next batch.
4. **Switch runtimes** whenever you like. Stop the session, start the other launcher, and paste the same prompt with the line `Continue this batch from the checkpoint.` The executor picks up from the status table in the handoff plan.

Check usage per runtime: `/usage` in Claude Code, and your router's usage page for opencode.

## Keep devices in sync

Apart from `opencode.jsonc` and the two router files, everything the installer places is a symlink into the clone, so editing those files on any device edits the repository. Commit and push the change; on the other devices run `git pull`, and `./install.sh` again if files were added or the opencode template changed.

What never goes into git: `~/.config/mandor/router-url` and `router-key`, each project's `.mandor/env.sh`, `plans/` and `CLAUDE.local.md`.

## Troubleshooting

- **An opencode session hangs right after start.** It happens now and then. Close it and start again once before suspecting a config change.
- **`model_not_found` for a combo.** A combo was renamed in the router. Its name must stay `executor-agent`, `coder-agent` and so on.
- **The work quality drops mid-batch.** A provider's quota ran out and the combo fell back to its next model. Check the router's usage page.
- **Cache hits look like zero for some providers in opencode.** Some routers do not pass cache usage through to opencode. Read the router's own usage log instead.
- **Diffs or test output look cut short.** A compression layer is on: the router's tool-output compression, or an RTK hook in a session not started by a launcher.
- **The executor runs at medium effort in Claude Code.** Start it with `claude-executor`, which passes `--effort high`, or type `/effort high` in the session.
- **A stopped executor starts working again.** Esc only interrupts the current turn, and a background command such as a wait on CI wakes the session when it ends. Stop an executor with `/exit`.

## Repository layout

| Path | Holds |
|---|---|
| `core/` | the two protocols, `WORKFLOW.md` for the executor and `PLANNER.md` for the planner |
| `claude/` | the Claude Code agents, the guard hook and the executor session settings |
| `opencode/` | the opencode agents and the `opencode.jsonc` template |
| `bin/` | the launchers `claude-executor` and `opencode-executor`, and `mandor-init` |
| `templates/project/` | the files `mandor-init` adds to a project |
| `tests/` | the guard and config tests |

## Development

Run the checks CI runs before you push:

```bash
shellcheck --severity=style install.sh bin/* templates/project/env.sh
python3 tests/test_guard.py
python3 tests/test_config.py    # needs PyYAML
```

The protocols and agent files are prompts. Keep the Claude Code and opencode versions of an agent in step, and keep `: ` out of a frontmatter `description`, which is a plain YAML scalar.

## License

[MIT](LICENSE)
