import pytest

from genecrew import main as main_mod
from genecrew.cli import build_parser

# (argv, nom de la fonction *_cmd que main() doit appeler)
ROUTES = [
    (["propose", "audit"], "audit_cmd"),
    (["propose", "places"], "lieux_cmd"),
    (["propose", "deaths"], "deces_cmd"),
    (["propose", "military"], "militaires_cmd"),
    (["propose", "gender"], "gender_cmd"),
    (["apply", "case"], "names_cmd"),
    (["apply", "gender"], "gender_apply_cmd"),
    (["apply", "places"], "lieux_apply_cmd"),
    (["apply", "citations", "--yaml", "relu.yaml"], "deces_apply_cmd"),
    (["apply", "deaths", "--yaml", "relu.yaml"], "deces_event_cmd"),
    (["apply", "all"], "apply_all_cmd"),
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
