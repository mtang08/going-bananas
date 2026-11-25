"""Exercise the shell runner against a temporary synthetic configuration."""

import os
import shutil
import subprocess
from pathlib import Path


def test_explicit_target_cannot_be_redirected_by_dotenv(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    root = Path(__file__).resolve().parents[3]
    for name in ("env.sh", "run", "with-mode"):
        shutil.copy(root / "scripts" / name, scripts / name)
    (tmp_path / ".env").write_text("APP_MODE=real\nDATABASE_URL=file/garmin_real\nPRIVATE_DIR=unused-real\n")
    base = {"PATH": os.environ["PATH"]}
    probe = ["sh", "-c", 'printf "%s %s %s" "$APP_MODE" "$DATABASE_URL" "$PRIVATE_DIR"']
    runner = str(scripts / "run")

    def run(env, *args):
        return subprocess.run(args, env={**base, **env}, capture_output=True, text=True)

    assert run({}, runner, *probe).stdout == "real file/garmin_real unused-real"
    conflict = run({"DATABASE_URL": "isolated/garmin_demo"}, runner, *probe)
    assert conflict.returncode == 2 and not conflict.stdout and "isolated/" not in conflict.stderr
    explicit = {"APP_MODE": "demo", "DATABASE_URL": "isolated/garmin_demo", "PRIVATE_DIR": "isolated-files"}
    assert run(explicit, runner, *probe).stdout == "demo isolated/garmin_demo isolated-files"
    explicit["PRIVATE_DIR"] = str(tmp_path / "synthetic-demo-files")
    nested_custom = run(explicit, str(scripts / "with-mode"), "demo", runner, *probe)
    assert nested_custom.stdout == f"demo isolated/garmin_demo {explicit['PRIVATE_DIR']}"
    nested = run({}, str(scripts / "with-mode"), "test", runner, *probe)
    assert nested.stdout == f"test file/garmin_test {tmp_path}/private/test"
