// OpenCode 1.x plugin: report the session this OpenCode TUI works in to the
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
// SPDX-License-Identifier: BSD-3-Clause
import { fileURLToPath } from "node:url";
import { isMainThread } from "node:worker_threads";

const recorder = fileURLToPath(
  new URL("../bin/tmux-agent-resurrect-record", import.meta.url),
);

export const TmuxAgentResurrect = async ({ client }) => {
  // The TUI runs plugins in a worker thread with the pane's environment.
  // `opencode run`, `serve`, and `web` run them on the main thread, and are
  // not interactive sessions in the user's pane.
  if (isMainThread) return {};

  const sessions = new Map(); // session ID -> { parentID, directory }
  let current;
  let queue = Promise.resolve();
  // Run tasks one at a time, in order, and keep failures from OpenCode.
  const enqueue = (task) => (queue = queue.then(task).catch(() => {}));

  const remember = (info) => {
    if (info?.id) {
      sessions.set(info.id, {
        parentID: info.parentID,
        directory: info.directory,
      });
    }
  };
  // Without an env option, Bun.spawn passes the environment from startup,
  // not variables OpenCode sets later. An argv array runs no shell.
  const record = async (args) => {
    const child = Bun.spawn([recorder, ...args], {
      env: process.env,
      stdin: "ignore",
      stdout: "ignore",
      stderr: "ignore",
    });
    await child.exited;
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
      enqueue(() => current && record(["end", "opencode", current]));
      await queue;
    },
  };
};
