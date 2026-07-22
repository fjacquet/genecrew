"""Orchestration des fusions de personnes : exécution, patch de genre, rapport."""

import json

import pytest

from crewai_custom_tools.tools.genealogy.models.domain import MergeCluster, PersonFacts
from genecrew import people_merge


class _OutilEspion:
    def __init__(self, echecs=()):
        self.appels = []
        self._echecs = set(echecs)

    def _run(self, **kwargs):
        self.appels.append(kwargs)
        titanic = kwargs.get("titanic_handle") or kwargs.get("handle")
        if titanic in self._echecs:
            return json.dumps({"success": False, "error": "boom"})
        return json.dumps({"success": True, "data": kwargs})


@pytest.fixture
def outils(monkeypatch):
    fusion, genre = _OutilEspion(), _OutilEspion()
    monkeypatch.setattr(people_merge, "GrampsMergePeopleTool", lambda: fusion)
    monkeypatch.setattr(people_merge, "GrampsUpdateGenderTool", lambda: genre)
    return fusion, genre


def _grappe(gender_patch=None, titanics=("hI2",)):
    return MergeCluster(
        phoenix_handle="hI1",
        phoenix_gramps_id="I1",
        titanic_handles=list(titanics),
        titanic_gramps_ids=[t.replace("h", "") for t in titanics],
        gender_patch=gender_patch,
    )


def test_une_grappe_fusionne_chaque_titanic(outils):
    fusion, _ = outils
    faites, erreurs = people_merge.executer_grappes(
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False
    )
    assert len(fusion.appels) == 2
    assert erreurs == []
    assert len(faites) == 2


def test_le_patch_de_genre_precede_la_fusion(outils):
    """Person.merge() ignore le genre : patcher APRÈS ne servirait à rien."""
    fusion, genre = outils
    ordre = []
    genre._run = lambda **kw: (ordre.append("genre"), json.dumps({"success": True}))[1]
    fusion._run = lambda **kw: (ordre.append("fusion"), json.dumps({"success": True}))[
        1
    ]
    people_merge.executer_grappes([_grappe(gender_patch=1)], dry_run=False)
    assert ordre == ["genre", "fusion"]


def test_sans_patch_le_genre_n_est_pas_touche(outils):
    _, genre = outils
    people_merge.executer_grappes([_grappe(gender_patch=None)], dry_run=False)
    assert genre.appels == []


def test_une_erreur_est_consignee_et_le_lot_continue(outils):
    fusion, _ = outils
    fusion._echecs = {"hI2"}
    faites, erreurs = people_merge.executer_grappes(
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False
    )
    assert len(erreurs) == 1
    assert len(faites) == 1


def test_patch_de_genre_echoue_la_grappe_n_est_pas_fusionnee():
    """Fusionner malgré l'échec du patch perdrait le genre sans trace, ce que le
    patch existe pour empêcher. La grappe est abandonnée, pas silencieusement fusionnée."""
    fusion, genre = _OutilEspion(), _OutilEspion()
    genre._run = lambda **kw: json.dumps({"success": False, "error": "boom"})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(people_merge, "GrampsMergePeopleTool", lambda: fusion)
        mp.setattr(people_merge, "GrampsUpdateGenderTool", lambda: genre)
        faites, erreurs = people_merge.executer_grappes(
            [_grappe(gender_patch=1)], dry_run=False
        )
    assert fusion.appels == []
    assert faites == []
    assert len(erreurs) == 1
    assert "abandonnée" in erreurs[0][1]


def test_dry_run_transmis_aux_outils(outils):
    fusion, genre = outils
    people_merge.executer_grappes([_grappe(gender_patch=1)], dry_run=True)
    assert fusion.appels[0]["dry_run"] is True
    assert genre.appels[0]["dry_run"] is True


def test_rapport_annonce_le_mode_et_invite_a_relancer():
    rapport = people_merge.render_people_merge_report(
        "2026-07-20",
        passes=[(1, 3, 0)],
        arbitrage=[],
        ignores=["nom:pagan"],
        dry_run=True,
    )
    assert "simulation" in rapport
    assert "nom:pagan" in rapport
    assert "relancer" in rapport.lower()


def test_rapport_sans_fusion_n_invite_pas_a_relancer():
    rapport = people_merge.render_people_merge_report(
        "2026-07-20", passes=[(1, 0, 0)], arbitrage=[], ignores=[], dry_run=False
    )
    assert "relancer" not in rapport.lower()


def _personne(gramps_id, handle, sex):
    return PersonFacts(
        gramps_id=gramps_id,
        handle=handle,
        name="",
        surname="Dupont",
        given="Jean",
        sex=sex,
    )


