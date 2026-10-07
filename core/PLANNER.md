# Planner protocol

This file is for the planner: a Claude Code session that writes plans, hands them to an executor, and reviews the result. The executor's side is in `WORKFLOW.md` next to this file. The executor runs in opencode by default, or in Claude Code when the owner chooses, and the owner switches between them at will (see "Executor runtimes"). Project-specific commands and risk tiers live in each project's own `CLAUDE.md`, `CLAUDE.local.md`, or `AGENTS.md`.

## The loop

1. The planner writes the plans and one execution prompt for a batch.
2. The owner pastes the prompt into a new executor session in whichever runtime is current: `opencode-executor` (the default) or `claude-executor`, run from the repository.
3. The executor works one plan at a time: read plan, code, PR, PR green, merge, `main` green, next plan. It merges by itself.
4. The owner relays the executor's final report to the planner.
5. The planner reviews every merged PR (see "Reviewing a batch"), then writes the next batch.

Merging and coding belong to the executor. The planner's one exception is a blocker left over after a batch (see "Blockers").

## Executor runtimes

The executor runs in **opencode by default**. **Claude Code is the occasional alternative**, used when the owner decides to, for example while the Claude subscription has quota to spare. **The owner may switch between them at any time and as often as they like: between batches, or in the middle of one.** Nothing the planner writes depends on the runtime. Both run the same `WORKFLOW.md`, the same four subagent roles, and the same report, so a plan and an execution prompt must work unchanged in either.

To switch in the middle of a batch, the owner stops the running session (or it has died), starts the other runtime, and pastes the same prompt with the line "Continue this batch from the checkpoint." The executor then resumes from the handoff plan's status table and the state of git and GitHub (`WORKFLOW.md`, "Continuing a batch").

| | opencode (default) | Claude Code (occasional) |
|---|---|---|
| Start | `opencode-executor` | `claude-executor` |
| Models | 9router combos per role (`~/.config/opencode/opencode.jsonc`) | Anthropic via the owner's subscription: reviewer Opus, executor and coder Sonnet, fixer and scout Haiku |
| Rules enforced by | per-agent permissions in the agent files and `opencode.jsonc` | a guard hook keyed on the agent (`~/.config/mandor/claude/guard.py`) |
| Project isolation | the launcher sources the project's `.mandor/env.sh` (throwaway config dirs, protected paths); RTK is not hooked in | the launcher sources the project's `.mandor/env.sh`; RTK rewriting is off |
| Reviewer independence | a different model family from the coder | same model family as the coder; relies on a different tier and a fresh context |
| Measuring usage | 9router's `usageHistory` table | the session transcripts under `~/.claude/projects/`, or `/usage` |

When reviewing a batch, check which runtime ran it (report item 1). Compare runtimes on the same measures: reviewer rejections, time per plan, and quota used per plan.

## Skills

The planner uses these from the `mattpocock-skills` plugin, in the order a batch meets them:

- `grilling`: when the owner's request is large or still fuzzy, interview the owner in rounds before writing any plan. When the work also needs a glossary or ADRs, suggest the owner run `/grill-with-docs` instead.
- `research`: when a plan rests on how an external system behaves, such as a router, a library, or a third-party API. Save its notes in `plans/`, where they stay untracked.
- `writing-for-agents`: before writing plans or an execution prompt, and before editing `WORKFLOW.md`, this file, or an agent file. Agents read every one of them.
- `/handoff`: after reviewing a batch in a long session, suggest the owner run it. Every turn re-sends the whole context, so the next batch is cheaper to plan in a fresh session that starts from the handoff document.

## Subagent models

A subagent the planner spawns inherits the planner's model unless the call names one. Name a model on every call:

- `sonnet` for searching, reading, auditing and any other work the planner hands off.
- `haiku` for `Explore` and for lookups that only locate code.
- The planner's own model only when the subagent must judge a design or review a change.

## Writing a batch

- Plans are files in the project's local, untracked `plans/` directory, and they stay untracked.
- Before writing a batch, run `git status` in the main checkout. Modified tracked files must be explained or stashed before the executor starts.
- Put plans in the order they must run. Mark a plan "needs X" when it depends on plan X. Two plans that touch the same file (other than the changelog) depend on each other. A plan that needs X goes after X in the same batch; the executor starts it only once X is merged and `main` is green.

### The execution prompt

The prompt carries only what is specific to this batch, in the shape below. Rules already in `WORKFLOW.md` or the project's rules file stay there.

```text
Batch <name>: <the goal in one sentence>. Run from the <repository> repository.

Handoff plan: <path> (section "<heading>")
Plans written against main at <SHA>

Order:
1. <plan path>
2. <plan path> (needs <plan number>)

Notes per plan:
- <plan number>: <what the plan file does not say>

Batch constraints:
- <a schema, version or file that must stay as it is, such as the files of a batch running in parallel>

STOP, for the whole batch:
- Before starting, git status shows modified tracked files.
- <a condition specific to this batch>
```

- Fill the text in the owner's language. Keep the labels and the words `needs` and `STOP` as written, because `WORKFLOW.md` uses them.
- The SHA is the `origin/main` commit you last checked every plan's premises against. The scout measures drift from it.
- Under a heading with nothing to say, write "none", so the executor knows the heading was considered.
- A STOP in this list ends the whole batch. A condition that ends one plan goes in that plan's file or in its note.

## Reviewing a batch

Every merged PR gets a light check. PRs that meet a trigger also get a full review.

**Light check, every PR:**

- CI on the PR and on `main` after its merge finished green, per the report. Read the errors if a run failed.
- Each claim in the report for this PR is spot-checked at the source: the files it says changed, the premises it says held.

**Full review, only when a trigger applies.** Triggers:

- The PR touches a path the project's rules file marks as high risk. If the project defines no risk tiers, treat security, authentication and access control, network exposure, secret handling, data migrations, and CI or deployment configuration as high risk.
- The report shows a problem for this PR: a premise that turned out wrong, a reviewer rejection, a fix round, or something the reviewer flagged that the executor chose not to change.
- A fix has no mutation evidence: no record of the line broken and the test failing.

A full review reads the merged change at the source (`git show <merge SHA>`) and checks:

1. Every plan step is done and the scope matches the plan.
2. Each test would fail if the fix were removed. Rerun the mutation when in doubt.
3. Nothing was missed: other callers, docs that describe the changed behavior, the changelog, a config or schema version.
4. The PR agrees in meaning with the other PRs in the same batch. Read `git diff <batch base>..<batch head>` for this.

**Outcomes:**

- Passes: record it.
- A defect: write a fix plan for the next batch.
- `main` is broken: revert the PR, then plan the fix.

## Blockers

The executor stops a plan after two failed fix rounds and writes a blocker prompt. The planner hands that prompt to the `coder` subagent (Sonnet) or another cheaper-model subagent in a separate worktree, so the planner's context and quota stay free, reviews the result, and merges it once CI is green. If resolving the blocker would change what the plan promised, stop and ask the owner instead. Commits made while resolving a blocker follow the "Commit and PR messages" section of `WORKFLOW.md`.
