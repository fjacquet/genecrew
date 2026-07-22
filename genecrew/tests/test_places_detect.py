"""Tests offline du mode détection de `merge places`."""

import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

from genecrew import places_merge
from genecrew.places_merge import collecter_lieux, render_detect_report, run_places_detect

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _arbre(places, backlinks=None):
    backlinks = backlinks or {}

    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        if p.startswith("/api/places/"):
            handle = p.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"backlinks": backlinks.get(handle, {})})
        return httpx.Response(404, json={})
    return _client(_h)


PLACE = {"handle": "H1", "gramps_id": "P0001", "name": {"value": "Bourges"},
         "place_type": "Municipality", "code": "18033", "lat": "47.081",
         "long": "2.398", "placeref_list": [{"ref": "HP"}]}


def test_collecte_les_champs_utiles():
    lieux = collecter_lieux(_arbre([PLACE]), "all")
    assert len(lieux) == 1
    p = lieux[0]
    assert (p.gramps_id, p.handle, p.nom) == ("P0001", "H1", "Bourges")
    assert p.place_type == "Municipality"
    assert p.code == "18033"
    assert (p.lat, p.long) == ("47.081", "2.398")
    assert p.a_parent is True


def test_compte_les_retroliens():
    client = _arbre([PLACE], backlinks={"H1": {"event": ["e1", "e2", "e3"],
                                               "place": ["p1"]}})
    assert collecter_lieux(client, "all")[0].retroliens == 4


def test_absence_de_retroliens_donne_zero():
    assert collecter_lieux(_arbre([PLACE]), "all")[0].retroliens == 0


def test_lieu_sans_nom_collecte_quand_meme_avec_nom_vide():
    """Le filtrage des noms vides appartient à la détection, pas à la collecte."""
    sans_nom = {**PLACE, "name": {}}
    assert collecter_lieux(_arbre([sans_nom]), "all")[0].nom == ""


def test_champs_absents_donnent_des_defauts_vides():
    nu = {"handle": "H2", "gramps_id": "P0002", "name": {"value": "X"}}
    p = collecter_lieux(_arbre([nu]), "all")[0]
    assert (p.place_type, p.code, p.lat, p.long, p.a_parent) == ("", "", "", "", False)


def test_echec_du_comptage_degrade_vers_zero_sans_faire_echouer_la_collecte():
    """Un vrai échec réseau/API sur le comptage ne doit ni lever, ni perdre le lieu."""
    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[PLACE] if page == 1 else [])
        if p.startswith("/api/places/"):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(404, json={})

    lieux = collecter_lieux(_client(_h), "all")
    assert len(lieux) == 1
    assert lieux[0].retroliens == 0


def test_categorie_de_retroliens_nulle_compte_pour_zero():
    """Une catégorie de rétroliens rendue à `null` par l'API ne doit pas faire tomber le lot

    (C1) : seule cette catégorie compte pour zéro, les autres catégories restent comptées.
    """
    client = _arbre([PLACE], backlinks={"H1": {"event": None, "place": ["p1"]}})
    lieux = collecter_lieux(client, "all")
    assert len(lieux) == 1
    assert lieux[0].retroliens == 1


def test_coupure_reseau_sur_le_comptage_degrade_vers_zero():
    """Une coupure réseau (avant toute réponse HTTP) dégrade vers zéro, comme un 5xx (C2)."""
    def _h(request):
        p = request.url.path
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[PLACE] if page == 1 else [])
        if p.startswith("/api/places/"):
            raise httpx.ConnectError("connexion refusée", request=request)
        return httpx.Response(404, json={})

    lieux = collecter_lieux(_client(_h), "all")
    assert len(lieux) == 1
    assert lieux[0].retroliens == 0


def test_handle_vide_ne_declenche_aucune_requete_de_retroliens():
    """Un lieu à handle vide rend zéro rétroliens sans jamais interroger l'URL de liste (C3)."""
    place_sans_handle = {**PLACE, "handle": ""}
    calls: list[str] = []

    def _h(request):
        p = request.url.path
        calls.append(p)
        if p == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[place_sans_handle] if page == 1 else [])
        return httpx.Response(404, json={})

    lieux = collecter_lieux(_client(_h), "all")
    assert len(lieux) == 1
    assert lieux[0].retroliens == 0
    # Deux pages de liste (page 1 avec le lieu, page 2 vide qui arrête la pagination) ;
    # un handle vide ne doit ajouter aucun appel de comptage vers "/api/places/".
    assert calls.count("/api/places/") == 2


