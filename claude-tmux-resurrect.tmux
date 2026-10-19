#!/usr/bin/env bash
# Plugin entry point, run by TPM or by run-shell in a tmux configuration.
# SPDX-License-Identifier: BSD-3-Clause

# TPM discards this script's output, so show a failure on attached clients.
if ! output=$("${BASH_SOURCE[0]%/*}/bin/claude-tmux-resurrect-setup" 2>&1); then
  message=${output##*$'\n'}
  tmux display-message "${message:-claude-tmux-resurrect: setup failed}" 2>/dev/null
  exit 1
fi
