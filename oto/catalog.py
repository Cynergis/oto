# -*- coding: utf-8 -*-
"""The catalog: a static site generated from a registry checkout, for browsing before installing.

    oto registry site [<dir>] [--out <dir>]

One page for the registry, one page per pack and one per ontology, all plain HTML with no
external assets, so the directory can be hosted anywhere static; the registry's Pages workflow
publishes it on every push. A pack's page draws its sample graph with the explorer: a throwaway
project is started from the pack, built, and exported as the explorer's static site under the
page. Nothing here writes into the registry checkout except the output directory.
"""
import contextlib
import html
import io
import json
import os
import re
import shutil
import tempfile

from . import __version__
from .apps import manifest as _apps
from .model import ontologies as _ontologies
from .model import packs as _packs
from .model import registry as _registry


def scrub(remote):
    """A remote with any credential removed: `https://user:token@host/...` becomes `https://host/...`.
    A page is public; a token in an install line would be too."""
    if not remote:
        return remote
    return re.sub(r"^([a-z]+://)[^/@]+@", r"\1", remote.strip())


def registry_address(work, url=None):
    """(what to type in Claude Code, what to type at a terminal) for the registry: from `url`, else
    the checkout's git remote; a GitHub remote becomes the `owner/repo` shorthand Claude Code takes.
    Unknown, both are placeholders."""
    remote = url
    if not remote:
        try:
            from . import gitx
            # the stored value, never `remote get-url`: that applies url.insteadOf rewrites, which
            # is where a workflow keeps its token
            remote = gitx.run(["config", "--get", "remote.origin.url"], cwd=work).strip()
        except Exception:                                               # noqa: BLE001 - no remote is fine
            remote = None
    remote = scrub(remote)
    if not remote:
        return "&lt;this registry&gt;", "&lt;this registry&gt;"
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    short = m.group(1) if m else remote
    https = ("https://github.com/%s" % m.group(1)) if m else remote
    return _e(short), _e(https)

