"""The sandbox kits carry the engine they are published with. The release workflow publishes
kits/oto-gcp as ghcr.io/cynergis/oto-gcp:<version> when it tags v<version>, so every place the kit
names the engine must name this one: a version bump that forgets the kit fails here, not in a tester's
sandbox.

Since sbx 0.51, `claude` names Docker's published Claude Code kit, a schema-3 kit, and a v2 kit can no
longer extend it. The kit is a schema-3 kit set on that kit. A set ships no files of its own, so its
descriptor carries them: tools/kit_files.py copies kits/oto-gcp/files into it, and CI builds the kit
with Docker's own frontend, which checks the descriptor strictly."""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "kits", "oto-gcp")
DESCRIPTOR = ("kits", "oto-gcp", "oto-gcp.yaml")
LIFECYCLE = "com.docker.sandbox/lifecycle@1"
NETWORK = "com.docker.sandbox/network-policy@1"


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def _version():
    return re.search(r'^version = "([^"]+)"', _read("pyproject.toml"), re.M).group(1)


def _descriptor():
    yaml = pytest.importorskip("yaml", reason="PyYAML reads the descriptor here; CI builds it with Docker's frontend")
    return yaml.safe_load(_read(*DESCRIPTOR))


def _capabilities(descriptor, kind):
    return [c for c in descriptor.get("capabilities") or [] if c.get("type") == kind]


def test_the_kit_is_a_schema_3_set_on_dockers_claude_kit():
    text = _read(*DESCRIPTOR)
    assert text.startswith("# syntax=docker/sandbox-kit:3\n"), "the first line hands the build to Docker's kit frontend"
    assert re.search(r'^schemaVersion: "3"$', text, re.M) and re.search(r"^kind: set$", text, re.M)
    assert re.search(r"^  - ref: docker\.io/sbx/claude:latest$", text, re.M), \
        "Docker's Claude Code kit, what `claude` names since sbx 0.51; publishing pins the digest it had"
    assert "extends:" not in text, "v2 and v3 kits do not combine"
    assert not os.path.exists(os.path.join(KIT, "spec.yaml")), "the v2 descriptor is gone: it cannot extend a v3 kit"


def test_the_oto_gcp_kit_carries_this_engine():
    version = _version()
    text = _read(*DESCRIPTOR)
    assert re.search(r'^version: "%s"$' % re.escape(version), text, re.M), \
        "kits/oto-gcp/oto-gcp.yaml: `version` must be the engine's, %s" % version
    assert "OTO_SOURCE" not in text, "the engine init.sh installs is the one the plugin runs (ADR-0014)"
    assert "the OTO engine %s," % version in text, "kits/oto-gcp/oto-gcp.yaml: the description names the engine %s" % version
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    assert '"oto-kg[intake,neo4j] @ git+https://github.com/Cynergis/oto@v%s"' % version in init, \
        "kits/oto-gcp/files/home/.oto/init.sh installs v%s, with the driver a sandbox reads a graph live through" % version
    assert "ghcr.io/cynergis/oto-gcp:%s " % version in _read("kits", "README.md"), "kits/README.md runs the kit at %s" % version


def test_the_descriptor_carries_the_kits_files_as_they_are():
    """The start script, the plugin lock and the note for the sandbox's Claude are edited as files;
    tools/kit_files.py copies them into the descriptor, and a stale copy fails here."""
    done = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "kit_files.py"), "--check"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_kit_declares_what_the_v2_kit_did():
    """The environment, the network, the install at creation and the start: the v2 kit's, in v3's terms."""
    from oto import sandbox
    d = _descriptor()
    args = d["args"]
    assert args["outsidePlugins"] == {"default": "blocked", "enum": ["blocked", "allowed"], "env": sandbox.OUTSIDE,
                                      "description": args["outsidePlugins"]["description"]}, "outside plugins blocked by default"
    assert sorted(args) == ["outsidePlugins", "sandbox"], "no OTO_SOURCE: the installed engine is the one (ADR-0014)"
    assert args["sandbox"]["env"] == sandbox.INSIDE_ENV and args["sandbox"]["enum"] == ["kit"], \
        "the kit tells the engine it runs inside a sandbox: oto serve binds all interfaces, no token"
    network = _capabilities(d, NETWORK)
    assert len(network) == 1
    runtime = set(network[0]["config"]["runtime"]["allow"])
    assert {"github.com", "*.github.com", "*.githubusercontent.com", "pypi.org", "files.pythonhosted.org", "dl.google.com",
            "*.googleapis.com", "cdn.playwright.dev", "playwright.download.prss.microsoft.com"} <= runtime
    install = set(network[0]["config"]["install"]["allow"])
    assert {"deb.debian.org", "dl.google.com", "pypi.org", "files.pythonhosted.org"} <= install, \
        "the install phase reaches what the install hooks download, and closes before the agent starts"
    lifecycle = _capabilities(d, LIFECYCLE)
    assert len(lifecycle) == 1, "a singleton: its hooks concatenate with the Claude kit's"
    hooks = lifecycle[0]["config"]
    installs = "\n".join(h["command"] for h in hooks["install"])
    assert all(h["user"] == "0" for h in hooks["install"]), "system packages are installed as root, once, at creation"
    assert "libreoffice-writer-nogui" in installs and "google-cloud-cli-linux" in installs and "install-deps chromium" in installs
    assert "chown agent:agent /home/agent/.oto" in installs, "the folder the lifecycle files land in is the agent's"
    start, = hooks["startup"]
    assert start["command"] == ["sh", "/home/agent/.oto/init.sh"] and start["user"] == "agent"
    assert start["env"] == [sandbox.OUTSIDE], "a hook sees only the variables it names: the plugin lock reads the switch"
    assert {f["path"] for f in hooks["files"]} == {"/home/agent/.oto/init.sh", "/home/agent/.oto/lock-plugins"}
    assert not _capabilities(d, "com.docker.sandbox/credential@1"), "the Claude kit's own credential carries the sign-in"


