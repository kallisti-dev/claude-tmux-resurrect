# tmux-agent-resurrect

A tmux plugin that restores Claude Code conversations with
[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect).

## Requirements

- macOS or Linux
- tmux 3.2 or newer, with tmux-resurrect
- Claude Code 2.1.280 or newer, or 2.1.157 or newer with the
  [Nix packages](#nix) and Home Manager
- Bash 3.2 or newer and jq 1.6 or newer on the tmux server's `PATH`, unless
  you use the Nix packages
- [TPM](https://github.com/tmux-plugins/tpm), or another way to load a tmux
  plugin

## Installation

Add the plugin to your tmux configuration after tmux-resurrect, and before
tmux-continuum if you use it:

```tmux
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'tmux-plugins/tmux-resurrect'
set -g @plugin 'kallisti-dev/tmux-agent-resurrect'

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

### Checking the setup

In a Claude session, run `/tmux-resurrect:check`. Claude runs the plugin's
check and explains any problem it reports. From a shell in a tmux pane, run the
check directly. The plugin records its directory in a tmux option:

```sh
"$(tmux show-options -gqv @agent-resurrect-dir)"/bin/tmux-agent-resurrect-check
```

### Without TPM

Clone this repository, then run its entry point from your tmux configuration
after any `@resurrect-hook-*` options:

```tmux
run-shell ~/path/to/tmux-agent-resurrect/tmux-agent-resurrect.tmux
```

### Updating

Press prefix + U to update plugins with TPM. Claude Code runs the plugin's hooks
from the same directory, so there is nothing to update separately.

TPM follows the `main` branch. To stay on a release instead, add its tag to the
plugin line:

```tmux
set -g @plugin 'kallisti-dev/tmux-agent-resurrect#v0.1.0'
```

TPM doesn't move a pinned tag, so change the tag to upgrade.

### Uninstalling

Remove the `@plugin` line and press prefix + alt + u. After TPM deletes the
plugin, the callbacks it registered do nothing; they and its
`CLAUDE_CODE_PLUGIN_DIRS` entry disappear when the tmux server exits. To clear
them from a running server instead, run this inside it before removing the
plugin:

```sh
"$(tmux show-options -gqv @agent-resurrect-dir)"/bin/tmux-agent-resurrect-setup --remove
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

The plugin reports problems in tmux's message line: for example, when a save
finds Claude running in a pane without a recorded session ID, or a restore
cannot resume a saved session.

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

The flake provides the two halves as separate packages, each with its runtime
dependencies wrapped in:

- `tmux-plugin`, built with nixpkgs' `tmuxPlugins.mkTmuxPlugin`
- `claude-plugin`, the Claude Code plugin with the session hooks and
  `/tmux-resurrect:check`

Install each where you configure that program. With Home Manager:

```nix
{ inputs, pkgs, ... }:
let
  tmux-agent-resurrect = inputs.tmux-agent-resurrect.packages.${pkgs.stdenv.hostPlatform.system};
in
{
  programs.tmux.plugins = [
    pkgs.tmuxPlugins.resurrect
    tmux-agent-resurrect.tmux-plugin
  ];
  programs.claude-code.plugins.tmux-resurrect = tmux-agent-resurrect.claude-plugin;
}
```

Home Manager links the Claude plugin into Claude Code's `skills` directory,
where Claude Code 2.1.157 or newer loads it in every session. The tmux plugin
then leaves `CLAUDE_CODE_PLUGIN_DIRS` alone, so restarting Claude in any pane
loads the hooks. Without Home Manager's `programs.claude-code`, link the Claude
plugin package to `~/.claude/skills/tmux-resurrect` yourself. NixOS's
`programs.tmux.plugins` takes the same tmux plugin.

Both modules load tmux plugins before `programs.tmux.extraConfig`, so set any
`@resurrect-hook-*` options in a plugin entry's `extraConfig` with Home
Manager, or in `programs.tmux.extraConfigBeforePlugins` with NixOS.

Without flakes, `default.nix` builds the same two packages with the nixpkgs
revision pinned in `flake.lock`, or with a `pkgs` argument you pass:

```nix
tmux-agent-resurrect = import (builtins.fetchTarball
  "https://github.com/kallisti-dev/tmux-agent-resurrect/archive/main.tar.gz") { inherit pkgs; };
# Then use tmux-agent-resurrect.tmux-plugin and tmux-agent-resurrect.claude-plugin.
```

## Development

`nix develop`, or direnv with the included `.envrc`, provides the tools. The
tests use real tmux, tmux-resurrect, and TPM, with a stub in place of Claude:

```sh
python3 -m unittest discover -s tests
```

To also run the tests that start Claude Code, without network access, set
`CLAUDE_BINARY`:

```sh
CLAUDE_BINARY=$(command -v claude) python3 -m unittest discover -s tests -k test_real_claude
```

`nix flake check` runs the tests against the source and the Nix packages, along
with linting and formatting checks and the Claude Code tests. On macOS, the
Claude Code check needs the Nix build sandbox off or relaxed, as building
claude-code there does.

Releases are tags on `main`. To release, set the version in
`.claude-plugin/plugin.json`, commit it to `main`, and push a tag named `v`
followed by that version, such as `v0.2.0`. The release workflow checks that
the tag matches the manifest and is on `main`, runs the checks on each
platform, and creates the GitHub release.

## Documentation

- [Design](docs/design.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Compatibility and limitations](docs/compatibility.md)
