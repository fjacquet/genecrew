"""Tests offline du mode détection de `merge places`."""

import json
import logging

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.models.domain import PlaceMergeProposition

from genecrew import places_merge
from genecrew.places_merge import (
    collecter_lieux,
    render_detect_report,
    run_places_detect,
    run_places_merge,
)

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


PLACE = {
    "handle": "H1",
    "gramps_id": "P0001",
    "name": {"value": "Bourges"},
    "place_type": "Municipality",
    "code": "18033",
    "lat": "47.081",
    "long": "2.398",
    "placeref_list": [{"ref": "HP"}],
}


def test_collecte_les_champs_utiles():
    lieux = collecter_lieux(_arbre([PLACE]), "all")
    assert len(lieux) == 1
    p = lieux[0]
    assert (p.gramps_id, p.handle, p.nom) == ("P0001", "H1", "Bourges")
    assert p.place_type == "Municipality"
    assert p.code == "18033"
    assert (p.lat, p.long) == ("47.081", "2.398")
    # `parent_id` porte l'IDENTIFIANT du contenant, pas un booléen : c'est lui qui
    # discrimine deux homonymes sans code officiel. Un booléen laissait la garde de
    # `evaluer_preuve` sans matière — pydantic ignore un champ inconnu en silence, la
    # construction réussissait et le contenant restait vide.
    assert p.parent_id == "HP"


def test_compte_les_retroliens():
    client = _arbre(
        [PLACE], backlinks={"H1": {"event": ["e1", "e2", "e3"], "place": ["p1"]}}
    )
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
    assert (p.place_type, p.code, p.lat, p.long, p.parent_id) == ("", "", "", "", "")


def test_un_contenant_multiple_reste_inconnu():
    """Contrat du modèle : `""` dès que le contenant n'est pas UNIQUE et connu.

    Une commune fusionnée porte deux `placeref_list` datées — le département avant la
    fusion, la commune absorbante après. En choisir un arbitrairement fabriquerait une
    différence de contenant là où il n'y en a pas, donc un refus de fusion sur un pur
    artefact de lecture. `""` vaut « on ne sait pas », qui n'oppose jamais rien.
    """
    fusionnee = {**PLACE, "placeref_list": [{"ref": "HDEP"}, {"ref": "HCOMMUNE"}]}
    assert collecter_lieux(_arbre([fusionnee]), "all")[0].parent_id == ""


def test_un_contenant_repete_reste_connu():
    """Deux références datées vers le MÊME contenant ne le rendent pas ambigu.

    L'unicité porte sur l'identifiant visé, pas sur le nombre de lignes de la liste :
    dédupliquer ici évite de perdre le seul discriminant des homonymes sans code sur
    une redondance de saisie.
    """
    repete = {**PLACE, "placeref_list": [{"ref": "HP"}, {"ref": "HP"}]}
    assert collecter_lieux(_arbre([repete]), "all")[0].parent_id == "HP"


def test_une_reference_de_contenant_vide_ne_compte_pas():
    """Un `ref` vide ou blanc n'est pas un contenant connu : il ne doit ni valoir
    identifiant, ni rendre ambigu le contenant réellement renseigné à côté."""
    bancal = {**PLACE, "placeref_list": [{"ref": "  "}, {"ref": "HP"}]}
    assert collecter_lieux(_arbre([bancal]), "all")[0].parent_id == "HP"


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
        gramps_id_keep=keep,
        handle_keep="H" + keep,
        gramps_id_merge=merge,
        handle_merge="H" + merge,
        canonical=canonical,
        reason="homonymes — code officiel identique",
        verdict=verdict,
        perte_evitee=perte,
    )


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
        "2026-07-21", [_prop(perte="coordonnées, code")], [], [], 303, dry_run=False
    )
    assert "coordonnées, code" in md


def test_l_arbitrage_est_une_section_distincte():
    md = render_detect_report(
        "2026-07-21",
        [],
        [_prop(verdict="arbitrage", canonical="Paris")],
        [],
        303,
        dry_run=False,
    )
    assert "Arbitrage" in md
    assert "À relire : 1" in md
    assert "Paris" in md


def test_rien_a_faire_reste_lisible():
    md = render_detect_report("2026-07-21", [], [], [], 303, dry_run=False)
    assert "Fusions appliquées : 0" in md
    assert "À relire : 0" in md
    assert "Aucun doublon" in md


