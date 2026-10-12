# No unattended automation: the full list

Read when: a task would schedule, repeat, detach or poll something; before writing a loop, a watcher, a launcher or a
recurring job; when unsure whether a background process is allowed.

The operative rule is in the always-loaded core; this file holds the complete list. Unattended automation burns
quota and leaves orphans (polling loops from dead sessions, leftover scheduled tasks, hidden relaunchers, forgotten
dev servers, a virtual machine pinned awake). Rules:

1. Never create scheduled tasks, startup or run-key entries, services, management-instrumentation subscriptions, cron
   jobs, systemd units or timers, lingering sessions, or cloud routines. Never edit the subsystem configuration
   that keeps a virtual machine alive. If something must recur, write the script and give the user the exact
   command to register it.
2. Never launch the agent headless (the print mode, or any flag that skips permission prompts) from scripts, tasks
   or CI on a subscription.
3. Never detach or hide a process so it outlives the session (`nohup`, `setsid`, `disown`, a hidden window, a
   windowless interpreter, a scheduled run on demand). No self-healing or keepalive relaunchers.
4. Every polling loop is bounded: a timeout, an iteration cap or a deadline. Before a session ends, stop every
   background task, loop, server and process it started, and say so.
5. Before a multi-hour or multi-agent job (fan-out, many subagents, loops over a near-full context), state the
   expected quota cost and get approval.

Enforcement is a guard hook on the shell tools, not this text; the hook is never edited, disabled or worked around by
the agent. Long API runs follow the orchestration procedures: started by hand, bounded in time, stopped with the
session.
