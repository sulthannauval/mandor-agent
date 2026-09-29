## Planner protocol (Claude Code only)

Claude Code sessions in this repository act as the planner. The shared rules are imported below; opencode executors see this line as plain text and follow `WORKFLOW.md` instead.

@~/.config/mandor/PLANNER.md

## Build and test rules for agents (project layer)

These are the project-specific commands and limits that the executor and its subagents follow, in either runtime. The general workflow lives in `~/.config/mandor/WORKFLOW.md`.

- Build: `<command>`
- Focused tests: `<command for one module>`. Never run the whole suite when a narrower target covers the change.
- Formatter: `<command>`
- Local gate before pushing (match what CI runs): `<commands>`
- Machine limits: `<RAM, cores, disk notes, parallel build limits>`
- High-risk paths (a full review and `security-review` apply): `<paths>`
- Changelog and versioning rules: `<rules, or "none">`
