"""The sandbox kits carry the engine they are published with. The release workflow publishes
kits/oto-gcp as ghcr.io/cynergis/oto-gcp:<version> when it tags v<version>, so every place the kit
names the engine must name this one: a version bump that forgets the kit fails here, not in a tester's
sandbox."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "kits", "oto-gcp")


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def _version():
    return re.search(r'^version = "([^"]+)"', _read("pyproject.toml"), re.M).group(1)


def test_the_oto_gcp_kit_carries_this_engine():
    version = _version()
    spec = _read("kits", "oto-gcp", "spec.yaml")
    assert re.search(r'^version: "%s"$' % re.escape(version), spec, re.M), \
        "kits/oto-gcp/spec.yaml: `version` must be the engine's, %s" % version
    assert 'OTO_SOURCE: "oto-kg @ git+https://github.com/Cynergis/oto@v%s"' % version in spec, \
        "kits/oto-gcp/spec.yaml: OTO_SOURCE must pin v%s" % version
    assert "the OTO engine %s," % version in spec, "kits/oto-gcp/spec.yaml: the description names the engine %s" % version
    assert re.search(r"^    OTO_SANDBOX: kit$", spec, re.M), "the kit tells the engine it runs inside a sandbox: oto serve binds all interfaces, no token"
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    assert '"oto-kg[intake] @ git+https://github.com/Cynergis/oto@v%s"' % version in init, \
        "kits/oto-gcp/files/home/.oto/init.sh installs v%s" % version
    assert "ghcr.io/cynergis/oto-gcp:%s " % version in _read("kits", "README.md"), "kits/README.md runs the kit at %s" % version


def test_the_release_workflow_publishes_the_kit_after_the_tag():
    release = _read(".github", "workflows", "tag-release.yml")
    publish = _read(".github", "workflows", "kit-publish.yml")
    assert "uses: ./.github/workflows/kit-publish.yml" in release and "needs.tag.outputs.created == 'true'" in release
    assert "packages: write" in release and "id-token: write" in release, "the calling job grants what the push and the signature need"
    assert 'sbx kit push kits/oto-gcp "ghcr.io/cynergis/oto-gcp:$VERSION" --sign' in publish
    assert "sbx login --username" in publish and "--password-stdin" in publish


def test_the_kit_keeps_the_sandbox_to_its_own_plugins():
    """kits/oto-gcp/files/home/.oto/lock-plugins runs at every start, blocked unless the person allowed
    outside plugins; the engine reads the same switch and the same hook (tests/test_plugin_lock.py)."""
    from oto import sandbox
    spec = _read("kits", "oto-gcp", "spec.yaml")
    assert re.search(r"^    %s: blocked$" % sandbox.OUTSIDE, spec, re.M), "the kit blocks outside plugins by default"
    assert 'python3 "$HOME/.oto/lock-plugins"' in _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh"), \
        "init.sh runs the lock at every start, through python3: kit files carry no exec bit"
    script = _read("kits", "oto-gcp", "files", "home", ".oto", "lock-plugins")
    assert sandbox.OUTSIDE in script and '"allowed"' in script and ".oto/lock-plugins" in sandbox.LOCK_CHECK
    assert "disableSideloadFlags" not in script, "the managed setting would refuse Desktop's --plugin-dir launch"


def test_the_kit_tells_its_claude_which_plugin_list_is_the_sandboxs():
    """Claude Desktop's ListPlugins and ListSkills tools describe the person's claude.ai account, where
    everything they ever added is enabled, not what loads in the sandbox. Asked "which plugins are on?",
    the sandbox's Claude answered from them. The kit's user memory says which list is the sandbox's."""
    note = _read("kits", "oto-gcp", "files", "home", ".claude", "CLAUDE.md")
    assert "ListPlugins" in note and "ListSkills" in note, "names the two account tools"
    assert "claude.ai account" in note and "claude plugin list" in note, "says what they describe, and what to read instead"
    assert "@cynergis" in note and "oto sandbox status" in note, "the sandbox's plugins, and the status that confirms the lock"
    readme = _read("kits", "README.md")
    assert "files/home/.claude/CLAUDE.md" in readme and "ListPlugins" in readme
