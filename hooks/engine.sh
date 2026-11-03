#!/bin/sh
# The session start of the oto plugin: the engine is the `oto` command installed on this computer
# (ADR-0014), and the plugin runs that one. Say in a line when it is missing, off the PATH Claude Code
# sees, or not the plugin's release, with the command that fixes it; then the project's status.
# Never fails: a session starts without the engine.
release=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$(dirname "$0")/../.claude-plugin/plugin.json" | head -1)
install="uv tool install --force \"oto-kg[intake] @ git+https://github.com/Cynergis/oto@v$release\""
if ! command -v oto >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/oto" ]; then
    echo "OTO's engine is installed in ~/.local/bin but not on the PATH Claude Code sees: run uv tool update-shell, then restart Claude Code."
  else
    echo "OTO's engine is not installed on this computer, and the oto plugin needs it: $install"
  fi
  exit 0
fi
have=$(oto version 2>/dev/null | sed -n 's/^oto \([^ ]*\).*/\1/p')
if [ -n "$release" ] && [ "$have" != "$release" ]; then
  echo "OTO's engine here is ${have:-of an unknown version} and the oto plugin is $release: $install"
fi
oto status --project "$1" 2>/dev/null || true
