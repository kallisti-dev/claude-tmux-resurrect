// OpenCode 1 plugin: report the session this OpenCode TUI works in to the
// tmux-agent-resurrect recorder, which records it on the tmux pane.
//
//   tmux-agent-resurrect-record start opencode SESSION_ID DIRECTORY
//     when a different root session is created or gets a prompt
//   tmux-agent-resurrect-record end opencode SESSION_ID
//     when the process shuts down cleanly
//
// OpenCode tells plugins which session the TUI shows only when that session
// is created or prompted, so a session opened with -s or switched to is
// reported at its next prompt.
//
// It also adds /tmux-resurrect-check, which runs tmux-agent-resurrect-check
// for the session and has OpenCode explain the result.
// SPDX-License-Identifier: BSD-3-Clause
import { isMainThread } from "node:worker_threads";
import {
  check,
  checkText,
  description,
  prompt,
  record,
  runCheck,
  serialize,
} from "./shared.js";

export const TmuxAgentResurrect = async ({ client }) => {
  // The TUI runs plugins in a worker thread with the pane's environment.
  // `opencode run`, `serve`, and `web` run them on the main thread, and are
  // not interactive sessions in the user's pane.
  if (isMainThread) return {};

  const sessions = new Map(); // session ID -> { parentID, directory }
  let current;
  const enqueue = serialize();

  const remember = (info) => {
    if (info?.id) {
      sessions.set(info.id, {
        parentID: info.parentID,
        directory: info.directory,
      });
    }
  };
  const show = async (id) => {
    if (!id || id === current) return;
    if (!sessions.has(id)) {
      remember((await client.session.get({ path: { id } })).data);
    }
    const info = sessions.get(id);
    // Subagent sessions have a parent; keep reporting the root session.
    if (!info || info.parentID || !info.directory) return;
    current = id;
    await record(["start", "opencode", id, info.directory]);
  };

  return {
    config: async (config) => {
      config.command = {
        ...config.command,
        [check]: { description, template: prompt },
      };
    },
    // Record the session before the check looks for it, since the command
    // may be its first prompt, then add the check's output to the prompt.
    "command.execute.before": async ({ command, sessionID }, output) => {
      if (command !== check) return;
      await enqueue(() => show(sessionID));
      const result = await runCheck(sessionID);
      const part = output.parts.find((part) => part.type === "text");
      if (!part) return;
      part.text += `\n\n${checkText(result)}\n`;
    },
    event: async ({ event }) => {
      if (event.type !== "session.created" && event.type !== "session.updated") {
        return;
      }
      remember(event.properties.info);
      if (event.type === "session.created") {
        enqueue(() => show(event.properties.info?.id));
      }
    },
    "chat.message": async (input) => {
      enqueue(() => show(input.sessionID));
    },
    dispose: async () => {
      await enqueue(() => current && record(["end", "opencode", current]));
    },
  };
};