def test_the_install_hooks_leave_the_agents_home_to_the_agent():
    """The hooks run as root with the image's HOME, /home/agent: gcloud's installer left a root-owned
    ~/.config there, and gcloud then could not write its logs. Each hook runs with root's own home."""
    hooks = _capabilities(_descriptor(), LIFECYCLE)[0]["config"]["install"]
    assert all(h["command"].startswith("export HOME=/root\n") for h in hooks), [h["description"] for h in hooks]


def test_the_kit_brings_a_uv_that_runs_on_the_sandboxs_kernel():
    """The Claude kit's image packages a uv that aborts where the kernel's pages are 16 KB, as in a
    sandbox on a Mac with Apple silicon (`jemalloc: Unsupported system page size`): nothing it runs,
    the engine and the plugin's server among them, starts. When it cannot run, the kit installs
    Astral's own build ahead of it on the PATH, before the hook that uses it."""
    hooks = _capabilities(_descriptor(), LIFECYCLE)[0]["config"]["install"]
    uv = next(h["command"] for h in hooks if "astral-sh/uv" in h["command"])
    assert "uv --version >/dev/null 2>&1" in uv and "uvx --version >/dev/null 2>&1" in uv, "only when the image's cannot run"
    assert 'https://github.com/astral-sh/uv/releases/latest/download/uv-$target.tar.gz' in uv and "unknown-linux-musl" in uv
    assert '"/tmp/uv-$target/uv" "/tmp/uv-$target/uvx" /usr/local/bin/' in uv, "/usr/local/bin is ahead of /usr/bin on the image's PATH"
    assert uv.index("astral-sh/uv") < uv.index("playwright install-deps"), "installed before it is used"
    assert 'export PATH="/usr/local/bin:$PATH"' in uv, "a hook's PATH puts /usr/bin first: the image's uv was still the one run"
    assert uv.index("/usr/local/bin/\n") < uv.index("hash -r") < uv.index("playwright install-deps"), \
        "the shell remembers where it found uv the first time: forgotten once Astral's is in place"


def test_the_start_says_ready_only_when_the_engine_is_there():
    """The start printed `OTO ready` whatever happened, so a start whose engine did not install looked
    ready. It says `OTO failed` then, and `oto sandbox up` stops waiting on either."""
    from oto import sandbox
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    ready, failed = init.index('echo "%s:' % sandbox.READY), init.index('echo "%s:' % sandbox.FAILED)
    assert "if command -v oto >/dev/null; then" in init[:ready] and ready < failed


def test_the_note_for_the_sandboxs_claude_is_its_agent_context():
    """The v2 kit wrote ~/.claude/CLAUDE.md. The Claude kit now owns that file, as its agent context; the
    kit's note joins it as a body of its own, in both versions while sbx accepts both."""
    d = _descriptor()
    note = _read("kits", "oto-gcp", "files", "home", ".claude", "CLAUDE.md")
    contexts = [c for c in d["capabilities"] if c["type"].startswith("com.docker.sandbox/agent-context@")]
    assert sorted(c["type"] for c in contexts) == ["com.docker.sandbox/agent-context@1", "com.docker.sandbox/agent-context@2"]
    assert all(c["optional"] is True and c["config"] == {"content": note} for c in contexts), \
        "a body alone: the Claude kit chooses the file it lands in"


def test_the_release_workflow_publishes_the_kit_after_the_tag():
    release = _read(".github", "workflows", "tag-release.yml")
    publish = _read(".github", "workflows", "kit-publish.yml")
    assert "uses: ./.github/workflows/kit-publish.yml" in release and "needs.tag.outputs.created == 'true'" in release
    assert "packages: write" in release and "id-token: write" in release, "the calling job grants what the push and the signature need"
    assert 'grep -q "^version: \\"$VERSION\\"$" kits/oto-gcp/oto-gcp.yaml' in publish
    assert "docker buildx build kits/oto-gcp -f kits/oto-gcp/oto-gcp.yaml --platform linux/amd64,linux/arm64" in publish
    assert '-t "ghcr.io/cynergis/oto-gcp:$VERSION" --push' in publish
    assert 'sbx kit sign "ghcr.io/cynergis/oto-gcp:$VERSION"' in publish, "signed, as the v2 kit was"
    assert "sbx login --username" in publish and "--password-stdin" in publish
    assert "sbx kit push" not in publish, "sbx kit push is for v1 and v2 kits"


