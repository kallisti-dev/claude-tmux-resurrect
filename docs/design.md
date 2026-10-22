# Design

This integration adds exact Claude conversation resumption to tmux-resurrect.
Resurrect handles the layout; these scripts associate each Claude pane with its
session ID and prepare the command needed to resume it.

## Plugin loading

The repository is a tmux plugin that is also a Claude Code plugin and holds an
OpenCode plugin. tmux runs `tmux-agent-resurrect.tmux`, which runs setup.
Setup registers the resurrect and tmux callbacks. When the plugin directory
also holds `hooks/hooks.json`, as the repository does, setup adds the directory
to `CLAUDE_CODE_PLUGIN_DIRS` in tmux's global environment. Claude Code loads
each directory listed in that variable in place, as a session-only plugin, so
Claude sessions started in new panes run `hooks/hooks.json` from the same
directory as the tmux callbacks, and both come from the same files.

When the directory holds `opencode/tmux-agent-resurrect.js`, setup also adds
that file to the plugin list in tmux's global `OPENCODE_CONFIG_CONTENT`,
keeping the rest of that JSON. OpenCode loads plugins listed there in addition
to those in its configuration files. The OpenCode TUI runs plugins in a worker
thread with the pane's environment, where the plugin reports the session to
`tmux-agent-resurrect-record` when a root session is created or prompted, and
reports its end when OpenCode shuts down cleanly. `opencode run`, `serve`, and
`web` run plugins on the main thread, where the plugin does nothing.

