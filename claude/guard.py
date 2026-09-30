#!/usr/bin/env python3
"""PreToolUse guard for mandor executor sessions started with `claude-executor`.

Claude Code loads this hook only through ~/.config/mandor/claude/executor-settings.json,
so it never runs in ordinary sessions. It applies per-agent rules keyed on the
hook input's `agent_type`; the main thread (no `agent_id`) is the executor.

A decision is printed as PreToolUse JSON. Printing nothing and exiting 0 means
"no objection": the normal permission rules then decide.

A Monitor command is a shell command too, so it gets the same checks as Bash.
A command that only passes time (`true`, `echo waiting`, `sleep 60; echo`) is
refused for every agent: in one measured batch, 1,645 such calls re-sent the
whole context and used 45% of all tokens. The refusal says how to wait instead.

A project can protect paths no agent may read, write or name in a command (for
example the live config of the app under development) by listing them,
colon-separated, in MANDOR_PROTECTED_PATHS, usually from the project's
`.mandor/env.sh`. Paths may start with `~/`.
"""
import json
import os
import re
import shlex
import sys

HOME = os.path.expanduser("~")


def protected_patterns():
    """Every spelling of each protected path that may appear in a command or a file path."""
    patterns = []
    for raw in os.environ.get("MANDOR_PROTECTED_PATHS", "").split(":"):
        raw = raw.strip().rstrip("/")
        if not raw:
            continue
        absolute = os.path.realpath(os.path.expanduser(raw))
        patterns.append(absolute)
        if absolute.startswith(HOME + os.sep):
            rest = absolute[len(HOME) + 1:]
            patterns += ["~/" + rest, "$HOME/" + rest, "${HOME}/" + rest]
        elif raw != absolute:
            patterns.append(raw)
    return tuple(patterns)


PROTECTED = protected_patterns()
PROTECTED_REASON = "this path is protected for the project (MANDOR_PROTECTED_PATHS); no agent reads, writes or names it"

SEPARATORS = {"&&", "||", ";", "|", "&", "|&", ";;"}
WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "env", "xargs"}
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

GIT_WRITE = r"(commit|push|add|stash|checkout|switch|reset|restore|clean|rebase|merge|cherry-pick|revert|am|apply|tag|branch\s+-[dDmM])"
GIT_WRITE_RE = re.compile(r"(^|[\s;&|(`])git(\s+(-C|-c)\s+\S+|\s+--[\w-]+(=\S+)?)*\s+" + GIT_WRITE + r"\b")

READ_ONLY_GIT = {"log", "show", "diff", "status", "grep", "blame", "rev-parse", "ls-files", "fetch",
                 "merge-base", "cat-file", "describe", "shortlog", "for-each-ref", "rev-list", "name-rev"}
READ_ONLY_CMDS = {"rg", "grep", "ls", "find", "wc", "cat", "head", "tail", "sed", "sort", "uniq", "cut", "tr",
                  "nl", "diff", "cmp", "file", "stat", "du", "basename", "dirname", "realpath", "readlink",
                  "pwd", "echo", "printf", "true", "test", "[", "which", "jq", "awk", "cd", "tree", "column"}
READ_ONLY_GH = {("run", "view"), ("run", "list"), ("pr", "view"), ("pr", "checks"), ("pr", "diff"), ("pr", "list"),
                ("issue", "view"), ("issue", "list")}

# Commands that do nothing but pass time when they make up the whole command.
IDLE_CMDS = {"true", ":", "sleep", "echo", "printf", "date"}
IDLE_REASON = (
    "this command only passes time, and every call re-sends your whole context. To wait for a long command, run it "
    "in the foreground with the Bash timeout set as high as 600000 ms. If a command is already running in the "
    "background, end your turn with one line saying what you wait for: you are re-invoked when it exits. To watch "
    "progress, use the Monitor tool (ToolSearch \"select:Monitor\") with an until-loop of read-only commands, e.g. "
    "until grep -qE 'test result:|error' <output file>; do sleep 5; done; tail -60 <output file>"
)


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def strip_heredocs(command):
    """Drop heredoc bodies so their text is not parsed as commands."""
    out, terminator = [], None
    for line in command.split("\n"):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        out.append(line)
        m = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line)
        if m:
            terminator = m.group(2)
    return "\n".join(out)


