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
