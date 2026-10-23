// OpenCode 2 loads the TUI plugin, tui.js, of a plugin listed in its
// configuration only if the plugin also has a server part. This one does
// nothing: OpenCode runs it in a background server that the TUIs in every
// pane share, so it can't tell which pane shows a session.
// SPDX-License-Identifier: BSD-3-Clause
export default { id: "tmux-agent-resurrect", setup() {} };
