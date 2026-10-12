# Disks, temp files and worktrees: the detail

Read when: creating a temp file, a clone, a build output, a dataset copy or a git worktree; before removing a
worktree; before ending a task that produced files outside the repository.

The operative rule, with this device's roots, is in the always-loaded core. Large clones, browser caches and
worktrees fill the system drive quickly, and a worktree removed right after a rejected push can orphan a commit.

1. **Temp files, artifacts and data go to the device's roots only**, with absolute paths: throwaway files, scripts,
   logs, screenshots, scratch builds, captures, clones and tarballs under the temp root (`{{temp_root}}`); datasets
   under the data root (`{{data_root}}`); checkpoints and weights under the models root (`{{models_root}}`); browser
   downloads for test tooling under a folder of the temp root. Never the system temp, never a session scratchpad,
   never inside a repository.
2. **Every git worktree or isolated tree lives under the worktrees root** (`{{worktrees_root}}`) as
   `<Repo>-<topic>`, unless the repository's own rules say otherwise.
3. **Remove a worktree only after its commits are on the remote:** `git fetch origin`, then
   `git merge-base --is-ancestor HEAD origin/<branch>` must succeed in that worktree. A rejected push is fixed first
   (fetch, rebase, push, check again). Never put a push and a removal in the same command.
4. **Clean up before the task ends:** delete my temp files, remove my worktrees (after rule 3), delete the ignored
   outputs I produced inside repositories (build folders, test results, screenshots, data copies), stop my
   background jobs, and say what I removed.
5. Another session's worktrees and files are not mine to move or delete unless the user orders it.

The roots come from the Batuta configuration (`roots` in `batuta.json`, or `BATUTA_TEMP`, `BATUTA_DATA`,
`BATUTA_WORKTREES`). A missing drive or folder is configuration to fix, never a reason to declare the device unable
to do the work.
