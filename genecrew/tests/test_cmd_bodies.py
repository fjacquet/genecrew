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
from genecrew.cli import build_parser

from genecrew import deces_apply as deces_apply_mod
from genecrew import lieux_wiki as lieux_wiki_mod
from genecrew import main as main_mod
from genecrew import places_merge as places_merge_mod

FAKE_CLIENT = object()


def _detection(tmp_path, *, lot_borne=False, scope_unitaire=False):
    """Retour type de `run_places_detect` — les deux gardes de simulation forcée y sont
    NOMMÉES, et c'est ce que `lieux_merge_cmd` doit consommer sans jamais redériver la
    décision depuis `args`."""
    return places_merge_mod.ResultatDetection(
        chemin=tmp_path / "rapport.md",
        lot_borne=lot_borne,
        scope_unitaire=scope_unitaire,
    )


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

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--yaml", "fusions_relues.yaml"])
    )

    assert captured["merges_yaml"] == "fusions_relues.yaml"


def test_lieux_merge_cmd_sans_yaml_detecte(monkeypatch, tmp_path):
    """Sans --yaml, la commande bascule sur le mode détection (run_places_detect)."""
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        captured["scope"] = scope
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    assert captured["scope"] == "all"


def test_lieux_merge_cmd_avertit_sur_la_console_quand_le_lot_est_borne(
    monkeypatch, tmp_path, capsys
):
    """La garde « un lot borné ne fusionne jamais » vit dans run_places_detect, et son
    explication n'existe sinon que dans le rapport Markdown. Quelqu'un qui lance la
    commande avec --limit et voit « zéro fusion » doit comprendre pourquoi sans aller
    ouvrir le rapport — le message doit donc apparaître sur la console."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path, lot_borne=True)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--scope", "all", "--limit", "5"])
    )

    out = capsys.readouterr().out
    assert "--limit" in out
    assert "lot borné" in out.lower()


def test_lieux_merge_cmd_sans_limit_ne_dit_rien_sur_le_lot_borne(
    monkeypatch, tmp_path, capsys
):
    """Sans --limit, aucune garde ne s'applique : pas d'avertissement à afficher."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    out = capsys.readouterr().out
    assert "lot borné" not in out.lower()


# --- C2 : une seule source de vérité pour « lot borné, donc aucune écriture » -------
#
# `lieux_merge_cmd` ne doit JAMAIS redériver la décision depuis `args.limit` : elle doit
# se contenter d'afficher ce que `run_places_detect` lui a renvoyé. Les deux tests
# ci-dessous posent volontairement la valeur renvoyée en CONTRADICTION avec ce
# qu'`args.limit` suggérerait, pour prouver que c'est bien le retour de la fonction —
# et lui seul — qui pilote l'avertissement console. Si la CLI se remettait à
# réimplémenter `args.limit is not None`, l'un des deux tomberait.


def test_lieux_merge_cmd_avertit_meme_sans_limit_si_la_fonction_le_dit(
    monkeypatch, tmp_path, capsys
):
    """Aucun --limit posé, mais la fonction dit quand même « lot borné » : l'avertissement
    doit apparaître. Une CLI qui déciderait elle-même depuis args.limit resterait muette."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path, lot_borne=True)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    out = capsys.readouterr().out
    assert "lot borné" in out.lower()


def test_lieux_merge_cmd_n_avertit_pas_si_la_fonction_dit_non_borne_malgre_limit(
    monkeypatch, tmp_path, capsys
):
    """--limit posé, mais la fonction dit qu'elle n'a PAS été bornée (cas construit,
    contredisant volontairement `args.limit`) : aucun avertissement ne doit apparaître.
    Une CLI qui imprimerait dès `args.limit is not None`, sans regarder le retour de la
    fonction, afficherait ici « simulation forcée » alors que des fusions auraient
    réellement lieu — exactement le scénario décrit en revue."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--scope", "all", "--limit", "5"])
    )

    out = capsys.readouterr().out
    assert "lot borné" not in out.lower()


# --- C1 : le drapeau de simulation, réellement transmis au moteur -------------------
#
# `test_lieux_merge_cmd_passes_yaml_flag_to_engine` et
# `test_lieux_merge_cmd_sans_yaml_detecte` prouvent que `merges_yaml`/`scope` arrivent ;
# aucun test n'observait `dry_run` avant ceux-ci. Un `dry_run=False` câblé en dur au lieu
# de `dry_run=args.dry_run` laissait toute la suite verte — le scénario le plus coûteux
# possible pour une commande qui fusionne irréversiblement des lieux.


