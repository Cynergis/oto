"""The packs skill: a sandbox starts with the engine plugin alone, and the packs a project needs are
chosen from the session Claude works in, from a checklist (the question tool with several answers) or
on advice from what the project is, then turned on for the project and recorded in its lock. The skill
runs where Claude runs, inside the sandbox over SSH or on a computer; the one step it cannot take is
`/reload-plugins`, which it asks the person for."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_skill_exists_as_a_plugin_skill_and_a_project_local_one():
    text = _read("skills", "packs", "SKILL.md")
    assert text.startswith("---\nname: packs\n")
    link = os.path.join(ROOT, ".claude", "skills", "packs")
    assert os.path.islink(link) and os.readlink(link) == os.path.join("..", "..", "skills", "packs")
    assert "| [packs](packs/SKILL.md) |" in _read("skills", "README.md")
    assert "/oto:packs" in _read("skills", "concierge", "SKILL.md"), "the concierge hands off to it"


def test_the_skill_shows_a_checklist_and_gives_advice_then_turns_packs_on_for_the_project():
    text = _read("skills", "packs", "SKILL.md")
    head = text.split("---")[1]
    assert "checklist" in head and "advice" in head.lower() and "engine alone" in head, "both ways in, and why"
    assert "several answers" in text and "checkboxes" in text, "the question tool, with several answers: a select list with checkboxes"
    assert "four options per" in text and "four questions per" in text, "the tool's limits shape the groups"
    assert ".claude/plugins/marketplaces/cynergis/.claude-plugin/marketplace.json" in text and "oto pack list" in text and "claude plugin list" in text
    assert "pattern of" in text and "binding" in text and "playbook" in text and "product type" in text, "what kind each pack is, from the registry"
    for pack in ("ddd", "agent", "medallion", "platform", "calm", "oto-factory", "product", "work", "product-report", "report",
                 "report-medallion", "pdf-to-template", "organization-process", "professional-services", "auto-claims", "flow"):
        assert pack in text, "the advice table knows %s" % pack
    assert "claude plugin install <name>@cynergis --scope project" in text and "oto lock --use" in text
    assert "/reload-plugins" in text and "cannot do" in text, "the one step left is the person's"
    assert "oto@cynergis-engine" in text and "claude plugin marketplace add Cynergis/oto" in text, "the engine from its own marketplace when it is missing"
    assert "## Talking with the person" in text and "Nothing is turned on or off without their yes" in text


def test_a_new_sandbox_starts_with_the_engine_alone_and_points_at_the_skill():
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    assert 'claude plugin install "oto@cynergis-engine"' in init
    assert "for p in" not in init and "@cynergis\"" not in init.replace('oto@cynergis-engine"', ""), "no pack is installed by default"
    assert "Cynergis/oto-registry" in init, "the registry is added, so the packs can be chosen"
    assert "/oto:packs" in init
    readme = _read("kits", "README.md")
    assert "engine\n  alone" in readme or "engine alone" in readme.replace("\n  ", " ")
    assert "/oto:packs" in readme and "none of its packs is installed" in readme
    note = _read("kits", "oto-gcp", "files", "home", ".claude", "CLAUDE.md")
    assert "/oto:packs" in note and "engine alone" in note and "/reload-plugins" in note
    sandbox = _read("skills", "sandbox", "SKILL.md")
    assert "/oto:packs" in sandbox and "engine plugin alone" in sandbox


def test_the_skill_names_no_secret_and_no_force():
    text = _read("skills", "packs", "SKILL.md")
    assert "sk-ant" not in text and "--force" not in text and not re.search(r"ghp_[A-Za-z0-9]", text)
