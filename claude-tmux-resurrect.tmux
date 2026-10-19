#!/usr/bin/env bash
# Plugin entry point, run by TPM or by run-shell in a tmux configuration.
# SPDX-License-Identifier: BSD-3-Clause
# shellcheck source=lib/claude-tmux-resurrect.sh
source "${BASH_SOURCE[0]%/*}/lib/claude-tmux-resurrect.sh"

# TPM discards this script's output, so also show a failure on tmux clients.
if ! output=$("$plugin_bin/claude-tmux-resurrect-setup" 2>&1); then
  message=${output##*$'\n'}
  message=${message#claude-tmux-resurrect: }
  notify "${message:-setup failed}"
  exit 1
fi