def test_les_erreurs_sont_rapportees():
    md = render_detect_report(
        "2026-07-21", [], [], [("P0070", "HTTP 500")], 303, dry_run=False
    )
    assert "P0070" in md and "HTTP 500" in md


def test_une_barre_verticale_dans_le_nom_n_ajoute_pas_de_colonne():
    """Un nom de lieu bancal (import réel : virgules et libellés composites) contenant
    une barre verticale et un saut de ligne ne doit ni ajouter de colonne ni faire
    éclater la ligne du tableau sur plusieurs lignes Markdown."""
    prop = _prop(canonical="Saint-Ouen | Faux-village\nligne2", verdict="auto")
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
    prop = _prop(canonical="Cerbois", perte="note *importante* | avec pipe\nligne2")
    md = render_detect_report("2026-07-21", [prop], [], [], 303, dry_run=False)
    ligne = next(row for row in md.splitlines() if "P0064" in row and "P0070" in row)
    assert ligne.count("|") == 6
    assert "avec pipe" in ligne and "ligne2" in ligne


def test_message_d_erreur_multiligne_ne_brise_pas_la_liste():
    """Un message d'erreur multiligne doit rester une seule puce, pas fusionner
    avec la puce suivante."""
    md = render_detect_report(
        "2026-07-21",
        [],
        [],
        [("P0070", "échec réseau\nsur la deuxième ligne"), ("P0080", "autre erreur")],
        303,
        dry_run=False,
    )
    section = md.split("## Erreurs", 1)[1]
    puces = [row for row in section.splitlines() if row.startswith("- ")]
    assert len(puces) == 2
    assert (
        "P0070" in puces[0]
        and "échec réseau" in puces[0]
        and "deuxième ligne" in puces[0]
    )
    assert "P0080" in puces[1]


DOUBLONS = [
    {
        "handle": "HA",
        "gramps_id": "P0064",
        "name": {"value": "Cerbois"},
        "place_type": "Municipality",
        "code": "18044",
        "lat": "47.1",
        "long": "2.3",
    },
    {
        "handle": "HB",
        "gramps_id": "P0070",
        "name": {"value": "Cerbois"},
        "place_type": "Municipality",
        "code": "18044",
        "lat": "47.1",
        "long": "2.3",
    },
]
PARIS = [
    {
        "handle": "HC",
        "gramps_id": "P0301",
        "name": {"value": "Paris"},
        "place_type": "Department",
        "code": "75",
    },
    {
        "handle": "HD",
        "gramps_id": "P0008",
        "name": {"value": "Paris"},
        "place_type": "Municipality",
        "code": "75056",
    },
]
# Homonymes sans code, de types connus mais différents : `evaluer_preuve` ne prouve
# rien (ni code commun, ni types égaux), et rien n'oppose de veto (aucun code
# renseigné des deux côtés) — la paire N'EST PAS écartée du lot comme Paris, elle
# atterrit en arbitrage. C'est le cas qui exerce le passage YAML, distinct du veto.
HOMONYMES_SANS_PREUVE = [
    {
        "handle": "HE",
        "gramps_id": "P0501",
        "name": {"value": "Fontenay"},
        "place_type": "Municipality",
    },
    {
        "handle": "HF",
        "gramps_id": "P0502",
        "name": {"value": "Fontenay"},
        "place_type": "Department",
    },
]
# Deux « Saint-Michel » sans code officiel, de MÊME type et aux coordonnées
# IDENTIQUES — la voie de preuve par coordonnées est grande ouverte — mais rattachés
# à deux contenants différents : deux communes de deux départements. Le contenant est
# ici le SEUL discriminant, et c'est la fixture qui prouve que la garde livrée par la
# bibliothèque n'est pas inerte côté collecte.
CONTENANTS_DIFFERENTS = [
    {
        "handle": "HI",
        "gramps_id": "P0801",
        "name": {"value": "Saint-Michel"},
        "place_type": "Municipality",
        "lat": "47.5",
        "long": "2.5",
        "placeref_list": [{"ref": "HDEP18"}],
    },
    {
        "handle": "HJ",
        "gramps_id": "P0802",
        "name": {"value": "Saint-Michel"},
        "place_type": "Municipality",
        "lat": "47.5",
        "long": "2.5",
        "placeref_list": [{"ref": "HDEP36"}],
    },
]
# Le contrepoint : mêmes conditions, MÊME contenant. La garde ne doit pas être trop
# serrée — un contenant identique ne refuse rien, la preuve par coordonnées tient.
MEME_CONTENANT = [
    {
        "handle": "HK",
        "gramps_id": "P0901",
        "name": {"value": "Levet"},
        "place_type": "Municipality",
        "lat": "46.9",
        "long": "2.4",
        "placeref_list": [{"ref": "HDEP18"}],
    },
    {
        "handle": "HL",
        "gramps_id": "P0902",
        "name": {"value": "Levet"},
        "place_type": "Municipality",
        "lat": "46.9",
        "long": "2.4",
        "placeref_list": [{"ref": "HDEP18"}],
    },
]
# Le cas d'école du chantier : deux « Annaba », l'un `Department` sans code, l'autre
# `Wilaya` code 23. Aucune preuve ne les départage — c'est exactement la paire que le
# relecteur doit trancher, et il lui faut les faits sous les yeux.
ANNABA = [
    {
        "handle": "HM",
        "gramps_id": "P1001",
        "name": {"value": "Annaba"},
        "place_type": "Department",
        "lat": "36.9",
        "long": "7.76",
        "placeref_list": [{"ref": "HDZ"}],
    },
    {
        "handle": "HN",
        "gramps_id": "P1002",
        "name": {"value": "Annaba"},
        "place_type": "Wilaya",
        "code": "23",
    },
]


