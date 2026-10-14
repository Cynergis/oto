"""`oto publishable`: a repository about to be published names no client and holds no credential.
The terms come from outside (OTO_DENY_TERMS, a gitignored .oto-denylist); a finding names the file
and the line, never the text, because a CI log is public."""
import os
import subprocess

from oto.cli import main


def _repo(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return str(tmp_path)


def test_a_client_term_fails_and_the_log_does_not_repeat_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OTO_DENY_TERMS", "Zorblax Holdings,zbx")
    root = _repo(tmp_path, {"README.md": "# A pack\n\nExported from the zorblax holdings project.\n",
                            "packs/p/manifest.json": '{"note": "ZBX release"}\n', "ok.md": "nothing here\n"})
    assert main(["publishable", root, "--strict"]) == 1
    out = capsys.readouterr().out
    assert "README.md:3  client term" in out and "packs/p/manifest.json:1  client term" in out
    assert "zorblax" not in out.lower() and "zbx" not in out.lower()


def test_a_credential_fails_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OTO_DENY_TERMS", "zorblax")
    root = _repo(tmp_path, {"ci.yml": "token: ghp_" + "a" * 30 + "\n"})
    assert main(["publishable", root]) == 1
    out = capsys.readouterr().out
    assert "ci.yml:1  GitHub personal access token" in out and "aaaa" not in out


def test_strict_refuses_to_pass_without_terms_and_a_local_denylist_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OTO_DENY_TERMS", raising=False)
    root = _repo(tmp_path, {"a.md": "clean\n"})
    assert main(["publishable", root, "--strict"]) == 1
    assert "name checking is DISABLED" in capsys.readouterr().out
    assert main(["publishable", root]) == 0
    (tmp_path / ".oto-denylist").write_text("# one per line\nclean\n")
    assert main(["publishable", root, "--strict"]) == 1, "the denylist file's term is found in a.md"


def test_in_a_git_repository_only_what_would_be_published_is_scanned(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OTO_DENY_TERMS", "zorblax")
    root = _repo(tmp_path, {"tracked.md": "clean\n", ".gitignore": "notes/\n", "notes/private.md": "zorblax\n"})
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert main(["publishable", root, "--strict"]) == 0
    assert "RESULT: PASS" in capsys.readouterr().out