def segments(command):
    """Split a shell command into simple commands (lists of words)."""
    text = strip_heredocs(command).replace("\n", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    seg, result = [], []
    for tok in lexer:
        if tok in SEPARATORS:
            if seg:
                result.append(seg)
            seg = []
        else:
            seg.append(tok)
    if seg:
        result.append(seg)
    return result


def head(words):
    """Return the words of a simple command without env assignments and wrappers."""
    i = 0
    while i < len(words):
        w = words[i]
        if ENV_ASSIGN.match(w):
            i += 1
        elif w in WRAPPERS:
            i += 1
            while i < len(words) and (words[i].startswith("-") or words[i].replace(".", "").isdigit()):
                i += 1
        elif w == "rtk" and i + 1 < len(words) and words[i + 1] == "proxy":
            i += 2
        else:
            break
    return words[i:]


def redirect_targets(words):
    targets = []
    for i, w in enumerate(words):
        if w in (">", ">>", ">|", "&>", "&>>") and i + 1 < len(words):
            targets.append(words[i + 1])
    return targets


def touches_protected(text):
    return any(p in text for p in PROTECTED)


def is_idle_command(command):
    """True when every simple command only passes time (`cd` aside) and nothing is redirected."""
    saw_idle = False
    for seg in segments(command):
        words = head(seg)
        if not words:
            continue
        if redirect_targets(words):
            return False
        if words[0] == "cd":
            continue
        if words[0] not in IDLE_CMDS:
            return False
        saw_idle = True
    return saw_idle


def check_read_only(command):
    if "$(" in command or "`" in command:
        return "command substitution is not allowed for this agent; run the commands separately"
    for seg in segments(command):
        words = head(seg)
        if not words:
            continue
        if redirect_targets(words) and any(t not in ("/dev/null",) and not t.startswith("&") for t in redirect_targets(words)):
            return "writing files through redirection is not allowed for this agent"
        cmd = words[0]
        if cmd == "git":
            rest = words[1:]
            while rest and (rest[0] in ("-C", "-c") or rest[0].startswith("--")):
                rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
            sub = rest[0] if rest else ""
            if sub == "branch" and all(a.startswith("-") and a not in ("-d", "-D", "-m", "-M", "-c", "-C") for a in rest[1:]):
                continue
            if sub == "remote" and rest[1:2] in (["-v"], ["get-url"]):
                continue
            if sub == "worktree" and rest[1:2] == ["list"]:
                continue
            if sub not in READ_ONLY_GIT:
                return f"`git {sub}` is not a read-only command"
        elif cmd == "gh":
            if tuple(words[1:3]) not in READ_ONLY_GH:
                return "only read-only gh commands are allowed (run/pr/issue view, list, checks, diff)"
        elif cmd == "find":
            if any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for a in words[1:]):
                return "find with -delete/-exec is not allowed for this agent"
        elif cmd == "sed":
            if any(a.startswith("-i") or a == "--in-place" for a in words[1:]):
                return "sed -i edits files; not allowed for this agent"
        elif cmd == "awk":
            if any("system" in a or ">" in a for a in words[1:]):
                return "awk programs that write files or run commands are not allowed for this agent"
        elif cmd not in READ_ONLY_CMDS:
            return f"`{cmd}` is not on the read-only list for this agent"
    return None


def main(data):
    tool = data.get("tool_name", "")
    tin = data.get("tool_input") or {}
    agent = data.get("agent_type") if data.get("agent_id") else "executor"
    cwd = os.path.realpath(data.get("cwd") or os.getcwd())

    if tool == "Read":
        real = os.path.realpath(os.path.expanduser(tin.get("file_path") or ""))
        if touches_protected(real):
            decide("deny", PROTECTED_REASON)
        return

    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        path = tin.get("file_path") or tin.get("notebook_path") or ""
        real = os.path.realpath(os.path.expanduser(path))
        if touches_protected(real):
            decide("deny", PROTECTED_REASON)
        if agent == "executor":
            plans = os.path.join(cwd, "plans") + os.sep
            if not real.startswith(plans):
                decide("deny", "the executor edits only the status table in plans/; send file changes to coder or fixer")
        if agent in ("scout", "reviewer"):
            decide("deny", f"{agent} never edits files")
        return

    if tool not in ("Bash", "Monitor"):
        return
    command = tin.get("command") or ""
    if touches_protected(command):
        decide("deny", PROTECTED_REASON)
    if is_idle_command(command):
        decide("deny", f"{agent}: {IDLE_REASON}")

    if agent in ("scout", "reviewer"):
        reason = check_read_only(command)
        if reason:
            decide("deny", f"{agent} is read-only: {reason}")
        return

    if agent == "executor":
        for seg in segments(command):
            words = head(seg)
            if words and words[0] in ("sed", "perl") and any(a.startswith("-i") or a == "--in-place" for a in words[1:]):
                decide("deny", "the executor does not edit files through the shell; send the change to coder or fixer")
            for t in redirect_targets(words):
                if t.startswith("&") or t == "/dev/null" or t.startswith("/tmp/"):
                    continue
                real = os.path.realpath(os.path.join(cwd, os.path.expanduser(t)))
                if not real.startswith(os.path.join(cwd, "plans") + os.sep):
                    decide("deny", "the executor writes files only under /tmp or plans/; send code changes to coder or fixer")
        return

    # coder, fixer, and any other subagent the executor starts
    if GIT_WRITE_RE.search(" " + command):
        decide("deny", f"{agent} does not commit, stage, stash, switch branches or rewrite history; the executor does")
    for seg in segments(command):
        words = head(seg)
        if words and words[0] == "gh":
            if agent == "fixer" and tuple(words[1:3]) in {("run", "view"), ("run", "list"), ("pr", "checks"), ("pr", "view")}:
                continue
            decide("deny", f"{agent} does not use gh; the executor handles PRs and merges")


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    try:
        main(payload)
    except SystemExit:
        raise
    except Exception as exc:
        # A guard bug must not silently widen a read-only agent: deny for scout and
        # reviewer, and let the normal permission rules decide for everyone else.
        print(f"guard.py error: {exc}", file=sys.stderr)
        if payload.get("agent_id") and payload.get("agent_type") in ("scout", "reviewer"):
            decide("deny", f"guard could not check this command ({exc}); run simpler separate commands")
        sys.exit(0)