# Quatre « Saint-Palais » : deux sans code officiel mais géocodés au même point, et
# deux portant des codes officiels DIFFÉRENTS. Ce sont ces deux derniers qui portent
# la preuve que la grappe mélange deux entités réelles ; le veto de grappe est une
# propriété du GROUPE ENTIER, pas de la paire courante. Tronquer le lot fait donc
# tomber la garde — d'où la simulation forcée dès que `--limit` est posé.
SAINT_PALAIS = [
    {
        "handle": "HA",
        "gramps_id": "P0201",
        "name": {"value": "Saint-Palais"},
        "place_type": "Municipality",
        "lat": "47.0",
        "long": "2.0",
    },
    {
        "handle": "HB",
        "gramps_id": "P0202",
        "name": {"value": "Saint-Palais"},
        "place_type": "Municipality",
        "lat": "47.0",
        "long": "2.0",
    },
    {
        "handle": "HC",
        "gramps_id": "P0203",
        "name": {"value": "Saint-Palais"},
        "place_type": "Municipality",
        "code": "18205",
    },
    {
        "handle": "HD",
        "gramps_id": "P0204",
        "name": {"value": "Saint-Palais"},
        "place_type": "Municipality",
        "code": "17398",
    },
]
# Deux lieux de MÊME code officiel dont seul l'absorbé porte le type. La preuve
# existe (« code officiel identique ») mais la fusion détruirait le seul type
# renseigné de la grappe : `etager_lieux` rend donc `verdict='arbitrage'` avec un
# motif qui contient malgré tout « code officiel identique ». C'est la seule fixture
# qui DISSOCIE le verdict du texte du motif — celle qui piège un tri sur `reason`.
CODE_IDENTIQUE_TYPE_PERDU = [
    {
        "handle": "HG",
        "gramps_id": "P0601",
        "name": {"value": "Vierzon"},
        "code": "18279",
    },
    {
        "handle": "HH",
        "gramps_id": "P0602",
        "name": {"value": "Vierzon"},
        "place_type": "Municipality",
        "code": "18279",
    },
]
# Une grappe de quatre clones parfaits : un survivant et TROIS fusions prouvées.
# Sert à interrompre le lot en cours de route.
QUADRUPLE = [
    {
        "handle": f"HQ{i}",
        "gramps_id": f"P07{i:02d}",
        "name": {"value": "Cerbois"},
        "place_type": "Municipality",
        "code": "18044",
        "lat": "47.1",
        "long": "2.3",
    }
    for i in range(4)
]


def _stub_fusion(monkeypatch, succes=True):
    vus = []

    class _Outil:
        def _run(self, **kw):
            vus.append(kw)
            return json.dumps(
                {"success": True, "data": kw}
                if succes
                else {"success": False, "error": "HTTP 500"}
            )

    monkeypatch.setattr(places_merge, "GrampsMergePlacesTool", _Outil)
    return vus


