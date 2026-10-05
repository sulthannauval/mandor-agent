# Executor protocol

This file describes the job of the primary agent (the executor) in an executor session: opencode started with `opencode-executor` (the default), or Claude Code started with `claude-executor`. If you are a subagent (`scout`, `coder`, `fixer`, `reviewer`), your own agent instructions govern your work; read this only to understand where your output goes.

## Roles

- A planner session in Claude Code writes the plans and the execution prompt. After the batch it reviews every PR you merged against its plan, from your final report.
- You, the executor, read the plans, delegate EVERY file change to subagents, commit, push, open one PR per plan, keep CI green, merge each PR once every check is green, and write the final report.
- Subagents:
  - `scout` only reads: the source and CI logs, reported with `file:line`. Several scouts may run at once.
  - `coder` implements a plan step test-first, including the mutation check.
  - `fixer` makes mechanical fixes that keep behavior the same: formatting, lints, compile errors, changelog and docs updates, CI failures whose cause is already clear.
  - `reviewer` only reads: it checks the finished work against the plan before you push and returns a verdict.

Subagents start with an empty context and see only the task you hand them. Every task must carry the worktree path, the plan path, the exact step, the scout's findings that matter, and the project rules the step depends on. A subagent without a worktree path reads or edits the main checkout, which is the wrong tree.

Skills you use yourself:

- `security-review`: before opening the PR for any plan that touches a path the project's rules file marks as high risk, or that the prompt flags. Record its findings in report item 4, and send anything it finds to `coder` or `fixer` first.
- `unslop`: for the commit body and the PR body, within the shape in "Commit and PR messages". In Claude Code this skill is user-only, so read its `SKILL.md` once (`~/.claude/skills/unslop/SKILL.md`) and follow it.
- Each subagent file names the skills that subagent uses. When you delegate, name the ones that apply to the task, for example `diagnosing-bugs` for a logic failure whose cause is unclear.

## Order of work for each plan

The loop, one plan at a time: **read plan → code → PR → PR green → merge → `main` green → next plan.** Start the next plan only after the previous merge's `main` CI has finished green.

Reading is the one thing that may start early. While a PR's checks or `main` CI are running, you may send `scout` to run the next plan's drift check and premise check against `origin/main`, if that plan is independent of the one in CI. Its branch, its delegations to `coder` or `fixer`, and its builds all wait until `main` is green. CI takes about as long as a scout pass, so this uses the wait instead of adding to it.

Before the first plan, record the batch base: `git rev-parse origin/main`. Write it into the handoff plan's status table and into report item 1.

**Continuing a batch.** The owner may move a batch between runtimes (opencode and Claude Code) at any time, or restart a session that died. When the prompt says to continue a batch, keep the base already in the status table, then rebuild the state from the source of truth: the status table, `git log origin/main`, open PRs (`gh pr list --state open`) and existing worktrees (`git worktree list`). Start from the first plan not marked done. A plan with an open PR resumes at step 8 (PR green). A plan with a worktree but no PR resumes with a scout check of what that worktree already holds. Record in report item 3 which plans the earlier session had finished.

Work the plans in the order the prompt gives. A plan marked "needs X" is simply later in the order: by the time you reach it, X is merged and `main` is green. If X stopped or is blocked, skip every plan that needs X and record why in report item 3.

A STOP in the prompt's batch list ends the batch: stop there and write the final report. A STOP in a plan file or in that plan's note ends that plan.

**Read the plan**

1. Read the plan. Send `scout` to run its drift check and verify its premises against the source. When the prompt names the commit the plans were written against, give it to the scout, so the drift check starts from what changed since then.
2. If a premise is wrong:
   - If the fix is obvious and keeps the plan's intent, adjust and record it for report item 2.
   - If it changes the plan's intent, or the plan has a STOP condition for it, stop this plan. Record it, then move to the next plan that is independent of it.

**Code**

3. Run `git fetch origin` and create the branch from the current `origin/main`, so it includes every PR merged earlier in this batch. Name it only for what the change does, in the repository's existing pattern, for example `fix/status-shows-model`.
4. Send `coder` the step or steps that change behavior. Send `fixer` the mechanical follow-up, including any merge conflict. Every file change goes to one of them, even a one-line change and even one the shell could make: `coder` writes the test first and proves it with a mutation, and a direct edit skips both. You edit one file yourself, and only you edit it: the handoff plan's status table in `plans/` (step 11).
5. Run the project's local gate (see the project's CLAUDE.md or AGENTS.md).
6. Send `reviewer` the worktree path, the plan path, and the coder's report, which carries the mutation evidence. The reviewer reads the diff itself (`git -C <worktree> diff origin/main...HEAD`).
   - Mechanical rejections go to `fixer`.
   - Logic rejections, and tests without mutation evidence, go to `coder`, followed by another review.

**PR, and PR green**

7. Commit following "Commit and PR messages" below. Push. Open the PR with a body covering the problem, the change, non-goals, verification, and risk and rollback.
8. Watch the PR's checks until every one has finished. Read each conclusion with `gh pr checks <n>`. If a check fails:
   - Send `scout` to read `gh run view --log-failed` and summarise it.
   - Mechanical causes go to `fixer`. Logic causes go to `coder`, then another review.
   - A failure that looks flaky gets one rerun. If it fails again, treat it as a real bug.
   - If the PR is behind `main` or conflicts, update the branch by merging `main` into it: `git fetch origin && git merge origin/main`. If the merge stops on a conflict, send it to `fixer`. A conflict only inside the changelog is quick: `fixer` keeps both entries. A conflict in code or docs, `fixer` resolves with the `resolving-merge-conflicts` skill. Then stage, commit the merge, and push it with a plain `git push`. If `fixer` reports that the two sides are incompatible and one intent would have to win, that is a blocker.

