# Design

This integration adds exact Claude conversation resumption to tmux-resurrect.
Resurrect handles the layout; these scripts associate each Claude pane with its
session ID and prepare the command needed to resume it.

## Plugin loading

The repository is both a tmux plugin and a Claude Code plugin. tmux runs
`claude-tmux-resurrect.tmux`, through TPM or `run-shell`, which runs setup. Setup
registers the resurrect and tmux callbacks. When the plugin directory also holds
`hooks/hooks.json`, as a TPM clone does, setup adds the directory to
`CLAUDE_CODE_PLUGIN_DIRS` in tmux's global environment. Claude Code loads each
directory listed in that variable in place, as a session-only plugin, so Claude
sessions started in new panes run `hooks/hooks.json` from the same directory as
the tmux callbacks, and the two halves come from the same files.

The Nix packages split the halves instead. The tmux plugin package has no
hooks, so setup leaves the variable alone, and the Claude plugin package is
installed where Claude Code loads plugins, such as its `skills` directory.
Either way, the tmux options under [transient tmux state](#transient-tmux-state)
are the only interface between the halves.

Setup records the directory it listed and replaces that entry when the plugin
moves, keeping entries that something else added. A process keeps the
environment it started with, so Claude sessions in panes opened before the
plugin loaded do not load its hooks. For the same reason, a pane opened before
the plugin moved starts Claude with the earlier copy. The SessionStart hook
compares its own manifest version with the one setup recorded, and reports a
difference once per pair of versions; this also covers separately installed
packages of different versions.

## Save and restore

Claude's SessionStart hook records the exact session ID on its tmux pane.
SessionEnd clears that ID only if it still matches, so a delayed event cannot
clear a newer conversation. Saving adds these mappings to the resurrect snapshot
and blanks the generic saved Claude commands to prevent a second process restart.
When resuming, there is no fallback to a session picker: a missing or ambiguous
transcript is skipped with a diagnostic.

Restore is split into two hooks because resurrect switches between sessions while
rebuilding its layout. The pre-restore hook blocks launches during those switches.
The post-restore hook prepares all resume commands, clears the gate, then dispatches
commands for sessions with attached clients. Detached sessions wait for their first
attachment or client switch. This avoids launching every saved conversation during
a detached restore.

The dispatcher serializes launches within each session and leaves panes pending
if they are outside a supported shell or in copy mode. After sending a command,
it marks the pane as dispatched and removes its pending state. That flag lasts
for the pane's lifetime, preventing later attachments or repeated restore calls
from launching the conversation again.
Dispatch records that the command was sent, not that Claude started successfully;
see [troubleshooting](troubleshooting.md) for recovery steps.

## Notices

Problems that need the user's attention are shown with `display-message` on
every attached client, as well as on stderr:

- setup failures, which TPM would otherwise discard
- the first load into a server that already has panes, since Claude sessions
  started in those panes do not load the plugin
- Claude panes without a recorded session ID when saving, once each time that
  set of panes changes, because automatic saves repeat
- saved sessions that a restore cannot resume, with the first reason
- pending resumes left for a later attach because a pane is busy or in copy mode
- a Claude session that loaded a copy of the plugin with another version

tmux-resurrect shows its own message after running its hooks, so a notice is
scheduled to appear one second after the event, for five seconds. If no client
is attached by then, the notice is kept and shown when a client next attaches.

## Hook registration

`claude-tmux-resurrect-setup` registers the existing commands with tmux and
resurrect. It does not add another dispatcher. Empty resurrect hook options run
the public commands directly. If an option already has a command, setup combines
it with ours in a single inline shell function that forwards hook arguments and
returns a failure status if either command fails. Our pre-restore guard runs first;
existing post-restore and save commands run before ours.

Each registered command first checks that its script still exists and otherwise
succeeds without doing anything. A tmux server keeps registrations until it
exits, and reloading a configuration does not remove them, so this keeps hooks
left behind by an uninstall from failing while other callbacks still run.

The existing command runs in a subshell, so an `exit` cannot prevent ours from
running. Its shell-local directory and environment changes stay in that subshell.
Setup does not try to untangle arbitrary wrappers around its generated functions;
it asks for a reset if one is found.

For tmux's native attach and session-switch hook arrays, setup selects a free
numeric slot and records tmux's canonical handler text. Reloads, including changes
to the installation path, reuse that slot only while its handler still matches;
otherwise setup chooses another free slot. `claude-tmux-resurrect-setup --remove`
removes its handlers and restores previous resurrect settings only where the
current value is still the one setup installed.

## Components

| Component | Responsibility |
| --- | --- |
| `claude-tmux-resurrect.tmux` | Entry point for TPM or `run-shell`: run setup and display its failures |
| `.claude-plugin/plugin.json`, `hooks/hooks.json` | Claude Code plugin manifest and session hook configuration |
| `claude-tmux-resurrect-setup [--remove]` | Register or remove hooks and the `CLAUDE_CODE_PLUGIN_DIRS` entry while preserving other integrations |
| `claude-tmux-resurrect-hook` | Record `@claude_session_id` on SessionStart; clear a matching ID on SessionEnd |
| `claude-tmux-resurrect-save SNAPSHOT` | Resolve cwd/worktree, embed mappings, blank generic saved Claude commands |
| `claude-tmux-resurrect-pre-restore` | Suppress launches during resurrect's layout restoration |
| `claude-tmux-resurrect-post-restore [SNAPSHOT]` | Queue exact resume commands, clear the restore gate, and launch sessions that have attached clients |
| `claude-tmux-resurrect-arm '$N' [CLIENT]` | Dispatch pending commands once for the attached tmux session ID, and show kept notices on an attaching client |
| `claude-tmux-resurrect-notify MESSAGE` | Show a scheduled notice on attached clients, or keep it for the next attach |
| `claude-tmux-resurrect-check [--session ID]` | Report problems with the tmux server, the calling shell, Claude Code, and panes running Claude |
| `skills/check/SKILL.md` | `/tmux-resurrect:check`, which has Claude run the check and explain its result |
| `lib/claude-tmux-resurrect.sh` | Share transcript lookup, metadata validation, command quoting, and snapshot path resolution |

## Local data

The only Claude files read are matching
`$CLAUDE_CONFIG_DIR/projects/*/SESSION_ID.jsonl` transcripts (default configuration
root: `~/.claude`). Save streams these files to obtain top-level `cwd` values,
using the latest valid absolute path or falling back to the pane's directory.
Restore checks for a unique, readable, nonempty matching transcript. No transcript,
worktree, or Claude settings file is modified. Transcript contents are never
copied into snapshots.

Each snapshot includes lines beginning `claude-tmux`, followed by a tab and a JSON
object containing schema version 1, tmux session name, window and pane indexes,
Claude session ID, absolute cwd, and worktree name. This local metadata can reveal
project names and paths. Snapshot files are replaced with mode 0600; use a private
snapshot directory as well. Existing resurrect pane titles, commands, or optional
pane-content captures may contain additional information independently of this
integration. There is no network service or telemetry in these scripts.

## Transient tmux state

| Option | Scope | Purpose |
| --- | --- | --- |
| `@claude_session_id` | Pane | Current Claude conversation ID, maintained by Claude hooks |
| `@claude_resume_data` | Pane | Snapshot metadata waiting to be dispatched |
| `@claude_resume_cmd` | Pane | Generated resume command, available for inspection |
| `@claude_launched` | Pane | Command already dispatched during this pane's lifetime |
| `@claude_pending` | Session | At least one pane has a pending resume |
| `@claude_restoring` | Global session | Launches are blocked while the layout or pending commands are being restored |
| `@claude-tmux-resurrect-notices` | Global session | Notices raised while no client was attached |
| `@claude-tmux-resurrect-unrecorded` | Global session | Claude panes without a session ID at the last save that warned about them |
| `@claude-tmux-resurrect-mismatch` | Global session | Plugin versions in the last mismatch reported at SessionStart |

Pending commands and metadata are removed after dispatch. The saved metadata is
also retained when saving a conversation that is still waiting for attachment.

Setup keeps previous and managed hook values, array slots, and expected handler
text in global `@claude-tmux-resurrect-*` options, and the directory it listed in
`CLAUDE_CODE_PLUGIN_DIRS` and its version in `@claude-tmux-resurrect-dir` and
`@claude-tmux-resurrect-version`. These describe the
running server's registrations. Removing a callback from the configuration file
alone does not clear a value setup previously captured; see
[replacing shared hooks](troubleshooting.md#replacing-or-removing-a-shared-hook).

See the [README](../README.md) for setup and usage.
