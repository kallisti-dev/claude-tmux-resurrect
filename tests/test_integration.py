"""Real scripts and real tmux, exclusively against disposable test state."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SOURCE = Path(os.environ.get("INSTALL_SOURCE", ROOT))
BIN = Path(os.environ.get("PROJECT_BIN", ROOT / "bin"))
BASH = shutil.which("bash")
TMUX = shutil.which("tmux")
PYTHON = shutil.which("python3")
RESURRECT = os.environ.get("RESURRECT_SOURCE")
ID = "11111111-2222-3333-4444-555555555555"


def wait_until(predicate, message, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.025)
    raise AssertionError(message)


class Integration(unittest.TestCase):
    def setUp(self):
        # A short socket path also works within Darwin's sockaddr_un limit.
        self.tmp = tempfile.TemporaryDirectory(prefix="ctr-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.cwd = self.home / "project"
        self.cwd.mkdir()
        self.snapdir = self.home / "snapshots"
        self.snapdir.mkdir()
        self.snapshot = self.snapdir / "tmux_resurrect_test.txt"
        self.stubdir = self.base / "stub"
        self.stubdir.mkdir()
        self.log = self.base / "launches.jsonl"
        self.socket = self.base / "tmux.sock"
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.stubdir}:{BIN}:{os.environ['PATH']}",
            "TERM": "xterm-256color",
            "SHELL": BASH,
            "LC_ALL": "C",
            "TMPDIR": str(self.base),
            "CLAUDE_TEST_LOG": str(self.log),
        }
        # The only executable named claude available before the inherited PATH
        # is this stub. It logs argv/cwd and holds the pane until teardown.
        stub = self.stubdir / "claude"
        stub.write_text(
            f"#!{PYTHON}\n"
            "import json, os, sys, time\n"
            "with open(os.environ['CLAUDE_TEST_LOG'], 'a') as f:\n"
            "    f.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
            "time.sleep(120)\n"
        )
        stub.chmod(0o755)
        config = self.base / "tmux.conf"
        config.write_text(
            f"set -g default-shell {shlex.quote(BASH)}\n"
            f"set -g default-command {shlex.quote(BASH + ' --noprofile --norc')}\n"
            # Snapshot comparisons need names independent of transient commands.
            "set -g automatic-rename off\n"
            "set -g status off\n"
            "set -g exit-empty off\n"
            "set -g remain-on-exit off\n"
            "set -g base-index 0\n"
            "set -g pane-base-index 0\n"
        )
        self.run_command(
            [
                TMUX,
                "-S",
                str(self.socket),
                "-f",
                str(config),
                "new-session",
                "-d",
                "-s",
                "work",
                "-c",
                str(self.cwd),
            ]
        )
        self.addCleanup(self.stop_server)
        # No script or upstream process ever receives the caller's TMUX value.
        self.env["TMUX"] = f"{self.socket},0,0"
        self.env["TMUX_PANE"] = "%0"
        self.tmux("set", "-g", "@resurrect-dir", str(self.snapdir))
        self.pane = self.tmux(
            "display", "-p", "-t", "work", "#{pane_id}"
        ).stdout.strip()
        self.session = self.tmux(
            "display", "-p", "-t", "work", "#{session_id}"
        ).stdout.strip()
        self.clients = []

    def run_command(self, args, *, data=None, env=None, check=True):
        result = subprocess.run(
            args,
            input=data,
            text=True,
            capture_output=True,
            env=self.env if env is None else env,
            cwd=ROOT,
            timeout=15,
            check=False,
        )
        if check and result.returncode:
            self.fail(
                f"Command failed ({result.returncode}): {args!r}\n{result.stdout}\n{result.stderr}"
            )
        return result

    def tmux(self, *args, **kwargs):
        return self.run_command([TMUX, "-S", str(self.socket), *args], **kwargs)

    def script(self, name, *args, data=None, env=None, check=True):
        return self.run_command(
            [str(BIN / name), *map(str, args)], data=data, env=env, check=check
        )

    def stop_server(self):
        # Never issue kill-server without the explicit test socket.
        assert self.socket.parent == self.base and self.base.name.startswith("ctr-")
        self.tmux("kill-server", check=False)
        for client in getattr(self, "clients", []):
            try:
                client.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                client.kill()
                client.communicate()

    def transcript(self, cwd=None, session_id=ID):
        path = (
            self.home
            / ".claude"
            / "projects"
            / "-synthetic-project"
            / f"{session_id}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = (ROOT / "tests/fixtures/transcript.jsonl").read_text().splitlines()
        lines[2] = json.dumps({"type": "system", "cwd": str(cwd or self.cwd)})
        path.write_text("\n".join(lines) + "\n")
        return path

    def hook(self, event, session_id=ID, **kwargs):
        return self.script(
            "claude-tmux-resurrect-hook",
            data=json.dumps({"hook_event_name": event, "session_id": session_id}),
            **kwargs,
        )

    def option(self, name, pane=None):
        return self.tmux("show", "-pqv", "-t", pane or self.pane, name).stdout.strip()

    def write_snapshot(self, command="claude", full="claude --resume", session="work"):
        # Includes an unrelated process and an empty title, exercising exact
        # tab positions rather than whitespace-collapsing shell reads.
        self.snapshot.write_text(
            "\t".join(
                [
                    "pane",
                    session,
                    "0",
                    "1",
                    ":*",
                    "0",
                    "",
                    ":" + str(self.cwd),
                    "1",
                    command,
                    ":" + full,
                ]
            )
            + "\n"
            + "pane\tother\t0\t1\t:*\t0\tvim\t:/synthetic\t1\tvim\t:vim notes\n"
        )
        return self.snapshot

    def records(self, snapshot=None):
        return [
            json.loads(line.split("\t", 1)[1])
            for line in (snapshot or self.snapshot).read_text().splitlines()
            if line.startswith("claude-tmux\t")
        ]

    def save(self, cwd=None, session="work"):
        self.transcript(cwd)
        self.hook("SessionStart")
        self.write_snapshot(session=session)
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.hook("SessionEnd")

    def attach(self, session="work"):
        env = {k: v for k, v in self.env.items() if k not in {"TMUX", "TMUX_PANE"}}
        client = subprocess.Popen(
            [TMUX, "-S", str(self.socket), "-C", "attach-session", "-t", session],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.clients.append(client)
        wait_until(
            lambda: (
                self.tmux(
                    "display", "-p", "-t", "=" + session, "#{session_attached}"
                ).stdout.strip()
                != "0"
            ),
            "client did not attach",
        )
        return client

    def launches(self):
        return (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )

    def expect_launches(self, count):
        wait_until(lambda: len(self.launches()) >= count, f"expected {count} launches")
        self.assertEqual(len(self.launches()), count)
        return self.launches()

    def load_hooks(self):
        readme = (ROOT / "README.md").read_text()
        configuration = readme.split("```tmux\n", 1)[1].split("```", 1)[0]
        config = self.base / "integration.conf"
        config.write_text(configuration)
        self.tmux("source-file", str(config))

    def global_option(self, name):
        return self.tmux("show", "-gqv", name).stdout.strip()

    def native_hooks(self, event):
        return self.tmux("show-hooks", "-g", event).stdout.splitlines()

    def execute_resurrect_hook(self, phase, *args, check=True):
        # Match upstream execute_hook: quote each argument, then evaluate the
        # configured command with those arguments appended.
        return self.run_command(
            [
                BASH,
                "-c",
                'hook=$1; shift; args=""; '
                'if [ "$#" -gt 0 ]; then printf -v args "%q " "$@"; fi; '
                'eval "$hook $args"',
                "resurrect-hook",
                self.global_option("@resurrect-hook-" + phase),
                *map(str, args),
            ],
            check=check,
        )

    def previous_hook(self, phase, *, status=0):
        callback = self.base / "previous hook.py"
        if not callback.exists():
            callback.write_text(
                "import json, os, subprocess, sys\n"
                "phase, output, status = sys.argv[1:4]\n"
                "gate = subprocess.check_output(\n"
                "    ['tmux', 'show', '-gqv', '@claude_restoring'], text=True).strip()\n"
                "with open(output, 'a') as stream:\n"
                "    stream.write(json.dumps({'phase': phase, 'args': sys.argv[4:],\n"
                "                             'gate': gate}) + '\\n')\n"
                "sys.exit(int(status))\n"
            )
        return shlex.join(
            [
                PYTHON,
                str(callback),
                phase,
                str(self.base / "previous.jsonl"),
                str(status),
            ]
        )

    def previous_calls(self):
        return [
            json.loads(line)
            for line in (self.base / "previous.jsonl").read_text().splitlines()
        ]

    def test_setup_uses_direct_commands_and_rejects_recapturing_them(self):
        self.load_hooks()
        for phase, script in [
            ("post-save-layout", "claude-tmux-resurrect-save"),
            ("pre-restore-all", "claude-tmux-resurrect-pre-restore"),
            ("post-restore-all", "claude-tmux-resurrect-post-restore"),
        ]:
            self.assertEqual(
                shlex.split(self.global_option("@resurrect-hook-" + phase)),
                [str(BIN / script)],
            )
        option = "@resurrect-hook-post-save-layout"
        external = self.global_option(option) + "; : another-action"
        self.tmux("set", "-g", option, external)
        result = self.script("claude-tmux-resurrect-setup", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(option, result.stderr)
        self.assertIn("reset", result.stderr)
        self.assertEqual(self.global_option(option), external)

    def test_setup_preserves_hooks_and_reloads_without_duplicates(self):
        original = self.previous_hook("save")
        self.tmux("set", "-g", "@resurrect-hook-post-save-layout", original)
        foreign = {}
        for event in ["client-attached", "client-session-changed"]:
            self.tmux(
                "set-hook",
                "-g",
                event + "[731]",
                "set-option -g @foreign-handler yes",
            )
            foreign[event] = self.native_hooks(event)
        self.load_hooks()
        installed_hooks = {event: self.native_hooks(event) for event in foreign}
        installed_save = self.global_option("@resurrect-hook-post-save-layout")
        for event, handlers in installed_hooks.items():
            self.assertEqual(len(handlers), len(foreign[event]) + 1)
            self.assertTrue(set(foreign[event]).issubset(handlers))
        self.load_hooks()
        self.assertEqual(
            self.global_option("@resurrect-hook-post-save-layout"), installed_save
        )
        for event, handlers in installed_hooks.items():
            self.assertEqual(self.native_hooks(event), handlers)

        replacements = {}
        for event, handlers in installed_hooks.items():
            owned = set(handlers) - set(foreign[event])
            self.assertEqual(len(owned), 1)
            slot = owned.pop().split(" ", 1)[0]
            self.tmux(
                "set-hook",
                "-g",
                slot,
                "set-option -g @replacement-handler yes",
            )
            replacements[event] = self.native_hooks(event)
        self.load_hooks()
        recovered = {event: self.native_hooks(event) for event in foreign}
        for event, handlers in recovered.items():
            self.assertEqual(len(handlers), len(replacements[event]) + 1)
            self.assertTrue(set(replacements[event]).issubset(handlers))
        self.load_hooks()
        for event, handlers in recovered.items():
            self.assertEqual(self.native_hooks(event), handlers)

        self.transcript()
        self.hook("SessionStart")
        self.write_snapshot()
        self.execute_resurrect_hook("post-save-layout", self.snapshot)
        self.assertEqual(self.records()[0]["session_id"], ID)
        self.assertEqual(
            self.previous_calls(),
            [{"phase": "save", "args": [str(self.snapshot)], "gate": ""}],
        )
        self.hook("SessionEnd")
        self.execute_resurrect_hook("post-restore-all", self.snapshot)
        self.attach()
        self.assertEqual(self.expect_launches(1)[0]["argv"], ["--resume", ID])

    def test_setup_composes_arguments_and_finishes_restore_after_previous_failure(self):
        self.transcript()
        self.hook("SessionStart")
        self.write_snapshot()
        unusual = self.snapdir / "layout ' $(touch INJECTED) `false` $ #.txt"
        self.snapshot.rename(unusual)
        self.snapshot = unusual
        for phase, label, status in [
            ("post-save-layout", "save", 0),
            ("pre-restore-all", "pre", 0),
            ("post-restore-all", "post", 7),
        ]:
            self.tmux(
                "set",
                "-g",
                "@resurrect-hook-" + phase,
                self.previous_hook(label, status=status),
            )
        self.load_hooks()
        self.execute_resurrect_hook("post-save-layout", self.snapshot)
        self.assertEqual(self.records()[0]["session_id"], ID)
        self.hook("SessionEnd")
        self.execute_resurrect_hook("pre-restore-all")
        self.assertEqual(self.global_option("@claude_restoring"), "1")
        result = self.execute_resurrect_hook(
            "post-restore-all", self.snapshot, check=False
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.global_option("@claude_restoring"), "")
        self.assertIn(ID, self.option("@claude_resume_cmd"))
        self.assertFalse((ROOT / "INJECTED").exists())
        self.assertEqual(
            self.previous_calls(),
            [
                {"phase": "save", "args": [str(self.snapshot)], "gate": ""},
                {"phase": "pre", "args": [], "gate": "1"},
                {"phase": "post", "args": [str(self.snapshot)], "gate": "1"},
            ],
        )

    def test_setup_remove_restores_previous_settings_and_preserves_foreign_hooks(self):
        previous = {}
        foreign = {}
        for phase in ["post-save-layout", "pre-restore-all", "post-restore-all"]:
            previous[phase] = self.previous_hook(phase)
            self.tmux("set", "-g", "@resurrect-hook-" + phase, previous[phase])
        for event in ["client-attached", "client-session-changed"]:
            self.tmux(
                "set-hook",
                "-g",
                event + "[731]",
                "set-option -g @foreign-handler yes",
            )
            foreign[event] = self.native_hooks(event)
        self.load_hooks()
        self.script("claude-tmux-resurrect-setup", "--remove")
        self.script("claude-tmux-resurrect-setup", "--remove")
        for phase, original in previous.items():
            self.assertEqual(self.global_option("@resurrect-hook-" + phase), original)
        for event, handlers in foreign.items():
            self.assertEqual(self.native_hooks(event), handlers)

        self.load_hooks()
        external = "set-option -g @external-handler yes"
        self.tmux("set", "-g", "@resurrect-hook-post-save-layout", external)
        for event in foreign:
            owned = set(self.native_hooks(event)) - set(foreign[event])
            self.assertEqual(len(owned), 1)
            slot = owned.pop().split(" ", 1)[0]
            self.tmux("set-hook", "-g", slot, external)
        changed = {event: self.native_hooks(event) for event in foreign}
        self.script("claude-tmux-resurrect-setup", "--remove")
        self.assertEqual(
            self.global_option("@resurrect-hook-post-save-layout"), external
        )
        for event, handlers in changed.items():
            self.assertEqual(self.native_hooks(event), handlers)

    def test_setup_path_upgrade_replaces_owned_registration(self):
        self.tmux(
            "set", "-g", "@resurrect-hook-post-save-layout", self.previous_hook("save")
        )
        first = self.base / "install one ' $ #"
        second = self.base / "install two ' $ #"
        installed_hooks = None
        for prefix in [first, second]:
            # Make consumes $$ itself; the shell preserves a dollar followed
            # by a space inside the quoted destination in the install recipe.
            self.run_command(
                [
                    "make",
                    "-C",
                    str(ROOT),
                    "install",
                    f"PREFIX={str(prefix).replace('$', '$$')}",
                ]
            )
            self.run_command([BASH, str(prefix / "bin/claude-tmux-resurrect-setup")])
            hooks = {
                event: [
                    handler.split(" ", 1)[0] for handler in self.native_hooks(event)
                ]
                for event in ["client-attached", "client-session-changed"]
            }
            if installed_hooks is None:
                installed_hooks = hooks
            else:
                self.assertEqual(hooks, installed_hooks)
        shutil.rmtree(first)
        self.transcript()
        self.hook("SessionStart")
        self.write_snapshot()
        self.execute_resurrect_hook("post-save-layout", self.snapshot)
        self.assertEqual(self.records()[0]["session_id"], ID)
        self.assertEqual(len(self.previous_calls()), 1)
        self.hook("SessionEnd")
        self.execute_resurrect_hook("post-restore-all", self.snapshot)
        self.attach()
        self.assertEqual(self.expect_launches(1)[0]["argv"], ["--resume", ID])

    def test_hook_start_end_and_out_of_order_end(self):
        self.hook("SessionStart")
        self.assertEqual(self.option("@claude_session_id"), ID)
        self.hook("SessionEnd", "newer-session")
        self.assertEqual(self.option("@claude_session_id"), ID)
        self.hook("SessionEnd")
        self.assertEqual(self.option("@claude_session_id"), "")

    def test_overlapping_session_end_does_not_clear_newer_start(self):
        self.hook("SessionStart")
        # Nix wrappers prepend tmux on PATH. Copy the tested entry point and
        # library so both source and package checks can interpose the proxy.
        copied = self.base / "hook-under-test"
        (copied / "bin").mkdir(parents=True)
        library = copied / "share/claude-tmux-resurrect/lib.sh"
        library.parent.mkdir(parents=True)
        shutil.copyfile(BIN.parent / "share/claude-tmux-resurrect/lib.sh", library)
        name = "claude-tmux-resurrect-hook"
        wrapped = BIN / f".{name}-wrapped"
        hook = copied / "bin" / name
        shutil.copyfile(wrapped if wrapped.is_file() else BIN / name, hook)
        marker = self.base / "interleaved-start"
        proxy = self.stubdir / "tmux"
        # Start the new conversation after the old End's first tmux request
        # finishes, before returning its result to the old hook process.
        proxy.write_text(
            f"#!{PYTHON}\n"
            "import subprocess, sys\n"
            "from pathlib import Path\n"
            f"result = subprocess.run([{TMUX!r}, *sys.argv[1:]], capture_output=True)\n"
            f"marker = Path({str(marker)!r})\n"
            "if not marker.exists():\n"
            "    marker.touch()\n"
            f"    subprocess.run([{BASH!r}, {str(hook)!r}], check=True, text=True,\n"
            f"        input={json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'newer-session'})!r})\n"
            "sys.stdout.buffer.write(result.stdout)\n"
            "sys.stderr.buffer.write(result.stderr)\n"
            "sys.exit(result.returncode)\n"
        )
        proxy.chmod(0o755)
        self.run_command(
            [BASH, str(hook)],
            data=json.dumps({"hook_event_name": "SessionEnd", "session_id": ID}),
        )
        self.assertTrue(marker.is_file(), "tmux proxy was not exercised")
        self.assertEqual(self.option("@claude_session_id"), "newer-session")

    def test_hook_malformed_payloads_do_not_mutate(self):
        self.hook("SessionStart")
        for payload in [
            "{",
            "null",
            "[]",
            "{}",
            "{} {}",
            '{"session_id":null}',
            '{"session_id":42}',
            json.dumps(
                {"hook_event_name": "SessionStart", "session_id": "$(touch bad)"}
            ),
            json.dumps({"hook_event_name": "Stop", "session_id": ID}),
            json.dumps({"hook_event_name": "SessionStart", "session_id": ID + "\n"}),
            json.dumps({"hook_event_name": "SessionStart", "session_id": "--resume"}),
        ]:
            with self.subTest(payload=payload):
                result = self.script(
                    "claude-tmux-resurrect-hook", data=payload, check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("claude-tmux-resurrect:", result.stderr)
                self.assertEqual(self.option("@claude_session_id"), ID)

    def test_hook_outside_tmux_is_noop(self):
        env = {k: v for k, v in self.env.items() if k not in {"TMUX", "TMUX_PANE"}}
        self.script("claude-tmux-resurrect-hook", data="not json", env=env)

    def test_save_changed_cwd_suppresses_generic_restart(self):
        changed = self.home / "changed directory"
        changed.mkdir()
        self.save(changed)
        self.assertEqual(self.records()[0]["cwd"], str(changed))
        self.assertEqual(self.snapshot.read_text().splitlines()[0].split("\t")[10], ":")
        self.assertIn("\t:vim notes", self.snapshot.read_text())
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o600)

    def test_hook_id_detects_node_process(self):
        self.transcript()
        self.hook("SessionStart")
        self.write_snapshot(command="node", full="node cli.js")
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.snapshot.read_text().splitlines()[0].split("\t")[10], ":")

    def test_claude_without_metadata_is_suppressed(self):
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.records(), [])
        self.assertEqual(self.snapshot.read_text().splitlines()[0].split("\t")[10], ":")

    def test_save_missing_transcript_falls_back_to_pane_cwd(self):
        self.hook("SessionStart")
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.records()[0]["cwd"], str(self.cwd.resolve()))

    def test_exact_resume_is_deferred_then_fires_once(self):
        self.save()
        self.load_hooks()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.script("claude-tmux-resurrect-arm", self.session)
        self.assertEqual(self.launches(), [])
        self.assertIn(ID, self.option("@claude_resume_cmd"))
        self.attach()
        launch = self.expect_launches(1)[0]
        self.assertEqual(
            launch, {"argv": ["--resume", ID], "cwd": str(self.cwd.resolve())}
        )
        wait_until(
            lambda: self.option("@claude_resume_cmd") == "",
            "pending command not cleared",
        )
        self.attach()
        self.script("claude-tmux-resurrect-arm", self.session)
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        time.sleep(0.15)
        self.assertEqual(len(self.launches()), 1)

    def test_attached_session_is_launched_after_restore(self):
        self.save()
        self.attach()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.expect_launches(1)

    def test_paths_and_session_names_with_spaces_and_shell_metacharacters(self):
        session = "team space ' $(false)"
        self.tmux("rename-session", "-t", self.session, session)
        changed = self.home / "quote' space $(touch INJECTED) `false` \\ path"
        changed.mkdir()
        self.save(changed, session=session)
        self.load_hooks()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.attach(session)
        self.assertEqual(self.expect_launches(1)[0]["cwd"], str(changed.resolve()))
        self.assertFalse((self.cwd / "INJECTED").exists())

    def test_named_worktree_resume_from_main_repository(self):
        worktree = self.cwd / ".claude/worktrees/feature space/subdir"
        worktree.mkdir(parents=True)
        self.save(worktree)
        self.attach()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertEqual(
            self.expect_launches(1)[0],
            {
                "argv": ["--resume", ID, "--worktree", "feature space"],
                "cwd": str(self.cwd.resolve()),
            },
        )

    def test_missing_transcript_skips_without_picker(self):
        self.save()
        self.transcript().unlink()
        result = self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertIn("missing or ambiguous transcript", result.stderr)
        self.assertEqual(self.option("@claude_resume_cmd"), "")
        self.assertEqual(self.launches(), [])

    def test_ambiguous_transcript_is_not_chosen_arbitrarily(self):
        self.save()
        duplicate = self.home / ".claude/projects/duplicate" / f"{ID}.jsonl"
        duplicate.parent.mkdir()
        duplicate.write_text(self.transcript().read_text())
        result = self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertIn("ambiguous", result.stderr)
        self.assertEqual(self.option("@claude_resume_cmd"), "")

    def test_missing_directory_and_empty_transcript_skip(self):
        self.save()
        self.cwd.rmdir()
        self.assertIn(
            "no longer exists",
            self.script("claude-tmux-resurrect-post-restore", self.snapshot).stderr,
        )
        self.cwd.mkdir()
        self.transcript().write_text("")
        self.assertIn(
            "empty transcript",
            self.script("claude-tmux-resurrect-post-restore", self.snapshot).stderr,
        )

    def test_invalid_snapshot_metadata_and_missing_panes(self):
        self.save()
        good = self.records()[0]
        bad = [
            None,
            {},
            dict(good, version=9),
            dict(good, session_id="../../bad"),
            dict(good, cwd="relative"),
            dict(good, cwd="/bad\nline"),
            dict(good, worktree="../bad"),
        ]
        self.snapshot.write_text(
            "claude-tmux\t{broken\n"
            + "".join(
                "claude-tmux\t" + json.dumps(record) + "\n"
                for record in bad + [dict(good, session="missing")]
            )
        )
        result = self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertIn("invalid session metadata", result.stderr)
        self.assertEqual(self.option("@claude_resume_cmd"), "")

    def test_metadata_is_specific_to_snapshot(self):
        self.save()
        earlier = self.snapdir / "earlier.txt"
        shutil.copyfile(self.snapshot, earlier)
        self.transcript(session_id="second-session")
        self.hook("SessionStart", "second-session")
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.hook("SessionEnd", "second-session")
        self.assertEqual(self.records()[0]["session_id"], "second-session")
        self.script("claude-tmux-resurrect-post-restore", earlier)
        self.assertIn(ID, self.option("@claude_resume_cmd"))

    def test_save_before_attach_preserves_pending_mapping_and_is_idempotent(self):
        self.save()
        expected = self.records()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.write_snapshot(command="bash", full="bash")
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.records(), expected)
        original = self.snapshot.read_bytes()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_restore_gate_ignores_intermediate_session_switches(self):
        self.save()
        self.load_hooks()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.script("claude-tmux-resurrect-pre-restore")
        self.assertEqual(
            self.tmux("show", "-gqv", "@claude_restoring").stdout.strip(), "1"
        )
        self.attach()
        self.script("claude-tmux-resurrect-arm", self.session)
        self.assertEqual(self.launches(), [])
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertEqual(
            self.tmux("show", "-gqv", "@claude_restoring").stdout.strip(), ""
        )
        self.expect_launches(1)

    def test_switching_client_to_pending_session_launches(self):
        self.save()
        self.load_hooks()
        self.tmux("new-session", "-d", "-s", "other", "-c", str(self.cwd))
        self.attach("other")
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertEqual(self.launches(), [])
        self.tmux("switch-client", "-t", self.session)
        self.expect_launches(1)

    def test_two_simultaneous_arm_calls_launch_once(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.attach()
        args = [str(BIN / "claude-tmux-resurrect-arm"), self.session]
        processes = [
            subprocess.Popen(
                args, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            for _ in range(2)
        ]
        for process in processes:
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
        self.expect_launches(1)

    def test_stale_pending_transcript_rechecked_at_attach(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.transcript().unlink()
        self.attach()
        self.assertIn(
            "missing or ambiguous",
            self.script("claude-tmux-resurrect-arm", self.session).stderr,
        )
        self.assertEqual(self.option("@claude_resume_cmd"), "")
        self.assertEqual(self.launches(), [])

    def test_busy_pane_remains_pending(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.tmux("send-keys", "-t", self.pane, "sleep 120", "Enter")
        wait_until(
            lambda: (
                self.tmux(
                    "display", "-p", "-t", self.pane, "#{pane_current_command}"
                ).stdout.strip()
                not in {"bash", "sh", "zsh"}
            ),
            "sleep not running",
        )
        self.attach()
        self.assertIn(
            "not at a supported shell",
            self.script("claude-tmux-resurrect-arm", self.session).stderr,
        )
        self.assertNotEqual(self.option("@claude_resume_cmd"), "")
        self.assertEqual(self.launches(), [])

    def test_missing_snapshot_and_no_tmux_have_useful_diagnostics(self):
        self.script("claude-tmux-resurrect-pre-restore")
        self.assertIn(
            "snapshot not found",
            self.script("claude-tmux-resurrect-post-restore", self.snapshot).stderr,
        )
        self.assertEqual(
            self.tmux("show", "-gqv", "@claude_restoring").stdout.strip(), ""
        )
        env = dict(self.env, TMUX="")
        result = self.script(
            "claude-tmux-resurrect-save", self.snapshot, env=env, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run inside tmux", result.stderr)

    def test_restore_replaces_stale_pending_set(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertNotEqual(self.option("@claude_resume_data"), "")
        self.write_snapshot()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertEqual(self.option("@claude_resume_data"), "")
        self.assertEqual(self.option("@claude_resume_cmd"), "")
        self.attach()
        self.script("claude-tmux-resurrect-arm", self.session)
        self.assertEqual(self.launches(), [])

    def test_copy_mode_remains_pending(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.tmux("copy-mode", "-t", self.pane)
        self.attach()
        result = self.script("claude-tmux-resurrect-arm", self.session)
        self.assertIn("copy mode", result.stderr)
        self.assertNotEqual(self.option("@claude_resume_data"), "")
        self.assertEqual(self.launches(), [])
        self.tmux("send-keys", "-X", "-t", self.pane, "cancel")
        self.script("claude-tmux-resurrect-arm", self.session)
        self.expect_launches(1)

    def test_custom_claude_config_dir(self):
        self.save()
        custom = self.home / "custom config"
        (self.home / ".claude").rename(custom)
        self.env["CLAUDE_CONFIG_DIR"] = str(custom)
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.assertIn(ID, self.option("@claude_resume_cmd"))

    def test_explicit_snapshot_path_with_spaces_and_symlink_rejection(self):
        self.transcript()
        self.hook("SessionStart")
        self.write_snapshot()
        renamed = self.snapdir / "saved layout.txt"
        self.snapshot.rename(renamed)
        self.script("claude-tmux-resurrect-save", renamed)
        self.hook("SessionEnd")
        link = self.snapdir / "last"
        link.symlink_to(renamed.name)
        self.assertIn(
            "not a symlink",
            self.script("claude-tmux-resurrect-save", link, check=False).stderr,
        )
        self.script("claude-tmux-resurrect-post-restore")
        self.assertIn(ID, self.option("@claude_resume_cmd"))

    def test_inconsistent_worktree_metadata_skips(self):
        self.save()
        record = dict(self.records()[0], worktree="not-this-directory")
        self.snapshot.write_text("claude-tmux\t" + json.dumps(record) + "\n")
        self.assertIn(
            "inconsistent worktree",
            self.script("claude-tmux-resurrect-post-restore", self.snapshot).stderr,
        )
        self.assertEqual(self.option("@claude_resume_cmd"), "")

    def test_missing_claude_leaves_pending_for_retry(self):
        self.save()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        self.attach()
        sparse = self.base / "without-claude"
        sparse.mkdir()
        for command in ["tmux", "jq"]:
            (sparse / command).symlink_to(shutil.which(command))
        # Run the source entry point directly: no host PATH and no real Claude.
        result = self.run_command(
            [BASH, str(ROOT / "bin/claude-tmux-resurrect-arm"), self.session],
            env=dict(self.env, PATH=str(sparse)),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required command not found on PATH: claude", result.stderr)
        self.assertNotEqual(self.option("@claude_resume_data"), "")
        self.script("claude-tmux-resurrect-arm", self.session)
        self.expect_launches(1)

    def test_missing_jq_reports_dependency(self):
        # Exercise the ordinary source script: Nix wrappers supply jq by design.
        sparse = self.base / "sparse"
        sparse.mkdir()
        (sparse / "tmux").symlink_to(TMUX)
        result = self.run_command(
            [BASH, str(ROOT / "bin/claude-tmux-resurrect-hook")],
            data="{}",
            env=dict(self.env, PATH=str(sparse)),
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required command not found on PATH: jq", result.stderr)

    def test_normal_install_works_in_prefix_with_spaces(self):
        prefix = self.base / "install space"
        self.run_command(
            ["make", "-C", str(INSTALL_SOURCE), "install", f"PREFIX={prefix}"]
        )
        self.assertEqual(
            {path.name for path in (prefix / "bin").iterdir()},
            {
                "claude-tmux-resurrect-hook",
                "claude-tmux-resurrect-save",
                "claude-tmux-resurrect-pre-restore",
                "claude-tmux-resurrect-post-restore",
                "claude-tmux-resurrect-arm",
                "claude-tmux-resurrect-setup",
            },
        )
        self.assertTrue((prefix / "share/claude-tmux-resurrect/lib.sh").is_file())
        self.assertFalse((prefix / "lib.sh").exists())
        installed = prefix / "bin/claude-tmux-resurrect-hook"
        self.run_command(
            [BASH, str(installed)],
            data=json.dumps({"hook_event_name": "SessionStart", "session_id": ID}),
        )
        self.assertEqual(self.option("@claude_session_id"), ID)
        self.assertNotIn("/nix/store", installed.read_text())
        self.run_command(["make", "uninstall", f"PREFIX={prefix}"])
        self.assertFalse(installed.exists())

    @unittest.skipUnless(
        RESURRECT, "RESURRECT_SOURCE is supplied by nix develop / flake checks"
    )
    def test_real_resurrect_save_restore_and_snapshot_deduplication(self):
        self.transcript()
        self.hook("SessionStart")
        self.load_hooks()
        self.tmux("set", "-g", "@resurrect-processes", ":all:")
        self.run_command([BASH, str(Path(RESURRECT) / "scripts/save.sh"), "quiet"])
        last = self.snapdir / "last"
        self.assertTrue(last.is_file())
        self.assertEqual(self.records(last)[0]["session_id"], ID)
        saved = last.read_bytes()
        # Upstream names snapshots to the second; a same-second save would
        # overwrite its own comparison target. Test dedup across distinct names.
        saved_second = int(last.stat().st_mtime)
        wait_until(lambda: int(time.time()) > saved_second, "clock did not advance")
        self.run_command([BASH, str(Path(RESURRECT) / "scripts/save.sh"), "quiet"])
        self.assertEqual(last.read_bytes(), saved)
        self.hook("SessionEnd")
        # Keep server alive while removing the saved session, then restore it.
        self.tmux("new-session", "-d", "-s", "bootstrap", "-c", str(self.cwd))
        self.tmux("new-window", "-t", "bootstrap")
        self.tmux("kill-session", "-t", self.session)
        result = self.run_command([BASH, str(Path(RESURRECT) / "scripts/restore.sh")])
        self.assertNotIn("claude-tmux-resurrect:", result.stderr)
        self.pane = self.tmux(
            "display", "-p", "-t", "work:0.0", "#{pane_id}"
        ).stdout.strip()
        self.assertIn(ID, self.option("@claude_resume_cmd"))
        self.assertEqual(self.launches(), [])
        self.attach()
        self.assertEqual(self.expect_launches(1)[0]["argv"], ["--resume", ID])

    @unittest.skipUnless(RESURRECT, "RESURRECT_SOURCE is supplied by Nix")
    def test_real_resurrect_attached_restore_keeps_other_sessions_deferred(self):
        self.transcript()
        self.hook("SessionStart")
        self.tmux("new-session", "-d", "-s", "later", "-c", str(self.cwd))
        later_pane = self.tmux(
            "display", "-p", "-t", "later", "#{pane_id}"
        ).stdout.strip()
        self.transcript(session_id="later-id")
        self.hook("SessionStart", "later-id", env=dict(self.env, TMUX_PANE=later_pane))
        self.load_hooks()
        self.attach()
        self.run_command([BASH, str(Path(RESURRECT) / "scripts/save.sh"), "quiet"])
        self.assertEqual(len(self.records(self.snapdir / "last")), 2)
        self.tmux("new-session", "-d", "-s", "bootstrap", "-c", str(self.cwd))
        self.tmux("new-window", "-t", "bootstrap")
        self.tmux("switch-client", "-t", "bootstrap")
        self.tmux("kill-session", "-t", self.session)
        self.tmux("kill-session", "-t", "=later")
        self.run_command([BASH, str(Path(RESURRECT) / "scripts/restore.sh")])
        self.assertEqual(self.expect_launches(1)[0]["argv"], ["--resume", ID])
        later_pane = self.tmux(
            "display", "-p", "-t", "later", "#{pane_id}"
        ).stdout.strip()
        self.assertIn("later-id", self.option("@claude_resume_cmd", later_pane))
        self.tmux("switch-client", "-t", "=later")
        self.assertEqual(self.expect_launches(2)[1]["argv"], ["--resume", "later-id"])


if __name__ == "__main__":
    unittest.main()
