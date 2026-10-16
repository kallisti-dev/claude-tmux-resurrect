# claude-tmux-resurrect

A shell integration for
[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) to resume
Claude Code conversations that were running in your tmux panes.

## Standard installation

### Installation

Prerequisites:

- macOS or Linux
- GNU Make and `install`.
- Bash 3.2 or newer
- jq 1.6 or newer.
- `mktemp`, `mv`, and `rm` on `PATH`.
- tmux 3.2 or newer.
- tmux-resurrect, installed with
  [TPM](https://github.com/tmux-plugins/tpm) or another installation method.
- Claude Code installed

From a checkout or unpacked source archive:

```sh
make install
```

The default install path is `$HOME/.local` on macOS and Linux. Commands use the
`claude-tmux-resurrect-` prefix and go in `$HOME/.local/bin`. The library stays
at `$HOME/.local/share/claude-tmux-resurrect/lib.sh`, with examples and the
license in the same project directory. Override the install prefix with
`make install PREFIX=/path/to/prefix`.

Add the installed `bin` directory to `PATH` in your shell startup file. For
the default prefix:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Load this change before starting tmux and Claude Code. Both the tmux server's
hook environment and the pane's shell must find the commands; an existing
tmux server may need its environment updated. No configuration files are
edited automatically.

### Configuration

1. Merge these hooks into your Claude Code user settings, normally
   `~/.claude/settings.json`:

   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "hooks": [{ "type": "command", "command": "claude-tmux-resurrect-hook" }]
         }
       ],
       "SessionEnd": [
         {
           "hooks": [{ "type": "command", "command": "claude-tmux-resurrect-hook" }]
         }
       ]
     }
   }
   ```

2. Add this to your tmux configuration after any existing resurrect hook
   settings. With TPM, keep its initialization at the end of your configuration:

   ```tmux
   run-shell 'claude-tmux-resurrect-setup'
   ```

3. Reload your tmux configuration and start or resume your Claude sessions so
   SessionStart records their IDs. Make a fresh resurrect save.

#### tmux hook setup

Run the setup script after your other resurrect callback definitions. It preserves those
callbacks and existing tmux attach hooks. Reloading does not add duplicates.
To change or remove an existing callback, follow the
[troubleshooting steps](docs/troubleshooting.md#replacing-or-removing-a-shared-hook).

Before disabling a module or removing the setup line, run this inside each
affected tmux server:

```sh
claude-tmux-resurrect-setup --remove
```

#### Claude configuration directory

For a custom `CLAUDE_CONFIG_DIR`, export the same absolute path to Claude and
tmux's hook environment. Only one Claude configuration directory per tmux server
is supported.

### Uninstall

Run `claude-tmux-resurrect-setup --remove` inside each tmux server, remove
the configuration entries above, then run:

```sh
make uninstall
```

If you installed with a custom `PREFIX`, pass the same value when uninstalling.

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

## Snapshot directory

`@resurrect-dir` sets the snapshot directory. The default is `~/.tmux/resurrect`
if it exists, otherwise `${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect`.

Use absolute paths or a leading `~/` or `$HOME/`; other variables are not expanded.
Avoid spaces in snapshot directories because tmux-resurrect does not handle them
reliably. Project directories may contain spaces.

## Nix-based installation

The Nix package supplies the scripts' runtime dependencies. Package or profile
installs still need tmux, Claude Code, and tmux-resurrect installed separately
and use the [standard configuration](#configuration). The modules below install
and configure them by default.

### Without flakes

Install from the source archive:

```sh
nix-env --install --file \
  https://github.com/kallisti-dev/claude-tmux-resurrect/archive/refs/heads/main.tar.gz
```

From a checkout, use `nix-env --install --file .` or build with `nix-build`.
`default.nix` uses the nixpkgs revision in `flake.lock`; no channel configuration
or flake support is required.

### With flakes

Enable the `nix-command` and `flakes` experimental features in your Nix
configuration.

Install into your profile with Nix 2.30 or newer:

```sh
nix profile add github:kallisti-dev/claude-tmux-resurrect
```

For a local build from a checkout, run `nix build`. Both `nix build` and
`nix-build` expose binaries in `result/bin`; use a persistent profile path if
configuring an absolute command path.

### Home Manager

This example uses standalone Home Manager. In your `flake.nix`, declare the
inputs and import the module:

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    claude-tmux-resurrect.url = "github:kallisti-dev/claude-tmux-resurrect";
  };

  outputs = { nixpkgs, home-manager, claude-tmux-resurrect, ... }:
    let
      system = "aarch64-darwin";
    in {
      homeConfigurations.yourname = home-manager.lib.homeManagerConfiguration {
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            nixpkgs.lib.getName pkg == "claude-code";
        };
        modules = [
          claude-tmux-resurrect.homeManagerModules.default
          ./home.nix
        ];
      };
    };
}
```

Replace `yourname` with your configuration name. Set `system` to
`aarch64-darwin`, `aarch64-linux`, or `x86_64-linux`.

Enable the integration in `home.nix`:

```nix
# home.nix
{
  programs.claude-tmux-resurrect.enable = true;
}
```

The module installs the integration, enables Claude Code and tmux, and merges
the Claude hooks with your declared Home Manager settings. It supplies the
resurrect plugin; omit that plugin from your own `programs.tmux.plugins` list.
Setup runs after your `programs.tmux.extraConfig` and uses
`programs.claude-code.configDir` for transcript lookup.

Use `programs.claude-tmux-resurrect.package` to override the integration package.
Other Claude Code and tmux settings use their existing Home Manager options.

Activate from the directory containing your `flake.nix`, then reload tmux:

```sh
home-manager switch --flake .#yourname
tmux source-file "${XDG_CONFIG_HOME:-$HOME/.config}/tmux/tmux.conf"
```

Start or resume Claude sessions so SessionStart records their IDs, then make a
fresh resurrect save.

#### Home Manager on NixOS and nix-darwin

Use the same Home Manager module for each user. In your flake's outputs, add
this to your existing `nixosSystem.modules` list alongside
`home-manager.nixosModules.home-manager`:

```nix
{
  home-manager.sharedModules = [
    claude-tmux-resurrect.homeManagerModules.default
  ];
  home-manager.users.yourname.programs.claude-tmux-resurrect.enable = true;
}
```

On nix-darwin, use the same settings in `darwinSystem.modules` alongside
`home-manager.darwinModules.home-manager`. Allow the `claude-code` unfree package
in the nixpkgs configuration used by Home Manager, as in the standalone example.

### NixOS

For system-wide setup, import the NixOS module in your host flake:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    claude-tmux-resurrect.url = "github:kallisti-dev/claude-tmux-resurrect";
  };

  outputs = { nixpkgs, claude-tmux-resurrect, ... }: {
    nixosConfigurations.yourhost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        claude-tmux-resurrect.nixosModules.default
        ./configuration.nix
      ];
    };
  };
}
```

Use your host's name and system (`x86_64-linux` or `aarch64-linux`), then enable
the integration in `configuration.nix`:

```nix
{ lib, ... }:
{
  nixpkgs.config.allowUnfreePredicate = pkg: lib.getName pkg == "claude-code";
  programs.claude-tmux-resurrect.enable = true;
}
```

The module installs the integration, Claude Code, and resurrect, and enables
tmux system-wide. It configures `/etc/tmux.conf` and writes the Claude hooks to
`/etc/claude-code/managed-settings.d/claude-tmux-resurrect.json`. These are
[managed settings](https://code.claude.com/docs/en/managed-settings) for all
users and require Claude Code 2.1.83 or newer. Claude Code ignores this file
when your organization delivers server-managed settings; organization-managed
settings are [unsupported](docs/compatibility.md#supported-environments).

Use `programs.claude-tmux-resurrect.package` to override the integration package
and `programs.claude-tmux-resurrect.claudePackage` to select another Claude Code
package, or set the latter to `null` if Claude is installed separately.

Rebuild the system, then reload tmux:

```sh
sudo nixos-rebuild switch --flake .#yourhost
tmux source-file /etc/tmux.conf
```

Start or resume Claude sessions and make a fresh resurrect save. If your
per-user tmux configuration also defines resurrect callbacks, put the setup
line from the [standard configuration](#configuration) after those definitions. Use
either the native NixOS module or the Home Manager module for a given user.

### nix-darwin

For system-wide setup on Apple Silicon macOS, import the nix-darwin module:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    claude-tmux-resurrect.url = "github:kallisti-dev/claude-tmux-resurrect";
  };

  outputs = { nix-darwin, claude-tmux-resurrect, ... }: {
    darwinConfigurations.yourhost = nix-darwin.lib.darwinSystem {
      modules = [
        claude-tmux-resurrect.darwinModules.default
        ./darwin-configuration.nix
      ];
    };
  };
}
```

