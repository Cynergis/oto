#!/bin/sh
# OTO for the agent user, at every start: quick once everything is there.
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"     # a startup step gets a bare PATH; claude and oto live here
log=/tmp/oto-init.log
{
  git config --global --get-all url."https://github.com/".insteadOf | grep -q "git@github.com:" || {
    git config --global --add url."https://github.com/".insteadOf git@github.com:
    git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/; }
  markets=$(claude plugin marketplace list 2>/dev/null)
  echo "$markets" | grep -q "(Cynergis/oto)" || claude plugin marketplace add Cynergis/oto                    # the engine plugin's own marketplace, cynergis-engine
  echo "$markets" | grep -q "(Cynergis/oto-registry)" || claude plugin marketplace add Cynergis/oto-registry   # the packs (ADR-0009: the registry carries no engine)
  have=$(claude plugin list 2>/dev/null)
  echo "$have" | grep -q "oto@cynergis-engine" || claude plugin install "oto@cynergis-engine"   # the engine alone: the packs a project needs are turned on from the session (/oto:packs)
  python3 "$HOME/.oto/lock-plugins"     # only the plugins installed here load: see the script
  # A shell over SSH or sbx run opens in the tool's default folder; the project is mounted at its own
  # path, which `oto sandbox up` passed as OTO_PROJECT_DIR. An interactive shell that starts in the home
  # folder or the default lands on the project; one started elsewhere on purpose is left alone.
  cat > "$HOME/.oto/landing.sh" <<'LANDING'
case "$-" in *i*)
  if [ -n "$OTO_PROJECT_DIR" ] && [ -d "$OTO_PROJECT_DIR" ]; then
    case "$PWD" in "$HOME"|"$HOME/workspace") cd "$OTO_PROJECT_DIR" ;; esac
  fi ;;
esac
LANDING
  for rc in "$HOME/.bashrc" "$HOME/.profile"; do
    grep -q 'oto/landing.sh' "$rc" 2>/dev/null || printf '\n[ -f "$HOME/.oto/landing.sh" ] && . "$HOME/.oto/landing.sh"\n' >> "$rc"
  done
  command -v oto >/dev/null || uv tool install "oto-kg[intake] @ git+https://github.com/Cynergis/oto@v0.16.5"
  [ -d "$HOME/.cache/ms-playwright" ] || uv tool run --from playwright playwright install chromium
} >>"$log" 2>&1
echo "OTO ready: $(claude plugin list 2>/dev/null | grep -c enabled) plugins" >>"$log"