def test_grappe_genres_titanics_contradictoires_non_fusionnee():
    """Phoenix de genre inconnu, mais ses titanics portent des genres OPPOSÉS (M et F) :
    signal que l'étage auto a peut-être mal jugé la paire (revue Task 5). On n'exécute
    pas la fusion, on consigne une erreur explicite, et le lot continue — même
    traitement que l'échec du patch de genre."""
    phoenix = _personne("I1", "hI1", "U")
    titanic_m = _personne("I2", "hI2", "M")
    titanic_f = _personne("I3", "hI3", "F")
    par_handle = {p.handle: p for p in (phoenix, titanic_m, titanic_f)}
    grappe = MergeCluster(
        phoenix_handle="hI1",
        phoenix_gramps_id="I1",
        titanic_handles=["hI2", "hI3"],
        titanic_gramps_ids=["I2", "I3"],
        gender_patch=1,
    )
    grappes_valides, erreurs = people_merge.filtrer_grappes_contradictoires(
        [grappe], par_handle
    )
    assert grappes_valides == []
    assert len(erreurs) == 1
    assert "contradictoires" in erreurs[0][1]
    assert "abandonnée" in erreurs[0][1]


def test_grappe_sans_gender_patch_ignore_la_contradiction():
    """Sans gender_patch, le genre du phoenix est déjà connu : aucun risque de perte
    silencieuse, donc la contradiction entre titanics n'est pas ce garde-fou."""
    phoenix = _personne("I1", "hI1", "M")
    titanic_m = _personne("I2", "hI2", "M")
    titanic_f = _personne("I3", "hI3", "F")
    par_handle = {p.handle: p for p in (phoenix, titanic_m, titanic_f)}
    grappe = MergeCluster(
        phoenix_handle="hI1",
        phoenix_gramps_id="I1",
        titanic_handles=["hI2", "hI3"],
        titanic_gramps_ids=["I2", "I3"],
        gender_patch=None,
    )
    grappes_valides, erreurs = people_merge.filtrer_grappes_contradictoires(
        [grappe], par_handle
    )
    assert grappes_valides == [grappe]
    assert erreurs == []


def test_grappe_titanics_tous_du_meme_genre_non_ecartee():
    """Phoenix inconnu, titanics TOUS M : pas de contradiction, le patch est légitime.
    La grappe ne doit pas être écartée (revue Task 8, exigence (c))."""
    phoenix = _personne("I1", "hI1", "U")
    par_handle = {
        phoenix.handle: phoenix,
        "hI2": _personne("I2", "hI2", "M"),
        "hI3": _personne("I3", "hI3", "M"),
    }
    grappe = MergeCluster(
        phoenix_handle="hI1",
        phoenix_gramps_id="I1",
        titanic_handles=["hI2", "hI3"],
        titanic_gramps_ids=["I2", "I3"],
        gender_patch=1,
    )
    grappes_valides, erreurs = people_merge.filtrer_grappes_contradictoires(
        [grappe], par_handle
    )
    assert grappes_valides == [grappe]
    assert erreurs == []


# --- Défaut 1 (revue Task 8) : effective_dry_run normalisé -------------------


def _fait_une_fusion(grappes, *, dry_run=False):
    """Faux executer_grappes : rend toujours une fusion, pour tester la boucle."""
    _fait_une_fusion.appels += 1
    return [("I1", "I2")], []


