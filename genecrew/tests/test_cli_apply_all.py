import subprocess
import sys


def test_apply_all_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "apply-all", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--min-ratio" in out.stdout and "--dry-run" in out.stdout
