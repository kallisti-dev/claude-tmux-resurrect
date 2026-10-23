# Contributing

`nix develop`, or direnv with the included `.envrc`, provides the tools. The
tests drive real tmux, tmux-resurrect, TPM, and Oh my tmux!, with stubs for the
harnesses:

```sh
python3 -m unittest discover -s tests
```

Set `CLAUDE_BINARY` and `OPENCODE_BINARY` to also run the `test_real_` tests,
which start the real harnesses without network access. `nix flake check` runs
all of the tests against the source and the Nix packages, plus linting and
formatting; on macOS it needs the Nix sandbox off or relaxed, as building
claude-code does. CI runs it on each platform.

[docs/design.md](docs/design.md) explains how the pieces fit together.

## Releasing

Set the version in `.claude-plugin/plugin.json`, commit it to `main`, and push
a matching tag such as `v0.2.0`. The release workflow checks the tag, runs the
checks, and creates the GitHub release.
