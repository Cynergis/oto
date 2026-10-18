"""The oto-gcp kit's lock-plugins: in a sandbox made from the kit only the plugins installed inside it
load. It merges into the sandbox's ~/.claude/settings.json the switches that keep out what Claude
Desktop brings from the person's computer (<name>@inline) and what their claude.ai account brings,
leaves every other key as it is, and changes nothing the second time. The engine's read-only check
(`oto sandbox status`) reads the same file the same way."""
import json
import os
import subprocess
import sys

import pytest

from oto import sandbox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "kits", "oto-gcp", "files", "home", ".oto", "lock-plugins")
HOOK = 'python3 "$HOME/.oto/lock-plugins" --hook'
SWITCHES = {"syncClaudeAiPlugins": False, "syncClaudeAiSkills": False, "disableClaudeAiConnectors": True}


def _env(home, **extra):
    env = {k: v for k, v in os.environ.items() if k != "OTO_OUTSIDE_PLUGINS"}
    env.update(HOME=str(home), USERPROFILE=str(home), **extra)
    return env


def run(home, *args, **env):
    return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, env=_env(home, **env))


def forward(home, folder, name=None, run_id="7171bda2", manifest=None):
    """A plugin Claude Desktop has copied into the sandbox for a session."""
    path = home / ".claude" / "remote" / "plugins" / run_id / folder
    (path / "skills").mkdir(parents=True)
    if name or manifest is not None:
        (path / ".claude-plugin").mkdir()
        (path / ".claude-plugin" / "plugin.json").write_text(manifest if manifest is not None else json.dumps({"name": name}))
    return path


def settings_file(home):
    return home / ".claude" / "settings.json"


def write_settings(home, data, indent=2):
    settings_file(home).parent.mkdir(parents=True, exist_ok=True)
    settings_file(home).write_text(json.dumps(data, indent=indent) + "\n")


def read_settings(home):
    return json.loads(settings_file(home).read_text())


def check(home, **env):
    """The engine's read-only check, as `oto sandbox status` runs it inside the sandbox."""
    done = subprocess.run([sys.executable, "-c", sandbox.LOCK_CHECK], capture_output=True, text=True, env=_env(home, **env))
    return json.loads(done.stdout)


def test_it_switches_off_what_comes_from_outside_and_keeps_every_other_key(tmp_path):
    original = {"permissions": {"allow": ["Bash(git:*)"]}, "themeId": "dark", "alwaysThinkingEnabled": True,
                "enabledPlugins": {"oto@cynergis": True, "report@cynergis": True},
                "extraKnownMarketplaces": {"cynergis": {"source": {"source": "github", "repo": "Cynergis/oto-registry"}}},
                "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hello"}]}],
                          "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]}}
    write_settings(tmp_path, original)
    forward(tmp_path, "b363e6967f456c2f", "engineering")
    forward(tmp_path, "91e5a4bc87be3566", "productivity", run_id="another-run")
    done = run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    after = read_settings(tmp_path)
    for key in ("permissions", "themeId", "alwaysThinkingEnabled", "extraKnownMarketplaces"):
        assert after[key] == original[key]
    assert after["enabledPlugins"] == {"oto@cynergis": True, "report@cynergis": True,
                                       "engineering@inline": False, "productivity@inline": False}
    assert {k: after[k] for k in SWITCHES} == SWITCHES
    assert after["hooks"]["PostToolUse"] == original["hooks"]["PostToolUse"]
    assert after["hooks"]["SessionStart"] == original["hooks"]["SessionStart"] + [{"hooks": [{"type": "command", "command": HOOK}]}]
    assert "2 plugins from your computer (engineering, productivity)" in done.stdout
    assert "the skills of your claude.ai account" in done.stdout and "added the check" in done.stdout


def test_a_second_run_changes_nothing(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    forward(tmp_path, "aaa", "engineering")
    run(tmp_path)
    text = settings_file(tmp_path).read_text()
    again = run(tmp_path)
    assert again.returncode == 0 and again.stdout == ""
    assert settings_file(tmp_path).read_text() == text
    hook = run(tmp_path, "--hook")
    assert hook.returncode == 0 and hook.stdout == ""
    assert settings_file(tmp_path).read_text() == text


def test_a_plugin_without_a_manifest_goes_by_its_folder(tmp_path):
    forward(tmp_path, "a1b2c3d4")
    forward(tmp_path, "e5f6", manifest="{ not json")
    forward(tmp_path, "g7h8", manifest=json.dumps({"version": "1.0.0"}))
    run(tmp_path)
    enabled = read_settings(tmp_path)["enabledPlugins"]
    assert enabled == {"a1b2c3d4@inline": False, "e5f6@inline": False, "g7h8@inline": False}


def test_a_forwarded_plugin_named_like_a_sandbox_plugin_leaves_the_sandbox_copy_on(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    forward(tmp_path, "c0ffee", "oto")
    run(tmp_path)
    enabled = read_settings(tmp_path)["enabledPlugins"]
    assert enabled["oto@inline"] is False and enabled["oto@cynergis"] is True


def test_switches_set_by_hand_and_their_backup_are_kept(tmp_path):
    by_hand = {"enabledPlugins": {"oto@cynergis": True, "engineering@inline": False, "bmad@inline": False},
               "syncClaudeAiPlugins": False, "disableClaudeAiConnectors": True}
    write_settings(tmp_path, by_hand)
    backup = settings_file(tmp_path).parent / "settings.json.before-plugin-switches"
    backup.write_text('{"enabledPlugins": {"oto@cynergis": true}}\n')
    before = settings_file(tmp_path).read_text()
    forward(tmp_path, "aaa", "engineering")
    forward(tmp_path, "bbb", "bmad")
    done = run(tmp_path)
    assert backup.read_text() == '{"enabledPlugins": {"oto@cynergis": true}}\n'
    assert (settings_file(tmp_path).parent / "settings.json.before-oto-plugin-lock").read_text() == before
    after = read_settings(tmp_path)
    assert after["enabledPlugins"] == by_hand["enabledPlugins"] and after["syncClaudeAiSkills"] is False
    assert done.stdout.splitlines()[0] == "plugin lock: switched off the skills of your claude.ai account"
    run(tmp_path)
    assert (settings_file(tmp_path).parent / "settings.json.before-oto-plugin-lock").read_text() == before, "one backup, the first"


def test_a_forwarded_plugin_switched_on_by_hand_is_switched_off(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"bmad@inline": True}})
    forward(tmp_path, "bbb", "bmad")
    done = run(tmp_path)
    assert read_settings(tmp_path)["enabledPlugins"]["bmad@inline"] is False
    assert "the plugin bmad from your computer" in done.stdout


