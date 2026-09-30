# shellcheck shell=bash
# mandor project settings, sourced by claude-executor and opencode-executor from <repo>/.mandor/env.sh.
# It stays out of git (mandor-init adds .mandor/ to .git/info/exclude).
# Everything exported here applies to every command in the executor session and its subagents.

# Paths no agent may read, write or name in a command, colon-separated; ~/ is allowed.
# Enforced by the Claude Code guard. Example: the live config of the app you are developing.
# export MANDOR_PROTECTED_PATHS="~/.myapp"

# Point the app's config and data directories at throwaway ones, so builds and tests in the
# session never touch the live install. Example:
# export MYAPP_CONFIG_DIR="$(mktemp -d -t myapp-executor-config-XXXXXX)"
