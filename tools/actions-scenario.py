#!/usr/bin/env python3
"""A sandbox for the actions feature: a project with an intended repository, and a stand-in for
GitHub and for an interface, so the whole loop runs on one machine with no token.

    python tools/actions-scenario.py setup <dir> [--owner <github owner>] [--port 8799]
    python tools/actions-scenario.py serve [--port 8799]

`setup` initialises a software-architecture project at <dir> (the ontology ships three
actions), writes the plan as a note in the inbox and ingests it, then takes one proposal citing
it through the curate gates: a Repository the payment API is
`implemented_by`, status `intended`, that does not exist yet, and a second Interface whose URL
points at the stand-in server. `serve` answers like GitHub's repositories API (404 until the
repository is created with a POST, then the repository) and like an interface (`/payments/v2`).
The walkthrough is docs/scenarios/actions.md. Standard library only; the engine is imported, so
run it from the checkout (`.venv/bin/python tools/actions-scenario.py ...`) or with `oto`
installed from the `actions` branch.
"""
import argparse
import datetime
import json
import os
import sys

REPO_NAME = "oto-actions-demo"


def setup(directory, owner, port):
    from oto.cli import main
    directory = os.path.abspath(directory)
    if os.path.exists(os.path.join(directory, "project.config.json")):
        print("a project already exists at %s; choose an empty directory" % directory)
        return 1
    if main(["init", "--name", "Actions Demo", "--slug", "demo", "--ontology", "software-architecture", "--project", directory]) != 0:
        return 1
    today = datetime.date.today().isoformat()
    # the plan is a source document like any other: a note in the inbox, ingested, cited
    note = os.path.join(directory, "inbox", "%s-the-plan.md" % today)
    with open(note, "w", encoding="utf-8") as f:
        f.write("# The plan for the next payment API\n\n> **Captured:** %s · **By:** the platform team · **Recorded by:** the actions scenario\n>\n"
                "> A planning note, the source the scenario's facts cite.\n\n## Statements\n\n"
                "1. \"The next payment API will live in the repository %s/%s. It does not exist yet.\" — the platform team, %s\n"
                "2. \"The payment API exposes a health endpoint at /payments/v2 on the demo host.\" — the platform team, %s\n"
                % (today, owner, REPO_NAME, today, today))
    if main(["ingest", "--project", directory]) != 0:
        return 1
    doc = "%s-the-plan" % today
    proposal = {
        "source_doc": doc,
        "as_of": today,
        "note": "the actions scenario: a repository that is planned and an interface the stand-in server answers for",
        "nodes": [
            {"id": "repo.%s" % REPO_NAME, "type": "Repository", "label": "%s/%s" % (owner, REPO_NAME), "aliases": ["the demo repo"],
             "summary": "Where the payment API's next version will live. Planned; it does not exist yet.",
             "attributes": {"owner": owner, "name": REPO_NAME}, "tags": ["repository"], "status": "intended",
             "as_of": today, "valid_from": today, "source_doc": doc, "sources": [doc],
             "evidence": [{"doc": doc, "where": "statement 1", "quote": "The next payment API will live in the repository %s/%s. It does not exist yet." % (owner, REPO_NAME)}]},
            {"id": "interface.demo-health", "type": "Interface", "label": "Demo health endpoint", "aliases": [],
             "summary": "A health endpoint the scenario's stand-in server answers for.",
             "attributes": {"url": "http://127.0.0.1:%d/payments/v2" % port}, "tags": ["interface"], "status": "current",
             "as_of": today, "valid_from": today, "source_doc": doc, "sources": [doc],
             "evidence": [{"doc": doc, "where": "statement 2", "quote": "The payment API exposes a health endpoint at /payments/v2 on the demo host."}]},
        ],
        "edges": [
            {"from": "component.payment-api", "rel": "implemented_by", "to": "repo.%s" % REPO_NAME},
            {"from": "component.payment-api", "rel": "exposes", "to": "interface.demo-health"},
        ],
    }
    os.makedirs(os.path.join(directory, "proposals"), exist_ok=True)
    path = os.path.join(directory, "proposals", "scenario.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2)
    for args in (["curate", "start"], ["curate", "add", "--from", path], ["curate", "check"],
                 ["curate", "apply", "--by", "the scenario", "--note", "an intended repository and a demo interface, for the actions walkthrough"],
                 ["build"], ["ingest", "complete"]):
        if main(args + ["--project", directory]) != 0:
            print("scenario: `oto %s` failed; read the output above" % " ".join(args))
            return 1
    print("\nscenario ready at %s" % directory)
    print("  the repository %s/%s is INTENDED; the demo interface points at http://127.0.0.1:%d" % (owner, REPO_NAME, port))
    print("  next: python tools/actions-scenario.py serve --port %d   (in another terminal), then docs/scenarios/actions.md" % port)
    return 0


def serve(port):
    import http.server

    repositories = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, status, payload):
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = self.path.split("?")[0].strip("/").split("/")
            if parts[:1] == ["repos"] and len(parts) == 3:
                key = "%s/%s" % (parts[1], parts[2])
                if key in repositories:
                    return self._json(200, repositories[key])
                return self._json(404, {"message": "Not Found", "documentation_url": "https://docs.github.com/rest/repos/repos#get-a-repository", "status": "404"})
            if parts[:1] == ["payments"]:
                return self._json(200, {"service": "payments", "version": parts[1] if len(parts) > 1 else "v2", "status": "ok",
                                        "endpoints": ["/payments/v2/charges", "/payments/v2/refunds"],
                                        "checked_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()})
            return self._json(404, {"message": "Not Found"})

        def do_POST(self):
            parts = self.path.strip("/").split("/")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"message": "Problems parsing JSON"})
            if parts == ["user", "repos"] or (parts[:1] == ["orgs"] and parts[2:3] == ["repos"]):
                owner = parts[1] if parts[0] == "orgs" else (body.get("owner") or "me")
                name = body.get("name")
                if not name:
                    return self._json(422, {"message": "name is required"})
                key = "%s/%s" % (owner, name)
                repositories[key] = {"id": 1000 + len(repositories), "name": name, "full_name": key,
                                     "html_url": "https://github.com/%s" % key, "default_branch": "main",
                                     "private": bool(body.get("private")), "description": body.get("description") or "",
                                     "owner": {"login": owner}, "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()}
                return self._json(201, repositories[key])
            return self._json(404, {"message": "Not Found"})

        def log_message(self, fmt, *args):
            sys.stderr.write("stand-in: %s\n" % (fmt % args))

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print("the stand-in for GitHub and the interface is on http://127.0.0.1:%d" % port)
    print("  GET  /repos/<owner>/<name>      404 until the repository is created")
    print("  POST /orgs/<owner>/repos        creates it: {\"name\": ..., \"private\": true}")
    print("  GET  /payments/v2               what the demo interface answers")
    print("Ctrl-C stops it. Nothing is written anywhere.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="the actions scenario: a sandbox project and a stand-in server")
    sub = parser.add_subparsers(dest="command")
    s = sub.add_parser("setup", help="initialise the sandbox project")
    s.add_argument("directory")
    s.add_argument("--owner", default="acme", help="the GitHub owner the intended repository names (default acme)")
    s.add_argument("--port", type=int, default=8799)
    v = sub.add_parser("serve", help="run the stand-in server")
    v.add_argument("--port", type=int, default=8799)
    args = parser.parse_args(argv)
    if args.command == "setup":
        return setup(args.directory, args.owner, args.port)
    if args.command == "serve":
        return serve(args.port)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
