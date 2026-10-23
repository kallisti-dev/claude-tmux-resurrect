// What the OpenCode 1 and OpenCode 2 plugins share: recording sessions and
// running the check for /tmux-resurrect-check.
// SPDX-License-Identifier: BSD-3-Clause
import { fileURLToPath } from "node:url";

const path = (file) => fileURLToPath(new URL(`../${file}`, import.meta.url));
const recorder = path("bin/tmux-agent-resurrect-record");
const checker = path("bin/tmux-agent-resurrect-check");
// The check gives up on each command it runs well before this.
const checkSeconds = 30;

export const check = "tmux-resurrect-check";
export const description =
  "Check whether tmux-resurrect can resume this OpenCode session";
export const prompt = `Summarize the result of tmux-agent-resurrect-check below, which reports whether the tmux server, this pane, and OpenCode are set up so that tmux-resurrect can resume this session. For each line marked \`problem\`, explain the cause and the fix, using \`${path("docs/troubleshooting.md")}\`. Change configuration only if the user asks.`;

// Return a function that runs tasks one at a time, in order, and keeps their
// failures from OpenCode. It returns a promise that settles after the task.
export const serialize = () => {
  let queue = Promise.resolve();
  return (task) => (queue = queue.then(task).catch(() => {}));
};

// Without an env option, Bun.spawn passes the environment from startup, not
// variables OpenCode sets later. An argv array runs no shell. With a limit in
// milliseconds, kill the process once it has run that long and resolve to
// null.
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

export const record = (args) => run([recorder, ...args]);

// Resolve to the check's output, for the session if one is given, or to null
// if it doesn't finish in time.
export const runCheck = (session) =>
  run(session ? [checker, "--session", session] : [checker], {
    output: "pipe",
    limit: checkSeconds * 1000,
  });

// The check's output, as text for a prompt.
export const checkText = (result) =>
  result === null
    ? `tmux-agent-resurrect-check did not finish within ${checkSeconds} seconds.`
    : `\`\`\`\n${result.trimEnd()}\n\`\`\``;
