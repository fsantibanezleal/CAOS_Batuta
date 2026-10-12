## Area `context` and `memory`: what loads at every session start

Claude Code loads user and project CLAUDE.md files and unscoped `.claude/rules/` files in full, `.claude/rules/` files
with `paths` front matter only with a matching file, `@imports` eagerly, and only the first 200 lines or 25 KB of each
project's MEMORY.md; topic files are read on demand. These areas keep the always-loaded part small and measured.

| Layer | What | Loads |
|---|---|---|
| L0 | rendered user core, project CLAUDE.md chain, unscoped rules, MEMORY.md index | every session |
| L1 | `.claude/rules/<id>.md` stubs with `paths` | with a matching file |
| L2 | reference files listed in `INDEX.md` with triggers, memory topic pages | when the task matches |

```
python scripts/batuta.py context build --manifest knowledge/manifest.json --out OUT [--apply]
python scripts/batuta.py context render --template templates/user/CLAUDE.template.md --values values.json --out ~/.claude/CLAUDE.md [--apply]
python scripts/batuta.py context check [--project DIR] [--home DIR] [--user-core FILE] [--memory-dir DIR] [--chain-root DIR]
python scripts/batuta.py context measure [--project DIR]
python scripts/batuta.py memory index --memory-dir DIR --project NAME [--topics FILE] [--budget FILE] [--apply]
```

- `context build` validates the manifest (C12: acyclic `requires`, unit files exist inside the manifest folder,
  summaries of at most 160 characters), writes `INDEX.md` (llms.txt style, one line per unit with load, triggers and
  requires), `CORE.md` (the `load: always` units) and `rules/<id>.md` (one stub per `load: path` unit), and refuses with
  `REFUSED` when the core or index exceeds the manifest budget. Dry run by default; output is sorted, LF only and
  carries no timestamp, so a second `--apply` reports `SAME` for every file.
- `context check` measures bytes, not characters. Budgets come from `batuta.json` (C01 `budgets`): `user_core_bytes`,
  `project_core_bytes`, `unscoped_rules_bytes`, `memory_index_bytes`, `memory_index_lines`. Exactly at a limit passes;
  one byte over fails (exit 1). A MEMORY.md over 200 lines or 25 KB fails for any project; another project's index
  over the C01 budget but under the cap is a warning (exit 2). A missing user core is `MISSING`; a project without a
  memory folder is reported `SKIP`.
- `@path` imports in the user core, the project CLAUDE.md chain and unscoped rules are counted the way Claude Code loads
  them: eagerly, relative to the importing file (`~/` is the home folder), up to 4 hops; code blocks, code spans and
  missing files are not imports. An import cycle or an import beyond 4 hops is a `WARN`. `measure` lists each import
  as its own L0 row.
- A memory index that belongs to an ancestor folder of the project is a warning, not a failure, because whether
  Claude Code keys memory by the repository root is UNVERIFIED. Lines are counted by `\n`, not by Unicode separators.
- `context build` writes the links of `INDEX.md` and of the stubs relative to where each page is written, and warns
  when the core exceeds the C01 `user_core_bytes`.
- `memory index --apply` removes only pages it generated (a page with the generation mark, or one named like a topic
  id of the topics file); hand-written files in `topics/` are never touched.
- `context measure` always exits 0 and prints each file's layer, bytes and estimated tokens (bytes divided by 4) and
  the L0 total.
- `memory index` needs a topics file (C13) listing the project; a project that is not listed exits 2 with nothing
  written. Memory folders are found under `<home>/.claude/projects/<sanitized project path>/memory`, where every
  character of the project path that is not a letter or digit becomes a hyphen.
- Templates: `templates/user/` (the generic user core and its `reference/` files) and `templates/knowledge/` (a sample
  manifest). Placeholders: `language`, `tone`, `user_name`, `python`, `deploy_root`, `temp_root`, `data_root`,
  `models_root`, `worktrees_root`; a placeholder without a value is refused.
