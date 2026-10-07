// Exercises the reader's pure functions under Node over a payload file, and prints what the
// Python test asserts on. Usage: node reader_checks.js <reader.js> <payload.json>
"use strict";
const fs = require("fs");
const reader = require(process.argv[2]);
const payload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const ix = reader.index(payload);
const out = {classes: ix.classes, routes: {}, pages: {}, search: {}};

for (const h of ["#/", "#/type/System", "#/entity/system.payments", "#/doc/handbook", "#/doc/notes/ledger", "#/search?q=settled+ledger", "#/findings", "#/changes", "#/docs", "#/nope"]) {
  const r = reader.parseRoute(h);
  out.routes[h] = r;
  out.pages[h] = reader.renderPage(ix, r);
}
out.pages["#/entity/missing.id"] = reader.renderPage(ix, reader.parseRoute("#/entity/missing.id"));
out.side = reader.sideNav(ix, reader.parseRoute("#/type/System"));
const s = reader.search(ix, "ledger");
out.search.ledger = {entities: s.entities.map(e => e.node.id), passages: s.passages.map(p => p.passage.path)};
out.search.empty = reader.search(ix, "   ");
out.search.nothing = reader.search(ix, "zzzzqqq");
out.passage = reader.passageFor(ix, "notes/ledger") ? reader.passageFor(ix, "notes/ledger").title : null;
process.stdout.write(JSON.stringify(out));
