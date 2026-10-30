"""The sandboxes skill: every sandbox on the computer and cleaning up the ones no longer used. It reads
`oto sandbox ls`, proposes candidates (stopped and idle, folders gone, not OTO's kit, a stale Desktop
connection) as a checklist the person ticks, removes with `oto sandbox rm` after a yes, and leaves to
the person and the app's own tools what the computer cannot remove: Claude Desktop's saved SSH
connections and its sessions. It runs on the computer, never inside a sandbox."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_skill_exists_as_a_plugin_skill_and_a_project_local_one():
    text = _read("skills", "sandboxes", "SKILL.md")
    assert text.startswith("---\nname: sandboxes\n")
    link = os.path.join(ROOT, ".claude", "skills", "sandboxes")
    assert os.path.islink(link) and os.readlink(link) == os.path.join("..", "..", "skills", "sandboxes")
    assert "| [sandboxes](sandboxes/SKILL.md) |" in _read("skills", "README.md")
    assert "/oto:sandboxes" in _read("skills", "concierge", "SKILL.md") and "/oto:sandboxes" in _read("skills", "sandbox", "SKILL.md")


def test_the_skill_lists_proposes_confirms_and_removes_and_names_what_it_cannot():
    text = _read("skills", "sandboxes", "SKILL.md")
    head = text.split("---")[1]
    assert "clean up" in head and "checklist" in head and "SSH environment menu" in head and "never inside a sandbox" in head
    assert "oto sandbox ls --json" in text and "oto sandbox rm <name>" in text and "oto sandbox stop <name>" in text
    for field in ("status", "from_kit", "exists", "last_used_at", "idle_days", "ssh", "connections"):
        assert "`%s`" % field in text, "the skill reads %s from the listing" % field
    assert "several answers" in text and "checkboxes" in text, "the question tool, with several answers"
    assert "seven days" in text and "folders are gone" in text and "not made from OTO's kit" in text and "stale connection" in text, "the candidate rules"
    assert "Never propose\nthe sandbox the person is working in" in text or "Never propose the sandbox the person is working in" in text.replace("\n", " ")
    flat = " ".join(text.split())
    assert "Removal is final" in text and "folders on their computer stay" in text and "remove nothing without their yes" in flat
    assert "archive a session (reversible) or delete it (final)" in text and "approval" in text
    assert "nothing but the app edits them" in text, "Desktop's connections are the app's own"
    assert "/home/agent/.oto/init.sh" in text, "inside a sandbox it stops"
    assert "## Talking with the person" in text


def test_the_engine_backs_every_step_the_skill_takes():
    from oto import sandbox
    from oto.cli import sandbox as cli
    assert callable(sandbox.list_sandboxes) and callable(sandbox.remove_sandboxes) and callable(sandbox.desktop_ssh_connections)
    source = _read("oto", "cli", "sandbox.py")
    assert 'choices=["up", "status", "ls", "stop", "rm"]' in source and "SSH environment menu" in source
    arch = _read("docs", "ARCHITECTURE.md")
    assert "`oto sandbox ls`" in arch and "ssh_configs.json" in arch and "the folders stay" in arch
    assert "oto sandbox ls" in _read("README.md")


def test_the_skill_names_no_secret_and_no_force_flag_for_the_person():
    text = _read("skills", "sandboxes", "SKILL.md")
    assert "sk-ant" not in text and not re.search(r"ghp_[A-Za-z0-9]", text)
    assert "sbx rm -f" not in text, "the skill speaks of oto sandbox rm; the flag is the engine's"
