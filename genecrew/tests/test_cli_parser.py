import pytest

from genecrew.cli import build_parser

# (argv, command, target) — 19 lignes de test pour 18 feuilles DISTINCTES : `merge
# places` y apparaît deux fois (une par mode, YAML relu et détection) mais reste une
# seule et même feuille — la grammaire à sept verbes n'en a pas gagné une (voir
# docs/adr/0012-cli-grammaire-verbes.md, « 16 anciens noms plats → 15 feuilles » pour
# l'historique ; `propose referentiel` et `apply referentiel` sont deux feuilles ajoutées
# ENSUITE, sous des verbes existants, ce qui porte le total à 18 — ADR 0016).
LEAVES = [
    (["stats"], "stats", None),
    (["propose", "audit"], "propose", "audit"),
    (["propose", "places"], "propose", "places"),
    (["propose", "deaths"], "propose", "deaths"),
    (["propose", "military"], "propose", "military"),
    (["propose", "gender"], "propose", "gender"),
    (["propose", "referentiel", "--country", "FR,CH"], "propose", "referentiel"),
    (["apply", "case"], "apply", "case"),
    (["apply", "gender"], "apply", "gender"),
    (["apply", "places"], "apply", "places"),
    (["apply", "citations", "--yaml", "relu.yaml"], "apply", "citations"),
    (["apply", "deaths", "--yaml", "relu.yaml"], "apply", "deaths"),
    (["apply", "all"], "apply", "all"),
    (["apply", "referentiel", "--yaml", "relu.yaml"], "apply", "referentiel"),
    (["merge", "places", "--yaml", "fusions.yaml"], "merge", "places"),
    (["merge", "places", "--scope", "all"], "merge", "places"),
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
    "audit",
    "names",
    "gender",
    "gender-apply",
    "apply-all",
    "lieux",
    "lieux-apply",
    "lieux-merge",
    "lieux-wiki",
    "deces",
    "deces-apply",
    "militaires",
    "militaires-apply",
    "lieu-import",
    "crew-audit",
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


def test_import_releve_lit_stdin_par_defaut():
    args = build_parser().parse_args(["import", "releve"])
    assert (args.command, args.target) == ("import", "releve")
    assert args.file is None


def test_import_releve_accepte_un_fichier():
    args = build_parser().parse_args(["import", "releve", "--file", "acte.txt"])
    assert args.file == "acte.txt"
    assert args.dry_run is False


def test_import_releve_person_est_parse():
    """--person doit remonter jusqu'à args.person : c'est l'ID qui, plus tard,
    force QUI on rattache (jamais le DROIT d'écrire — les gardes tiennent)."""
    args = build_parser().parse_args(["import", "releve", "--person", "I0042"])
    assert args.person == "I0042"


def test_import_releve_person_absent_vaut_none():
    args = build_parser().parse_args(["import", "releve"])
    assert args.person is None


def test_merge_people_accepte_le_mode_detection():
    args = build_parser().parse_args(
        ["merge", "people", "--scope", "all", "--limit", "50", "--dry-run"]
    )
    assert (args.command, args.target) == ("merge", "people")
    assert args.scope == "all"
    assert args.limit == 50
    assert args.dry_run is True
    assert args.yaml is None
    assert args.max_passes == 5


def test_merge_people_accepte_un_yaml_relu():
    args = build_parser().parse_args(["merge", "people", "--yaml", "arbitrage.yaml"])
    assert args.yaml == "arbitrage.yaml"


def test_merge_places_accepte_le_mode_detection_sans_yaml():
    """`--yaml` devient optionnel : sans lui, la commande détecte."""
    args = build_parser().parse_args(["merge", "places", "--scope", "all"])
    assert args.yaml is None
    assert args.scope == "all"
    assert args.limit is None


def test_l_aide_du_verbe_merge_ne_contredit_pas_l_aide_de_la_feuille_places():
    """`uv run genecrew --help` (le verbe) et `uv run genecrew merge places --help` (la
    feuille) doivent raconter la même histoire. La feuille décrit bien les deux modes
    (détection ou YAML relu, voir le bloc `merge_sub.add_parser("places", ...)` juste
    en dessous) ; l'aide du verbe, un cran au-dessus, ne doit donc pas prétendre que les
    lieux ne fusionnent QUE depuis un YAML relu."""
    aide_verbe = build_parser().format_help()
    ligne_merge = next(
        ligne for ligne in aide_verbe.splitlines() if ligne.strip().startswith("merge")
    )
    assert "lieux relus" not in ligne_merge


def test_yaml_is_required_for_apply_referentiel():
    """Le YAML relu est le SEUL point d'entrée de l'écriture (spec) : sans lui, rien."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["apply", "referentiel"])


def test_propose_referentiel_sans_country_vaut_tous_les_pays():
    """`--country` absent doit rester `None` au niveau du parseur : c'est à la commande
    (pas au parseur) de traduire l'absence en « tous les pays de la table »."""
    args = build_parser().parse_args(["propose", "referentiel"])
    assert args.country is None


def test_propose_referentiel_country_est_lu_tel_quel():
    args = build_parser().parse_args(["propose", "referentiel", "--country", "FR,CH"])
    assert args.country == "FR,CH"


def test_referentiel_ne_cree_pas_de_nouveau_verbe():
    """`propose referentiel`/`apply referentiel` sont des feuilles sous des verbes
    déjà existants (ADR 0012) : aucun verbe `init` (ni aucun autre) n'a été créé
    pour les accueillir."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["init"])