def _prop(keep="P0064", merge="P0070", verdict="auto", perte="", canonical="Cerbois"):
    return PlaceMergeProposition(
        gramps_id_keep=keep, handle_keep="H" + keep,
        gramps_id_merge=merge, handle_merge="H" + merge,
        canonical=canonical, reason="homonymes — code officiel identique",
        verdict=verdict, perte_evitee=perte)


def test_mode_simulation_annonce_et_conjugue_au_conditionnel():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=True)
    assert "simulation" in md
    assert "Fusions à appliquer : 1" in md
    assert "Fusions appliquées" not in md


def test_mode_reel_annonce_les_ecritures():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=False)
    assert "écritures appliquées" in md
    assert "Fusions appliquées : 1" in md


def test_le_tableau_nomme_survivant_et_absorbe():
    md = render_detect_report("2026-07-21", [_prop()], [], [], 303, dry_run=False)
    assert "P0064" in md and "P0070" in md and "Cerbois" in md


def test_la_perte_evitee_apparait_quand_il_y_en_a_une():
    md = render_detect_report(
        "2026-07-21", [_prop(perte="coordonnées, code")], [], [], 303, dry_run=False)
    assert "coordonnées, code" in md


def test_l_arbitrage_est_une_section_distincte():
    md = render_detect_report("2026-07-21", [], [_prop(verdict="arbitrage",
                                                       canonical="Paris")], [], 303,
                              dry_run=False)
    assert "Arbitrage" in md
    assert "À relire : 1" in md
    assert "Paris" in md


def test_rien_a_faire_reste_lisible():
    md = render_detect_report("2026-07-21", [], [], [], 303, dry_run=False)
    assert "Fusions appliquées : 0" in md
    assert "À relire : 0" in md
    assert "Aucun doublon" in md


def test_les_erreurs_sont_rapportees():
    md = render_detect_report("2026-07-21", [], [], [("P0070", "HTTP 500")], 303,
                              dry_run=False)
    assert "P0070" in md and "HTTP 500" in md


def test_une_barre_verticale_dans_le_nom_n_ajoute_pas_de_colonne():
    """Un nom de lieu bancal (import réel : virgules et libellés composites) contenant
    une barre verticale et un saut de ligne ne doit ni ajouter de colonne ni faire
    éclater la ligne du tableau sur plusieurs lignes Markdown."""
    prop = _prop(canonical="Saint-Ouen | Faux-village\nligne2",
                 verdict="auto")
    md = render_detect_report("2026-07-21", [prop], [], [], 303, dry_run=False)
    lignes = md.splitlines()
    ligne = next(row for row in lignes if "P0064" in row and "P0070" in row)
    # 5 colonnes déclarées par l'en-tête == 6 barres verticales de structure ;
    # la barre du nom ne doit pas en ajouter une 7e.
    assert ligne.count("|") == 6
    assert "ligne2" in ligne  # le saut de ligne a été aplati, pas perdu
    assert "Faux-village" in ligne


def test_un_motif_multiligne_avec_pipe_n_ajoute_pas_de_colonne():
    """Même défaut sur le motif (`reason`) et la perte évitée : valeurs libres
    composées à partir des mêmes noms de lieux bancals."""
    prop = _prop(canonical="Cerbois",
                 perte="note *importante* | avec pipe\nligne2")
    md = render_detect_report("2026-07-21", [prop], [], [], 303, dry_run=False)
    ligne = next(row for row in md.splitlines() if "P0064" in row and "P0070" in row)
    assert ligne.count("|") == 6
    assert "avec pipe" in ligne and "ligne2" in ligne


def test_message_d_erreur_multiligne_ne_brise_pas_la_liste():
    """Un message d'erreur multiligne doit rester une seule puce, pas fusionner
    avec la puce suivante."""
    md = render_detect_report("2026-07-21", [], [],
                              [("P0070", "échec réseau\nsur la deuxième ligne"),
                               ("P0080", "autre erreur")],
                              303, dry_run=False)
    section = md.split("## Erreurs", 1)[1]
    puces = [row for row in section.splitlines() if row.startswith("- ")]
    assert len(puces) == 2
    assert "P0070" in puces[0] and "échec réseau" in puces[0] and "deuxième ligne" in puces[0]
    assert "P0080" in puces[1]