def _stub_fusion_interrompue(monkeypatch, exc, a_l_appel):
    """Outil de fusion qui réussit puis lève `exc` au `a_l_appel`-ième appel."""
    vus = []

    class _Outil:
        def _run(self, **kw):
            vus.append(kw)
            if len(vus) == a_l_appel:
                raise exc
            return json.dumps({"success": True, "data": kw})

    monkeypatch.setattr(places_merge, "GrampsMergePlacesTool", _Outil)
    return vus


def test_fusionne_les_doublons_prouves(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
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
    resultat = run_places_detect(
        _arbre(PARIS), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "Fusions appliquées : 0" in md
    assert "À relire : 0" in md


def test_l_arbitrage_est_ecrit_en_yaml_consommable(tmp_path, monkeypatch):
    """Le YAML doit être relisible par `merge places --yaml` sans transformation."""
    _stub_fusion(monkeypatch)
    run_places_detect(
        _arbre(HOMONYMES_SANS_PREUVE), tmp_path, scope="all", date="2026-07-21"
    )
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1
    assert set(lignes[0]) >= {
        "handle_keep",
        "handle_merge",
        "gramps_id_keep",
        "gramps_id_merge",
        "canonical",
    }


def test_la_simulation_n_execute_aucune_fusion(tmp_path, monkeypatch):
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21", dry_run=True
    )
    assert vus == []
    md = resultat.chemin.read_text(encoding="utf-8")
    assert "simulation" in md
    assert "Fusions à appliquer : 1" in md


def test_un_echec_de_fusion_est_rapporte(tmp_path, monkeypatch):
    _stub_fusion(monkeypatch, succes=False)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert "Fusions appliquées : 0" in md
    assert "P0070" in md and "HTTP 500" in md


def test_une_proposition_d_arbitrage_n_est_jamais_executee_comme_fusion(
    tmp_path, monkeypatch
):
    """Un couple 'arbitrage' ne doit JAMAIS transiter par l'outil de fusion, même
    lorsqu'un autre couple prouvé du même lot, lui, s'exécute — sans quoi l'outil
    fusionnerait irréversiblement une paire que la détection a explicitement
    renvoyée à la relecture humaine faute de preuve."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS + HOMONYMES_SANS_PREUVE),
        tmp_path,
        scope="all",
        date="2026-07-21",
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert len(vus) == 1
    assert vus[0]["keep_handle"] == "HA" and vus[0]["merge_handle"] == "HB"
    assert {v["merge_handle"] for v in vus}.isdisjoint({"HE", "HF"})
    assert "Fusions appliquées : 1" in md
    assert "À relire : 1" in md
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1
    assert lignes[0]["handle_merge"] in {"HE", "HF"}


# --- C1 : un lot borné ne peut pas décider d'une fusion -----------------------------


def test_le_scan_complet_de_la_grappe_melangee_ne_fusionne_rien(tmp_path, monkeypatch):
    """Référence de comparaison : sur les quatre « Saint-Palais », le veto de grappe
    tient et renvoie les trois couples à la relecture."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(SAINT_PALAIS), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "À relire : 3" in md
    assert (
        resultat.lot_borne is False
    )  # aucun --limit ici : ce n'est pas la garde du lot


def test_un_lot_borne_n_execute_aucune_fusion(tmp_path, monkeypatch):
    """Le cœur de C1 : borner le lot tronque les groupes et fait tomber une garde qui
    est une propriété du GROUPE ENTIER. Sur les mêmes quatre « Saint-Palais » bornés à
    trois, le membre exclu est justement celui qui portait la preuve du mélange : sans
    la simulation forcée, la paire HA/HB partirait en fusion IRRÉVERSIBLE."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(SAINT_PALAIS), tmp_path, scope="all", date="2026-07-21", limit=3
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "Fusions à appliquer" in md
    assert "Fusions appliquées" not in md
    # (C2) `lot_borne` est la seule source de vérité que la CLI doit consommer pour son
    # avertissement console — elle ne doit plus jamais réinspecter `args.limit`.
    assert resultat.lot_borne is True


def test_un_lot_borne_dit_pourquoi_rien_n_a_ete_ecrit(tmp_path, monkeypatch):
    """Sans explication, l'utilisateur qui suit la consigne de borner croirait à une
    panne. Le rapport doit nommer `--limit` et dire que le passage complet est requis."""
    _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21", limit=2
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert "--limit" in md
    assert "lot borné" in md
    assert resultat.lot_borne is True


def test_un_lot_borne_ignore_la_demande_d_ecriture(tmp_path, monkeypatch):
    """`dry_run=False` explicite ne rachète pas un lot tronqué."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS),
        tmp_path,
        scope="all",
        date="2026-07-21",
        limit=2,
        dry_run=False,
    )
    assert vus == []
    assert resultat.lot_borne is True


