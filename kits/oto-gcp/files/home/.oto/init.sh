#!/bin/sh
# OTO for the agent user, at every start: quick once everything is there.
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"     # a startup step gets a bare PATH; claude and oto live here
log=/tmp/oto-init.log
{
  git config --global --get-all url."https://github.com/".insteadOf | grep -q "git@github.com:" || {
    git config --global --add url."https://github.com/".insteadOf git@github.com:
    git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/; }
  claude plugin marketplace list 2>/dev/null | grep -q cynergis || claude plugin marketplace add Cynergis/oto-registry
  have=$(claude plugin list 2>/dev/null)
  for p in product software-architecture product-report report flow medallion report-medallion platform work pdf-to-template; do
    echo "$have" | grep -q "$p@cynergis" || claude plugin install "$p@cynergis"
  done
  python3 "$HOME/.oto/lock-plugins"     # only the plugins installed here load: see the script
  command -v oto >/dev/null || uv tool install "oto-kg[intake] @ git+https://github.com/Cynergis/oto@v0.12.0"
  [ -d "$HOME/.cache/ms-playwright" ] || uv tool run --from playwright playwright install chromium
} >>"$log" 2>&1
echo "OTO ready: $(claude plugin list 2>/dev/null | grep -c enabled) plugins" >>"$log"