The Nix packages split the halves instead. The tmux plugin package has neither
agent plugin, so setup leaves both variables alone, and each agent plugin
package is installed where that agent loads plugins, such as Claude Code's
`skills` directory or OpenCode's configuration file. Either way, the tmux
options under [transient tmux state](#transient-tmux-state) are the only
interface between the halves.

Setup records the directory it listed and replaces that entry when the plugin
moves, keeping entries that something else added. A process keeps the
environment it started with, so Claude sessions in panes opened before the
plugin loaded do not load its hooks. For the same reason, a pane opened before
the plugin moved starts Claude with the earlier copy. The SessionStart hook
compares its own manifest version with the one setup recorded, and reports a
difference once per pair of versions; this also covers separately installed
packages of different versions.

## Save and restore

Claude's SessionStart hook records the exact session ID on its tmux pane, with
the `CLAUDE_CONFIG_DIR` that Claude runs with: the session's transcript is in
that directory, and resuming it needs the same one. SessionEnd clears them
only if the ID still matches, so a delayed event cannot clear a newer
conversation. Saving adds these mappings to the resurrect snapshot
and blanks the generic saved agent commands to prevent a second process restart.
A pane runs an agent if its process name or, failing that, its command line
names one: macOS names a process after the file a symlink resolves to, such as
`versions/2.1.300` for Claude's native installer, and an npm installation runs
as `node`.
When resuming, there is no fallback to a session picker: a missing or ambiguous
transcript is skipped with a diagnostic. A session whose directory does not
exist may be on a volume that is not mounted yet, so it stays queued, and in
later snapshots, until an attach finds the directory; closing its pane discards
it. A worktree missing from an existing repository has been removed, so its
session is skipped.

OpenCode reports sessions late: a new session exists only after its first
prompt, a session reopened with `-s` is reported at its next prompt, and an
unclean exit reports nothing. For such an agent, saves keep a session the
dispatcher resumed until the agent reports a session, and keep a session the
agent reported only while the pane's command is still that agent. Panes running it
without a recorded session are not reported, because before the first prompt
there is nothing to resume.

Restore is split into two hooks because resurrect switches between sessions while
rebuilding its layout. The pre-restore hook blocks launches during those switches.
The post-restore hook prepares all resume commands, clears the gate, then dispatches
commands for sessions with attached clients. Detached sessions wait for their first
attachment or client switch. This avoids launching every saved conversation during
a detached restore.

The dispatcher serializes launches within each session and leaves panes pending
if they are outside a supported shell or in copy mode. It types the command
without looking for the agent itself: the pane's shell, whose configuration
can extend its `PATH`, finds it. After sending a command, it marks the pane as
dispatched. That flag lasts for the pane's lifetime, preventing later
attachments or repeated restore calls from launching the conversation again.
The pane keeps the saved record until the agent reports a session, so saves
keep a conversation whose command failed in the pane;
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
- saved sessions that wait for their directory to exist
- pending resumes left for a later attach because a pane is busy or in copy mode
- a Claude session that loaded a copy of the plugin with another version

tmux-resurrect shows its own message after running its hooks, so a notice is
scheduled to appear one second after the event, for five seconds. If no client
is attached by then, the notice is kept and shown when a client next attaches.

## Hook registration

`tmux-agent-resurrect-setup` registers the existing commands with tmux and
resurrect. It does not add another dispatcher. Empty resurrect hook options run
the public commands directly. If an option already has a command, setup combines
it with ours in a single inline shell function that forwards hook arguments and
returns a failure status if either command fails. Our pre-restore guard runs first;
existing post-restore and save commands run before ours.

Each registered command first checks that its script still exists and otherwise
succeeds without doing anything. A tmux server keeps registrations until it
exits, and reloading a configuration does not remove them, so this keeps hooks
left behind by an uninstall from failing while other callbacks still run.
Scheduled notices check the same way, since tmux shows a failed delayed command
in view mode in the current pane, where pending resumes wait.

The existing command runs in a subshell, so an `exit` cannot prevent ours from
running. Its shell-local directory and environment changes stay in that subshell.
Setup does not try to untangle arbitrary wrappers around its generated functions;
it asks for a reset if one is found.

For tmux's native attach and session-switch hook arrays, setup selects a free
numeric slot and records tmux's canonical handler text. Reloads, including changes
to the installation path, reuse that slot only while its handler still matches;
otherwise setup chooses another free slot. `tmux-agent-resurrect-setup --remove`
removes its handlers and restores previous resurrect settings only where the
current value is still the one setup installed.

## Former name

Earlier versions of the plugin were named claude-tmux-resurrect and used that
name for their scripts, options, and snapshot records. Before registering its
own hooks, setup removes that version's registrations as its own
`claude-tmux-resurrect-setup --remove` would, along with its other
`@claude-tmux-resurrect-*` options, so it captures the callbacks they wrapped
instead of nesting them. It also carries over the resumes that a restore by
that version left pending and the flags on panes it dispatched. `--remove`
removes both versions' registrations.

Claude Code keeps the hook commands a session loaded when it started, so a
Claude session that loaded the earlier version keeps running that version's
hook, which records only the session ID, in `@claude_session_id`. Save,
restore, and the check read that option for a pane without
`@agent-resurrect-session`, and the current hook clears it when it records or
ends a session. The earlier version's callbacks read only that option, so
while they are still registered, as after a Home Manager switch until tmux
reloads its configuration, the current hook records Claude sessions there too.
Where the plugin directory was updated in place, as in a TPM clone or a Home
Manager link, such a session runs
`claude-tmux-resurrect-hook`, which runs the current hook. Restore also reads
the earlier version's snapshot records, which begin `claude-tmux` and do not
name an agent, as Claude's.

## Components

| Component | Responsibility |
| --- | --- |
| `tmux-agent-resurrect.tmux` | tmux entry point: run setup and display its failures |
| `.claude-plugin/plugin.json`, `hooks/hooks.json` | Claude Code plugin manifest and session hook configuration |
| `tmux-agent-resurrect-setup [--remove]` | Register or remove hooks and the `CLAUDE_CODE_PLUGIN_DIRS` entry while preserving other integrations |
| `tmux-agent-resurrect-claude-hook` | Claude Code's session hook: record `@agent-resurrect-session` on SessionStart; clear a matching session on SessionEnd |
| `claude-tmux-resurrect-hook` | The session hook's [former name](#former-name), for Claude sessions that loaded it: run `tmux-agent-resurrect-claude-hook` |
| `tmux-agent-resurrect-record start\|end AGENT ID [DIR]` | Record or clear a session on the calling pane, for agent plugins such as OpenCode's |
| `tmux-agent-resurrect-save SNAPSHOT` | Resolve cwd/worktree, embed mappings, blank generic saved agent commands |
| `tmux-agent-resurrect-pre-restore` | Suppress launches during resurrect's layout restoration |
| `tmux-agent-resurrect-post-restore [SNAPSHOT]` | Queue exact resume commands, clear the restore gate, and launch sessions that have attached clients |
| `tmux-agent-resurrect-arm '$N' [CLIENT]` | Dispatch pending commands once for the attached tmux session ID, and show kept notices on an attaching client |
| `tmux-agent-resurrect-notify MESSAGE` | Show a scheduled notice on attached clients, or keep it for the next attach |
| `tmux-agent-resurrect-check [--session ID]` | Report problems with the tmux server, the calling shell, Claude Code, and panes running Claude |
| `skills/check/SKILL.md` | `/tmux-resurrect:check`, which has Claude run the check and explain its result |
| `lib/tmux-agent-resurrect.sh` | Share transcript lookup, metadata validation, command quoting, and snapshot path resolution |

## Local data

The only Claude files read are matching
`$CLAUDE_CONFIG_DIR/projects/*/SESSION_ID.jsonl` transcripts, in the configuration
directory the session ran with (default: `~/.claude`). Records saved by earlier
versions do not name one, and the tmux server's `CLAUDE_CONFIG_DIR` stands in.
Save streams these files to obtain top-level `cwd` values,
using the latest valid absolute path or falling back to the pane's directory.
Restore checks for a unique, readable, nonempty matching transcript. No transcript,
worktree, or Claude settings file is modified. Transcript contents are never
copied into snapshots.

Each snapshot includes lines beginning `agent-resurrect`, followed by a tab and a JSON
object containing schema version 1, the agent (`claude`), tmux session name,
window and pane indexes, the agent's session ID, absolute cwd, and Claude
worktree name, which is empty for other agents. Claude records also hold the
session's `CLAUDE_CONFIG_DIR` as `config_dir`, empty when it was unset, and as
`options` the arguments that the resume command repeats. Those are read from
Claude's command line when its session starts, and include
`--dangerously-skip-permissions` if the transcript shows that the session last
bypassed permissions. This local metadata can reveal
project names and paths. Snapshot files are replaced with mode 0600; use a private
snapshot directory as well. Existing resurrect pane titles, commands, or optional
pane-content captures may contain additional information independently of this
integration. There is no network service or telemetry in these scripts.

## Transient tmux state

| Option | Scope | Purpose |
| --- | --- | --- |
| `@agent-resurrect-session` | Pane | The agent and session ID running in the pane, such as `claude 1111…`, maintained by the agent's hooks |
| `@agent-resurrect-cwd` | Pane | The recorded session's directory, from agents whose session files save does not read |
| `@agent-resurrect-launch` | Pane | How the recorded session's agent runs, such as Claude's `config_dir`, for save to add to its record |
| `@agent-resurrect-resume-data` | Pane | Snapshot metadata waiting to be dispatched, or dispatched and not yet reported by the agent |
| `@agent-resurrect-resume-cmd` | Pane | Generated resume command, available for inspection |
| `@agent-resurrect-launched` | Pane | Command already dispatched during this pane's lifetime |
| `@agent-resurrect-pending` | Session | At least one pane has a pending resume |
| `@agent-resurrect-restoring` | Global session | Launches are blocked while the layout or pending commands are being restored |
| `@agent-resurrect-notices` | Global session | Notices raised while no client was attached |
| `@agent-resurrect-unrecorded` | Global session | Claude panes without a session ID at the last save that warned about them |
| `@agent-resurrect-mismatch` | Global session | Plugin versions in the last mismatch reported at SessionStart |

Pending commands and metadata are removed when the agent reports a session in
the pane. Until then, saving retains the saved metadata, whether the
conversation is waiting for attachment or was dispatched.

Setup keeps previous and managed hook values, array slots, and expected handler
text in global `@agent-resurrect-*` options, and the directory it listed in
`CLAUDE_CODE_PLUGIN_DIRS` and its version in `@agent-resurrect-dir` and
`@agent-resurrect-version`. These describe the
running server's registrations. Removing a callback from the configuration file
alone does not clear a value setup previously captured; see
[replacing shared hooks](troubleshooting.md#replacing-or-removing-a-shared-hook).

See the [README](../README.md) for setup and usage.