def test_un_lot_complet_fusionne_toujours(tmp_path, monkeypatch):
    """La garde ne doit pas être trop serrée : sans `--limit`, une grappe saine
    s'exécute comme avant."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21", limit=None
    )
    assert len(vus) == 1
    assert "Fusions appliquées : 1" in resultat.chemin.read_text(encoding="utf-8")
    assert resultat.lot_borne is False


# --- C2 : une interruption ne perd pas la trace des fusions déjà faites -------------


def test_chaque_fusion_executee_laisse_une_ligne_de_journal(
    tmp_path, monkeypatch, caplog
):
    """La trace doit être posée AU MOMENT de la fusion, pas à la fin du lot : c'est la
    seule chose qui survive à une interruption brutale."""
    _stub_fusion(monkeypatch)
    with caplog.at_level(logging.INFO, logger="genecrew"):
        run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21")
    trace = "\n".join(r.getMessage() for r in caplog.records)
    assert "P0070" in trace and "P0064" in trace


def test_la_simulation_ne_journalise_aucune_fusion(tmp_path, monkeypatch, caplog):
    """Une simulation n'écrit rien : le journal ne doit pas laisser croire l'inverse."""
    _stub_fusion(monkeypatch)
    with caplog.at_level(logging.INFO, logger="genecrew"):
        run_places_detect(
            _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21", dry_run=True
        )
    assert "P0070" not in "\n".join(r.getMessage() for r in caplog.records)


def test_une_coupure_reseau_laisse_le_rapport_des_fusions_deja_faites(
    tmp_path, monkeypatch
):
    """Deux fusions irréversibles ont eu lieu : le rapport doit exister et les nommer,
    et l'exception doit poursuivre son chemin plutôt que d'être avalée."""
    vus = _stub_fusion_interrompue(
        monkeypatch, httpx.ConnectError("coupure"), a_l_appel=3
    )
    with pytest.raises(httpx.ConnectError):
        run_places_detect(_arbre(QUADRUPLE), tmp_path, scope="all", date="2026-07-21")
    assert len(vus) == 3
    md = (tmp_path / "lieux" / "2026-07-21_doublons_lieux_all.md").read_text(
        encoding="utf-8"
    )
    assert "Fusions appliquées : 2" in md
    assert "P0701" in md and "P0702" in md


def test_une_interruption_clavier_laisse_le_rapport_des_fusions_deja_faites(
    tmp_path, monkeypatch
):
    """Ctrl-C n'est pas une hypothèse : ces passages durent des minutes. `KeyboardInterrupt`
    dérive de `BaseException`, donc un `except Exception` ne suffirait pas."""
    _stub_fusion_interrompue(monkeypatch, KeyboardInterrupt(), a_l_appel=3)
    with pytest.raises(KeyboardInterrupt):
        run_places_detect(_arbre(QUADRUPLE), tmp_path, scope="all", date="2026-07-21")
    md = (tmp_path / "lieux" / "2026-07-21_doublons_lieux_all.md").read_text(
        encoding="utf-8"
    )
    assert "Fusions appliquées : 2" in md


def test_une_interruption_ecrit_quand_meme_le_yaml_d_arbitrage(tmp_path, monkeypatch):
    """Le fichier d'arbitrage est la seule liste de ce qui reste à faire ; le perdre
    obligerait à relancer un scan complet sur un arbre déjà à moitié fusionné."""
    _stub_fusion_interrompue(monkeypatch, KeyboardInterrupt(), a_l_appel=3)
    with pytest.raises(KeyboardInterrupt):
        run_places_detect(
            _arbre(QUADRUPLE + HOMONYMES_SANS_PREUVE),
            tmp_path,
            scope="all",
            date="2026-07-21",
        )
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert [ligne["handle_merge"] for ligne in lignes] == ["HF"]


# --- I3 : le tri se fait sur le verdict, jamais sur le texte du motif ---------------


def test_un_arbitrage_dont_le_motif_dit_code_officiel_identique_n_est_pas_fusionne(
    tmp_path, monkeypatch
):
    """La fixture qui dissocie le verdict du motif. Deux « Vierzon » de même code
    officiel : la preuve existe et le motif la nomme, mais l'absorbé porte seul le
    type, que la fusion écraserait — verdict « arbitrage ». Trier la boucle sur le
    texte du motif au lieu du verdict fusionnerait irréversiblement ce couple que la
    détection a explicitement renvoyé à un humain."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(CODE_IDENTIQUE_TYPE_PERDU), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert vus == []  # tue la mutation « boucle de fusion »
    assert "Fusions appliquées : 0" in md
    assert "À relire : 1" in md
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    lignes = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert len(lignes) == 1  # tue la mutation « liste d'arbitrage »
    assert lignes[0]["handle_merge"] == "HH"
    assert lignes[0]["verdict"] == "arbitrage"
    # Le piège est bien armé : le motif contient la formule qui trompe un tri textuel.
    assert "code officiel identique" in lignes[0]["reason"]


