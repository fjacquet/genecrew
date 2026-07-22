"""Offline tests for the *_cmd() function BODIES — closes a gap the final review of
`cli-grammaire-verbes` flagged: no test actually executes a `*_cmd(args)` body.

`test_cli_dispatch.py` monkeypatches the `*_cmd` functions themselves — it only proves
`main()` routes to the right name, never runs the body. The business-logic tests
(`test_deces_apply.py`, `test_lieux_wiki.py`, `test_places_merge.py`, ...) call the
`run_*` engines directly, bypassing `main.py` entirely. Nothing exercised the three
`*_cmd` bodies that read this branch's renamed CLI attributes — `args.yaml` on
`lieux_merge_cmd` / `deces_apply_cmd`, `args.no_images` on `lieux_wiki_cmd` — exactly
where a typo would pass all other tests and only blow up on the first real run.

Each test below builds a real `args` via `build_parser().parse_args([...])` (so it also
proves the flag name matches the parser), mocks `get_client` and the target module's
`run_*` engine, calls the real `*_cmd(args)`, and asserts the flag's value reached the
engine call.
"""

from pathlib import Path

from crewai_custom_tools.tools.genealogy.gramps import client as gramps_client_mod

from genecrew import deces_apply as deces_apply_mod
from genecrew import lieux_wiki as lieux_wiki_mod
from genecrew import main as main_mod
from genecrew import places_merge as places_merge_mod
from genecrew.cli import build_parser

FAKE_CLIENT = object()


def _args(argv):
    return build_parser().parse_args(argv)


def test_lieux_merge_cmd_passes_yaml_flag_to_engine(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, merges_yaml, output_dir, *, date, dry_run=False):
        captured["merges_yaml"] = merges_yaml
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_merge", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--yaml", "fusions_relues.yaml"]))

    assert captured["merges_yaml"] == "fusions_relues.yaml"


def test_lieux_merge_cmd_sans_yaml_detecte(monkeypatch, tmp_path):
    """Sans --yaml, la commande bascule sur le mode détection (run_places_detect)."""
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        captured["scope"] = scope
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    assert captured["scope"] == "all"


def test_lieux_merge_cmd_avertit_sur_la_console_quand_le_lot_est_borne(
        monkeypatch, tmp_path, capsys):
    """La garde « un lot borné ne fusionne jamais » vit dans run_places_detect, et son
    explication n'existe sinon que dans le rapport Markdown. Quelqu'un qui lance la
    commande avec --limit et voit « zéro fusion » doit comprendre pourquoi sans aller
    ouvrir le rapport — le message doit donc apparaître sur la console."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--scope", "all", "--limit", "5"]))

    out = capsys.readouterr().out
    assert "--limit" in out
    assert "lot borné" in out.lower()


def test_lieux_merge_cmd_sans_limit_ne_dit_rien_sur_le_lot_borne(
        monkeypatch, tmp_path, capsys):
    """Sans --limit, aucune garde ne s'applique : pas d'avertissement à afficher."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    out = capsys.readouterr().out
    assert "lot borné" not in out.lower()


def test_deces_apply_cmd_passes_yaml_flag_to_engine(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, propositions_yaml, output_dir, *, date, dry_run=False):
        captured["propositions_yaml"] = propositions_yaml
        return tmp_path / "rapport.md"

    monkeypatch.setattr(deces_apply_mod, "run_deces_apply", _spy)

    main_mod.deces_apply_cmd(
        _args(["apply", "citations", "--yaml", "propositions_relues.yaml"]))

    assert captured["propositions_yaml"] == Path("propositions_relues.yaml")


def test_lieux_wiki_cmd_no_images_flag_disables_images(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, date, limit=None, images=True, dry_run=False):
        captured["images"] = images
        return tmp_path / "rapport.md"

    monkeypatch.setattr(lieux_wiki_mod, "run_lieux_wiki", _spy)

    main_mod.lieux_wiki_cmd(_args(["enrich", "wiki", "--no-images"]))

    assert captured["images"] is False


def test_lieux_wiki_cmd_images_stay_on_by_default(monkeypatch, tmp_path):
    """Sans --no-images, args.no_images vaut False -> images=True doit passer au moteur."""
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, date, limit=None, images=True, dry_run=False):
        captured["images"] = images
        return tmp_path / "rapport.md"

    monkeypatch.setattr(lieux_wiki_mod, "run_lieux_wiki", _spy)

    main_mod.lieux_wiki_cmd(_args(["enrich", "wiki"]))

    assert captured["images"] is True
