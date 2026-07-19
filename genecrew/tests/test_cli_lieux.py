import subprocess


def test_lieux_help_lists_min_score():
    out = subprocess.run(["uv", "run", "genecrew", "lieux", "--help"],
                         capture_output=True, text=True, cwd="/Users/fjacquet/Projects/genecrew")
    assert out.returncode == 0
    assert "--min-score" in out.stdout and "--scope" in out.stdout