# --- I4 : la valeur réellement transmise à l'outil de fusion ------------------------


def test_l_outil_de_fusion_recoit_une_demande_d_ecriture_reelle(tmp_path, monkeypatch):
    """L'argument de simulation passé à l'outil n'est observé par aucun test : le
    forcer à `True` laisserait la suite verte tout en produisant un rapport qui
    annonce des fusions appliquées sur un arbre resté dédoublé."""
    vus = _stub_fusion(monkeypatch)
    run_places_detect(_arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21")
    assert len(vus) == 1
    assert vus[0]["dry_run"] is False


# --- I5 : le fichier d'arbitrage porte son exigence de relecture --------------------


def test_le_yaml_d_arbitrage_porte_un_en_tete_de_relecture(tmp_path, monkeypatch):
    """`merge places --yaml` ne regarde jamais le verdict : il exécutera toutes les
    lignes restantes. Le fichier doit le dire lui-même, pas seulement le rapport."""
    _stub_fusion(monkeypatch)
    run_places_detect(
        _arbre(HOMONYMES_SANS_PREUVE), tmp_path, scope="all", date="2026-07-21"
    )
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    texte = p.read_text(encoding="utf-8")
    entete = [ligne for ligne in texte.splitlines() if ligne.startswith("#")]
    assert entete, "aucun en-tête en commentaire"
    bloc = "\n".join(entete).lower()
    assert "relire" in bloc or "relecture" in bloc
    assert "élaguer" in bloc or "supprim" in bloc
    assert "irréversible" in bloc
    # Un commentaire YAML est ignoré à la lecture : le fichier reste consommable tel quel.
    lignes = yaml.safe_load(texte)
    assert len(lignes) == 1
    assert set(lignes[0]) >= {"handle_keep", "handle_merge"}


# --- C1 : le contenant discrimine les homonymes sans code officiel -----------------


def test_deux_homonymes_de_contenants_differents_ne_fusionnent_pas(
    tmp_path, monkeypatch
):
    """La garde livrée par la bibliothèque ne doit plus être inerte.

    Deux « Saint-Michel » sans code officiel, de même type et aux coordonnées
    identiques : la voie de preuve par coordonnées les fusionnerait automatiquement et
    IRRÉVERSIBLEMENT. Seul leur rattachement à deux départements différents dit que ce
    sont deux communes. Tant que la collecte alimentait un booléen « a un contenant »,
    pydantic ignorait le champ en silence, `parent_id` restait vide, et la garde ne se
    déclenchait jamais.
    """
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(CONTENANTS_DIFFERENTS), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert vus == []
    assert "Fusions appliquées : 0" in md
    assert "À relire : 1" in md


def test_un_contenant_identique_ne_refuse_rien(tmp_path, monkeypatch):
    """Le contrepoint : la garde ne doit pas être trop serrée. Même type, mêmes
    coordonnées, MÊME contenant — la preuve par coordonnées tient et la fusion part."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(MEME_CONTENANT), tmp_path, scope="all", date="2026-07-21"
    )
    assert len(vus) == 1
    assert vus[0]["keep_handle"] == "HK" and vus[0]["merge_handle"] == "HL"
    assert "Fusions appliquées : 1" in resultat.chemin.read_text(encoding="utf-8")


# --- C2 : le fichier d'arbitrage porte de quoi décider sans ouvrir Gramps ----------


def _arbitrage(tmp_path, places, backlinks=None, scope="all"):
    run_places_detect(
        _arbre(places, backlinks), tmp_path, scope=scope, date="2026-07-21"
    )
    p = tmp_path / "lieux" / "2026-07-21_arbitrage_lieux_all.yaml"
    return p, yaml.safe_load(p.read_text(encoding="utf-8"))


def test_le_yaml_d_arbitrage_porte_les_faits_des_deux_lieux(tmp_path, monkeypatch):
    """Spécification du chantier : « types, codes, coordonnées et nombre de rétroliens
    en clair, pour que la relecture soit possible sans ouvrir Gramps ». Sur le cas
    d'école (deux « Annaba »), le relecteur ne voyait que « aucune preuve »."""
    _stub_fusion(monkeypatch)
    _p, lignes = _arbitrage(
        tmp_path,
        ANNABA,
        backlinks={"HM": {"event": ["e1", "e2"]}, "HN": {"event": ["e3"]}},
    )
    assert len(lignes) == 1
    relecture = lignes[0]["relecture"]
    assert relecture["garde"] == {
        "type": "Department",
        "code": "",
        "lat": "36.9",
        "long": "7.76",
        "contenant": "HDZ",
        "retroliens": 2,
    }
    assert relecture["absorbe"] == {
        "type": "Wilaya",
        "code": "23",
        "lat": "",
        "long": "",
        "contenant": "",
        "retroliens": 1,
    }


def test_le_yaml_d_arbitrage_enrichi_reste_consommable_tel_quel(tmp_path, monkeypatch):
    """Contrainte forte : aller-retour RÉEL. Le fichier produit par la détection doit
    être exécutable par `merge places --yaml` sans la moindre transformation — les
    faits de relecture sont un supplément, pas un changement de contrat."""
    vus = _stub_fusion(monkeypatch)
    chemin_yaml, lignes = _arbitrage(tmp_path, ANNABA)
    assert len(lignes) == 1

    rapport = run_places_merge(_arbre(ANNABA), chemin_yaml, tmp_path, date="2026-07-22")
    assert [(v["keep_handle"], v["merge_handle"]) for v in vus] == [("HM", "HN")]
    md = rapport.read_text(encoding="utf-8")
    assert "P1001" in md and "P1002" in md and "Annaba" in md


def test_le_tableau_d_arbitrage_montre_les_faits_et_la_perte_evitee(
    tmp_path, monkeypatch
):
    """Le rapport est l'autre moitié de la porte humaine : mêmes faits, plus la perte
    évitée, qui manquait alors qu'elle était déjà calculée."""
    _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(ANNABA, backlinks={"HM": {"event": ["e1", "e2"]}}),
        tmp_path,
        scope="all",
        date="2026-07-21",
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    ligne = next(row for row in md.splitlines() if "P1001" in row and "P1002" in row)
    assert "Department" in ligne and "Wilaya" in ligne  # types
    assert "23" in ligne  # code de l'absorbé
    assert "36.9" in ligne and "7.76" in ligne  # coordonnées du gardé
    assert "2" in ligne  # rétroliens du gardé
    assert "coordonnées, type" in ligne  # perte évitée


def test_le_tableau_d_arbitrage_ne_laisse_aucune_cellule_vide(tmp_path, monkeypatch):
    """Une cellule vide se lit « je n'ai pas regardé » ; le tiret dit « non renseigné ».

    Deux « Fontenay » sans code, sans coordonnées, sans contenant : trois colonnes de
    faits n'ont rien à montrer des deux côtés, et doivent porter `— / —` plutôt que du
    blanc. On compte les cellules au lieu de chercher un tiret dans la ligne — le motif
    contient lui-même un tiret cadratin (« homonymes — aucune preuve »), qui rendrait
    l'assertion vraie quoi qu'il arrive.
    """
    _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(HOMONYMES_SANS_PREUVE), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    ligne = next(row for row in md.splitlines() if "P0501" in row and "P0502" in row)
    cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
    assert all(cellules), f"cellule vide dans {cellules}"
    assert cellules.count("— / —") == 3  # code, coordonnées, contenant


def test_un_fait_de_lieu_bancal_n_ajoute_pas_de_colonne(tmp_path, monkeypatch):
    """Les faits viennent de l'arbre comme les noms : un code saisi avec une barre
    verticale ne doit pas décaler les colonnes du tableau d'arbitrage — un relecteur
    associerait la mauvaise preuve au mauvais couple sur une décision irréversible."""
    bancal = [
        {**HOMONYMES_SANS_PREUVE[0], "code": "A|B"},
        {**HOMONYMES_SANS_PREUVE[1], "place_type": "Dé|partement\nsuite"},
    ]
    _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(bancal), tmp_path, scope="all", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    section = md.split("## Arbitrage", 1)[1]
    entete = next(row for row in section.splitlines() if row.startswith("| Gardé"))
    ligne = next(
        row for row in section.splitlines() if "P0501" in row and "P0502" in row
    )
    assert ligne.count("|") == entete.count("|")
    assert "suite" in ligne  # le saut de ligne a été aplati, pas perdu


# --- C3 : les docstrings disent ce que le code fait ---------------------------------


def test_le_module_ne_promet_plus_de_ne_jamais_fusionner_automatiquement():
    """`merge places` détecte ET fusionne les doublons prouvés depuis ce chantier. Dans
    un dépôt où la docstring tient lieu de spécification de sûreté, l'en-tête du module
    d'orchestration est la première ligne que lira le prochain relecteur."""
    entete = (places_merge.__doc__ or "").lower()
    assert "never automatic" not in entete
    assert "jamais automatique" not in entete
    assert "détecte" in entete or "detect" in entete


def test_le_fichier_de_conventions_ne_dit_plus_jamais_auto_pour_merge_places():
    """CLAUDE.md conserve « (jamais auto) » juste au-dessus de la ligne qui annonce la
    détection automatique — deux lignes voisines qui se contredisent."""
    from pathlib import Path

    conventions = Path(__file__).resolve().parents[2] / "CLAUDE.md"
    lignes = [
        ligne
        for ligne in conventions.read_text(encoding="utf-8").splitlines()
        if "genecrew merge places" in ligne
    ]
    assert lignes, "aucune ligne `genecrew merge places` dans CLAUDE.md"
    assert not [ligne for ligne in lignes if "jamais auto" in ligne]


# --- C4 : un périmètre à un seul lieu ne peut pas décider d'une fusion --------------


def test_un_scope_a_un_seul_lieu_n_execute_aucune_fusion(tmp_path, monkeypatch):
    """Un lieu isolé ne forme jamais de groupe d'homonymes : le périmètre `place:` ne
    peut structurellement rien conclure. L'arbre rendu ici contient pourtant les DEUX
    « Cerbois » — si la garde n'existait pas, la fusion irréversible partirait, et la
    commande annoncerait « écritures appliquées, aucun doublon détecté »."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS),
        tmp_path,
        scope="place:P0064",
        date="2026-07-21",
        dry_run=False,
    )
    assert vus == []
    assert resultat.scope_unitaire is True


def test_un_scope_a_un_seul_lieu_dit_pourquoi_rien_n_a_ete_ecrit(tmp_path, monkeypatch):
    """Sans explication, l'utilisateur croit à une absence de doublons — alors que la
    commande n'a tout simplement pas pu regarder."""
    _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="place:P0064", date="2026-07-21"
    )
    md = resultat.chemin.read_text(encoding="utf-8")
    assert "place:" in md
    assert "un seul lieu" in md
    assert "Fusions appliquées" not in md


def test_un_scope_all_n_est_pas_unitaire(tmp_path, monkeypatch):
    """La garde ne doit pas être trop large : `--scope all` fusionne comme avant."""
    vus = _stub_fusion(monkeypatch)
    resultat = run_places_detect(
        _arbre(DOUBLONS), tmp_path, scope="all", date="2026-07-21"
    )
    assert len(vus) == 1
    assert resultat.scope_unitaire is False