OUT_NAME = "site"
STYLE = """
:root{--bg:#FFFFFF;--surface:#FFFFFF;--ink:#151A1F;--muted:#5C6570;--line:#E4E7EC;--code:#F2F4F7;--paper:#F5F6F8;--paper-line:#E6E8EC;--paper-ink:#5C6570;
--accent:#2D3E8F;--accent-soft:#E9ECF7;--accent-2:#1F8A9E;--accent-2-soft:#E3F3F6;--accent-3:#B7791F;--accent-3-soft:#FBF3E4}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}h1,h2,h3{margin:0;line-height:1.15;letter-spacing:-.01em}
h1{font-size:2.2rem;font-weight:700}h2{font-size:1.35rem;font-weight:700}h3{font-size:1rem;font-weight:600}p{margin:0;max-width:72ch}
code,pre{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.86em}code{background:var(--code);padding:1px 6px;border-radius:4px}
pre{background:#1B1F27;color:#E9ECEF;padding:12px 14px;border-radius:8px;overflow-x:auto;margin:0;line-height:1.5}pre code{background:none;padding:0;color:inherit}
.top{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
.top .in{max-width:1180px;margin:0 auto;padding:12px 20px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.05rem;color:var(--ink);letter-spacing:-.01em}.brand img{width:26px;height:26px}.brand:hover{text-decoration:none}
.top nav{display:flex;gap:16px;align-items:center;font-size:.93rem;color:var(--muted)}.top nav a{color:var(--muted)}.top nav a:hover{color:var(--ink);text-decoration:none}
.top nav a.btn{color:var(--button-ink,var(--accent-2));background:var(--button,var(--accent-2-soft));border:1px solid var(--button-ink,var(--accent-2));border-radius:9px;padding:7px 14px;font-weight:600}.top nav a.btn:hover{color:var(--button-ink,var(--accent-2));background:#fff;text-decoration:none}
.search{margin:0 auto;display:flex;align-items:center;gap:8px;min-width:260px;flex:1 1 320px;max-width:520px}.top nav{margin-left:auto}
.search input{width:100%;padding:9px 12px 9px 34px;border:1px solid var(--line);border-radius:9px;font:inherit;font-size:.93rem;background:var(--paper) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%235C6570' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='m20 20-3.5-3.5'/%3E%3C/svg%3E") 11px 50% no-repeat;color:var(--ink)}
.search input:focus{outline:2px solid var(--accent-soft);border-color:var(--accent)}
.wrap{max-width:1180px;margin:0 auto;padding:36px 20px 64px;display:flex;flex-direction:column;gap:36px}
.hero{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:28px;align-items:start}
@media (max-width:820px){.hero{grid-template-columns:1fr}}
.hero .lede{font-size:1.1rem;color:var(--muted);margin-top:10px}
.eyebrow{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);font-weight:500}
.counts{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}.counts span{font-size:.85rem;color:var(--muted);background:var(--paper);border:1px solid var(--paper-line);border-radius:999px;padding:4px 12px}
.counts b{color:var(--ink);margin-right:4px}
.install{background:var(--paper);border:1px solid var(--paper-line);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.install .t{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--paper-ink);font-weight:600}.install p{font-size:.88rem;color:var(--muted)}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.filters .f{font-size:.84rem;padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--muted);cursor:pointer;font-family:inherit}
.filters .f.on{background:var(--accent);border-color:var(--accent);color:#fff}.filters .f:hover{border-color:var(--accent)}.filters .sep{width:1px;height:20px;background:var(--line);margin:0 6px}.filters .f.d.on{background:var(--accent-2);border-color:var(--accent-2)}
section{display:flex;flex-direction:column;gap:14px}section>h2{padding-top:18px;border-top:1px solid var(--line)}
.group{display:flex;flex-direction:column;gap:10px}.group h3{color:var(--muted);font-weight:600;font-size:.8rem;letter-spacing:.06em;text-transform:uppercase}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:8px;min-width:0}
.card.onto{border-top-color:var(--accent-2)}.card:hover{border-color:var(--accent);box-shadow:0 4px 18px rgba(21,26,31,.06)}
.card .name{font-size:1.08rem;font-weight:700;letter-spacing:-.01em;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.card .name a{color:var(--ink)}
.card p{font-size:.93rem;color:var(--muted)}.card .meta{font-size:.82rem;color:var(--muted);margin-top:auto;padding-top:6px;border-top:1px dashed var(--line)}
.card.hidden{display:none}.none{color:var(--muted);font-size:.93rem}
.chip{display:inline-block;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
.chip.two{background:var(--accent-2-soft);color:var(--accent-2)}.chip.three{background:var(--accent-3-soft);color:var(--accent-3)}.rel{font-size:.8rem;color:var(--muted);font-weight:500}
.head{display:flex;flex-direction:column;gap:10px}.head .sub{color:var(--muted);font-size:.95rem}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:.93rem;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;vertical-align:top;padding:9px 12px;border-top:1px solid var(--line)}th{border-top:0;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);background:var(--accent-soft);font-weight:500}
.tablewrap{overflow-x:auto}iframe{width:100%;height:600px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}iframe.expanded{position:fixed;inset:0;width:100vw;height:100vh;z-index:50;border:0;border-radius:0}
ul{margin:0;padding-left:20px}li{margin:3px 0}details{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 14px}summary{cursor:pointer;font-weight:600}
.md h1,.md h2,.md h3{border:0;padding:0;font-size:1.02rem;margin-top:10px}.md p{margin:6px 0}.muted{color:var(--muted)}
footer{color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:14px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
"""

SEARCH = """<script>(function(){var q=document.getElementById('q');if(!q)return;var cards=[].slice.call(document.querySelectorAll('.card'));var groups=[].slice.call(document.querySelectorAll('.group'));var fs=[].slice.call(document.querySelectorAll('.filters .f[data-kind]'));var ds=[].slice.call(document.querySelectorAll('.filters .f[data-domain]'));var kind='all',domain='';
function apply(){var t=q.value.trim().toLowerCase();cards.forEach(function(c){var ok=(kind==='all'||c.dataset.kind===kind)&&(!domain||c.dataset.domain===domain)&&(!t||c.dataset.text.indexOf(t)>=0);c.classList.toggle('hidden',!ok);});
groups.forEach(function(g){g.style.display=g.querySelector('.card:not(.hidden)')?'':'none';});var n=cards.filter(function(c){return !c.classList.contains('hidden');}).length;var e=document.getElementById('nothing');if(e)e.style.display=n?'none':'';}
q.addEventListener('input',apply);fs.forEach(function(f){f.addEventListener('click',function(){kind=f.dataset.kind;fs.forEach(function(x){x.classList.toggle('on',x===f);});apply();});});
ds.forEach(function(f){f.addEventListener('click',function(){domain=(domain===f.dataset.domain)?'':f.dataset.domain;ds.forEach(function(x){x.classList.toggle('on',x.dataset.domain===domain);});apply();});});
document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();}});})();</script>"""


