#!/usr/bin/env bash
# mandor-agent installer: links this repository into the places Claude Code and opencode read.
#
#   ./install.sh               install or refresh (safe to run again after `git pull`)
#   ./install.sh --force       also replace existing files that are not mandor links
#   ./install.sh --no-skills   skip the plugin and skill installs
#   ./install.sh --uninstall   remove the links that point into this repository
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
FORCE=0
UNINSTALL=0
SKILLS=1
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-skills) SKILLS=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

# Repository file -> link path.
LINKS=(
  "core/WORKFLOW.md:$HOME/.config/mandor/WORKFLOW.md"
  "core/PLANNER.md:$HOME/.config/mandor/PLANNER.md"
  "claude/guard.py:$HOME/.config/mandor/claude/guard.py"
  "claude/executor-settings.json:$HOME/.config/mandor/claude/executor-settings.json"
  "bin/claude-executor:$HOME/.local/bin/claude-executor"
  "bin/opencode-executor:$HOME/.local/bin/opencode-executor"
  "bin/mandor-init:$HOME/.local/bin/mandor-init"
)
for f in "$REPO"/claude/agents/*.md; do
  LINKS+=("claude/agents/$(basename "$f"):$HOME/.claude/agents/$(basename "$f")")
done
for f in "$REPO"/opencode/agents/*.md; do
  LINKS+=("opencode/agents/$(basename "$f"):$HOME/.config/opencode/agents/$(basename "$f")")
done

link() {
  local src="$REPO/$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -L "$dst" ]; then
    [ "$(readlink -f "$dst")" = "$src" ] && return 0
    ln -sfn "$src" "$dst"
    say "relinked $dst"
    return 0
  fi
  if [ -e "$dst" ]; then
    if [ "$FORCE" = 1 ]; then
      rm -f "$dst"
    else
      warn "$dst exists and is not a mandor link; left alone (compare it with $1, then rerun with --force)"
      return 0
    fi
  fi
  ln -s "$src" "$dst"
  say "linked $dst"
}

if [ "$UNINSTALL" = 1 ]; then
  for pair in "${LINKS[@]}"; do
    dst="${pair#*:}"
    if [ -L "$dst" ] && [[ "$(readlink -f "$dst")" == "$REPO"/* ]]; then
      rm "$dst"
      say "removed $dst"
    fi
  done
  say "left in place: ~/.config/mandor/router-url and router-key, ~/.config/opencode/opencode.jsonc, installed skills and plugins"
  exit 0
fi

# Prerequisites.
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (it runs the Claude Code guard)" >&2; exit 1; }
command -v claude >/dev/null || warn "claude not found: the planner and the Claude Code executor need Claude Code"
command -v opencode >/dev/null || warn "opencode not found: the opencode executor needs it"
command -v gh >/dev/null || warn "gh not found: the executor opens and merges PRs with the GitHub CLI"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "$HOME/.local/bin is not on PATH; add it so the launchers are found" ;; esac

for pair in "${LINKS[@]}"; do
  link "${pair%%:*}" "${pair#*:}"
done

# Per-device router settings that never go into git, one value per file. opencode.jsonc reads
# them with {file:...}, so a plain `opencode` session finds them as well as opencode-executor.
mkdir -p "$HOME/.config/mandor"
for name in router-url router-key; do
  if [ ! -f "$HOME/.config/mandor/$name" ]; then
    (umask 077 && printf 'replace-me\n' > "$HOME/.config/mandor/$name")
    warn "write your router's ${name#router-} into $HOME/.config/mandor/$name"
  fi
done

# opencode config: rendered, because it needs this device's home path.
render_opencode() {
  local dst="$HOME/.config/opencode/opencode.jsonc" tmp
  tmp="$(mktemp)"
  sed "s|@HOME@|$HOME|g" "$REPO/opencode/opencode.jsonc.template" > "$tmp"
  mkdir -p "$(dirname "$dst")"
  if [ -f "$dst" ] && ! head -1 "$dst" | grep -q '^// mandor-agent'; then
    if [ "$FORCE" = 1 ]; then
      mv "$tmp" "$dst"
      say "replaced $dst"
    else
      rm -f "$tmp"
      warn "$dst was not written by mandor; left alone (merge opencode/opencode.jsonc.template by hand, or rerun with --force)"
    fi
    return 0
  fi
  if [ -f "$dst" ] && cmp -s "$tmp" "$dst"; then
    rm -f "$tmp"
    return 0
  fi
  mv "$tmp" "$dst"
  say "wrote $dst"
}
render_opencode

# An RTK hook would compress the executor's diffs and test output; let the launchers switch it off.
if [ -f "$HOME/.claude/settings.json" ]; then
  python3 - "$HOME/.claude/settings.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
changed = False
for matcher in data.get("hooks", {}).get("PreToolUse", []):
    for hook in matcher.get("hooks", []):
        if hook.get("command", "").strip() == "rtk hook claude":
            hook["command"] = '[ -n "$RTK_HOOK_OFF" ] || rtk hook claude'
            changed = True
if changed:
    open(path, "w").write(json.dumps(data, indent=2) + "\n")
    print("the RTK hook in ~/.claude/settings.json now honours RTK_HOOK_OFF")
PY
fi

if [ "$SKILLS" = 1 ]; then
  # Engineering skills: the Claude Code plugin, also linked for opencode.
  cache="$HOME/.claude/plugins/cache/claude-plugins-official/mattpocock-skills"
  if [ ! -d "$cache" ] && command -v claude >/dev/null; then
    say "installing the Claude Code plugin mattpocock-skills"
    claude plugin install mattpocock-skills@claude-plugins-official \
      || warn "could not install it; run: claude plugin install mattpocock-skills@claude-plugins-official"
  fi
  if [ -d "$cache" ]; then
    version="$(ls "$cache" | sort -V | tail -1)"
    skills="$cache/$version/skills/engineering"
    target="$HOME/.config/opencode/skill"
    mkdir -p "$target"
    find "$target" -maxdepth 1 -xtype l -lname '*mattpocock-skills*' -delete
    for dir in "$skills"/*/; do
      dir="${dir%/}"
      # User-only skills stay out of opencode, which ignores disable-model-invocation.
      grep -q '^disable-model-invocation: true' "$dir/SKILL.md" 2>/dev/null && continue
      ln -sfn "$dir" "$target/$(basename "$dir")"
    done
    say "opencode skills linked from mattpocock-skills $version"
  else
    warn "mattpocock-skills is not installed; tdd, code-review and the other engineering skills will be missing"
  fi

  # Third-party skills.
  if command -v npx >/dev/null; then
    grep -Ev '^[[:space:]]*(#|$)' "$REPO/skills.txt" | while read -r spec; do
      name="${spec##*@}"
      if [ -e "$HOME/.claude/skills/$name" ] || [ -e "$HOME/.agents/skills/$name" ]; then
        continue
      fi
      say "installing skill $spec"
      npx -y skills add "$spec" -g -y || warn "could not install $spec"
    done
  else
    warn "npx not found; install the skills listed in skills.txt by hand"
  fi
fi

say ""
say "mandor-agent is installed. Next:"
say "  1. If you use opencode, write the router URL and key into ~/.config/mandor/router-url and router-key."
say "  2. In each project: run mandor-init, then fill in the project layer in CLAUDE.local.md and .mandor/env.sh."
say "  3. Plan in a Claude Code session in the project; execute with opencode-executor or claude-executor."
