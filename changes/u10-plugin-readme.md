## Install

One step, for Claude Code 2.1.275 or later (from a shell, 2.1.292 or later):

```
/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta
```

The two-step form is `/plugin marketplace add fsantibanezleal/CAOS_Batuta` then `/plugin install batuta@caos-batuta`. Claude Code asks for the
plugin option `python` (the command that starts Python 3.10 or newer, used by every hook); hooks with `onFailure: "block"` need Claude Code 2.1.295
or later. The full guide is `docs/guides/install.md` in the repository.
