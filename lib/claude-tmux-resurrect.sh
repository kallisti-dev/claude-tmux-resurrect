# Shared by the entry points; Bash 3.2 or newer.
# shellcheck shell=bash
# SPDX-License-Identifier: BSD-3-Clause

# Usage: warn MESSAGE...
# Print MESSAGE on stderr, prefixed with the project name.
warn() { printf 'claude-tmux-resurrect: %s\n' "$*" >&2; }

# Usage: die MESSAGE...
# Print MESSAGE as warn does and exit with status 1. Inside $(...), this exits
# only that subshell.
die() {
  warn "$*"
  exit 1
}

# Usage: need COMMAND...
# Exit with a diagnostic unless every COMMAND is on PATH.
need() {
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || die "required command not found on PATH: $tool"
  done
}

# Exit unless tmux and jq are on PATH and TMUX is set. Entry points call this
# before using tmux, so that their tmux commands reach the enclosing server
# rather than the default socket.
require_tmux() {
  need tmux jq
  [[ -n ${TMUX:-} ]] || die 'run inside tmux (TMUX must identify the intended server)'
}

# Usage: pane_option PANE OPTION
# Print PANE's own value of OPTION, or nothing if it is unset.
pane_option() { tmux show-options -pqv -t "$1" "$2"; }

# Usage: valid_id ID
# Succeed if ID has the form of a Claude session ID: 1 to 128 letters, digits,
# underscores, or hyphens, starting with a letter or digit. valid_record and
# claude-tmux-resurrect-hook repeat this pattern in jq.
valid_id() { [[ $1 =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$ ]]; }

# Usage: quote STRING
# Print STRING as one single-quoted shell word, writing each ' as '\''. Bash
# 3.2 handles quotes in the replacement of a double-quoted
# ${var//pattern/replacement} differently from later versions, so the
# replacement is kept in a variable.
quote() {
  local q="'\\''"
  printf "'%s'" "${1//\'/$q}"
}

# Print the directory that holds Claude's transcripts, under CLAUDE_CONFIG_DIR
# or ~/.claude.
projects_dir() { printf '%s/projects\n' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"; }

# Usage: find_transcript SESSION_ID
# Print the path of the session's transcript: the only readable
# SESSION_ID.jsonl in a project directory under projects_dir. Fail silently if
# SESSION_ID is invalid or has no transcript; warn and fail if several projects
# have one.
find_transcript() {
  local candidate found=''
  valid_id "$1" || return 1
  for candidate in "$(projects_dir)"/*/"$1".jsonl; do
    [[ -f $candidate && -r $candidate ]] || continue
    if [[ -n $found ]]; then
      warn "ambiguous transcript for session $1; skipping"
      return 1
    fi
    found=$candidate
  done
  [[ -n $found ]] || return 1
  printf '%s\n' "$found"
}

# Usage: valid_record JSON
# Succeed if JSON is exactly one saved pane record, in the format described
# under "Local data" in docs/design.md. Validate before decoding fields into
# shell variables. Control characters are incompatible with tmux-resurrect's
# line/tab-oriented snapshot format.
valid_record() {
  jq -se '
    def text: type == "string" and length > 0 and
      (test("[\u0000-\u001f\u007f]") | not);
    length == 1 and (.[0] |
    type == "object" and .version == 1 and
    (.session | text) and (.session | test("[:.]") | not) and
    (.window | type == "string" and test("^[0-9]+\\z")) and
    (.pane | type == "string" and test("^[0-9]+\\z")) and
    (.session_id | type == "string" and test("^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\\z")) and
    (.cwd | text and startswith("/")) and
    (.worktree | type == "string" and (test("[\u0000-\u001f\u007f/]") | not)))
  ' >/dev/null 2>&1 <<<"$1"
}

# Usage: record_target RECORD
# Print the tmux target =SESSION:WINDOW.PANE for a record that passed
# valid_record. The = prefix allows only an exact session-name match.
record_target() {
  jq -r '"=" + .session + ":" + .window + "." + .pane' <<<"$1"
}

# Usage: worktree_name DIR
# Print NAME if DIR is REPO/.claude/worktrees/NAME or a directory below it;
# otherwise print nothing.
worktree_name() {
  local name=''
  case "$1" in
    */.claude/worktrees/*)
      name=${1#*/.claude/worktrees/}
      name=${name%%/*}
      ;;
  esac
  printf '%s' "$name"
}

# Usage: resume_command RECORD
# Print the command line that resumes RECORD's conversation from a pane's
# shell: cd to the saved directory and run claude --resume SESSION_ID, or, for
# a named worktree, cd to the main repository and add --worktree NAME. Warn and
# fail without output if the record is invalid or inconsistent, its transcript
# is missing, ambiguous, or empty, or a directory no longer exists.
# Deliberately no picker fallback: restoration must identify one exact session.
resume_command() {
  local record=$1 dir id worktree transcript root
  valid_record "$record" || {
    warn 'invalid session metadata; skipping'
    return 1
  }
  dir=$(jq -r '.cwd' <<<"$record")
  id=$(jq -r '.session_id' <<<"$record")
  worktree=$(jq -r '.worktree' <<<"$record")
  transcript=$(find_transcript "$id") || {
    warn "missing or ambiguous transcript for $id; skipping"
    return 1
  }
  [[ -s $transcript ]] || {
    warn "empty transcript for $id; skipping"
    return 1
  }
  [[ -d $dir ]] || {
    warn "saved directory no longer exists: $dir"
    return 1
  }
  [[ $worktree == "$(worktree_name "$dir")" ]] || {
    warn "inconsistent worktree metadata for $id; skipping"
    return 1
  }
  if [[ -n $worktree ]]; then
    [[ $worktree != . && $worktree != .. && $worktree != -* ]] || {
      warn 'invalid worktree name; skipping'
      return 1
    }
    root=${dir%%/.claude/worktrees/*}
    [[ -d $root ]] || {
      warn "main repository no longer exists: $root"
      return 1
    }
    printf 'cd -- %s && claude --resume %s --worktree %s' "$(quote "$root")" "$(quote "$id")" "$(quote "$worktree")"
  else
    printf 'cd -- %s && claude --resume %s' "$(quote "$dir")" "$(quote "$id")"
  fi
}

# Print the path of tmux-resurrect's link to its latest snapshot. The directory
# follows resurrect's defaults: @resurrect-dir, else ~/.tmux/resurrect if it
# exists, else the XDG data directory. Unlike resurrect, only a leading ~/ or
# $HOME/ is expanded; any other relative directory exits through die.
last_snapshot() {
  local dir
  dir=$(tmux show-options -gqv @resurrect-dir)
  if [[ -z $dir ]]; then
    if [[ -d $HOME/.tmux/resurrect ]]; then
      dir=$HOME/.tmux/resurrect
    else
      dir=${XDG_DATA_HOME:-$HOME/.local/share}/tmux/resurrect
    fi
  fi
  case "$dir" in
    \~/*) dir=$HOME/${dir#\~/} ;;
    \$HOME/*) dir=$HOME/${dir#\$HOME/} ;;
  esac
  [[ $dir == /* ]] || die "@resurrect-dir must be absolute or start with ~/ or \$HOME/"
  printf '%s/last\n' "$dir"
}
