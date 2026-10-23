// OpenCode 2 TUI plugin: report the session this TUI shows to the
// tmux-agent-resurrect recorder, which records it on the tmux pane. OpenCode
// runs it in each TUI's own process, with the pane's environment.
//
//   tmux-agent-resurrect-record start opencode SESSION_ID DIRECTORY
//     when the TUI shows a different root session
//   tmux-agent-resurrect-record end opencode SESSION_ID
//     when the TUI exits
//
// It also adds /tmux-resurrect-check, which runs tmux-agent-resurrect-check
// for the session and has OpenCode explain the result.
// SPDX-License-Identifier: BSD-3-Clause
import { createEffect, createRoot } from "solid-js";
import {
  check,
  checkText,
  description,
  prompt,
  record,
  runCheck,
  serialize,
} from "./shared.js";

export default {
  id: "tmux-agent-resurrect",
  setup(ctx) {
    let current; // { id, directory }
    const enqueue = serialize();

    // The root session of the session the TUI shows, once OpenCode has its
    // directory. Subagent sessions have a parent; report the root session.
    const shown = () => {
      const route = ctx.ui.router.current();
      if (route.type !== "session") return;
      const id = ctx.data.session.root(route.sessionID);
      const directory = ctx.data.session.get(id)?.location.directory;
      return directory && { id, directory };
    };
    const show = (session) =>
      enqueue(async () => {
        if (
          current?.id === session.id &&
          current.directory === session.directory
        ) {
          return;
        }
        current = session;
        await record(["start", "opencode", session.id, session.directory]);
      });

    // The route and session data are reactive, so this runs again when the
    // TUI shows another session.
    const stop = createRoot((dispose) => {
      createEffect(() => {
        const session = shown();
        if (session) show(session);
      });
      return dispose;
    });

    ctx.keymap.layer(() => ({
      // A layer in the default mode is unreachable from the prompt.
      mode: "global",
      commands: [
        {
          id: "tmux-agent-resurrect.check",
          description,
          slash: { name: check },
          run: async () => {
            const session = shown();
            if (!session) {
              const result = await runCheck();
              await ctx.ui.dialog.alert({
                title: "tmux-agent-resurrect-check",
                message: result === null ? checkText(result) : result.trimEnd(),
              });
              return;
            }
            // Record the session before the check looks for it.
            await show(session);
            const result = await runCheck(session.id);
            await ctx.client.session.prompt({
              sessionID: session.id,
              text: `${prompt}\n\n${checkText(result)}\n`,
            });
          },
        },
      ],
    }));

    return async () => {
      stop();
      await enqueue(() => current && record(["end", "opencode", current.id]));
    };
  },
};
