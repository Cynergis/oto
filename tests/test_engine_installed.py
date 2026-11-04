"""One engine on a computer: the `oto` command installed there (ADR-0014). The plugin's server and
hooks run it, never a copy they download, and a project repository's server does the same. The
session start says when it is missing, off Claude Code's PATH, or not the plugin's release, with the
one command that fixes it. Nothing reads OTO_SOURCE any more."""
import json
import os
import stat
import subprocess

import pytest

from oto import repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "engine.sh")

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the hook is a POSIX shell script")


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def _release():
    return json.loads(_read(".claude-plugin", "plugin.json"))["version"]


def _install(version):
    return 'uv tool install --force "oto-kg[intake,neo4j] @ git+https://github.com/Cynergis/oto@v%s"' % version


def _session_start(tmp_path, version=None, where="path"):
    """The hook on a computer whose engine is `version` (None: not installed), on the PATH or only in
    ~/.local/bin, where `uv tool install` puts it."""
    path_bin, home = tmp_path / "bin", tmp_path / "home"
    local_bin = home / ".local" / "bin"
    path_bin.mkdir()
    local_bin.mkdir(parents=True)
    if version:
        fake = (path_bin if where == "path" else local_bin) / "oto"
        fake.write_text('#!/bin/sh\ncase "$1" in version) echo "oto %s";; *) echo "oto ran: $*";; esac\n' % version)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = {"PATH": "%s:/usr/bin:/bin" % path_bin, "HOME": str(home)}
    return subprocess.run(["sh", HOOK, str(tmp_path / "project")], env=env, capture_output=True, text=True)


def test_the_plugins_server_and_hooks_run_the_installed_engine():
    server = json.loads(_read(".mcp.json"))["mcpServers"]["oto"]
    assert server == {"command": "oto", "args": ["serve", "--project", "${CLAUDE_PROJECT_DIR}"]}
    hooks = json.loads(_read("hooks", "hooks.json"))["hooks"]
    assert hooks["SessionStart"][0]["hooks"][0]["command"] == 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/engine.sh" "${CLAUDE_PROJECT_DIR}"'
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == "oto clipboard --when-asked 2>/dev/null || true"
    for text in (_read(".mcp.json"), _read("hooks", "hooks.json"), _read("hooks", "engine.sh")):
        assert "uvx" not in text and "OTO_SOURCE" not in text, "no copy of the engine is downloaded beside the installed one"


def test_the_session_start_runs_the_installed_engines_status(tmp_path):
    done = _session_start(tmp_path, _release())
    assert done.returncode == 0 and done.stdout.strip() == "oto ran: status --project %s" % (tmp_path / "project")


def test_the_session_start_says_when_the_engine_is_not_the_plugins_release(tmp_path):
    done = _session_start(tmp_path, "0.11.31")
    first = done.stdout.splitlines()[0]
    assert "0.11.31" in first and _release() in first and _install(_release()) in first
    assert "oto ran: status" in done.stdout, "the status still runs"


def test_the_session_start_says_how_to_install_a_missing_engine(tmp_path):
    done = _session_start(tmp_path, None)
    assert done.returncode == 0, "a session starts without the engine"
    assert "not installed" in done.stdout and _install(_release()) in done.stdout


def test_an_engine_off_claude_codes_path_is_said(tmp_path):
    done = _session_start(tmp_path, _release(), where="local")
    assert "uv tool update-shell" in done.stdout and "not on the PATH" in done.stdout


def test_a_project_repository_serves_with_the_installed_engine():
    files = repo.files("x", "X")
    assert json.loads(files[".mcp.json"])["mcpServers"]["x-kg"] == {"command": "oto", "args": ["serve", "--project", "."]}
    assert "uvx" not in files["CLAUDE.md"] and 'uv tool install "oto-kg[intake,neo4j] @ git+%s' % repo.ENGINE in files["CLAUDE.md"]


def test_nothing_reads_oto_source_any_more():
    listed = subprocess.run(["git", "grep", "-l", "OTO_SOURCE", "--", ".", ":!CHANGELOG.md", ":!docs/adr/0014-*", ":!tests/*"],
                            cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert listed == [], listed


def test_adr_0014_records_the_decision():
    adr = _read("docs", "adr", "0014-one-engine-on-a-computer.md")
    assert "id: ADR-0014" in adr and "status: accepted" in adr and "decided_by: Chiheb Dkhil" in adr
    assert "uv tool install" in adr and "OTO_SOURCE" in adr and "--editable" in adr
