# -*- coding: utf-8 -*-
"""Git as a transport, through the `git` on the PATH.

The engine, the query repository and the ontology registry all move through git repositories:
no library, no second protocol, and the same credential model everywhere. A token comes from the
environment and is put into an https URL for the length of one call; it is never written to disk
or printed, and a path or ssh URL is left alone. A call that reaches a remote sends no header the
configuration it runs under would add, so the token in the URL is the credential that arrives.
"""
import os
import subprocess

from .project import ProjectError


def run(args, cwd=None, env=None, remote=None):
    """Run one git command; raise ProjectError naming the subcommand and git's last words. `remote` is
    the URL the command reaches, when it reaches one: the headers the configuration would add for it
    are dropped (`no_inherited_headers`)."""
    full = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if env:
        full.update(env)
    options = no_inherited_headers(remote) if remote else []
    result = subprocess.run(["git"] + options + list(args), cwd=cwd, env=full, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProjectError("git %s failed: %s" % (args[0], (result.stderr or result.stdout).strip()[-400:]))
    return result.stdout


def with_token(url, token):
    """The clone URL with the token in it, for https remotes only; a path or ssh URL is unchanged."""
    if token and url.startswith("https://") and "@" not in url.split("//", 1)[1].split("/", 1)[0]:
        return "https://x-access-token:%s@%s" % (token, url[len("https://"):])
    return url


def no_inherited_headers(url):
    """The `-c` option that empties `http.extraheader` for `url`, so a call sends the token in its URL
    (or what the credential helper gives), never a header it inherited. actions/checkout keeps the
    job's GITHUB_TOKEN in the workspace's git config as `http.https://github.com/.extraheader`: a call
    run from that workspace sends it in place of the token in the URL, and a private repository the
    job's token cannot see answers "Repository not found". git applies the most specific URL match, so
    an unscoped `-c http.extraheader=` loses to that setting; the reset is scoped to `url` itself,
    without its credentials. A path or ssh URL sends no headers and gets no option."""
    if not url.startswith(("https://", "http://")):
        return []
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    return ["-c", "http.%s://%s/%s.extraheader=" % (scheme, host.rsplit("@", 1)[-1], path)]


def clone(url, dest, ref=None, token=None, depth=1):
    """A shallow clone at `ref` (a branch or tag; the default branch when None)."""
    args = ["clone", "--quiet"]
    if depth:
        args += ["--depth", str(depth)]
    if ref:
        args += ["--branch", ref]
    run(args + [with_token(url, token), dest], remote=url)
    return dest


def head(directory):
    """The short commit id the checkout is at."""
    return run(["rev-parse", "--short", "HEAD"], cwd=directory).strip()


def has_ref(url, ref, token=None):
    """True when the remote has a branch or tag by that name."""
    out = run(["ls-remote", with_token(url, token), ref, "refs/tags/%s" % ref, "refs/heads/%s" % ref], remote=url)
    return bool(out.strip())
