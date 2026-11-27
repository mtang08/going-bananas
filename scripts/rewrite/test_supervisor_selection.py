"""Exercise mode-specific native supervisor startup without starting real services."""

import os
import runpy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "serve.py"


class SupervisorSelection(unittest.TestCase):
    def test_mode_and_worker(self):
        cases = [
            ("test", ["going-bananas", "npm"]),
            ("demo", ["going-bananas", "npm"]),
            ("real", ["going-bananas", "going-bananas", "npm"]),
        ]
        for mode, expected in cases:
            with self.subTest(mode=mode), ExitStack() as stack:
                stack.enter_context(
                    patch.dict(
                        os.environ,
                        {
                            "APP_MODE": mode,
                            "APP_PORT": "8765",
                            "VITE_PORT": "8766",
                            "GARMIN_API_KEY": "fixture",
                            "DATABASE_URL": "fixture",
                        },
                        clear=True,
                    )
                )
                stack.enter_context(patch.object(sys, "argv", [str(SCRIPT), "--dev"]))
                for name in (
                    "fcntl.flock",
                    "socket.socket",
                    "signal.signal",
                    "time.sleep",
                    "builtins.print",
                ):
                    stack.enter_context(patch(name))
                builds = stack.enter_context(patch("subprocess.run"))
                builds.return_value.returncode = 0
                child = Mock(returncode=3)
                child.poll.return_value = 3
                launched = stack.enter_context(
                    patch("subprocess.Popen", return_value=child)
                )
                with self.assertRaises(SystemExit) as exit_status:
                    runpy.run_path(str(SCRIPT), run_name="__main__")
                self.assertEqual(exit_status.exception.code, 3)
                commands = [call.args[0] for call in launched.call_args_list]
                self.assertEqual([Path(cmd[0]).name for cmd in commands], expected)
                self.assertTrue(
                    all(
                        call.kwargs["start_new_session"]
                        for call in launched.call_args_list
                    )
                )
                self.assertEqual(commands[-1][-3:], ["--port", "8766", "--strictPort"])
                env = launched.call_args_list[-1].kwargs["env"]
                self.assertNotIn("DATABASE_URL", env)
                self.assertNotIn("GARMIN_API_KEY", env)
                self.assertIn("-startup", commands[0])
                self.assertIn("127.0.0.1:8765", commands[0])
                self.assertIn("build", builds.call_args.args[0])
                if mode == "real":
                    self.assertEqual(commands[1][1:], ["worker"])



if __name__ == "__main__":
    unittest.main()