Use your host's name, then enable the integration in
`darwin-configuration.nix`:

```nix
{ lib, ... }:
{
  nixpkgs.hostPlatform = "aarch64-darwin";
  nixpkgs.config.allowUnfreePredicate = pkg: lib.getName pkg == "claude-code";
  programs.claude-tmux-resurrect.enable = true;
}
```

The module installs the integration and Claude Code, and configures resurrect
and setup in `/etc/tmux.conf`. It links the generated hooks into
`/Library/Application Support/ClaudeCode/managed-settings.d/claude-tmux-resurrect.json`.
As with the NixOS module, these are managed settings for all users and require
Claude Code 2.1.83 or newer. The `package` and `claudePackage` options work the
same way as in the [NixOS configuration](#nixos).

Rebuild the system, then reload tmux:

```sh
sudo darwin-rebuild switch --flake .#yourhost
tmux source-file /etc/tmux.conf
```

Start or resume Claude sessions and make a fresh resurrect save. If
`/etc/tmux.conf.local` defines resurrect callbacks, put the setup line from
the [standard configuration](#configuration) after those definitions. Use either the
native nix-darwin module or the Home Manager module for a given user.

To uninstall, set `programs.claude-tmux-resurrect.enable = false` and rebuild
before removing the module import. This removes the managed hook link.

## Documentation

- [Design](docs/design.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Compatibility and limitations](docs/compatibility.md)

