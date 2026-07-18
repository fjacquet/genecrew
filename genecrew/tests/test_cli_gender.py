import subprocess
import sys


def test_gender_help_lists_options():
    out = subprocess.run(
        [sys.executable, "-m", "genecrew.main", "gender", "--help"],
        capture_output=True, text=True, cwd="genecrew/src",
    )
    assert out.returncode == 0
    assert "--scope" in out.stdout and "--limit" in out.stdout
    assert "--dry-run" not in out.stdout        # lecture seule
