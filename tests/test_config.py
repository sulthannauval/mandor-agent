#!/usr/bin/env python3
"""Checks that the agent files and configs parse and agree with each other.

Run: python3 tests/test_config.py   (needs PyYAML)
"""
import glob
import json
import os
import re
import sys

import yaml

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROLES = {"scout", "coder", "fixer", "reviewer"}
HOME = "/home/example"
checks = 0
failures = []


def check(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def frontmatter(rel):
    """Split an agent file into its YAML frontmatter (parsed) and its body."""
    text = read(rel)
    if not text.startswith("---\n"):
        raise ValueError("the file does not start with a frontmatter block")
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        raise ValueError("the frontmatter block is not closed")
    return yaml.safe_load(head), body


def strip_jsonc(text):
    """Drop // and /* */ comments outside strings, and trailing commas."""
    out, i, n, in_str, escaped = [], 0, len(text), False, False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def agents(pattern):
    """Parse every agent file matching the pattern; a parse error is a failure."""
    found = {}
    for path in sorted(glob.glob(os.path.join(ROOT, pattern))):
        rel = os.path.relpath(path, ROOT)
        try:
            found[os.path.basename(path)[:-3]] = (rel, *frontmatter(rel))
        except (ValueError, yaml.YAMLError) as exc:
            check(False, f"{rel}: frontmatter does not parse ({exc})")
    return found


def main():
    skills_txt = [line.strip() for line in read("skills.txt").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    for spec in skills_txt:
        check(re.fullmatch(r"[\w.-]+/[\w.-]+@[\w.-]+", spec), f"skills.txt: {spec!r} is not owner/repo@skill")
    listed = {spec.rsplit("@", 1)[1] for spec in skills_txt}

    claude = agents("claude/agents/*.md")
    check(set(claude) == ROLES | {"executor"}, f"claude/agents holds {sorted(claude)}")
    for name, (rel, meta, body) in claude.items():
        check(meta.get("name") == name, f"{rel}: name is {meta.get('name')!r}")
        check(isinstance(meta.get("description"), str) and meta["description"].strip(), f"{rel}: no description")
        check(meta.get("model") in {"opus", "sonnet", "haiku"}, f"{rel}: model {meta.get('model')!r}")
        check(body.strip(), f"{rel}: empty body")
        for skill in meta.get("skills") or []:
            if ":" in skill:
                check(skill.startswith("mattpocock-skills:"), f"{rel}: preloads {skill!r} from an unknown plugin")
            else:
                check(skill in listed, f"{rel}: preloads {skill!r}, which skills.txt does not install")

    config = json.loads(strip_jsonc(read("opencode/opencode.jsonc.template").replace("@HOME@", HOME)))
    combos = set(config["provider"]["9router-anthropic"]["models"])
    check(combos == {f"{role}-agent" for role in ROLES | {"executor"}}, f"template combos are {sorted(combos)}")
    check(config.get("model") == "9router-anthropic/executor-agent", f"template default model is {config.get('model')!r}")
    check(f"{HOME}/.config/mandor/WORKFLOW.md" in config.get("instructions", []), "template instructions miss WORKFLOW.md")
    for name, provider in config["provider"].items():
        options = provider.get("options", {})
        check(options.get("baseURL") == "{file:~/.config/mandor/router-url}", f"template {name}: baseURL is not read from router-url")
        check(options.get("apiKey") == "{file:~/.config/mandor/router-key}", f"template {name}: apiKey is not read from router-key")
    task = config.get("permission", {}).get("task", {})
    check(task.get("*") == "deny" and {k for k, v in task.items() if v == "allow"} == ROLES,
          f"template task permission is {task}")

    opencode = agents("opencode/agents/*.md")
    check(set(opencode) == ROLES, f"opencode/agents holds {sorted(opencode)}")
    for name, (rel, meta, body) in opencode.items():
        check(isinstance(meta.get("description"), str) and meta["description"].strip(), f"{rel}: no description")
        check(meta.get("mode") == "subagent", f"{rel}: mode is {meta.get('mode')!r}")
        check(meta.get("model") == f"9router-anthropic/{name}-agent", f"{rel}: model is {meta.get('model')!r}")
        check(isinstance(meta.get("permission"), dict), f"{rel}: no permission block")
        check(body.strip(), f"{rel}: empty body")

    settings = json.loads(read("claude/executor-settings.json"))
    hooks = settings.get("hooks", {}).get("PreToolUse", [])
    guarded = [m.get("matcher", "") for m in hooks
               if any("~/.config/mandor/claude/guard.py" in h.get("command", "") for h in m.get("hooks", []))]
    check(guarded, "executor-settings.json: no PreToolUse hook runs the guard")
    for tool in ("Bash", "Monitor", "Read", "Edit", "Write"):
        check(any(tool in m.split("|") for m in guarded), f"executor-settings.json: the guard does not see {tool}")
    check(settings.get("env", {}).get("RTK_HOOK_OFF") == "1", "executor-settings.json: RTK_HOOK_OFF is not set")

    for message in failures:
        print(f"BAD {message}")
    print(f"{checks - len(failures)}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