BRAND_FILE = "site.json"


def brand(work, index=None):
    """What the catalog looks like and says: the registry's optional `site.json` over the
    defaults. `title` and `tagline` name the site (default: the registry's name and summary);
    `colors` overrides any token of the stylesheet (`accent`, `accent-2`, `accent-3`, `paper`, `button`, `button-ink`, ...);
    `logo` is a file beside site.json copied to the site's root; `domain` writes the CNAME GitHub
    Pages needs; `links` are [{label, url, button?}] shown in the top bar; a link with `button` true is drawn as one."""
    out = {"title": (index or {}).get("name") or "", "tagline": (index or {}).get("summary") or "", "colors": {}, "logo": None, "domain": None, "links": []}
    path = os.path.join(work, BRAND_FILE)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            given = json.load(f)
        for key in ("title", "tagline", "logo", "domain"):
            if given.get(key):
                out[key] = str(given[key])
        if isinstance(given.get("colors"), dict):
            out["colors"] = {str(k): str(v) for k, v in given["colors"].items() if re.match(r"^[a-z0-9-]+$", str(k)) and re.match(r"^#[0-9A-Fa-f]{3,8}$", str(v))}
        if isinstance(given.get("links"), list):
            out["links"] = [{"label": str(l.get("label")), "url": str(l.get("url")), "button": bool(l.get("button"))}
                            for l in given["links"] if isinstance(l, dict) and l.get("label") and l.get("url")]
    return out


def _e(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def _markdown(text):
    """A small, honest rendering of the Markdown the engine writes: headings, bullets, fenced
    code, paragraphs, inline code and bold. Enough for a skill or a guide."""
    out, para, bullets, code = [], [], [], None
    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para))); para.clear()
        if bullets:
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _inline(b) for b in bullets)); bullets.clear()
    for line in (text or "").splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                out.append("<pre><code>%s</code></pre>" % _e("\n".join(code))); code = None
            else:
                code.append(line)
            continue
        if line.strip().startswith("```"):
            flush(); code = []; continue
        if line.startswith("---") and not out and not para:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush(); out.append("<h%d>%s</h%d>" % (min(len(m.group(1)) + 1, 4), _inline(m.group(2)), min(len(m.group(1)) + 1, 4))); continue
        if re.match(r"^\s*[-*]\s+", line):
            if para: flush()
            bullets.append(re.sub(r"^\s*[-*]\s+", "", line)); continue
        if not line.strip():
            flush(); continue
        if bullets and line.startswith("  "):
            bullets[-1] += " " + line.strip(); continue
        para.append(line.strip())
    if code is not None:
        out.append("<pre><code>%s</code></pre>" % _e("\n".join(code)))
    flush()
    return "\n".join(out)