DOUBLONS = [
    {"handle": "HA", "gramps_id": "P0064", "name": {"value": "Cerbois"},
     "place_type": "Municipality", "code": "18044", "lat": "47.1", "long": "2.3"},
    {"handle": "HB", "gramps_id": "P0070", "name": {"value": "Cerbois"},
     "place_type": "Municipality", "code": "18044", "lat": "47.1", "long": "2.3"},
]
PARIS = [
    {"handle": "HC", "gramps_id": "P0301", "name": {"value": "Paris"},
     "place_type": "Department", "code": "75"},
    {"handle": "HD", "gramps_id": "P0008", "name": {"value": "Paris"},
     "place_type": "Municipality", "code": "75056"},
]
# Homonymes sans code, de types connus mais différents : `evaluer_preuve` ne prouve
# rien (ni code commun, ni types égaux), et rien n'oppose de veto (aucun code
# renseigné des deux côtés) — la paire N'EST PAS écartée du lot comme Paris, elle
# atterrit en arbitrage. C'est le cas qui exerce le passage YAML, distinct du veto.
HOMONYMES_SANS_PREUVE = [
    {"handle": "HE", "gramps_id": "P0501", "name": {"value": "Fontenay"},
     "place_type": "Municipality"},
    {"handle": "HF", "gramps_id": "P0502", "name": {"value": "Fontenay"},
     "place_type": "Department"},
]


def _stub_fusion(monkeypatch, succes=True):
    vus = []

    class _Outil:
        def _run(self, **kw):
            vus.append(kw)
            return json.dumps({"success": True, "data": kw} if succes
                              else {"success": False, "error": "HTTP 500"})

    monkeypatch.setattr(places_merge, "GrampsMergePlacesTool", _Outil)
    return vus


def test_fusionne_les_doublons_prouves(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Fusions appliquées : 1" in md
    assert len(vus) == 1
    assert vus[0]["keep_handle"] == "HA" and vus[0]["merge_handle"] == "HB"


def test_paris_n_est_jamais_fusionne(tmp_path, monkeypatch):
    """Le cas qui doit rester rouge si le veto disparaît.

    Deux codes officiels renseignés et différents (75 / 75056) prouvent deux
    entités distinctes : `etager_lieux` ne se contente pas de refuser la fusion
    automatique, elle retire la paire du lot — proposer un couple qu'on sait
    faux à un relecteur reviendrait à lui tendre un bouton pour le casser.
    Zéro fusion ET zéro arbitrage, donc — pas seulement zéro fusion.
    """
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(PARIS), tmp_path, scope="all", date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "Fusions appliquées : 0" in md
    assert "À relire : 0" in md


def test_l_arbitrage_est_ecrit_en_yaml_consommable(tmp_path, monkeypatch):
    """Le YAML doit être relisible par `merge places --yaml` sans transformation."""
    _stub_fusion(monkeypatch)
    run_places_detect(_arbre(HOMONYMES_SANS_PREUVE), tmp_path, scope="all",
                      date="2026-07-21")
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1
    assert set(lignes[0]) >= {"handle_keep", "handle_merge",
                              "gramps_id_keep", "gramps_id_merge", "canonical"}


def test_la_simulation_n_execute_aucune_fusion(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21", dry_run=True)
    assert vus == []
    md = chemin.read_text(encoding="utf-8")
    assert "simulation" in md
    assert "Fusions à appliquer : 1" in md


def test_un_echec_de_fusion_est_rapporte(tmp_path, monkeypatch):
    _stub_fusion(monkeypatch, succes=False)
    chemin = run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all",
                               date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Fusions appliquées : 0" in md
    assert "P0070" in md and "HTTP 500" in md


def test_une_proposition_d_arbitrage_n_est_jamais_executee_comme_fusion(tmp_path, monkeypatch):
    """Un couple 'arbitrage' ne doit JAMAIS transiter par l'outil de fusion, même
    lorsqu'un autre couple prouvé du même lot, lui, s'exécute — sans quoi l'outil
    fusionnerait irréversiblement une paire que la détection a explicitement
    renvoyée à la relecture humaine faute de preuve."""
    vus = _stub_fusion(monkeypatch)
    chemin = run_places_detect(_arbre(DOUBLONS + HOMONYMES_SANS_PREUVE), tmp_path,
                               scope="all", date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert len(vus) == 1
    assert vus[0]["keep_handle"] == "HA" and vus[0]["merge_handle"] == "HB"
    assert {v["merge_handle"] for v in vus}.isdisjoint({"HE", "HF"})
    assert "Fusions appliquées : 1" in md
    assert "À relire : 1" in md
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1
    assert lignes[0]["handle_merge"] in {"HE", "HF"}
