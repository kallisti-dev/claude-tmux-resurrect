# Compatibility and limitations

## Supported environments

The flake supports Apple Silicon macOS and Linux (`aarch64-darwin`,
`aarch64-linux`, and `x86_64-linux`). Its pinned nixpkgs does not support Intel
macOS, and the plugin is untested there.

TPM 3.0.0, which Debian 12 and Ubuntu 22.04 package, reads only
`~/.tmux.conf` and cannot install a plugin line with a tag. Oh my tmux! loads
plugins after tmux creates the first session, so agents started in that
session's first pane are not tracked, as the plugin reports when it loads.

One foreground agent conversation per pane is supported. Fish, Nushell, native
Windows, and remote agent processes are unsupported. Linux under WSL2 is
untested.

OpenCode support covers the 1.x terminal interface; the tests use OpenCode
1.18 and the plugin was also tried with 1.19. The plugin relies on the
interface running plugins in a worker thread, which tells it apart from
`opencode run`. OpenCode 2, which keeps sessions in a shared background
service, is unsupported. OpenCode reports a session at its first prompt, so a
session switched to inside OpenCode is saved as the previous one until its next
prompt.

Claude Code loads the plugin's hooks through `CLAUDE_CODE_PLUGIN_DIRS`, which
requires version 2.1.280 or later; earlier versions ignore the variable, so
their sessions are not tracked. Home Manager installs the Nix Claude plugin as
a personal plugin, which requires 2.1.157 or later. Organization policies that stop these hooks are unsupported: [managed settings](https://code.claude.com/docs/en/managed-settings)
can turn off plugins loaded from `CLAUDE_CODE_PLUGIN_DIRS`, `allowManagedHooksOnly`
runs only hooks from managed settings and the plugins they force-enable, and
`disableAllHooks` stops all hooks. `/status` shows which managed settings Claude
Code uses.

## Testing limits

Most tests stub the harnesses. They verify exact argv, cwd, hook behavior, tmux
lifecycle, interoperability with upstream resurrect and TPM, and upgrades from
the plugin's last version under its former name. They install the plugin with
TPM from `~/.tmux.conf` and from `~/.config/tmux/tmux.conf`, with Oh my tmux!,
and as a clone, and load the Nix tmux package with `run-shell`, as Home Manager
and NixOS do; tpack and nix-darwin are untested. Two tests run
the Claude Code and OpenCode binaries from the pinned nixpkgs, without network
access, to check that a session started in a new pane loads the plugin and
records and clears its session ID. Claude Code loads it through
`CLAUDE_CODE_PLUGIN_DIRS` from the source and from the `skills` directory for
the Nix packages; OpenCode through `OPENCODE_CONFIG_CONTENT` and its
configuration file. The tests do not cover authentication, session file
compatibility across versions, or an actual conversation resumption.

The transcript directory layout and top-level `cwd` and `permissionMode` fields
are an integration assumption and can change with Claude versions, as can the
command-line options that the resume command repeats, which are Claude Code
2.1.300's. An option a later version adds ends the options that are repeated. Worktree inference covers the
standard `.claude/worktrees/<name>` layout; it does not recreate deleted trees
or preserve a subdirectory within a named worktree at launch.

## Integration limits

The dispatcher checks for a supported shell and copy mode, but cannot prove the
prompt is empty or that shell startup has finished. Avoid typing into pending
panes while they launch.

Hooks cannot guarantee exactly-once execution across a process crash between
sending Enter and clearing state. A killed dispatcher can also leave its tmux
lock held; restart the disposable session or, after confirming no dispatcher is
running, release `tmux-agent-resurrect-arm-N` with `tmux wait-for -U`.

Abnormally terminated Claude processes may leave their pane ID option behind.
Clean SessionEnd events clear it. Old snapshots remain local executable-session
configuration and should only be restored from trusted sources.

The integration does not change resurrect's own layout limitations, grouped
windows, snapshot pruning, or simultaneous save/restore behavior. Serialize save
and restore operations. Filenames and session names containing control
characters are unsupported.

See [troubleshooting](troubleshooting.md) for inspecting and recovering pending
sessions.