def test_lieux_merge_cmd_mode_yaml_transmet_dry_run_vrai(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, merges_yaml, output_dir, *, date, dry_run=False):
        captured["dry_run"] = dry_run
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_merge", _spy)

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--yaml", "fusions_relues.yaml", "--dry-run"])
    )

    assert captured["dry_run"] is True


def test_lieux_merge_cmd_mode_yaml_transmet_dry_run_faux(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, merges_yaml, output_dir, *, date, dry_run=False):
        captured["dry_run"] = dry_run
        return tmp_path / "rapport.md"

    monkeypatch.setattr(places_merge_mod, "run_places_merge", _spy)

    main_mod.lieux_merge_cmd(
        _args(["merge", "places", "--yaml", "fusions_relues.yaml"])
    )

    assert captured["dry_run"] is False


def test_lieux_merge_cmd_mode_detection_transmet_dry_run_vrai(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        captured["dry_run"] = dry_run
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all", "--dry-run"]))

    assert captured["dry_run"] is True


def test_lieux_merge_cmd_mode_detection_transmet_dry_run_faux(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        captured["dry_run"] = dry_run
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    assert captured["dry_run"] is False


# --- C4 : le périmètre à un seul lieu reçoit le même traitement que `--limit` -------
#
# `--scope place:ID` est annoncé dans l'aide de la commande, mais un lieu isolé ne forme
# jamais de groupe d'homonymes : la détection ne peut structurellement rien conclure, et
# la commande annonçait pourtant « écritures appliquées, aucun doublon détecté ». Comme
# pour `--limit`, la décision appartient à `run_places_detect` et la CLI se contente de
# l'afficher — les deux tests de contradiction ci-dessous le verrouillent.


def test_lieux_merge_cmd_avertit_quand_le_scope_ne_vise_qu_un_lieu(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path, scope_unitaire=True)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "place:P0080"]))

    out = capsys.readouterr().out
    assert "place:" in out
    assert "un seul lieu" in out.lower()


def test_lieux_merge_cmd_ne_dit_rien_du_scope_quand_il_est_complet(
    monkeypatch, tmp_path, capsys
):
    """`--scope all` : aucune garde de périmètre, donc aucun avertissement."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    assert "un seul lieu" not in capsys.readouterr().out.lower()


def test_lieux_merge_cmd_avertit_sur_le_scope_meme_si_args_dit_all(
    monkeypatch, tmp_path, capsys
):
    """Contradiction volontaire : `--scope all` mais la fonction dit « un seul lieu ».
    Une CLI qui redériverait la décision depuis `args.scope` resterait muette."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path, scope_unitaire=True)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "all"]))

    assert "un seul lieu" in capsys.readouterr().out.lower()


def test_lieux_merge_cmd_ne_dit_rien_si_la_fonction_dit_scope_complet_malgre_place(
    monkeypatch, tmp_path, capsys
):
    """Contradiction inverse : `--scope place:ID` mais la fonction dit qu'elle a pu
    décider. Une CLI qui imprimerait dès `args.scope` afficherait « simulation forcée »
    pendant qu'une fusion irréversible aurait réellement lieu."""
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, output_dir, *, scope, date, limit=None, dry_run=False):
        return _detection(tmp_path)

    monkeypatch.setattr(places_merge_mod, "run_places_detect", _spy)

    main_mod.lieux_merge_cmd(_args(["merge", "places", "--scope", "place:P0080"]))

    assert "un seul lieu" not in capsys.readouterr().out.lower()


def test_deces_apply_cmd_passes_yaml_flag_to_engine(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gramps_client_mod, "get_client", lambda: FAKE_CLIENT)
    monkeypatch.setenv("GENECREW_OUTPUT_DIR", str(tmp_path))

    def _spy(client, propositions_yaml, output_dir, *, date, dry_run=False):
        captured["propositions_yaml"] = propositions_yaml
        return tmp_path / "rapport.md"

    monkeypatch.setattr(deces_apply_mod, "run_deces_apply", _spy)

    main_mod.deces_apply_cmd(
        _args(["apply", "citations", "--yaml", "propositions_relues.yaml"])
    )

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
