"""Tests offline de `apply deaths` — création d'événements décès sourcés."""

import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew import deces_event, evenements
from genecrew.deces_event import (
    index_lieux,
    normaliser_lieu,
    render_deaths_report,
    resoudre_lieu,
    run_deces_event,
    trier_propositions,
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


def _places_client(places):
    def _h(request):
        if request.url.path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        return httpx.Response(404, json={})
    return _client(_h)


def test_normalisation_ignore_casse_accents_et_separateurs():
    assert normaliser_lieu("Saint-Palais") == normaliser_lieu("SAINT PALAIS")
    assert normaliser_lieu("Nohant-en-Goût") == normaliser_lieu("nohant en gout")


def test_index_rend_le_handle_d_un_lieu_unique():
    client = _places_client([
        {"handle": "P1", "name": {"value": "Bourges"}},
        {"handle": "P2", "name": {"value": "Vierzon"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "bourges") == "P1"


def test_lieu_absent_rend_none():
    client = _places_client([{"handle": "P1", "name": {"value": "Bourges"}}])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Saint-Palais") is None


def test_homonymes_rendent_none_plutot_qu_un_choix():
    """Deux lieux du même nom : rattacher au hasard poserait un décès dans la
    mauvaise commune sans que rien ne le signale."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index          # connu…
    assert resoudre_lieu(index, "Saint-Palais") is None   # …mais pas résolu


def test_lieu_sans_nom_est_ignore():
    client = _places_client([
        {"handle": "P1", "name": {}},
        {"handle": "P2", "name": {"value": "Bourges"}},
    ])
    index = index_lieux(client)
    assert resoudre_lieu(index, "Bourges") == "P2"


def test_normalisation_ignore_apostrophe_typographique():
    """« L'Isle-Adam » (apostrophe ASCII) et « L’Isle-Adam » (apostrophe
    typographique U+2019, usage courant en copier-coller) doivent produire la
    même clé — sinon la commune n'est jamais reconnue, sans que rien ne le
    signale."""
    assert normaliser_lieu("L'Isle-Adam") == normaliser_lieu("L’Isle-Adam")


def test_normalisation_deplie_la_ligature_oe():
    """« Vœuil-et-Giget » (commune de Charente) et « Voeuil-et-Giget »
    désignent la même commune ; NFD décompose les accents mais pas les
    ligatures, donc sans dépliage explicite les deux clés diffèrent."""
    assert normaliser_lieu("Vœuil-et-Giget") == normaliser_lieu("Voeuil-et-Giget")


def test_trois_homonymes_rendent_toujours_none():
    """Verrou de non-régression : au-delà de deux occurrences du même nom, la
    résolution doit rester None. Le code actuel teste la présence de la clé
    (pas sa valeur), donc il est déjà correct à trois — mais rien ne l'exerçait
    avant ce test ; une réécriture par compteur pourrait « ressusciter » un
    handle à la troisième occurrence sans que la CI ne le voie."""
    client = _places_client([
        {"handle": "P1", "name": {"value": "Saint-Palais"}},
        {"handle": "P2", "name": {"value": "Saint-Palais"}},
        {"handle": "P3", "name": {"value": "Saint-Palais"}},
    ])
    index = index_lieux(client)
    assert "saint palais" in index
    assert resoudre_lieu(index, "Saint-Palais") is None


def _prop(**kw):
    base = {
        "type": "date", "gramps_id": "I0174", "handle": "H174",
        "personne": "Alain Rolland", "cible": "décès de I0174 (absent de l'arbre)",
        "action": "Renseigner le décès : 2021-12-23 à Saint-Palais.",
        "preuve_url": "https://deces.matchid.io/id/X",
        "preuve_detail": "Fichier des décès INSEE : 2021-12-23 à Saint-Palais "
                         "(score 1.000).",
        "priorite": "moyenne", "confiance": 2,
        "date_iso": "2021-12-23", "lieu_nom": "Saint-Palais",
    }
    base.update(kw)
    from crewai_custom_tools.tools.genealogy.models.domain import PropositionAudit
    return PropositionAudit(**base)


def test_retient_une_proposition_date_confiance_2_datee():
    retenues, motifs = trier_propositions([_prop()])
    assert len(retenues) == 1
    assert motifs == {"hors_perimetre": 0, "sans_donnee": 0}


def test_ecarte_le_type_source():
    """`type: source` est le métier de `apply citations`, pas de `apply deaths`."""
    retenues, motifs = trier_propositions([_prop(type="source")])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_la_confiance_1():
    """Confiance 1 = date de naissance non concordante : homonyme possible."""
    retenues, motifs = trier_propositions([_prop(confiance=1)])
    assert retenues == []
    assert motifs["hors_perimetre"] == 1


def test_ecarte_un_yaml_sans_champs_structures():
    """Un lot produit avant les champs structurés ne doit pas se lire comme un lot vide."""
    retenues, motifs = trier_propositions([_prop(date_iso="", lieu_nom="")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1
    assert motifs["hors_perimetre"] == 0


def test_ecarte_une_date_incomplete():
    retenues, motifs = trier_propositions([_prop(date_iso="2021")])
    assert retenues == []
    assert motifs["sans_donnee"] == 1


def test_rapport_annonce_le_mode_effectif():
    md = render_deaths_report("2026-07-21", [], [], [], {"hors_perimetre": 0,
                              "sans_donnee": 0}, [], dry_run=True)
    assert "simulation" in md
    assert "écritures appliquées" not in md


def test_rapport_liste_les_evenements_crees():
    md = render_deaths_report(
        "2026-07-21",
        [("I0174", "Alain Rolland", "E9001", "Saint-Palais")],
        [], [], {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "I0174 Alain Rolland" in md
    assert "E9001" in md
    assert "Saint-Palais" in md
    assert "Décès créés : 1" in md


def test_rapport_distingue_les_deux_motifs_de_rejet():
    """Chaque libellé doit porter SON compte, pas celui de l'autre motif.

    Une simple présence indépendante des deux libellés et des deux nombres ne
    verrouille rien : intervertir les compteurs dans `render_deaths_report`
    laisserait ce test passer. On exige donc que le nombre attendu soit sur la
    MÊME ligne que son libellé.
    """
    md = render_deaths_report("2026-07-21", [], [], [],
                              {"hors_perimetre": 8, "sans_donnee": 3}, [], dry_run=False)
    lignes = md.splitlines()
    ligne_hors_perimetre = next(ligne for ligne in lignes if "Hors périmètre" in ligne)
    ligne_sans_donnee = next(ligne for ligne in lignes if "sans donnée machine" in ligne.lower())
    assert "8" in ligne_hors_perimetre
    assert "3" in ligne_sans_donnee


def test_rapport_signale_les_lieux_non_resolus():
    md = render_deaths_report("2026-07-21", [], [], [("I0186", "Nohant-en-Goût")],
                              {"hors_perimetre": 0, "sans_donnee": 0}, [], dry_run=False)
    assert "Lieux non résolus" in md
    assert "Nohant-en-Goût" in md


def test_rapport_porte_le_handle_de_l_orphelin():
    """Un événement non rattaché doit être retrouvable : son handle en clair."""
    md = render_deaths_report(
        "2026-07-21", [], [], [], {"hors_perimetre": 0, "sans_donnee": 0},
        [("I0174", "Death créé mais NON rattaché (orphelin EV_ORPH) : timeout")],
        dry_run=False)
    assert "EV_ORPH" in md


def _yaml_lot(tmp_path, props):
    p = tmp_path / "props.yaml"
    p.write_text(yaml.safe_dump({"propositions": props}, allow_unicode=True),
                 encoding="utf-8")
    return p


PROP_DATE = {
    "type": "date", "gramps_id": "I0174", "handle": "H174",
    "personne": "Alain Rolland", "cible": "décès de I0174 (absent de l'arbre)",
    "action": "Renseigner le décès : 2021-12-23 à Saint-Palais.",
    "preuve_url": "https://deces.matchid.io/id/X",
    "preuve_detail": "Fichier des décès INSEE : 2021-12-23 à Saint-Palais "
                     "(score 1.000).",
    "priorite": "moyenne", "confiance": 2,
    "date_iso": "2021-12-23", "lieu_nom": "Saint-Palais",
}

SANS_DECES = {"handle": "H174", "gramps_id": "I0174", "death_ref_index": -1,
              "event_ref_list": [{"ref": "EV_B"}]}
AVEC_DECES = {"handle": "H174", "gramps_id": "I0174", "death_ref_index": 1,
              "event_ref_list": [{"ref": "EV_B"}, {"ref": "EV_D"}]}
PLACES = [{"handle": "P1", "name": {"value": "Saint-Palais"}}]


def _arbre(person, places=PLACES):
    def _h(request):
        path = request.url.path
        if path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=places if page == 1 else [])
        if path == "/api/sources/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=[] if page > 1 else [])
        if path == "/api/tags/":
            return httpx.Response(200, json=[])
        if path.startswith("/api/people/"):
            return httpx.Response(200, json=person)
        return httpx.Response(200, json={})
    return _client(_h)


def _section(md: str, titre: str) -> str:
    """Contenu de la section `## titre` du rapport, jusqu'au titre suivant.

    Chercher un handle « quelque part dans le texte » ne verrouille rien : le
    tableau des décès créés le contient tout aussi bien que la liste des erreurs.
    Un rapport ne dit ce qu'il dit que par la section où il le dit.
    """
    lignes = md.splitlines()
    reste = lignes[lignes.index(f"## {titre}") + 1:]
    fin = next((i for i, ligne in enumerate(reste) if ligne.startswith("## ")),
               len(reste))
    return "\n".join(reste[:fin])


def _stub_ecritures(monkeypatch, *, evenement=None, echecs=None,
                    vrai_evenement=False):
    """Neutralise les outils d'écriture : on teste l'orchestration, pas l'API.

    `vus["appels"]` enregistre TOUT passage par un outil d'écriture, dans l'ordre
    et avec ses arguments. C'est ce qui permet d'exiger qu'une garde n'écrive
    RIEN — et pas seulement « pas d'événement » — et que la simulation demandée
    atteigne bien chaque appel. `echecs` fait refuser un outil nommé (`src`,
    `cit`, `note`, `tag`, `attach`) ; `vrai_evenement` laisse tourner la vraie
    brique partagée au lieu de la remplacer.
    """
    echecs = echecs or {}
    vus = {"evenement": None, "attach": None, "appels": []}

    def _fake_creer(person_handle, **kw):
        vus["evenement"] = {"person_handle": person_handle, **kw}
        vus["appels"].append(("evenement", kw))
        return evenement or {"posee": True, "event_handle": "EV_NEW",
                             "attache": True, "raison": "Death créé"}

    class _Ok:
        def __init__(self, key):
            self.key = key

        def _run(self, **kw):
            vus["appels"].append((self.key, kw))
            if self.key == "attach":
                vus["attach"] = kw
            if self.key in echecs:
                return json.dumps({"success": False, "error": echecs[self.key]})
            return json.dumps({"success": True, "data": {"handle": f"{self.key}1"}})

    if not vrai_evenement:
        monkeypatch.setattr(deces_event, "creer_evenement_source", _fake_creer)
    monkeypatch.setattr(deces_event, "GrampsEnsureSourceTool", lambda: _Ok("src"))
    monkeypatch.setattr(deces_event, "GrampsCreateCitationTool", lambda: _Ok("cit"))
    monkeypatch.setattr(deces_event, "GrampsCreateNoteTool", lambda: _Ok("note"))
    monkeypatch.setattr(deces_event, "GrampsEnsureTagTool", lambda: _Ok("tag"))
    monkeypatch.setattr(deces_event, "GrampsAttachTool", lambda: _Ok("attach"))
    return vus


def test_cree_le_deces_absent(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    assert vus["evenement"]["event_type"] == "Death"
    assert vus["evenement"]["dateval"] == [23, 12, 2021]
    assert vus["evenement"]["place_handle"] == "P1"


def test_refuse_une_personne_deja_decedee(tmp_path, monkeypatch):
    """L'outil protège le pointeur death_ref_index, pas la liste : sans cette garde
    on créerait un SECOND événement décès, invisible mais bien présent.

    La garde doit précéder TOUTE écriture, pas seulement celle de l'événement :
    la déplacer après la source et la citation laisserait ces deux objets dans
    l'arbre pour une personne déjà décédée. On exige donc qu'aucun outil
    d'écriture n'ait été appelé, et pas seulement que l'événement soit absent.
    """
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(AVEC_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 0" in md
    assert "Refusés (décès déjà présent dans l'arbre) : 1" in md
    assert vus["appels"] == []


def test_lieu_inconnu_donne_un_evenement_sans_lieu(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES, places=[]),
                             _yaml_lot(tmp_path, [PROP_DATE]), tmp_path,
                             date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    assert vus["evenement"]["place_handle"] is None
    assert "Lieux non résolus" in md
    assert "Saint-Palais" in md


def test_orphelin_rapporte_avec_son_handle(tmp_path, monkeypatch):
    """Un orphelin va en ERREUR, jamais dans les créés : l'arbre ne le montre pas.

    Le handle doit être dans la section des erreurs — le tableau des créés le
    porterait aussi bien — ET le compteur de créations rester à zéro, sans quoi
    basculer l'orphelin du côté des succès annoncerait « Décès créés : 1 /
    Erreurs : 0 » pour un décès que personne ne verra dans l'arbre.
    """
    _stub_ecritures(monkeypatch, evenement={
        "posee": True, "event_handle": "EV_ORPH", "attache": False,
        "raison": "Death créé mais NON rattaché (orphelin EV_ORPH) : timeout"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "EV_ORPH" in _section(md, "Erreurs")
    assert "Décès créés : 0" in md
    assert "Erreurs : 1" in md


def test_note_et_tag_poses_sur_la_personne(tmp_path, monkeypatch):
    vus = _stub_ecritures(monkeypatch)
    run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]), tmp_path,
                    date="2026-07-21")
    assert vus["attach"]["handle"] == "H174"
    assert vus["attach"]["note_handle"] == "note1"
    assert vus["attach"]["tag_handle"] == "tag1"


def test_dry_run_effectif_annonce_la_simulation(tmp_path, monkeypatch):
    """Annoncer la simulation ne suffit pas : elle doit atteindre CHAQUE outil.

    Remplacer les propagations de `dry_run` par `False` ferait partir les
    écritures pour de vrai pendant que le rapport annonce une simulation — le
    pire des deux mondes. On exige donc que tout appel enregistré l'ait reçue, et
    qu'il y ait bien eu des appels (sans quoi l'assertion serait vide de sens).
    """
    vus = _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21", dry_run=True)
    assert "simulation" in chemin.read_text(encoding="utf-8")
    assert vus["appels"], "aucun outil appelé : le verrou ne vérifierait rien"
    for nom, kw in vus["appels"]:
        assert kw.get("dry_run") is True, f"{nom} n'a pas reçu la simulation"


class _OutilEvenementSimule:
    """Réplique la charge que `GrampsCreateEventTool` rend réellement en dry-run."""

    def _run(self, **kw):
        return json.dumps({"success": True, "data": {
            "handle": "DRYRUN:event", "dry_run": True,
            "created": False, "attached": False}})


def test_simulation_ne_rapporte_pas_un_orphelin(tmp_path, monkeypatch):
    """Bout en bout : une simulation doit donner un aperçu exploitable.

    L'outil rend `attached: False` en dry-run sans avoir rien écrit ; lu comme un
    orphelin, il produisait « Décès créés : 0 / Erreurs : 1 » et un message
    alarmant sur un « orphelin DRYRUN:event » qui n'existe pas — sur l'aperçu même
    dont dépend l'autorisation d'écrire. Le classement en orphelin coupait de plus
    la suite, si bien que le chemin note/tag n'était jamais simulé. Seul l'outil
    Gramps est neutralisé ici : la vraie brique partagée tourne.
    """
    vus = _stub_ecritures(monkeypatch, vrai_evenement=True)
    monkeypatch.setattr(evenements, "GrampsCreateEventTool", _OutilEvenementSimule)
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21", dry_run=True)
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    assert "Erreurs : 0" in md
    assert "orphelin" not in md
    assert vus["attach"] is not None, "le chemin note/tag n'a pas été simulé"


def test_registre_inconnu_n_avorte_pas_le_lot(tmp_path, monkeypatch):
    """Un registre non reconnu fait lever `source_title_for` EN PLEINE BOUCLE.

    Laisser l'exception remonter interrompait le lot après la création — déjà
    irréversible — des propositions précédentes, et n'écrivait aucun rapport : une
    donnée cœur modifiée sans la moindre trace. C'est une erreur DE CETTE
    proposition.
    """
    _stub_ecritures(monkeypatch)
    inconnu = {**PROP_DATE, "gramps_id": "I0999",
               "preuve_detail": "Registre d'un fonds jamais routé."}
    chemin = run_deces_event(_arbre(SANS_DECES),
                             _yaml_lot(tmp_path, [PROP_DATE, inconnu]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md           # la première a bien été faite…
    erreurs = _section(md, "Erreurs")
    assert "I0999" in erreurs                # …et la seconde est rapportée
    assert "registre non reconnu" in erreurs.lower()


def test_source_refusee_n_avorte_pas_le_lot(tmp_path, monkeypatch):
    """Même exigence pour l'échec de création de source (`RuntimeError`)."""
    _stub_ecritures(monkeypatch, echecs={"src": "503 Service Unavailable"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 0" in md
    assert "503 Service Unavailable" in _section(md, "Erreurs")


DECES_NUL = {"handle": "H174", "gramps_id": "I0174", "death_ref_index": None,
             "event_ref_list": [{"ref": "EV_B"}]}


def test_pointeur_de_deces_nul_vaut_pas_de_deces(tmp_path, monkeypatch):
    """Le schéma Gramps type `death_ref_index` `int | None`.

    Comparer `None` à un entier levait un `TypeError` qui avortait le lot entier
    sans écrire de rapport, là où un pointeur nul dit simplement « pas de décès ».
    """
    _stub_ecritures(monkeypatch)
    chemin = run_deces_event(_arbre(DECES_NUL), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    assert "Décès créés : 1" in chemin.read_text(encoding="utf-8")


def test_panne_de_lecture_n_est_pas_une_personne_introuvable(tmp_path, monkeypatch):
    """Un 503 rapporté « personne introuvable » dit au relecteur « ce lot est
    périmé, abandonne » là où il faut lire « réessaie » — et un décès parfaitement
    créable est abandonné en silence. Le message doit porter la cause réelle."""
    _stub_ecritures(monkeypatch)

    def _h(request):
        if request.url.path == "/api/places/":
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=PLACES if page == 1 else [])
        if request.url.path.startswith("/api/people/"):
            return httpx.Response(503, json={})
        return httpx.Response(200, json={})

    chemin = run_deces_event(_client(_h), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    erreurs = _section(chemin.read_text(encoding="utf-8"), "Erreurs")
    assert "503" in erreurs
    assert "introuvable" not in erreurs.lower()


def test_lieu_non_resolu_taise_si_l_evenement_echoue(tmp_path, monkeypatch):
    """« Décès créés : 0 » sous une section « Événement créé sans lieu » est un
    rapport qui se contredit : la commune ne se signale que si l'événement est
    effectivement créé ET rattaché."""
    _stub_ecritures(monkeypatch, evenement={
        "posee": False, "event_handle": None, "attache": False,
        "raison": "création Death refusée : 500"})
    chemin = run_deces_event(_arbre(SANS_DECES, places=[]),
                             _yaml_lot(tmp_path, [PROP_DATE]), tmp_path,
                             date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 0" in md
    assert "Lieux non résolus" not in md


def test_note_refusee_compte_le_deces_cree_et_l_erreur(tmp_path, monkeypatch):
    """Contrairement à l'orphelin, le décès EST créé et rattaché : il compte comme
    créé. L'annotation manquante se rapporte à part, en nommant le handle de
    l'événement — la seule prise pour l'annoter à la main ensuite."""
    _stub_ecritures(monkeypatch, echecs={"note": "note refusée : 500"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    erreurs = _section(md, "Erreurs")
    assert "EV_NEW" in erreurs
    assert "note refusée : 500" in erreurs


def test_tag_refuse_compte_le_deces_cree_et_l_erreur(tmp_path, monkeypatch):
    """Même verrou que la note : le tag échoue seul, le décès reste acquis."""
    _stub_ecritures(monkeypatch, echecs={"tag": "tag refusé : 500"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    erreurs = _section(md, "Erreurs")
    assert "EV_NEW" in erreurs
    assert "tag refusé : 500" in erreurs


def test_rattachement_d_annotation_refuse_compte_le_deces_cree_et_l_erreur(
        tmp_path, monkeypatch):
    """Note et tag créés, mais leur pose sur la personne échoue : troisième chemin,
    même règle — décès créé, annotation rapportée avec le handle."""
    _stub_ecritures(monkeypatch, echecs={"attach": "409 conflit"})
    chemin = run_deces_event(_arbre(SANS_DECES), _yaml_lot(tmp_path, [PROP_DATE]),
                             tmp_path, date="2026-07-21")
    md = chemin.read_text(encoding="utf-8")
    assert "Décès créés : 1" in md
    erreurs = _section(md, "Erreurs")
    assert "EV_NEW" in erreurs
    assert "409 conflit" in erreurs
