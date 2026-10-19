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
# The packaging check points this at the built plugin instead of the source.
PLUGIN_ROOT = Path(os.environ.get("PLUGIN_ROOT", ROOT))
PLUGIN_FILES = ["claude-tmux-resurrect.tmux", "bin", "lib", "hooks", ".claude-plugin"]
BIN = PLUGIN_ROOT / "bin"
ENTRY = PLUGIN_ROOT / "claude-tmux-resurrect.tmux"
BASH = shutil.which("bash")
TMUX = shutil.which("tmux")
PYTHON = shutil.which("python3")
GIT = shutil.which("git")
RESURRECT = os.environ.get("RESURRECT_SOURCE")
TPM = os.environ.get("TPM_SOURCE")
CLAUDE = os.environ.get("CLAUDE_BINARY")
ID = "11111111-2222-3333-4444-555555555555"


def system_plugins():
    try:
        return "@plugin" in Path("/etc/tmux.conf").read_text()
    except OSError:
        return False


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
        # Control-mode output, including %message lines, is kept for messages().
        output = self.base / f"client-{len(self.clients)}.out"
        with output.open("w") as stream:
            client = subprocess.Popen(
                [TMUX, "-S", str(self.socket), "-C", "attach-session", "-t", session],
                stdin=subprocess.PIPE,
                stdout=stream,
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

    def messages(self):
        # display-message reaches control-mode clients as %message lines.
        return [
            line.removeprefix("%message ")
            for path in sorted(self.base.glob("client-*.out"))
            for line in path.read_text().splitlines()
            if line.startswith("%message ")
        ]

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

    def load_plugin(self, entry=ENTRY):
        # run-shell expands formats in its command before the shell runs it.
        self.tmux("run-shell", shlex.quote(str(entry)).replace("#", "##"))

    def global_option(self, name):
        return self.tmux("show", "-gqv", name).stdout.strip()

    def plugin_dirs(self):
        result = self.tmux(
            "show-environment", "-g", "CLAUDE_CODE_PLUGIN_DIRS", check=False
        )
        _, separator, value = result.stdout.rstrip("\n").partition("=")
        return value if result.returncode == 0 and separator else None

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

    def run_with_git(self, *args):
        # Keep host Git configuration out of test repositories and clones.
        return self.run_command(
            [str(arg) for arg in args],
            env=dict(
                self.env,
                GIT_CONFIG_NOSYSTEM="1",
                GIT_AUTHOR_NAME="Test",
                GIT_AUTHOR_EMAIL="test@example.invalid",
                GIT_COMMITTER_NAME="Test",
                GIT_COMMITTER_EMAIL="test@example.invalid",
            ),
        )

    def git(self, directory, *args):
        return self.run_with_git(GIT, "-C", directory, *args)

    def copy_plugin(self, destination):
        # A Nix wrapper runs its wrapped script from the store, so copy the
        # wrapped script itself; the copy then runs from where it is.
        for name in PLUGIN_FILES:
            source = PLUGIN_ROOT / name
            for path in [source] if source.is_file() else sorted(source.iterdir()):
                if path.name.startswith("."):
                    continue
                wrapped = path.with_name(f".{path.name}-wrapped")
                copied = destination / path.relative_to(PLUGIN_ROOT)
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(wrapped if wrapped.is_file() else path, copied)
                copied.chmod(0o755 if os.access(path, os.X_OK) else 0o644)

    def test_setup_registers_guarded_commands_and_rejects_recapturing_them(self):
        self.load_plugin()
        for phase, script in [
            ("post-save-layout", "claude-tmux-resurrect-save"),
            ("pre-restore-all", "claude-tmux-resurrect-pre-restore"),
            ("post-restore-all", "claude-tmux-resurrect-post-restore"),
        ]:
            path = str(BIN / script)
            self.assertEqual(
                shlex.split(self.global_option("@resurrect-hook-" + phase)),
                ["[", "!", "-e", path, "]", "||", path],
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
        self.load_plugin()
        installed_hooks = {event: self.native_hooks(event) for event in foreign}
        installed_save = self.global_option("@resurrect-hook-post-save-layout")
        for event, handlers in installed_hooks.items():
            self.assertEqual(len(handlers), len(foreign[event]) + 1)
            self.assertTrue(set(foreign[event]).issubset(handlers))
        self.load_plugin()
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
        self.load_plugin()
        recovered = {event: self.native_hooks(event) for event in foreign}
        for event, handlers in recovered.items():
            self.assertEqual(len(handlers), len(replacements[event]) + 1)
            self.assertTrue(set(replacements[event]).issubset(handlers))
        self.load_plugin()
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
        self.load_plugin()
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
        self.load_plugin()
        self.script("claude-tmux-resurrect-setup", "--remove")
        self.script("claude-tmux-resurrect-setup", "--remove")
        for phase, original in previous.items():
            self.assertEqual(self.global_option("@resurrect-hook-" + phase), original)
        for event, handlers in foreign.items():
            self.assertEqual(self.native_hooks(event), handlers)

        self.load_plugin()
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

    def test_moving_the_plugin_replaces_its_registrations(self):
        self.tmux(
            "set", "-g", "@resurrect-hook-post-save-layout", self.previous_hook("save")
        )
        self.tmux("set-environment", "-g", "CLAUDE_CODE_PLUGIN_DIRS", "/other/plugins")
        first = self.base / "plugin one ' $ #"
        second = self.base / "plugin two ' $ #"
        installed_hooks = None
        for directory in [first, second]:
            self.copy_plugin(directory)
            self.load_plugin(directory / "claude-tmux-resurrect.tmux")
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
            self.assertEqual(self.plugin_dirs(), f"/other/plugins:{directory}")
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

    def test_registrations_do_nothing_after_the_scripts_are_deleted(self):
        self.tmux(
            "set", "-g", "@resurrect-hook-post-save-layout", self.previous_hook("save")
        )
        copy = self.base / "deleted copy"
        self.copy_plugin(copy)
        self.load_plugin(copy / "claude-tmux-resurrect.tmux")
        shutil.rmtree(copy)
        self.write_snapshot()
        original = self.snapshot.read_bytes()
        self.execute_resurrect_hook("post-save-layout", self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), original)
        self.assertEqual(len(self.previous_calls()), 1)
        self.execute_resurrect_hook("pre-restore-all")
        self.execute_resurrect_hook("post-restore-all", self.snapshot)
        for event in ["client-attached", "client-session-changed"]:
            handler = shlex.split(
                self.global_option(f"@claude-tmux-resurrect-{event}-handler")
            )
            self.assertEqual(handler[:2], ["run-shell", "-b"])
            # Run the registered command synchronously to observe its status.
            self.tmux("run-shell", handler[2])

    def test_new_panes_list_the_plugin_beside_other_plugin_directories(self):
        self.tmux("set-environment", "-g", "CLAUDE_CODE_PLUGIN_DIRS", "/other/plugins")
        self.load_plugin()
        self.load_plugin()
        listed = f"/other/plugins:{PLUGIN_ROOT}"
        self.assertEqual(self.plugin_dirs(), listed)
        self.assertEqual(
            self.global_option("@claude-tmux-resurrect-dir"), str(PLUGIN_ROOT)
        )
        output = self.base / "pane environment"
        self.tmux(
            "new-window",
            "-d",
            f"printenv CLAUDE_CODE_PLUGIN_DIRS > {shlex.quote(str(output))}",
        )
        wait_until(
            lambda: output.is_file() and output.read_text().endswith("\n"),
            "new pane did not write its environment",
        )
        self.assertEqual(output.read_text(), listed + "\n")
        self.script("claude-tmux-resurrect-setup", "--remove")
        self.assertEqual(self.plugin_dirs(), "/other/plugins")
        self.assertEqual(self.global_option("@claude-tmux-resurrect-dir"), "")

    def test_remove_unsets_a_plugin_list_with_only_this_plugin(self):
        self.load_plugin()
        self.assertEqual(self.plugin_dirs(), str(PLUGIN_ROOT))
        self.script("claude-tmux-resurrect-setup", "--remove")
        self.assertIsNone(self.plugin_dirs())

    def test_plugin_directory_with_a_colon_is_rejected(self):
        copy = self.base / "plugin:copy"
        self.copy_plugin(copy)
        result = self.run_command(
            [str(copy / "bin/claude-tmux-resurrect-setup")], check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains ':'", result.stderr)
        self.assertIsNone(self.plugin_dirs())
        self.assertEqual(self.global_option("@resurrect-hook-post-save-layout"), "")

    def test_entry_shows_setup_failures_on_attached_clients(self):
        self.attach()
        option = "@resurrect-hook-post-save-layout"
        self.tmux("set", "-g", option, "__claude_tmux_resurrect_post_save_layout")
        result = self.tmux("run-shell", shlex.quote(str(ENTRY)), check=False)
        self.assertNotEqual(result.returncode, 0)
        message = wait_until(self.messages, "setup failure was not displayed")
        self.assertEqual(len(message), 1)
        self.assertIn(f"claude-tmux-resurrect: {option} wraps", message[0])

    def expect_message(self, text):
        return wait_until(
            lambda: [message for message in self.messages() if text in message],
            f"no message containing {text!r}",
        )

    def expect_no_new_messages(self, count):
        # Notices are shown a second after the event that raises them.
        time.sleep(1.5)
        self.assertEqual(len(self.messages()), count)

    def test_first_load_notice_is_kept_until_a_client_attaches(self):
        self.load_plugin()
        notices = "@claude-tmux-resurrect-notices"
        wait_until(lambda: self.global_option(notices), "notice was not kept")
        self.attach()
        [message] = self.expect_message("start Claude in a new pane")
        self.assertTrue(message.startswith("claude-tmux-resurrect: loaded"))
        self.assertEqual(self.global_option(notices), "")
        self.load_plugin()
        self.expect_no_new_messages(1)

    def test_save_warns_once_about_claude_panes_without_a_session_id(self):
        self.load_plugin()
        self.attach()
        self.expect_message("loaded")
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        [message] = self.expect_message("no session ID recorded for Claude")
        self.assertIn("in work:0.0;", message)
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.expect_no_new_messages(2)
        self.hook("SessionStart")
        self.write_snapshot()
        self.script("claude-tmux-resurrect-save", self.snapshot)
        self.assertEqual(self.global_option("@claude-tmux-resurrect-unrecorded"), "")
        self.expect_no_new_messages(2)

    def test_restore_reports_sessions_it_cannot_resume(self):
        self.save()
        self.transcript().unlink()
        self.attach()
        self.script("claude-tmux-resurrect-post-restore", self.snapshot)
        [message] = self.expect_message("couldn't resume")
        self.assertEqual(
            message,
            "claude-tmux-resurrect: couldn't resume a saved Claude session: "
            f"missing or ambiguous transcript for {ID}",
        )

    def test_session_start_reports_a_plugin_copy_with_another_version(self):
        self.load_plugin()
        self.attach()
        self.expect_message("loaded")
        payload = json.dumps({"hook_event_name": "SessionStart", "session_id": ID})
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin/plugin.json").read_text())
        for name, version in [
            ("same version", manifest["version"]),
            ("older", "0.0.1"),
        ]:
            copy = self.base / name
            self.copy_plugin(copy)
            (copy / ".claude-plugin/plugin.json").write_text(
                json.dumps(dict(manifest, version=version))
            )
            self.run_command(
                [str(copy / "bin/claude-tmux-resurrect-hook")], data=payload
            )
        [message] = self.expect_message("loaded plugin version 0.0.1")
        self.assertIn(f"but tmux runs {manifest['version']};", message)
        self.run_command([str(copy / "bin/claude-tmux-resurrect-hook")], data=payload)
        self.expect_no_new_messages(2)
        self.assertEqual(self.option("@claude_session_id"), ID)

    def test_hook_start_end_and_out_of_order_end(self):
        self.hook("SessionStart")
        self.assertEqual(self.option("@claude_session_id"), ID)
        self.hook("SessionEnd", "newer-session")
        self.assertEqual(self.option("@claude_session_id"), ID)
        self.hook("SessionEnd")
        self.assertEqual(self.option("@claude_session_id"), "")

    def test_overlapping_session_end_does_not_clear_newer_start(self):
        self.hook("SessionStart")
        # Nix wrappers prepend tmux on PATH. Copy the scripts so both source
        # and package checks can interpose the proxy.
        copied = self.base / "hook-under-test"
        self.copy_plugin(copied)
        hook = copied / "bin/claude-tmux-resurrect-hook"
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
        self.load_plugin()
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
        self.load_plugin()
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
        self.load_plugin()
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
        self.load_plugin()
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
            "once its pane is at a shell prompt",
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

    @unittest.skipUnless(CLAUDE, "CLAUDE_BINARY is supplied by the claude flake check")
    def test_real_claude_records_and_clears_its_session_on_a_new_pane(self):
        self.load_plugin()
        # Requests go to a closed local port, so nothing leaves the machine;
        # session hooks run before the first request fails.
        for name, value in {
            "CLAUDE_CONFIG_DIR": str(self.home / "claude config"),
            "ANTHROPIC_API_KEY": "sk-ant-test-not-a-key",
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }.items():
            self.tmux("set-environment", "-g", name, value)
        command = f"{shlex.quote(CLAUDE)} -p hello; sleep 60"
        self.tmux("new-window", "-d", "-n", "claude", command)
        pane = self.tmux("display", "-p", "-t", "work:claude", "#{pane_id}")
        pane = pane.stdout.strip()

        def recorded():
            result = self.tmux(
                "show", "-pqv", "-t", pane, "@claude_session_id", check=False
            )
            return result.stdout.strip()

        session_id = wait_until(recorded, "Claude did not record its session", 30)
        self.assertRegex(session_id, r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
        # Interrupting Claude ends its session while the pane stays open.
        self.tmux("send-keys", "-t", pane, "C-c")
        wait_until(lambda: not recorded(), "Claude did not clear its session", 30)

    @unittest.skipUnless(TPM and RESURRECT, "TPM_SOURCE and RESURRECT_SOURCE are set")
    @unittest.skipIf(PLUGIN_ROOT != ROOT, "TPM installs from a Git repository")
    @unittest.skipIf(system_plugins(), "TPM also reads @plugin lines in /etc/tmux.conf")
    def test_tpm_installs_updates_and_cleans_the_readme_configuration(self):
        plugins = self.home / ".tmux/plugins"
        for name, source in [("tpm", TPM), ("tmux-resurrect", RESURRECT)]:
            copied = plugins / name
            shutil.copytree(source, copied, symlinks=True)
            # Sources from the Nix store are read-only.
            for path in [copied, *copied.rglob("*")]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o200)
            # TPM treats any Git repository in its directory as installed.
            self.git(copied, "init", "-q")
        # A local repository stands in for the GitHub repository.
        upstream = self.base / "upstream/claude-tmux-resurrect"
        self.copy_plugin(upstream)
        self.git(upstream, "init", "-q")
        self.git(upstream, "add", "-A")
        self.git(upstream, "commit", "-q", "-m", "Release")
        readme = (ROOT / "README.md").read_text()
        configuration = readme.split("```tmux\n", 1)[1].split("```", 1)[0]
        line = "set -g @plugin 'kallisti-dev/claude-tmux-resurrect'\n"
        self.assertIn(line, configuration)
        # TPM reads plugin names from the user's configuration file.
        config = self.home / ".tmux.conf"
        config.write_text(configuration.replace(line, f"set -g @plugin '{upstream}'\n"))
        self.tmux("source-file", str(config))
        self.run_with_git(plugins / "tpm/bin/install_plugins")
        self.tmux("source-file", str(config))
        installed = plugins / "claude-tmux-resurrect"
        self.assertEqual(self.plugin_dirs(), str(installed))
        save = self.global_option("@resurrect-hook-post-save-layout")
        self.assertIn(str(installed / "bin/claude-tmux-resurrect-save"), save)

        (upstream / "UPDATED").touch()
        self.git(upstream, "add", "UPDATED")
        self.git(upstream, "commit", "-q", "-m", "Update")
        self.run_with_git(plugins / "tpm/bin/update_plugins", "claude-tmux-resurrect")
        self.assertTrue((installed / "UPDATED").is_file())
        self.tmux("source-file", str(config))
        self.assertEqual(self.plugin_dirs(), str(installed))
        self.assertEqual(self.global_option("@resurrect-hook-post-save-layout"), save)

        config.write_text(configuration.replace(line, ""))
        self.run_with_git(plugins / "tpm/bin/clean_plugins")
        self.assertFalse(installed.exists())
        self.tmux("source-file", str(config))
        self.write_snapshot()
        original = self.snapshot.read_bytes()
        self.execute_resurrect_hook("post-save-layout", self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), original)

    @unittest.skipUnless(
        RESURRECT, "RESURRECT_SOURCE is supplied by nix develop / flake checks"
    )
    def test_real_resurrect_save_restore_and_snapshot_deduplication(self):
        self.transcript()
        self.hook("SessionStart")
        self.load_plugin()
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
        self.load_plugin()
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
