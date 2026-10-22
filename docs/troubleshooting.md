# Troubleshooting

Run these commands inside the affected tmux server. The scripts are in the
plugin's `bin` directory, which setup records in a tmux option:

```sh
plugin=$(tmux show-options -gqv @agent-resurrect-dir)
```

Start with the check, which reports each problem it finds with a line beginning
`problem`. In a Claude session, `/tmux-resurrect:check` runs it and explains the
result.

```sh
"$plugin"/bin/tmux-agent-resurrect-check
```

## No session was saved

A save reports Claude panes without a recorded session ID in tmux's message
line. Inspect the current pane:

```sh
tmux show-options -pqv @agent-resurrect-session
```

An empty value means Claude's session hook has not run in that pane. With TPM,
Claude loads the hook only when the pane's environment lists the plugin
directory, which is true of panes opened after the plugin loaded. Check in the
pane's shell:

```sh
printenv CLAUDE_CODE_PLUGIN_DIRS
```

In Claude Code, `/plugin` lists the hook's plugin as `tmux-resurrect@inline`,
or as `tmux-resurrect@skills-dir` for the Nix Claude plugin installed with Home
Manager. Start or resume Claude where it loads the plugin, then save again.

OpenCode records a session only once it has had a prompt, and a save skips a
recorded OpenCode session unless the pane is still running OpenCode. With TPM,
OpenCode loads the plugin when the pane's `OPENCODE_CONFIG_CONTENT` lists
`opencode/tmux-agent-resurrect.js` in the plugin directory:

```sh
printenv OPENCODE_CONFIG_CONTENT
```

With the Nix packages, OpenCode's `opencode.json` must list that file in its
`plugin` list.

## No resume after attach

Inspect the pending command and restore gate:

```sh
tmux show-options -pqv @agent-resurrect-resume-cmd
tmux show-options -gqv @agent-resurrect-restoring
```

Run `"$plugin"/bin/tmux-agent-resurrect-post-restore` inside tmux and check its
stderr. Missing transcripts, removed worktrees, ambiguous IDs, and invalid
metadata produce diagnostics and are skipped. A session whose directory does
not exist waits for it: it resumes on an attach once the directory exists, and
saves keep it until then. To discard it instead, close its pane.

## Restore was interrupted

After resurrect has stopped, clear the restore gate and prepare the current
snapshot again:

```sh
tmux set-option -gu @agent-resurrect-restoring
"$plugin"/bin/tmux-agent-resurrect-post-restore
```

## Replacing or removing a shared hook

Setup remembers existing resurrect callbacks in the running tmux server. Removing
one from the configuration file does not remove that captured value on reload.
Reset setup before changing those callbacks:

```sh
"$plugin"/bin/tmux-agent-resurrect-setup --remove
```

Edit the source configuration, keeping callback definitions before the plugin
loads, then reload it. Removal restores the previous resurrect options; if the
new configuration no longer sets one, explicitly unset that option before
reloading. For example, when removing a previous post-save callback:

```sh
tmux set-option -gu @resurrect-hook-post-save-layout
tmux source-file /path/to/tmux.conf
```

If setup reports that an option wraps a setup-generated hook, use the same reset
sequence and replace that option with its plain callback or unset it before
reloading. Setup leaves changed settings alone rather than rewriting an unknown
wrapper.

## Setup was interrupted

If setup was killed while holding its lock, confirm no setup command is still
running, then release it and reload the configuration:

```sh
tmux wait-for -U tmux-agent-resurrect-setup
tmux source-file /path/to/tmux.conf
```

## Pane was busy or in copy mode

Return it to an empty shell prompt, exit copy mode, then detach and attach again,
or run:

```sh
"$plugin"/bin/tmux-agent-resurrect-arm "$(tmux display-message -p '#{session_id}')"
```

## Dependency not found

Make jq and the other named executables available on the tmux server's PATH;
the Nix packages supply them themselves. The agent itself only needs to be on
the PATH of the pane's shell, which runs the resume command.

## A dispatched command failed

The pane keeps the saved session until the agent reports one, so saves keep
it, but it is not typed again. Fix the cause, such as an agent the pane's shell
does not find, and run the resume command, which is kept for inspection:

```sh
tmux show-options -pqv @agent-resurrect-resume-cmd
```

To deliberately requeue it from the snapshot instead, first clear the
dispatched flag on that pane:

```sh
tmux set-option -pu @agent-resurrect-launched
"$plugin"/bin/tmux-agent-resurrect-post-restore
```

See [compatibility and limitations](compatibility.md) for unsupported setups and
failure cases that cannot be recovered automatically.