def test_the_hook_tells_the_person_once_about_a_new_plugin(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    run(tmp_path)                                   # the sandbox starts, before any Desktop session
    forward(tmp_path, "aaa", "engineering")         # Desktop's first session brings a plugin
    first = run(tmp_path, "--hook")
    assert first.returncode == 0
    message = json.loads(first.stdout)["systemMessage"]
    assert message == ("The plugin engineering from your computer was just switched off in this sandbox, but it is "
                       "still loaded in this session: start a new session, or type /reload-plugins, to work without it.")
    assert run(tmp_path, "--hook").stdout == "", "the next session starts without it, and says nothing"
    forward(tmp_path, "bbb", "bmad")
    forward(tmp_path, "ccc", "productivity")
    assert "2 plugins from your computer (bmad, productivity) were just switched off" in json.loads(run(tmp_path, "--hook").stdout)["systemMessage"]


def test_without_a_settings_file_it_writes_one(tmp_path):
    forward(tmp_path, "aaa", "engineering")
    assert run(tmp_path).returncode == 0
    after = read_settings(tmp_path)
    assert after["enabledPlugins"] == {"engineering@inline": False} and {k: after[k] for k in SWITCHES} == SWITCHES
    assert not (settings_file(tmp_path).parent / "settings.json.before-oto-plugin-lock").exists(), "nothing to back up"


@pytest.mark.parametrize("text", ["{ not json", "[1, 2]", '{"enabledPlugins": ["oto@cynergis"]}', '{"hooks": {"SessionStart": {}}}'])
def test_settings_it_cannot_read_are_left_as_they_are(tmp_path, text):
    settings_file(tmp_path).parent.mkdir(parents=True)
    settings_file(tmp_path).write_text(text)
    forward(tmp_path, "aaa", "engineering")
    done = run(tmp_path)
    assert done.returncode == 1 and "left as it is" in done.stdout
    assert settings_file(tmp_path).read_text() == text
    hook = run(tmp_path, "--hook")
    assert hook.returncode == 0 and hook.stdout == "", "a session always starts"


def test_allowed_changes_nothing(tmp_path):
    forward(tmp_path, "aaa", "engineering")
    done = run(tmp_path, OTO_OUTSIDE_PLUGINS="allowed")
    assert done.returncode == 0 and "off, by choice" in done.stdout
    assert not settings_file(tmp_path).exists()
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    text = settings_file(tmp_path).read_text()
    run(tmp_path, OTO_OUTSIDE_PLUGINS="allowed")
    assert run(tmp_path, "--hook", OTO_OUTSIDE_PLUGINS="allowed").stdout == ""
    assert settings_file(tmp_path).read_text() == text


def test_the_file_keeps_its_indentation(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}}, indent=4)
    run(tmp_path)
    assert settings_file(tmp_path).read_text().startswith('{\n    "enabledPlugins": {\n        "oto@cynergis": true\n    },\n    "syncClaudeAiPlugins"')


def test_names_given_before_desktop_copies_them_in_are_switched_off(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    forward(tmp_path, "aaa", "engineering")
    done = run(tmp_path, "--names", "bmad", "engineering", "anthropic-skills")
    assert "3 plugins from your computer (engineering, bmad, anthropic-skills)" in done.stdout
    enabled = read_settings(tmp_path)["enabledPlugins"]
    assert enabled == {"oto@cynergis": True, "engineering@inline": False, "bmad@inline": False, "anthropic-skills@inline": False}
    text = settings_file(tmp_path).read_text()
    forward(tmp_path, "bbb", "bmad")                 # Desktop's first session brings it: nothing new to say
    assert run(tmp_path, "--hook").stdout == "" and settings_file(tmp_path).read_text() == text
    assert run(tmp_path, "--names", "bmad").stdout == ""


def test_the_engines_check_reads_what_the_script_writes(tmp_path):
    write_settings(tmp_path, {"enabledPlugins": {"oto@cynergis": True}})
    forward(tmp_path, "aaa", "engineering")
    forward(tmp_path, "bbb")
    before = check(tmp_path)
    assert before["mode"] == "blocked" and not before["locked"] and not before["hook"]
    assert before["loading"] == ["engineering", "bbb"]
    run(tmp_path)
    after = check(tmp_path)
    assert after["locked"] and after["hook"] and after["loading"] == [] and after["forwarded"] == ["engineering", "bbb"]
    assert after["switched_off"] == ["bbb", "engineering"]
    assert "blocked: only the sandbox's own plugins load (2 from your computer switched off)" == sandbox.describe_lock(after)
    assert sandbox.describe_lock(before).startswith("NOT blocked: engineering, bbb, your claude.ai plugins")
    assert check(tmp_path, OTO_OUTSIDE_PLUGINS="allowed")["mode"] == "allowed"