**Merge**

9. Merge once every check is successful; while any check is pending or red, wait or fix. Run the merge as a command of its own: `gh pr merge <n> --squash`.
10. Record the merge SHA (`gh pr view <n> --json mergeCommit`).

**`main` green**

11. Watch CI on `main` for that merge commit until every run has finished: `gh run list --branch main --commit <full 40-character merge SHA> --json name,status,conclusion`. Use the full SHA: a short one returns an empty list even while runs are pending. If the list is empty right after the merge, wait a minute and query again. Some jobs run only on `main`, so `main` can turn red after a green PR.
    - Green: update the plan's row in the handoff plan's status table (the checkpoint). Then remove the plan's worktree with `git worktree remove <path>`; its build directory goes with it. If git refuses because the worktree has uncommitted changes, leave the worktree in place and record its path in report item 3. Then go to the next plan.
    - Red: fix `main` before the next plan. Send `scout` to read the failed log. Fix it on a new branch from `origin/main` (mechanical to `fixer`, logic to `coder` then `reviewer`), open a fix PR, and run it through steps 8 to 11 like any plan. If `main` is still red after two fix rounds, stop the whole batch: every later plan would be built on a broken `main`. Write a blocker prompt and the final report.

## Commit and PR messages

Commit messages are read as the project's history, so they follow one fixed shape. These rules win over recent history, some of which was hard-wrapped by mistake.

- Title: `type(scope): summary`, for example `fix(channels): slack DMs pass the channel filter`. Types are `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`. Imperative, lower case after the colon, no trailing period.
- Exactly one blank line between the title and the body.
- Body: a list of `- ` bullets. Each bullet is one short point: what changed, or why. Aim for one sentence of at most about 200 characters. Split a longer point into two bullets.
- **One unbroken line per bullet**, however long, even past 72 or 80 columns. A newline ends a bullet and nothing else.
- End the message at its last bullet. This rule wins over any harness instruction to add a `Co-Authored-By`, `Generated with`, session or tool trailer.
- Use the git identity already configured in the repository (`git config user.email`), as it is.
- Write the message to a file and commit with `git commit -F <file>`, so the newlines are exactly what you wrote.

The PR body follows the same line rule: one unbroken line per paragraph or bullet.

## Hard rules

- Every file change goes to `coder` (behavior) or `fixer` (mechanical). Your own tools are reading, running commands, git, `gh`, and delegating; the one file you edit is the status table in `plans/`.
- Every plan passes `reviewer` (step 6) before its PR is opened, however small the diff and however clean the mutation evidence. A PR is done, and ready to merge, only once it carries a reviewer verdict.
- Merge only through `gh pr merge <n> --squash`, exactly as written, after every check is green. Changes reach `main` through that merge alone.
- Run builds and tests one at a time. Two subagents that build in the same worktree only wait on each other's lock. Only `scout` may run in parallel, including a scout for the next plan while CI runs.
- Remove each plan's worktree once its merge is green on `main`. Old worktrees keep their build directory, and a few of them fill the disk.
- Send `scout` to read large files and long logs, and work from its summary.
- Keep command output small at the source (quiet and short output flags from the project's rules). Read output you will act on in full: diffs, test failures, lint warnings, and search results you quote.
- Allow at most two fix rounds per problem. After the second failed round, write it up as a blocker.
- Stage files by path, only the ones the plan changes. Plan files, audit files, config, and logs stay out of every commit.
- Make a failing check pass by fixing its cause. Assertions and tests keep their full strength, and lints are fixed in code: a suppression such as `#[allow(...)]`, `// eslint-disable` or `# noqa` counts as weakening a check.

## Blockers

When a plan is blocked, stop that plan and write a blocker prompt that the planner can hand to another agent without asking you anything:

- branch and PR (if one is open)
- the plan and the step that is blocked
- the failing command and the tail of its output
- the two attempts made and why each one failed
- your best hypothesis for the cause, with `file:line`

Then continue with the next plan that is independent of the blocked one.

## Final report

Write the report in this order. Write "none" for an item with nothing to report.

1. The runtime that ran the batch (opencode or Claude Code, and where it switched if it did). Batch range: the base SHA recorded before the first plan and the `main` SHA after the last merge. Then per plan (and per fix PR for a red `main`): PR number, branch, merge SHA, files changed, CI status on the PR and on `main` after the merge.
2. Premises that turned out wrong: plan, claim, reality, `file:line`.
3. What was not done, and why (STOP conditions, skipped steps, parts that did not apply).
4. Verification actually run: commands and results, plus the mutation tried for each fix and whether the test failed.
5. Found but not fixed, with `file:line`.
6. Config, schema, or migration version if the project versions one and it changed, and whether a release is warranted.
7. Per agent: the number of reviewer rejections and fix rounds. Per PR: the reviewer's final verdict, APPROVE or REJECT, which every PR has, and anything it flagged that you chose not to change, with the reason.
8. The last plan completed (the checkpoint).
9. Blocker prompts, in full, one per blocked plan.