def test_env_force_simulation_une_seule_passe(monkeypatch, tmp_path):
    """Sous GENECREW_DRY_RUN=true (simulation venue de l'env) et dry_run=False explicite,
    run_people_merge ne doit exécuter qu'UNE passe — pas max_passes — car rien ne change
    côté serveur. Sans la normalisation, la boucle relit 5 fois inutilement."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    monkeypatch.setattr(people_merge, "_collecter", lambda *a, **k: ([], {}))
    monkeypatch.setattr(people_merge, "etager", lambda *a, **k: ([], []))
    monkeypatch.setattr(
        people_merge, "plan_fusions", lambda *a, **k: ["grappe-factice"]
    )
    monkeypatch.setattr(
        people_merge, "filtrer_grappes_contradictoires", lambda g, ph: (g, [])
    )
    _fait_une_fusion.appels = 0
    monkeypatch.setattr(people_merge, "executer_grappes", _fait_une_fusion)
    path = people_merge.run_people_merge(
        object(), tmp_path, scope="all", date="2026-07-21", max_passes=5, dry_run=False
    )
    assert _fait_une_fusion.appels == 1
    rapport = path.read_text(encoding="utf-8")
    assert "simulation" in rapport
    # Une seule passe : si la boucle avait ignoré l'env et tourné 5 fois, le stub
    # (une fusion par appel) aurait gonflé le total à 5.
    assert "Fusions automatiques : 1" in rapport


# --- Défaut 3 (revue Task 8) : le rapport liste les personnes fusionnées -----


def test_rapport_liste_les_fusions_phoenix_titanic():
    """Une suppression irréversible doit laisser une trace nominative : quel titanic
    a été absorbé par quel phoenix, pas seulement un compteur (revue Task 8)."""
    rapport = people_merge.render_people_merge_report(
        "2026-07-21",
        passes=[(1, 1, 0)],
        arbitrage=[],
        ignores=[],
        dry_run=False,
        fusions=[("I1", "I2")],
    )
    assert "I1" in rapport
    assert "I2" in rapport


# --- Défaut 2 (revue Task 8) : le chemin YAML relu ne perd pas le genre -------


class _FetcherEspion:
    def __init__(self, personnes):
        self._p = {p.handle: p for p in personnes}

    def get_person_facts(self, handle):
        return self._p.get(handle)


def test_yaml_preserve_le_genre_du_titanic(monkeypatch, tmp_path):
    """Paire relue : phoenix de genre inconnu (mais plus complet) + titanic M. Le chemin
    YAML doit préserver le M — via un patch de genre AVANT la fusion, comme le chemin auto.
    Sans le correctif, phoenix=A/titanic=B figés + gender_patch=None perdaient le M."""
    from crewai_custom_tools.tools.genealogy.models.domain import EventFact

    phoenix_u = PersonFacts(
        gramps_id="I1",
        handle="hI1",
        name="",
        surname="Dupont",
        given="Jean",
        sex="U",
        birth=EventFact(type="Birth", sortval=677000, year=1850, place_name="Bourges"),
        parent_family_handles=["F1"],
    )
    titanic_m = PersonFacts(
        gramps_id="I2", handle="hI2", name="", surname="Dupont", given="Jean", sex="M"
    )
    fetcher = _FetcherEspion([phoenix_u, titanic_m])
    monkeypatch.setattr(people_merge, "FactsFetcher", lambda client: fetcher)
    fusion, genre = _OutilEspion(), _OutilEspion()
    monkeypatch.setattr(people_merge, "GrampsMergePeopleTool", lambda: fusion)
    monkeypatch.setattr(people_merge, "GrampsUpdateGenderTool", lambda: genre)
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    yaml_path = tmp_path / "arbitrage.yaml"
    yaml_path.write_text(
        "- {gramps_id_a: I1, handle_a: hI1, gramps_id_b: I2, handle_b: hI2}\n",
        encoding="utf-8",
    )
    people_merge.run_people_merge_yaml(
        object(), yaml_path, tmp_path, date="2026-07-21", dry_run=False
    )
    # Le phoenix (I1, plus complet) est de genre inconnu : son genre est patché à
    # 1 (M) AVANT toute fusion, faute de quoi le M du titanic disparaîtrait.
    assert genre.appels, "aucun patch de genre émis — le M du titanic serait perdu"
    assert genre.appels[0]["handle"] == "hI1"
    assert genre.appels[0]["gender"] == 1


def test_yaml_personne_introuvable_paire_ignoree_sans_planter(monkeypatch, tmp_path):
    """Un handle absent de l'arbre (get_person_facts -> None) ne doit pas planter :
    la paire est ignorée, l'erreur consignée, aucune fusion émise. Chemin d'erreur
    d'un module de fusions irréversibles — testé, pas seulement supposé."""
    present = PersonFacts(
        gramps_id="I1", handle="hI1", name="", surname="Dupont", given="Jean", sex="M"
    )
    fetcher = _FetcherEspion([present])  # hI2 absent -> get_person_facts rend None
    monkeypatch.setattr(people_merge, "FactsFetcher", lambda client: fetcher)
    fusion, genre = _OutilEspion(), _OutilEspion()
    monkeypatch.setattr(people_merge, "GrampsMergePeopleTool", lambda: fusion)
    monkeypatch.setattr(people_merge, "GrampsUpdateGenderTool", lambda: genre)
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    yaml_path = tmp_path / "arbitrage.yaml"
    yaml_path.write_text(
        "- {gramps_id_a: I1, handle_a: hI1, gramps_id_b: I2, handle_b: hI2}\n",
        encoding="utf-8",
    )
    path = people_merge.run_people_merge_yaml(
        object(), yaml_path, tmp_path, date="2026-07-21", dry_run=False
    )
    assert fusion.appels == []
    rapport = path.read_text(encoding="utf-8")
    assert "introuvable" in rapport or "| 1 | 0 | 1 |" in rapport
