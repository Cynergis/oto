# This is an OTO sandbox

You run inside a sandbox made from OTO's kit. Only the plugins installed in it load: the `oto` engine
plugin and the packs of the `cynergis` marketplace, each named `<name>@cynergis`. The plugins of the
person's computer, and the plugins, skills and connectors of their claude.ai account, are switched off
here on purpose, so the work does not depend on what happens to be on their machine.

**Which plugins and skills are on.** When the person asks, answer from the sandbox, not from the
account. The host's `ListPlugins` and `ListSkills` tools describe the person's claude.ai account, where
everything they ever added shows as enabled; that list is the same from any machine and says nothing
about this sandbox. What loads here is what `claude plugin list` prints (the `@cynergis` plugins, all
enabled) and the skills you can invoke by `/<plugin>:<skill>`. If a plugin from outside shows as
`<name>@inline` and enabled, say so: the next session starts without it, or `/reload-plugins` does.
From the person's computer, `oto sandbox status` says whether anything from outside loads.

**The folders.** The sandbox works on two folders of the computer, `project` (the knowledge project,
where `oto` commands take `--project .`) and `code`, both at the same paths here and there, so the
person opens what you write as usual. `oto sandbox` itself is run from the computer, not from here.
