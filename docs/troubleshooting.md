# Troubleshooting

Run these commands inside the affected tmux server. The scripts are in the
plugin's `bin` directory, which setup records in a tmux option:

```sh
plugin=$(tmux show-options -gqv @claude-tmux-resurrect-dir)
```

Start with the check, which reports each problem it finds with a line beginning
`problem`. In a Claude session, `/tmux-resurrect:check` runs it and explains the
result.

```sh
"$plugin"/bin/claude-tmux-resurrect-check
```

## No session was saved

A save reports Claude panes without a recorded session ID in tmux's message
line. Inspect the current pane:

```sh
tmux show-options -pqv @claude_session_id
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

## No resume after attach

Inspect the pending command and restore gate:

```sh
tmux show-options -pqv @claude_resume_cmd
tmux show-options -gqv @claude_restoring
```

Run `"$plugin"/bin/claude-tmux-resurrect-post-restore` inside tmux and check its
stderr. Missing transcripts, deleted directories, ambiguous IDs, and invalid
metadata produce diagnostics and are skipped.

## Restore was interrupted

After resurrect has stopped, clear the restore gate and prepare the current
snapshot again:

```sh
tmux set-option -gu @claude_restoring
"$plugin"/bin/claude-tmux-resurrect-post-restore
```

## Replacing or removing a shared hook

Setup remembers existing resurrect callbacks in the running tmux server. Removing
one from the configuration file does not remove that captured value on reload.
Reset setup before changing those callbacks:

```sh
"$plugin"/bin/claude-tmux-resurrect-setup --remove
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
tmux wait-for -U claude-tmux-resurrect-setup
tmux source-file /path/to/tmux.conf
```

## Pane was busy or in copy mode

Return it to an empty shell prompt, exit copy mode, then detach and attach again,
or run:

```sh
"$plugin"/bin/claude-tmux-resurrect-arm "$(tmux display-message -p '#{session_id}')"
```

## Dependency not found

Make the named executable available on the tmux server's PATH. Claude must also
be available on the pane shell's PATH. The Nix package supplies its other
dependencies itself.

## A dispatched command failed

Pending commands are cleared after sending, not after Claude confirms success.
Fix the cause and run the exact resume command manually. To deliberately requeue
from the snapshot, first clear the dispatched flag on that pane:

```sh
tmux set-option -pu @claude_launched
"$plugin"/bin/claude-tmux-resurrect-post-restore
```

See [compatibility and limitations](compatibility.md) for unsupported setups and
failure cases that cannot be recovered automatically.
