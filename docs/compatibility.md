# Compatibility and limitations

## Supported environments

The flake supports Apple Silicon macOS and Linux (`aarch64-darwin`,
`aarch64-linux`, and `x86_64-linux`). Its pinned nixpkgs does not support Intel
macOS; the ordinary shell installation is untested there.

One foreground Claude conversation per pane is supported. Fish, Nushell, native
Windows, and remote Claude processes are unsupported. Linux under WSL2 is
untested.

## Testing limits

Tests stub Claude. They verify exact argv, cwd, hook behavior, tmux lifecycle,
and upstream resurrect interoperability. They do not test Claude authentication,
transcript compatibility across versions, or an actual conversation resumption.

The transcript directory layout and top-level `cwd` fields are an integration
assumption and can change with Claude versions. Worktree inference covers the
standard `.claude/worktrees/<name>` layout; it does not recreate deleted trees
or preserve a subdirectory within a named worktree at launch.

## Integration limits

The dispatcher checks for a supported shell and copy mode, but cannot prove the
prompt is empty or that shell startup has finished. Avoid typing into pending
panes while they launch.

Hooks cannot guarantee exactly-once execution across a process crash between
sending Enter and clearing state. A killed dispatcher can also leave its tmux
lock held; restart the disposable session or, after confirming no dispatcher is
running, release `claude-tmux-arm-N` with `tmux wait-for -U`.

Abnormally terminated Claude processes may leave their pane ID option behind.
Clean SessionEnd events clear it. Old snapshots remain local executable-session
configuration and should only be restored from trusted sources.

The integration does not change resurrect's own layout limitations, grouped
windows, snapshot pruning, or simultaneous save/restore behavior. Serialize save
and restore operations. Filenames and session names containing control
characters are unsupported.

See [troubleshooting](troubleshooting.md) for inspecting and recovering pending
sessions.
