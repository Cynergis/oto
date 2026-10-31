# -*- coding: utf-8 -*-
"""Facts a command generated, landed through the gates. A command that writes facts a person never
typed (a framework's model read by its adapter, the code map, the IAM bindings derived from the
policy) never writes the graph: it writes proposals and lands them the way a person does, through
`curate start`, `add`, `check` and `apply`, then builds. Refused at the gate, it aborts the candidate
and raises with the findings, and the graph is unchanged. The architecture and policy packs call this
(ADR-0011: it was the arch module's until the arch module became the architecture pack's code)."""
import contextlib
import io
import os

from ..project import ProjectError


class GateError(ProjectError):
    """A refusal at the gate, in words the person can act on; the graph is unchanged."""


def apply_proposals(project, proposals, by, note):
    """Open a candidate, add each proposal, check, apply with `by` and `note`, build. Raises GateError
    when any step refuses, after aborting the candidate."""
    from ..cli import main as _main
    root = project.data
    if not (by or "").strip():
        raise GateError("--by names who applies: the workflow, or a person")

    def run(*args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = _main(list(args) + ["--project", root])
        return code, out.getvalue()

    code, out = run("curate", "start")
    if code != 0:
        raise GateError("could not open a candidate:\n%s" % out.strip())
    try:
        for path in proposals:
            code, out = run("curate", "add", "--from", path)
            if code != 0:
                raise GateError("refused while adding %s:\n%s" % (os.path.relpath(path, root), out.strip()))
        code, out = run("curate", "check")
        if code != 0:
            findings = out.split("gap (")[0] if "blocking (" in out.split("gap (")[0] else out
            findings = findings[findings.index("blocking ("):] if "blocking (" in findings else findings
            raise GateError("refused at the gate; the graph is unchanged:\n%s" % findings.strip())
        code, out = run("curate", "apply", "--by", by.strip(), "--note", note.strip())
        if code != 0:
            raise GateError("could not apply:\n%s" % out.strip())
    except GateError:
        run("curate", "abort")
        raise
    code, out = run("build")
    if code != 0:
        raise GateError("applied, but the build failed:\n%s" % out.strip())
