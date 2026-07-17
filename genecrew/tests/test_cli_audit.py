import subprocess
import sys


def test_audit_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "audit", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--resume" in out.stdout
