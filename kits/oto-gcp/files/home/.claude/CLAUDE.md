# This is an OTO sandbox

You run inside a sandbox made from OTO's kit. Only the plugins installed in it load: the engine plugin
`oto@cynergis-engine` (from the engine's own marketplace) and the packs of the `cynergis` marketplace
the person has turned on, each named `<name>@cynergis`. A new sandbox has the engine alone; the packs a
project needs are chosen from this session with the packs skill (`/oto:packs`), which shows what the
registry offers, installs the chosen ones for the project and says to type `/reload-plugins`. The plugins
of the person's computer, and the plugins, skills and connectors of their claude.ai account, are switched
off here on purpose, so the work does not depend on what happens to be on their machine.

**Which plugins and skills are on.** When the person asks, answer from the sandbox, not from the
account. The host's `ListPlugins` and `ListSkills` tools describe the person's claude.ai account, where
everything they ever added shows as enabled; that list is the same from any machine and says nothing
about this sandbox. What loads here is what `claude plugin list` prints (`oto@cynergis-engine` and the `@cynergis`
plugins turned on so far, all enabled) and the skills you can invoke by `/<plugin>:<skill>`. If a plugin from outside shows as
`<name>@inline` and enabled, say so: the next session starts without it, or `/reload-plugins` does.
From the person's computer, `oto sandbox status` says whether anything from outside loads.

**Serving the graph.** `oto serve --project . --http 8798` here listens on all interfaces, with no
token: the engine knows it runs inside the kit, and the sandbox tool forwards the port only to the
person's computer, on its localhost. The person opens `http://localhost:8798/` in their own browser (8799
for a second server, a pack's view with `--view <name>`). A server bound to this sandbox's loopback is unreachable from the
computer, so never pass `127.0.0.1:<port>`. The ports are published when the sandbox is made
(`oto sandbox up`, 8798 and 8799); another port is `sbx ports <name> --publish <port>:<port>` on the
computer, live from the sandbox's next start.

**The folders.** The sandbox works on two folders of the computer, `project` (the knowledge project,
where `oto` commands take `--project .`) and `code`, both at the same paths here and there, so the
person opens what you write as usual. `oto sandbox` itself is run from the computer, not from here.
