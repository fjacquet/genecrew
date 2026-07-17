from genecrew.checkpoint import Checkpoint, load_checkpoint, save_checkpoint


def test_roundtrip(tmp_path):
    path = tmp_path / "cp.json"
    cp = Checkpoint(workflow="audit", scope="all", done_handles={"h1", "h2"})
    save_checkpoint(path, cp)
    loaded = load_checkpoint(path)
    assert loaded.workflow == "audit" and loaded.scope == "all"
    assert loaded.done_handles == {"h1", "h2"}


def test_load_missing_returns_none(tmp_path):
    assert load_checkpoint(tmp_path / "absent.json") is None