def test_ci_builds_the_kit_on_every_change():
    """Nothing here runs Docker's kit frontend; CI does, on every push, without publishing."""
    ci = _read(".github", "workflows", "ci.yml")
    job = re.search(r"^  kit:\n(.*?)(?=^  \S|\Z)", ci, re.M | re.S)
    assert job, "ci.yml has a kit job"
    assert "docker buildx build kits/oto-gcp -f kits/oto-gcp/oto-gcp.yaml --platform linux/amd64,linux/arm64" in job.group(1)
    assert "--push" not in job.group(1) and "python3 tools/kit_files.py --check" in job.group(1)


def test_the_kit_keeps_the_sandbox_to_its_own_plugins():
    """kits/oto-gcp/files/home/.oto/lock-plugins runs at every start, blocked unless the person allowed
    outside plugins; the engine reads the same switch and the same hook (tests/test_plugin_lock.py)."""
    from oto import sandbox
    text = _read(*DESCRIPTOR)
    assert re.search(r"^    default: blocked\n    enum: \[blocked, allowed\]\n", text, re.M), "the kit blocks outside plugins by default"
    assert "env: %s" % sandbox.OUTSIDE in text
    assert 'python3 "$HOME/.oto/lock-plugins"' in _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh"), \
        "init.sh runs the lock at every start, through python3: kit files carry no exec bit"
    script = _read("kits", "oto-gcp", "files", "home", ".oto", "lock-plugins")
    assert sandbox.OUTSIDE in script and '"allowed"' in script and ".oto/lock-plugins" in sandbox.LOCK_CHECK
    assert "disableSideloadFlags" not in script, "the managed setting would refuse Desktop's --plugin-dir launch"


def test_a_shell_in_the_sandbox_lands_on_the_project_folder():
    """ssh <name>.sbx and sbx run open a shell in the sandbox tool's default folder; the person's project
    is mounted elsewhere, at its own path. `oto sandbox up` passes that path in (OTO_PROJECT_DIR), and the
    kit's startup script writes a profile hook that moves an interactive shell there when it starts in
    the home folder or the tool's default; a shell started elsewhere on purpose is left alone."""
    from oto import sandbox
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    assert sandbox.PROJECT_DIR_ENV in init and "landing.sh" in init, "init.sh writes the hook from the variable up passes"
    assert ".bashrc" in init and ".profile" in init, "sourced by interactive and login shells alike"
    assert 'case "$-" in *i*)' in init, "interactive shells only"
    assert '"$HOME/workspace"' in init and '"$HOME"' in init, "only from the home folder or the tool's default landing"
    readme = _read("kits", "README.md")
    assert sandbox.PROJECT_DIR_ENV in readme and "lands" in readme
    skill = _read("skills", "sandbox", "SKILL.md")
    assert "lands in the project folder" in skill


def test_the_kit_tells_its_claude_which_plugin_list_is_the_sandboxs():
    """Claude Desktop's ListPlugins and ListSkills tools describe the person's claude.ai account, where
    everything they ever added is enabled, not what loads in the sandbox. Asked "which plugins are on?",
    the sandbox's Claude answered from them. The kit's note says which list is the sandbox's."""
    note = _read("kits", "oto-gcp", "files", "home", ".claude", "CLAUDE.md")
    assert "ListPlugins" in note and "ListSkills" in note, "names the two account tools"
    assert "claude.ai account" in note and "claude plugin list" in note, "says what they describe, and what to read instead"
    assert "@cynergis" in note and "oto sandbox status" in note, "the sandbox's plugins, and the status that confirms the lock"
    readme = _read("kits", "README.md")
    assert "files/home/.claude/CLAUDE.md" in readme and "ListPlugins" in readme and "agent context" in readme


def test_the_readme_says_which_sandbox_tool_the_kit_needs():
    from oto import sandbox
    readme = _read("kits", "README.md")
    assert "sbx %s" % sandbox.MIN_SBX in readme and "tools/kit_files.py" in readme
    assert "sbx kit push" not in readme and "sbx kit validate" not in readme, "the v2 commands are gone"


def test_the_end_to_end_guide_walks_the_kit_on_the_sandbox_tool_it_needs():
    from oto import sandbox
    guide = _read("docs", "E2E-TESTING.md")
    section = guide[guide.index("## 36. The sandbox kit"):]
    assert "33 to 42" in guide and "Docker Sandboxes %s or later" % sandbox.MIN_SBX[:-2] in guide
    assert "older than the kit needs (%s or later)" % sandbox.MIN_SBX in section and "--kit kits/oto-gcp" in section
    assert "/usr/share/sandbox/kit/" in section and "This is an OTO sandbox" in section and "oto sandbox rm oto-kit-try" in section
