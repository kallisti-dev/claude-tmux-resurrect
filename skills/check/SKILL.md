---
description: Check whether tmux-resurrect can resume this Claude session, and explain how to fix any problem found
disable-model-invocation: true
allowed-tools: Bash(claude-tmux-resurrect-check *)
---

Run `claude-tmux-resurrect-check --session ${CLAUDE_SESSION_ID}` with the Bash
tool. It reports whether the tmux server, this pane, and Claude Code are set up
so that tmux-resurrect can resume this session.

Summarize the result. For each line marked `problem`, explain the cause and the
fix, using `${CLAUDE_PLUGIN_ROOT}/docs/troubleshooting.md`. Change configuration
only if the user asks.
