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
    return MergeCluster(phoenix_handle="hI1", phoenix_gramps_id="I1",
                        titanic_handles=list(titanics),
                        titanic_gramps_ids=[t.replace("h", "") for t in titanics],
                        gender_patch=gender_patch)


def test_une_grappe_fusionne_chaque_titanic(outils):
    fusion, _ = outils
    faites, erreurs = people_merge.executer_grappes(
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False)
    assert len(fusion.appels) == 2
    assert erreurs == []
    assert len(faites) == 2


def test_le_patch_de_genre_precede_la_fusion(outils):
    """Person.merge() ignore le genre : patcher APRÈS ne servirait à rien."""
    fusion, genre = outils
    ordre = []
    genre._run = lambda **kw: (ordre.append("genre"), json.dumps({"success": True}))[1]
    fusion._run = lambda **kw: (ordre.append("fusion"), json.dumps({"success": True}))[1]
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
        [_grappe(titanics=("hI2", "hI3"))], dry_run=False)
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
            [_grappe(gender_patch=1)], dry_run=False)
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
        "2026-07-20", passes=[(1, 3, 0)], arbitrage=[], ignores=["nom:pagan"],
        dry_run=True)
    assert "simulation" in rapport
    assert "nom:pagan" in rapport
    assert "relancer" in rapport.lower()


def test_rapport_sans_fusion_n_invite_pas_a_relancer():
    rapport = people_merge.render_people_merge_report(
        "2026-07-20", passes=[(1, 0, 0)], arbitrage=[], ignores=[], dry_run=False)
    assert "relancer" not in rapport.lower()


def _personne(gramps_id, handle, sex):
    return PersonFacts(gramps_id=gramps_id, handle=handle, name="", surname="Dupont",
                       given="Jean", sex=sex)


def test_grappe_genres_titanics_contradictoires_non_fusionnee():
    """Phoenix de genre inconnu, mais ses titanics portent des genres OPPOSÉS (M et F) :
    signal que l'étage auto a peut-être mal jugé la paire (revue Task 5). On n'exécute
    pas la fusion, on consigne une erreur explicite, et le lot continue — même
    traitement que l'échec du patch de genre."""
    phoenix = _personne("I1", "hI1", "U")
    titanic_m = _personne("I2", "hI2", "M")
    titanic_f = _personne("I3", "hI3", "F")
    par_handle = {p.handle: p for p in (phoenix, titanic_m, titanic_f)}
    grappe = MergeCluster(phoenix_handle="hI1", phoenix_gramps_id="I1",
                          titanic_handles=["hI2", "hI3"],
                          titanic_gramps_ids=["I2", "I3"], gender_patch=1)
    grappes_valides, erreurs = people_merge.filtrer_grappes_contradictoires(
        [grappe], par_handle)
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
    grappe = MergeCluster(phoenix_handle="hI1", phoenix_gramps_id="I1",
                          titanic_handles=["hI2", "hI3"],
                          titanic_gramps_ids=["I2", "I3"], gender_patch=None)
    grappes_valides, erreurs = people_merge.filtrer_grappes_contradictoires(
        [grappe], par_handle)
    assert grappes_valides == [grappe]
    assert erreurs == []
