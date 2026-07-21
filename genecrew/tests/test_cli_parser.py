import pytest

from genecrew.cli import build_parser

# (argv, command, target) — les 15 feuilles de la nouvelle grammaire
LEAVES = [
    (["stats"], "stats", None),
    (["propose", "audit"], "propose", "audit"),
    (["propose", "places"], "propose", "places"),
    (["propose", "deaths"], "propose", "deaths"),
    (["propose", "military"], "propose", "military"),
    (["propose", "gender"], "propose", "gender"),
    (["apply", "case"], "apply", "case"),
    (["apply", "gender"], "apply", "gender"),
    (["apply", "places"], "apply", "places"),
    (["apply", "citations", "--yaml", "relu.yaml"], "apply", "citations"),
    (["apply", "all"], "apply", "all"),
    (["merge", "places", "--yaml", "fusions.yaml"], "merge", "places"),
    (["enrich", "wiki"], "enrich", "wiki"),
    (["import", "place", "Bourges, Cher, France"], "import", "place"),
    (["crew", "audit"], "crew", "audit"),
]


@pytest.mark.parametrize("argv,command,target", LEAVES)
def test_every_leaf_parses(argv, command, target):
    args = build_parser().parse_args(argv)
    assert args.command == command
    assert getattr(args, "target", None) == target


OLD_NAMES = [
    "audit", "names", "gender", "gender-apply", "apply-all", "lieux",
    "lieux-apply", "lieux-merge", "lieux-wiki", "deces", "deces-apply",
    "militaires", "militaires-apply", "lieu-import", "crew-audit",
]


@pytest.mark.parametrize("old", OLD_NAMES)
def test_old_names_are_rejected(old):
    """Coupure nette : les anciens noms échouent bruyamment, ils n'écrivent rien."""
    with pytest.raises(SystemExit):
        build_parser().parse_args([old])


def test_a_verb_without_target_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["propose"])


def test_yaml_is_required_for_apply_citations():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "citations"])


def test_yaml_is_required_for_merge_places():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["merge", "places"])


def test_defaults_are_preserved():
    args = build_parser().parse_args(["apply", "all"])
    assert args.scope == "all"
    assert args.min_ratio == 0.98
    assert args.min_score == 0.90
    assert args.limit is None
    assert args.dry_run is False


def test_batch_size_reads_the_environment(monkeypatch):
    monkeypatch.setenv("GENECREW_BATCH_SIZE", "7")
    args = build_parser().parse_args(["propose", "audit"])
    assert args.batch_size == 7


def test_renamed_flags_land_on_the_expected_attributes():
    args = build_parser().parse_args(["apply", "citations", "--yaml", "relu.yaml"])
    assert args.yaml == "relu.yaml"
    args = build_parser().parse_args(["enrich", "wiki", "--no-images"])
    assert args.no_images is True
    args = build_parser().parse_args(["import", "place", "Bourges, Cher, France"])
    assert args.place == "Bourges, Cher, France"


@pytest.mark.parametrize("cible", ["wikidata", "dhs"])
def test_propose_accepte_les_deux_sources_d_archives(cible):
    args = build_parser().parse_args(["propose", cible, "--scope", "all"])
    assert args.command == "propose" and args.target == cible

# Pas de test dédié au rejet de "scriptorium" : il ne prouverait rien de plus que
# le rejet générique d'un mot inconnu, déjà couvert par `test_old_names_are_rejected`
# et par argparse lui-même (choix fermé). "scriptorium" n'a jamais été une feuille
# valide de `propose` — la source a été écartée avant d'être câblée, voir
# docs/BACKLOG.md — donc son rejet n'est pas un comportement spécifique à verrouiller.


def test_merge_people_accepte_le_mode_detection():
    args = build_parser().parse_args(
        ["merge", "people", "--scope", "all", "--limit", "50", "--dry-run"])
    assert (args.command, args.target) == ("merge", "people")
    assert args.scope == "all"
    assert args.limit == 50
    assert args.dry_run is True
    assert args.yaml is None
    assert args.max_passes == 5


def test_merge_people_accepte_un_yaml_relu():
    args = build_parser().parse_args(["merge", "people", "--yaml", "arbitrage.yaml"])
    assert args.yaml == "arbitrage.yaml"
