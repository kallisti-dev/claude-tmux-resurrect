# Design

This integration adds exact Claude conversation resumption to tmux-resurrect.
Resurrect handles the layout; these scripts associate each Claude pane with its
session ID and prepare the command needed to resume it.

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
| `claude-tmux-resurrect-setup [--remove]` | Register or remove hooks while preserving other integrations |
| `claude-tmux-resurrect-hook` | Record `@claude_session_id` on SessionStart; clear a matching ID on SessionEnd |
| `claude-tmux-resurrect-save SNAPSHOT` | Resolve cwd/worktree, embed mappings, blank generic saved Claude commands |
| `claude-tmux-resurrect-pre-restore` | Suppress launches during resurrect's layout restoration |
| `claude-tmux-resurrect-post-restore [SNAPSHOT]` | Queue exact resume commands, clear the restore gate, and launch sessions that have attached clients |
| `claude-tmux-resurrect-arm '$N'` | Dispatch pending commands once for the attached tmux session ID |
| `share/claude-tmux-resurrect/lib.sh` | Share transcript lookup, metadata validation, command quoting, and snapshot path resolution |

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

Pending commands and metadata are removed after dispatch. The saved metadata is
also retained when saving a conversation that is still waiting for attachment.

Setup keeps previous and managed hook values, array slots, and expected handler
text in global `@claude-tmux-resurrect-*` options. These describe the running
server's registrations. Removing a callback from the configuration file alone
does not clear a value setup previously captured; see
[replacing shared hooks](troubleshooting.md#replacing-or-removing-a-shared-hook).

See the [README](../README.md) for setup and usage.
