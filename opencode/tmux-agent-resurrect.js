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
//
// It also adds /tmux-resurrect-check, which runs tmux-agent-resurrect-check
// for the session and has OpenCode explain the result.
// SPDX-License-Identifier: BSD-3-Clause
import { fileURLToPath } from "node:url";
import { isMainThread } from "node:worker_threads";

const path = (file) => fileURLToPath(new URL(`../${file}`, import.meta.url));
const recorder = path("bin/tmux-agent-resurrect-record");
const checker = path("bin/tmux-agent-resurrect-check");
const check = "tmux-resurrect-check";
// The check gives up on each command it runs well before this.
const checkSeconds = 30;

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
  // not variables OpenCode sets later. An argv array runs no shell. With a
  // limit in milliseconds, kill the process once it has run that long and
  // resolve to null.
  const run = async (argv, { output = "ignore", limit } = {}) => {
    const child = Bun.spawn(argv, {
      env: process.env,
      stdin: "ignore",
      stdout: output,
      stderr: output,
    });
    const finished = Promise.all(
      [child.stdout, child.stderr].map((stream) =>
        stream ? new Response(stream).text() : "",
      ),
    ).then(async ([stdout, stderr]) => {
      await child.exited;
      return stdout + stderr;
    });
    if (!limit) return finished;
    let timer;
    const expired = new Promise((resolve) => {
      timer = setTimeout(resolve, limit, null);
    });
    const result = await Promise.race([finished, expired]);
    clearTimeout(timer);
    if (result === null) child.kill("SIGKILL");
    return result;
  };
  const record = (args) => run([recorder, ...args]);
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
        [check]: {
          description:
            "Check whether tmux-resurrect can resume this OpenCode session",
          template: `Summarize the result of tmux-agent-resurrect-check below, which reports whether the tmux server, this pane, and OpenCode are set up so that tmux-resurrect can resume this session. For each line marked \`problem\`, explain the cause and the fix, using \`${path("docs/troubleshooting.md")}\`. Change configuration only if the user asks.`,
        },
      };
    },
    // Record the session before the check looks for it, since the command
    // may be its first prompt, then add the check's output to the prompt.
    "command.execute.before": async ({ command, sessionID }, output) => {
      if (command !== check) return;
      await enqueue(() => show(sessionID));
      const result = await run([checker, "--session", sessionID], {
        output: "pipe",
        limit: checkSeconds * 1000,
      });
      const part = output.parts.find((part) => part.type === "text");
      if (!part) return;
      part.text +=
        result === null
          ? `\n\ntmux-agent-resurrect-check did not finish within ${checkSeconds} seconds.\n`
          : `\n\n\`\`\`\n${result.trimEnd()}\n\`\`\`\n`;
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
      enqueue(() => current && record(["end", "opencode", current]));
      await queue;
    },
  };
};
