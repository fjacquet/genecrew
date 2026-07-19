import subprocess


def test_lieux_apply_help_lists_flags():
    out = subprocess.run(["uv", "run", "genecrew", "lieux-apply", "--help"],
                         capture_output=True, text=True, cwd="/Users/fjacquet/Projects/genecrew")
    assert out.returncode == 0
    assert "--min-score" in out.stdout and "--dry-run" in out.stdout
