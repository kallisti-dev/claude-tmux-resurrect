# tmux-agent-resurrect

A tmux plugin that restores Claude Code and OpenCode conversations with
[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect).

## Requirements

- macOS or Linux
- tmux 3.2 or newer, with tmux-resurrect
- Claude Code 2.1.280 or newer, or 2.1.157 or newer with the
  [Nix packages](#nix) and Home Manager; or OpenCode 1.18 or newer in the 1.x
  line. OpenCode 2 is not supported.
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
existing ones and lists its agent plugins in tmux's global environment, so
agents started in new panes load them from the plugin directory:

- Claude Code loads the directory listed in `CLAUDE_CODE_PLUGIN_DIRS` as the
  session-only plugin `tmux-resurrect@inline`.
- OpenCode loads the plugin file listed in `OPENCODE_CONFIG_CONTENT`, in
  addition to the plugins in its configuration files.

Nothing is installed into either agent's configuration. Panes opened before the
plugin first loaded don't have these variables, so agent sessions started in
them are not tracked. Start those sessions again in a new pane, for example
with `claude --continue`, then make a fresh resurrect save. After the next tmux
server start, every pane has the variables.

If your shell startup files set `CLAUDE_CODE_PLUGIN_DIRS` or
`OPENCODE_CONFIG_CONTENT`, add to the inherited value instead of replacing it:

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

### Upgrading from claude-tmux-resurrect

Earlier versions of this plugin were named claude-tmux-resurrect. GitHub
redirects that name, so an existing
`set -g @plugin 'kallisti-dev/claude-tmux-resurrect'` line keeps working, and
prefix + U updates the plugin in place. When it loads, the plugin replaces the
earlier version's registrations, keeping the resurrect callbacks they wrapped.
It restores snapshots that version saved and keeps track of Claude sessions
that started under it.

To use the new name instead, replace the line and press prefix + I. That moves
the plugin to a new directory, and Claude in panes opened before the move keeps
loading hooks from the old one, so remove the old directory with
prefix + alt + u after restarting those sessions in new panes.

If Claude Code's settings run `claude-tmux-resurrect-hook`, as instructions
for earlier versions configured, remove those hooks; the plugin provides its
own. With Nix, point the flake input at
`github:kallisti-dev/tmux-agent-resurrect` and install the
[packages](#nix).

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

Authenticate the agents before saving sessions. Restored panes must use a
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

Claude Code sessions resume with `claude --resume SESSION_ID`. For a named
worktree at `<repo>/.claude/worktrees/<name>`, the command is run from `<repo>`
and adds `--worktree NAME`. Other sessions use the latest valid absolute `cwd`
in their transcript, falling back to the pane's directory if there is no usable
transcript cwd.

OpenCode sessions resume with `opencode -s SESSION_ID`, run from the session's
directory. OpenCode reports a session to the plugin at its first prompt, so a
session that has had no prompt is not saved. A session you switch to inside
OpenCode is recorded at its next prompt; until then, a save keeps the session
the pane last prompted.

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

Each Claude session resumes with the `CLAUDE_CONFIG_DIR` it ran with, so panes
can use different configuration directories. Use an absolute path; a session
with a relative one is restored as one saved by an earlier version of the
plugin, which uses the `CLAUDE_CONFIG_DIR` in tmux's global environment, where
the save and restore callbacks run.

## Nix

The flake provides the tmux plugin and each agent's plugin as separate
packages, each with its runtime dependencies wrapped in:

- `tmux-plugin`, built with nixpkgs' `tmuxPlugins.mkTmuxPlugin`
- `claude-plugin`, the Claude Code plugin with the session hooks and
  `/tmux-resurrect:check`
- `opencode-plugin`, whose `opencode/tmux-agent-resurrect.js` is the OpenCode
  plugin

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
  programs.opencode.settings.plugin = [
    "${tmux-agent-resurrect.opencode-plugin}/opencode/tmux-agent-resurrect.js"
  ];
}
```

Home Manager links the Claude plugin into Claude Code's `skills` directory,
where Claude Code 2.1.157 or newer loads it in every session, and lists the
OpenCode plugin in OpenCode's configuration file. The tmux plugin then leaves
`CLAUDE_CODE_PLUGIN_DIRS` and `OPENCODE_CONFIG_CONTENT` alone, so restarting an
agent in any pane loads its plugin. Without Home Manager, link the Claude plugin
package to `~/.claude/skills/tmux-resurrect` and list the OpenCode plugin file
in the `plugin` list of OpenCode's `opencode.json` yourself. NixOS's
`programs.tmux.plugins` takes the same tmux plugin.

Both modules load tmux plugins before `programs.tmux.extraConfig`, so set any
`@resurrect-hook-*` options in a plugin entry's `extraConfig` with Home
Manager, or in `programs.tmux.extraConfigBeforePlugins` with NixOS.

Without flakes, `default.nix` builds the same packages with the nixpkgs
revision pinned in `flake.lock`, or with a `pkgs` argument you pass:

```nix
tmux-agent-resurrect = import (builtins.fetchTarball
  "https://github.com/kallisti-dev/tmux-agent-resurrect/archive/main.tar.gz") { inherit pkgs; };
# Then use tmux-agent-resurrect.tmux-plugin, .claude-plugin, and .opencode-plugin.
```

## Development

`nix develop`, or direnv with the included `.envrc`, provides the tools. The
tests use real tmux, tmux-resurrect, and TPM, with a stub in place of Claude:

```sh
python3 -m unittest discover -s tests
```

To also run the tests that start Claude Code and OpenCode, without network
access, set `CLAUDE_BINARY` and `OPENCODE_BINARY`:

```sh
CLAUDE_BINARY=$(command -v claude) OPENCODE_BINARY=$(command -v opencode) \
  python3 -m unittest discover -s tests -k test_real_
```

`nix flake check` runs the tests against the source and the Nix packages, along
with linting and formatting checks and the tests with the real agents. On
macOS, that check needs the Nix build sandbox off or relaxed, as building
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