def _inline(text):
    text = _e(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def _frontmatter(text):
    """(fields, body) of a SKILL.md."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    fields, key = {}, None
    for line in text[4:end].splitlines():
        m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1); fields[key] = m.group(2).strip().lstrip(">-").strip()
        elif key and line.startswith("  "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields, text[end + 4:].lstrip("\n")


def _page(title, body, depth, registry_name, address=("&lt;this registry&gt;", "&lt;this registry&gt;"), look=None, search=False):
    up = "../" * depth
    look = look or {"title": registry_name, "tagline": "", "colors": {}, "logo": None, "domain": None, "links": []}
    tokens = "".join("--%s:%s;" % (_e(k), _e(v)) for k, v in look["colors"].items())
    style = STYLE + (":root{%s}" % tokens if tokens else "")
    logo = ("<img src=\"%s%s\" alt=\"\">" % (up, _e(os.path.basename(look["logo"])))) if look.get("logo") else ""
    links = "".join("<a%s href=\"%s\">%s</a>" % (' class="btn"' if l.get("button") else "", _e(l["url"]), _e(l["label"])) for l in look["links"])
    box = ("<div class=\"search\"><input id=\"q\" type=\"search\" placeholder=\"Search packs and ontologies\" autocomplete=\"off\" aria-label=\"Search\"></div>" if search else "")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap\"><style>%s</style></head><body>"
            "<header class=\"top\"><div class=\"in\"><a class=\"brand\" href=\"%sindex.html\">%s<span>%s</span></a>%s<nav>%s</nav></div></header>"
            "<div class=\"wrap\">%s"
            "<footer><span>%s · generated by <code>oto registry site</code>, OTO %s</span><span>Install: <code>/plugin marketplace add %s</code>, then <code>/plugin install &lt;pack&gt;@%s</code></span></footer>"
            "</div>%s</body></html>\n" % (_e(title), style, up, logo, _e(look["title"]), box, links, body, _e(look["title"]), _e(__version__), address[0], _e(registry_name),
                                          SEARCH if search else ""))


def _grouped(entries):
    """[(domain or None, [entries])] with the named domains first, sorted."""
    groups = {}
    for entry in entries:
        groups.setdefault(entry.get("domain"), []).append(entry)
    keys = sorted((k for k in groups if k), key=str) + ([None] if None in groups else [])
    return [(k, sorted(groups[k], key=lambda e: e["name"])) for k in keys]


# ---- the explorer on a pack's sample ----

def _export_explorer(pack_dir, out_dir):
    """Start a throwaway project from the pack, build it, export the explorer. Returns the node
    and edge counts, or None with the reason when it cannot be drawn."""
    from .builder import build as _build
    from .project import Project
    from .scaffold import init as _init
    from .targets import site as _site

    work = tempfile.mkdtemp(prefix="oto-catalog-")
    try:
        manifest = _packs.read(pack_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            _init(work, slug="sample", name=manifest.get("summary") or manifest["name"], pack=pack_dir)
            project = Project.standard(work)
            _build(project)
            site, payload = _site.write(project, app_dir=_apps.resolve("explorer"), passages=False)
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        shutil.copytree(site, out_dir)
        return {"nodes": len(payload["nodes"]), "edges": len(payload["edges"])}, None
    except Exception as exc:                                            # noqa: BLE001 - the page says why
        return None, str(exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- the pages ----

def _ontology_sections(name, roots):
    result = _ontologies.composed(name, roots=roots)
    config, rationale = result["config"], result.get("rationale") or {}
    classes = config.get("classes") or {}
    rows = []
    for kind, description in classes.items():
        why = (rationale.get("classes") or {}).get(kind) or {}
        rows.append("<tr><td><strong>%s</strong></td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (_e(kind), _e(description), _e(why.get("question") or ""), _e(why.get("why") or "")))
    classes_html = ("<div class=\"tablewrap\"><table><thead><tr><th>Class</th><th>What it is</th><th>The question it answers</th><th>Why it exists</th></tr></thead><tbody>%s</tbody></table></div>"
                    % "".join(rows))
    rels = []
    for rel, spec in (config.get("properties") or {}).items():
        spec = list(spec) + [None] * 4
        rels.append("<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (_e(rel), _e(spec[0]), _e(spec[1]), _e(spec[3] or "")))
    rels_html = ("<div class=\"tablewrap\"><table><thead><tr><th>Relation</th><th>From</th><th>To</th><th>Meaning</th></tr></thead><tbody>%s</tbody></table></div>"
                 % "".join(rels))
    actions = "".join("<li><code>%s</code> on <strong>%s</strong>%s: %s</li>"
                      % (_e(a.get("id")), _e(a.get("subject")), " (read-only)" if (a.get("annotations") or {}).get("readOnlyHint") else "",
                         _e(a.get("description") or a.get("label") or ""))
                      for a in result.get("actions") or [])
    guide = result.get("guide")
    return {"classes": classes_html, "relations": rels_html, "actions": actions, "guide": guide,
            "counts": (len(classes), len(config.get("properties") or {}), len(result.get("rules") or []), len(result.get("actions") or [])),
            "parts": result["report"]["parts"]}


def _pack_page(entry, pack_dir, registry_name, drawn, address, look=None):
    manifest = _packs.read(pack_dir)
    onto = manifest.get("ontology") or {}
    sections = _ontology_sections(_packs.embedded_name(pack_dir), [_packs.embedded_root(pack_dir)])
    skills = []
    for skill, path in _packs.skills(pack_dir).items():
        with open(path, encoding="utf-8") as f:
            fields, body = _frontmatter(f.read())
        skills.append("<details%s><summary><code>/%s:%s</code> <span class=\"muted\">%s</span></summary><div class=\"md\">%s</div></details>"
                      % ("", _e(manifest["name"]), _e(skill), _e(fields.get("description") or ""), _markdown(body)))
    views = "".join("<li><code>%s</code>: <code>oto serve --http &lt;port&gt; --view %s</code></li>" % (_e(v), _e(v)) for v in _packs.views(pack_dir))
    changelog = "".join("<li><strong>@%s</strong> <span class=\"muted\">%s</span> %s</li>" % (_e(c.get("release")), _e(c.get("at") or ""), _e(c.get("note") or ""))
                        for c in sorted(manifest.get("changelog") or [], key=lambda c: -int(c.get("release", 0))))
    body = ["<section class=\"head\"><div class=\"eyebrow\">Pack%s</div><h1>%s <span class=\"rel\">@%d</span></h1><p class=\"sub\">%s</p>"
            "<p class=\"muted\">%s</p></section>"
            % ((" · " + _e(manifest["domain"])) if manifest.get("domain") else "", _e(manifest["name"]), manifest["release"], _e(manifest.get("summary") or ""),
               " · ".join(x for x in [("by " + _e(manifest["maintainer"])) if manifest.get("maintainer") else "",
                                      "embeds the ontology <code>%s@%s</code>" % (_e(onto.get("name")), _e(onto.get("release"))),
                                      "engine %s" % _e(manifest["engine"]) if manifest.get("engine") else ""] if x)),
            "<section><h2>Install</h2><pre><code>/plugin marketplace add %s\n/plugin install %s@%s</code></pre>"
            "<p>The engine plugin <code>oto</code> comes with it. Then the pack's <code>start</code> skill begins a project from the installed copy: "
            "<code>oto init --name \"&lt;project&gt;\" --pack \"${CLAUDE_PLUGIN_ROOT}\" --project &lt;root&gt;</code>. "
            "At a terminal: <code>oto registry add %s</code>, <code>oto pack add %s</code>, <code>oto init --pack %s</code>.</p></section>"
            % (address[0], _e(manifest["name"]), _e(registry_name), address[1], _e(manifest["name"]), _e(manifest["name"]))]
    counts = sections["counts"]
    body.append("<section><h2>The ontology</h2><p><code>%s@%s</code>: %d classes, %d relations, %d rules, %d actions%s.</p>%s%s</section>"
                % (_e(onto.get("name")), _e(onto.get("release")), counts[0], counts[1], counts[2], counts[3],
                   (", extends " + ", ".join("<code>%s</code>" % _e(p) for p in sections["parts"][:-1])) if len(sections["parts"]) > 1 else "",
                   sections["classes"], sections["relations"]))
    if drawn and drawn[0]:
        body.append("<section><h2>The sample, drawn</h2><p class=\"muted\">The pack's sample graph, %d nodes and %d edges, in the explorer every project gets: "
                    "<a href=\"explorer/index.html\">open it full size</a>.</p><iframe src=\"explorer/index.html\" title=\"the sample graph\" loading=\"lazy\"></iframe>"
                    "<script>window.addEventListener('message',function(e){if(!e.data||e.data.oto!=='explorer')return;var f=document.querySelector('iframe');if(!f||e.source!==f.contentWindow)return;f.classList.toggle('expanded',!!e.data.expanded);document.body.style.overflow=e.data.expanded?'hidden':'';});</script></section>"
                    % (drawn[0]["nodes"], drawn[0]["edges"]))
    elif drawn:
        body.append("<section><h2>The sample, drawn</h2><p class=\"muted\">Could not be drawn: %s</p></section>" % _e(drawn[1]))
    if sections["actions"]:
        body.append("<section><h2>Actions it ships</h2><p class=\"muted\">OTO lists them; the caller invokes.</p><ul>%s</ul></section>" % sections["actions"])
    body.append("<section><h2>Skills</h2>%s</section>" % ("".join(skills) or "<p class=\"muted\">none</p>"))
    body.append("<section><h2>Views</h2>%s</section>" % (("<ul>%s</ul>" % views) if views else "<p class=\"muted\">None yet: the explorer and the reader every project has.</p>"))
    if sections["guide"]:
        body.append("<section><h2>The guide</h2><div class=\"md\">%s</div></section>" % _markdown(sections["guide"]))
    if changelog:
        body.append("<section><h2>Changelog</h2><ul>%s</ul></section>" % changelog)
    return _page("%s, an OTO pack" % manifest["name"], "".join(body), 2, registry_name, address, look)


def _ontology_page(entry, directory, registry_name, work, address, look=None):
    manifest = _ontologies.manifest_dir(directory)
    sections = _ontology_sections(entry["name"], [work])
    counts = sections["counts"]
    body = ["<section class=\"head\"><div class=\"eyebrow\">Ontology%s</div><h1>%s <span class=\"rel\">@%d</span></h1><p class=\"sub\">%s</p><p class=\"muted\">%d classes, %d relations, %d rules, %d actions%s. "
            "<code>oto registry add %s</code>, <code>oto ontology add %s</code>, then <code>oto init --ontology %s</code>.</p></section>"
            % ((" · " + _e(manifest["domain"])) if manifest.get("domain") else "", _e(entry["name"]), manifest["release"], _e(manifest.get("summary") or ""),
               counts[0], counts[1], counts[2], counts[3],
               (", extends " + ", ".join("<code>%s</code>" % _e(p) for p in sections["parts"][:-1])) if len(sections["parts"]) > 1 else "",
               address[1], _e(entry["name"]), _e(entry["name"])),
            "<section><h2>Classes</h2>%s</section><section><h2>Relations</h2>%s</section>" % (sections["classes"], sections["relations"])]
    if sections["actions"]:
        body.append("<section><h2>Actions it ships</h2><ul>%s</ul></section>" % sections["actions"])
    if sections["guide"]:
        body.append("<section><h2>The guide</h2><div class=\"md\">%s</div></section>" % _markdown(sections["guide"]))
    return _page("%s, an OTO ontology" % entry["name"], "".join(body), 2, registry_name, address, look)


def _card(kind, href, entry, extra, text):
    return ("<div class=\"card %s\" data-kind=\"%s\" data-domain=\"%s\" data-text=\"%s\"><div><span class=\"chip%s\">%s</span></div>"
            "<div class=\"name\"><a href=\"%s\">%s</a> <span class=\"rel\">@%d</span></div><p>%s</p><div class=\"meta\">%s</div></div>"
            % ("pack" if kind == "pack" else "onto", kind, _e(entry.get("domain") or ""), _e(text.lower()), "" if kind == "pack" else " two", _e(entry.get("domain") or ("pack" if kind == "pack" else "ontology")),
               href, _e(entry["name"]), int(entry.get("release") or 1), _e(entry.get("summary") or ""), extra))


def _index_page(index, pack_notes, registry_name, address, look=None):
    look = look or brand(".", index)
    packs, ontos = index.get("packs") or [], index.get("ontologies") or []
    body = ["<div class=\"hero\"><div><div class=\"eyebrow\">OTO registry · %s</div><h1>%s</h1><p class=\"lede\">%s</p>"
            "<div class=\"counts\"><span><b>%d</b> packs</span><span><b>%d</b> ontologies</span><span><b>%d</b> domains</span></div>"
            "<p class=\"muted\" style=\"margin-top:14px;font-size:.93rem\">%d packs, %d ontologies. A pack is what you install: an ontology, its skills and its views. An ontology is what a project starts from.</p></div>"
            "<div class=\"install\"><div class=\"t\">Install in Claude Code</div><pre><code>/plugin marketplace add %s\n/plugin install &lt;pack&gt;@%s</code></pre>"
            "<p>At a terminal: <code>oto registry add %s</code>, then <code>oto pack add &lt;pack&gt;</code> or <code>oto ontology add &lt;ontology&gt;</code>.</p></div></div>"
            % (_e(registry_name), _e(look["title"]), _e(look["tagline"] or index.get("summary") or ""), len(packs), len(ontos),
               len({e.get("domain") for e in packs + ontos if e.get("domain")}), len(packs), len(ontos), address[0], _e(registry_name), address[1])]
    domains = sorted({e.get("domain") for e in packs + ontos if e.get("domain")})
    body.append("<div class=\"filters\"><span class=\"eyebrow\" style=\"margin-right:6px\">Show</span><button class=\"f on\" data-kind=\"all\" type=\"button\">Everything</button>"
                "<button class=\"f\" data-kind=\"pack\" type=\"button\">Packs</button><button class=\"f\" data-kind=\"ontology\" type=\"button\">Ontologies</button>"
                + ("<span class=\"sep\"></span>" + "".join("<button class=\"f d\" data-domain=\"%s\" type=\"button\">%s</button>" % (_e(d), _e(d)) for d in domains) if domains else "")
                + "</div>")
    body.append("<section class=\"group\"><h2>Packs</h2><div class=\"cards\">")
    for domain, entries in _grouped(packs):
        for entry in entries:
            onto = entry.get("ontology") or {}
            note = pack_notes.get(entry["name"]) or {}
            extra = "ontology <code>%s@%s</code>%s%s" % (_e(onto.get("name")), _e(onto.get("release")),
                                                          (" · %d skill%s" % (note["skills"], "" if note["skills"] == 1 else "s")) if note else "",
                                                          (" · %d view%s" % (note["views"], "" if note["views"] == 1 else "s")) if note and note["views"] else "")
            body.append(_card("pack", "packs/%s/index.html" % _e(entry["name"]), entry, extra,
                              " ".join(str(x) for x in (entry["name"], entry.get("summary"), entry.get("domain"), onto.get("name"), "pack"))))
    body.append("</div>%s</section>" % ("" if packs else "<p class=\"none\">No packs yet.</p>"))
    body.append("<section class=\"group\"><h2>Ontologies</h2><div class=\"cards\">")
    for domain, entries in _grouped(ontos):
        for entry in entries:
            extra = ("extends %s" % ", ".join("<code>%s</code>" % _e(x) for x in entry["extends"])) if entry.get("extends") else "the base every ontology rests on"
            body.append(_card("ontology", "ontologies/%s/index.html" % _e(entry["name"]), entry, extra,
                              " ".join(str(x) for x in (entry["name"], entry.get("summary"), entry.get("domain"), " ".join(entry.get("extends") or []), "ontology"))))
    body.append("</div></section><p class=\"none\" id=\"nothing\" style=\"display:none\">Nothing matches.</p>")
    return _page("%s, an OTO registry" % look["title"], "".join(body), 0, registry_name, address, look, search=True)


def write(work, out=None, url=None):
    """Generate the catalog for the registry checkout at `work` into `out` (default <work>/site).
    `url` is what a person types to add the registry (default: the checkout's git remote).
    Returns (out directory, {"packs": n, "ontologies": n, "drawn": n, "problems": [...]})."""
    index = _registry.read_index(work)
    problems = _registry.index_problems(index, work)
    if problems:
        raise _registry.ProjectError("the registry index has problems:\n  - %s" % "\n  - ".join(problems[:10]))
    out = os.path.abspath(out or os.path.join(work, OUT_NAME))
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    registry_name = index["name"]
    address = registry_address(work, url)
    look = brand(work, index)
    if look.get("logo"):
        src = os.path.join(work, look["logo"])
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(out, os.path.basename(look["logo"])))
        else:
            look["logo"] = None
    report = {"packs": 0, "ontologies": 0, "drawn": 0, "problems": []}
    pack_notes = {}
    for entry in index.get("packs") or []:
        if not entry.get("path"):
            continue
        pack_dir = os.path.join(work, entry["path"])
        page_dir = os.path.join(out, "packs", entry["name"])
        os.makedirs(page_dir, exist_ok=True)
        drawn = _export_explorer(pack_dir, os.path.join(page_dir, "explorer"))
        if drawn[0]:
            report["drawn"] += 1
        else:
            report["problems"].append("pack %s: the sample could not be drawn: %s" % (entry["name"], drawn[1]))
        with open(os.path.join(page_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_pack_page(entry, pack_dir, registry_name, drawn, address, look))
        pack_notes[entry["name"]] = {"skills": len(_packs.skills(pack_dir)), "views": len(_packs.views(pack_dir))}
        report["packs"] += 1
    for entry in index.get("ontologies") or []:
        if not entry.get("path"):
            continue
        page_dir = os.path.join(out, "ontologies", entry["name"])
        os.makedirs(page_dir, exist_ok=True)
        with open(os.path.join(page_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_ontology_page(entry, os.path.join(work, entry["path"]), registry_name, work, address, look))
        report["ontologies"] += 1
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_index_page(index, pack_notes, registry_name, address, look))
    with open(os.path.join(out, ".nojekyll"), "w") as f:
        f.write("")
    if look.get("domain"):
        with open(os.path.join(out, "CNAME"), "w", encoding="utf-8", newline="\n") as f:
            f.write(look["domain"] + "\n")
    with open(os.path.join(out, "catalog.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"registry": registry_name, "engine": __version__, "packs": index.get("packs") or [],
                   "ontologies": index.get("ontologies") or []}, f, indent=2, ensure_ascii=False)
    return out, report
