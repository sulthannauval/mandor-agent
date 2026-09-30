#!/usr/bin/env python3
"""Checks the Claude Code guard against allowed and blocked calls for every agent.

Run: python3 tests/test_guard.py
"""
import json
import os
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude", "guard.py")
REPO = tempfile.mkdtemp(prefix="mandor-guard-repo-")
WT = os.path.join(os.path.dirname(REPO), "wt", "fix-x")
HOME = os.path.expanduser("~")
ENV = dict(os.environ, MANDOR_PROTECTED_PATHS="~/.demoapp")


def run(agent, tool, tool_input):
    data = {"tool_name": tool, "tool_input": tool_input, "cwd": REPO, "hook_event_name": "PreToolUse"}
    if agent != "executor":
        data.update(agent_id="a1", agent_type=agent)
    out = subprocess.run([sys.executable, GUARD], input=json.dumps(data), capture_output=True, text=True, env=ENV)
    if out.stdout.strip():
        decision = json.loads(out.stdout)["hookSpecificOutput"]
        return decision["permissionDecision"], decision["permissionDecisionReason"]
    return "pass", out.stderr.strip()


def bash(command):
    return {"command": command}


CASES = [
    # executor: plans/ only, no shell edits, protected paths
    ("executor", "Edit", {"file_path": f"{REPO}/plans/400-x.md"}, "pass"),
    ("executor", "Edit", {"file_path": f"{REPO}/src/main.rs"}, "deny"),
    ("executor", "Write", {"file_path": f"{WT}/src/a.rs"}, "deny"),
    ("executor", "Bash", bash("git fetch origin && git worktree add ../wt/fix-x -b fix/x origin/main"), "pass"),
    ("executor", "Bash", bash("cat > /tmp/msg.txt <<'EOF'\nfix(x): y > z\n\n- a | b; c\nEOF\ngit commit -F /tmp/msg.txt"), "pass"),
    ("executor", "Bash", bash("gh pr merge 12 --squash"), "pass"),
    ("executor", "Bash", bash("sed -i 's/a/b/' src/main.rs"), "deny"),
    ("executor", "Bash", bash("echo x > src/main.rs"), "deny"),
    ("executor", "Bash", bash("cat ~/.demoapp/config.toml"), "deny"),
    ("executor", "Read", {"file_path": f"{HOME}/.demoapp/config.toml"}, "deny"),
    ("executor", "Read", {"file_path": f"{REPO}/src/main.rs"}, "pass"),
    ("executor", "Bash", bash("gh pr checks 12 2>&1 | tail -5"), "pass"),
    ("executor", "Bash", bash("sleep 60; echo done"), "deny"),
    # coder
    ("coder", "Edit", {"file_path": f"{WT}/src/a.rs"}, "pass"),
    ("coder", "Bash", bash(f"cd {WT} && cargo test -q --lib channels"), "pass"),
    ("coder", "Bash", bash("git add -A && git commit -m wip"), "deny"),
    ("coder", "Bash", bash("git -C /x stash"), "deny"),
    ("coder", "Bash", bash("git diff && git status"), "pass"),
    ("coder", "Bash", bash("gh pr view 12"), "deny"),
    ("coder", "Edit", {"file_path": f"{HOME}/.demoapp/config.toml"}, "deny"),
    ("coder", "Bash", bash("HOME=/tmp/h cargo test -q; grep -m1 schema /tmp/h/.demoapp/config.toml"), "pass"),
    # fixer
    ("fixer", "Bash", bash("gh run view 123 --log-failed | tail -50"), "pass"),
    ("fixer", "Bash", bash("gh pr merge 12 --squash"), "deny"),
    ("fixer", "Bash", bash("git checkout -- src/a.rs"), "deny"),
    # scout and reviewer are read-only
    ("scout", "Bash", bash(f"git -C {WT} diff origin/main...HEAD"), "pass"),
    ("scout", "Bash", bash("git fetch origin && git show origin/main:src/main.rs | sed -n '1,40p'"), "pass"),
    ("scout", "Bash", bash("rg -n 'fn listen' src/channels | head -20"), "pass"),
    ("scout", "Bash", bash("touch /tmp/x"), "deny"),
    ("scout", "Bash", bash("git commit -m x"), "deny"),
    ("reviewer", "Bash", bash("git log origin/main..HEAD --oneline && gh pr checks 12"), "pass"),
    ("reviewer", "Bash", bash("echo $(git rev-parse HEAD)"), "deny"),
    ("reviewer", "Edit", {"file_path": "/tmp/a"}, "deny"),
]


def main():
    failures = 0
    for agent, tool, tool_input, want in CASES:
        got, why = run(agent, tool, tool_input)
        ok = got == want
        failures += not ok
        label = (tool_input.get("command") or tool_input.get("file_path"))[:70].replace("\n", " / ")
        print(f"{'ok ' if ok else 'BAD'} {agent:8} {tool:5} want={want:4} got={got:4} | {label}" + ("" if ok else f"  <- {why}"))
    print(f"\n{len(CASES) - failures}/{len(CASES)} as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
