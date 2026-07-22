from pathlib import Path

import pytest
from crewai_custom_tools.tools.genealogy.gramps import client as gramps_client_mod

from genecrew import main as main_mod
from genecrew import referentiel as referentiel_mod
from genecrew import referentiel_apply as referentiel_apply_mod
from genecrew.cli import build_parser

# (argv, nom de la fonction *_cmd que main() doit appeler)
ROUTES = [
    (["propose", "audit"], "audit_cmd"),
    (["propose", "places"], "lieux_cmd"),
    (["propose", "deaths"], "deces_cmd"),
    (["propose", "military"], "militaires_cmd"),
    (["propose", "gender"], "gender_cmd"),
    (["propose", "referentiel"], "referentiel_cmd"),
    (["apply", "case"], "names_cmd"),
    (["apply", "gender"], "gender_apply_cmd"),
    (["apply", "places"], "lieux_apply_cmd"),
    (["apply", "citations", "--yaml", "relu.yaml"], "deces_apply_cmd"),
    (["apply", "deaths", "--yaml", "relu.yaml"], "deces_event_cmd"),
    (["apply", "all"], "apply_all_cmd"),
    (["apply", "referentiel", "--yaml", "relu.yaml"], "referentiel_apply_cmd"),
    (["merge", "places", "--yaml", "f.yaml"], "lieux_merge_cmd"),
    (["merge", "places", "--scope", "all"], "lieux_merge_cmd"),
    (["enrich", "wiki"], "lieux_wiki_cmd"),
    (["import", "place", "Bourges"], "lieu_import_cmd"),
    (["crew", "audit"], "crew_audit_cmd"),
]


@pytest.mark.parametrize("argv,expected_fn", ROUTES)
def test_each_leaf_routes_to_its_command(argv, expected_fn, monkeypatch, tmp_path):
    called = {}

    def _spy(args):
        called["fn"] = expected_fn

    monkeypatch.setattr(main_mod, expected_fn, _spy)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["genecrew", *argv])

    main_mod.main()

    assert called["fn"] == expected_fn


def test_stats_routes_without_a_target(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(main_mod, "stats", lambda: called.setdefault("ok", True))
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["genecrew", "stats"])

    main_mod.main()

    assert called["ok"] is True


def test_merge_people_est_route():
    from genecrew.cli import build_parser

    args = build_parser().parse_args(["merge", "people"])
    assert (args.command, args.target) == ("merge", "people")


def test_referentiel_cmd_sans_country_interroge_tous_les_pays(monkeypatch, tmp_path):
    """`--country` absent doit se traduire ICI (jamais dans le parseur, où il reste
    `None`) en `codes_pays=None` — la valeur que `run_referentiel` documente comme
    « tous les pays de la table »."""
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: object())
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, date, codes_pays=None):
        captured["codes_pays"] = codes_pays
        return tmp_path / "rapport.md", tmp_path / "propositions.yaml"

    monkeypatch.setattr(referentiel_mod, "run_referentiel", _spy)

    main_mod.referentiel_cmd(build_parser().parse_args(["propose", "referentiel"]))

    assert captured["codes_pays"] is None


def test_referentiel_cmd_country_devient_une_liste_de_codes(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: object())
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, date, codes_pays=None):
        captured["codes_pays"] = codes_pays
        return tmp_path / "rapport.md", tmp_path / "propositions.yaml"

    monkeypatch.setattr(referentiel_mod, "run_referentiel", _spy)

    main_mod.referentiel_cmd(
        build_parser().parse_args(["propose", "referentiel", "--country", "FR,CH"]))

    assert captured["codes_pays"] == ["FR", "CH"]


def test_referentiel_apply_cmd_passe_le_yaml_et_le_dry_run(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: object())
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, yaml_path, output_dir, *, date, dry_run=False):
        captured["yaml_path"] = yaml_path
        captured["dry_run"] = dry_run
        return tmp_path / "rapport.md"

    monkeypatch.setattr(referentiel_apply_mod, "run_referentiel_apply", _spy)

    main_mod.referentiel_apply_cmd(build_parser().parse_args(
        ["apply", "referentiel", "--yaml", "relu.yaml", "--dry-run"]))

    assert captured["yaml_path"] == Path("relu.yaml")
    assert captured["dry_run"] is True


def test_there_is_no_separate_military_apply_leaf():
    """La fusion revendiquée par le spec : une seule feuille pour tous les registres.

    Le moteur est déjà couvert par test_deces_apply.py (INSEE et Mémoire des hommes
    passent par run_deces_apply) ; ici on vérifie seulement que la CLI n'en réexpose
    pas deux portes.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "military-citations", "--yaml", "x.yaml"])
    args = build_parser().parse_args(["apply", "citations", "--yaml", "x.yaml"])
    assert args.target == "citations"
