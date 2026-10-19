# claude-tmux-resurrect

A tmux plugin that restores Claude Code conversations with
[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect).

## Requirements

- macOS or Linux
- tmux 3.2 or newer, with tmux-resurrect
- Claude Code 2.1.280 or newer
- Bash 3.2 or newer and jq 1.6 or newer on the tmux server's `PATH`
- [TPM](https://github.com/tmux-plugins/tpm), or another way to load a tmux
  plugin

## Installation

Add the plugin to your tmux configuration after tmux-resurrect, and before
tmux-continuum if you use it:

```tmux
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'tmux-plugins/tmux-resurrect'
set -g @plugin 'kallisti-dev/claude-tmux-resurrect'

# Keep this line at the end of the configuration.
run '~/.tmux/plugins/tpm/tpm'
```

Set any `@resurrect-hook-*` options before TPM's `run` line, then press
prefix + I to install the plugin.

Each time tmux loads the plugin, it registers its resurrect callbacks alongside
existing ones and adds its directory to `CLAUDE_CODE_PLUGIN_DIRS` in tmux's
global environment. Claude Code sessions started in new panes load the plugin's
session hooks from that directory, as the session-only plugin
`tmux-resurrect@inline`. Nothing is installed into Claude Code's configuration.

Panes opened before the plugin first loaded don't have the variable, so Claude
sessions started in them are not tracked. Start those sessions again in a new
pane, for example with `claude --continue`, then make a fresh resurrect save.
After the next tmux server start, every pane has the variable.

If your shell startup files set `CLAUDE_CODE_PLUGIN_DIRS`, append to the
inherited value instead of replacing it:

```sh
export CLAUDE_CODE_PLUGIN_DIRS="${CLAUDE_CODE_PLUGIN_DIRS:+$CLAUDE_CODE_PLUGIN_DIRS:}$HOME/my-plugins"
```

### Without TPM

Clone this repository, then run its entry point from your tmux configuration
after any `@resurrect-hook-*` options:

```tmux
run-shell ~/path/to/claude-tmux-resurrect/claude-tmux-resurrect.tmux
```

### Updating

Press prefix + U to update plugins with TPM. Claude Code runs the plugin's hooks
from the same directory, so there is nothing to update separately.

### Uninstalling

Remove the `@plugin` line and press prefix + alt + u. After TPM deletes the
plugin, the callbacks it registered do nothing; they and its
`CLAUDE_CODE_PLUGIN_DIRS` entry disappear when the tmux server exits. To clear
them from a running server instead, run this inside it before removing the
plugin:

```sh
"$(tmux show-options -gqv @claude-tmux-resurrect-dir)"/bin/claude-tmux-resurrect-setup --remove
```

## Usage

Authenticate Claude Code before saving sessions. Restored panes must use a
Bourne-compatible shell (`bash`, `zsh`, `sh`, `dash`, or `ksh`).

Use your normal tmux-resurrect save and restore bindings (by default,
prefix + Ctrl-s and prefix + Ctrl-r). During a save, the integration records
exact session mappings and removes those panes from resurrect's generic process
restart. During restore, it prepares commands without launching detached sessions.
An already attached session resumes when restore finishes; other sessions resume
on the first attachment or client switch. Later attachments do not relaunch them.

For a named worktree at `<repo>/.claude/worktrees/<name>`, the command is run from
`<repo>` using `claude --resume SESSION_ID --worktree NAME`. Other sessions use
the latest valid absolute `cwd` in their transcript, falling back to the pane's
directory if there is no usable transcript cwd.

## Configuration

### Snapshot directory

`@resurrect-dir` sets the snapshot directory. The default is `~/.tmux/resurrect`
if it exists, otherwise `${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect`.

Use absolute paths or a leading `~/` or `$HOME/`; other variables are not expanded.
Avoid spaces in snapshot directories because tmux-resurrect does not handle them
reliably. Project directories may contain spaces.

### Existing resurrect callbacks

The plugin keeps existing resurrect callbacks and tmux attach hooks, and
reloading the configuration does not add duplicates. To change or remove a
callback that was set before the plugin loaded, follow the
[troubleshooting steps](docs/troubleshooting.md#replacing-or-removing-a-shared-hook).

### Claude configuration directory

For a custom `CLAUDE_CONFIG_DIR`, set the same absolute path in tmux's global
environment, where the save and restore callbacks run. Only one Claude
configuration directory per tmux server is supported.

## Nix

The flake's default package is the tmux plugin, built with nixpkgs'
`tmuxPlugins.mkTmuxPlugin`, with its runtime dependencies wrapped in. Add it
wherever you list tmux plugins. For example, with Home Manager:

```nix
programs.tmux.plugins = [
  pkgs.tmuxPlugins.resurrect
  inputs.claude-tmux-resurrect.packages.${pkgs.stdenv.hostPlatform.system}.default
];
```

NixOS's `programs.tmux.plugins` takes the same list. Both modules load plugins
before `programs.tmux.extraConfig`, so set any `@resurrect-hook-*` options in a
plugin entry's `extraConfig` with Home Manager, or in
`programs.tmux.extraConfigBeforePlugins` with NixOS.

Without flakes, `default.nix` builds the same package with the nixpkgs revision
pinned in `flake.lock`, or with a `pkgs` argument you pass:

```nix
claude-tmux-resurrect = import (builtins.fetchTarball
  "https://github.com/kallisti-dev/claude-tmux-resurrect/archive/main.tar.gz") { inherit pkgs; };
```

## Documentation

- [Design](docs/design.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Compatibility and limitations](docs/compatibility.md)
