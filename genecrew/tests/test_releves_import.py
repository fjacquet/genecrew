"""Tests hors-ligne de l'import de relevés (LLM stubbé, Gramps via MockTransport)."""

import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachCitationTool,
    GrampsAttachTool,
    GrampsCreateCitationTool,
    GrampsCreateNoteTool,
    GrampsEnsureSourceTool,
    GrampsEnsureTagTool,
)

from genecrew.deces_apply import source_title_for
from genecrew.releves import Appariement
from genecrew.releves_import import (
    TAG_RELEVE,
    _parents_par_handle,
    code_fonds,
    corps_note_releve,
    deja_importe,
    ecrire_citation,
    format_import_releve,
    handle_evenement,
    marqueur_releve,
    parse_releve,
    run_import_releve,
)

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)
    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))

COLLAGE_ROSE = """Rose JACQUET
Le 10 décembre 1894
Saint-Martin-D'auxigny
(location_on Saint-Martin-D'auxigny, Cher )
Détails
Rose JACQUET
Naissance
Vers 1821
Âge : 73
Parents
Pierre JACQUET
Décès
Avant 1894
Marie Anne VILLEPELLET
Décès
Avant 1894
Référence n° 106710046161418286
Source du relevé : Cercle Généalogique du Haut-Berry
"""

_JSON_ATTENDU = {
    "fonds": "Cercle Généalogique du Haut-Berry",
    "reference": "106710046161418286",
    "sujet_nom": "JACQUET", "sujet_prenom": "Rose",
    "evenement_type": "Death", "evenement_date": "1894-12-10",
    "evenement_lieu": "Saint-Martin-d'Auxigny", "naissance_estimee": 1821,
    "personnes_liees": [{"nom": "Pierre JACQUET", "role": "père", "detail": ""},
                        {"nom": "Marie Anne VILLEPELLET", "role": "mère", "detail": ""}],
}


class _LLMStub:
    def __init__(self, reponse):
        self.reponse = reponse
        self.prompts = []

    def call(self, prompt):
        self.prompts.append(prompt)
        return self.reponse


def test_parse_produit_un_releve_indexe():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert r.reference == "106710046161418286"
    assert r.evenement_date == "1894-12-10"
    assert [p.role for p in r.personnes_liees] == ["père", "mère"]


def test_texte_brut_est_conserve_integralement():
    """Quoi qu'il arrive à l'interprétation, la source reste lisible dans l'arbre."""
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    assert r.texte_brut == COLLAGE_ROSE


def test_le_llm_ne_choisit_pas_le_texte_brut():
    """Même si le LLM en renvoie un, c'est le collage réel qui fait foi."""
    menteur = dict(_JSON_ATTENDU, texte_brut="inventé")
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(menteur)))
    assert r.texte_brut == COLLAGE_ROSE


def test_json_entoure_de_texte_est_extrait():
    bavard = "Voici le JSON :\n```json\n" + json.dumps(_JSON_ATTENDU) + "\n```\n"
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(bavard))
    assert r.reference == "106710046161418286"


def test_reponse_illisible_leve_clairement():
    with pytest.raises(ValueError, match="JSON"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub("je ne sais pas"))


def test_reference_vide_leve_une_erreur_explicite():
    """Une référence vide dégraderait la clé d'idempotence en constante — voir
    la docstring de parse_releve : refuser bruyamment plutôt que sauter en silence."""
    donnees = dict(_JSON_ATTENDU, reference="")
    with pytest.raises(ValueError, match="(?i)référence"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(donnees)))


def test_fonds_vide_leve_une_erreur_explicite():
    donnees = dict(_JSON_ATTENDU, fonds="")
    with pytest.raises(ValueError, match="(?i)fonds"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(donnees)))


def test_reference_uniquement_blancs_leve_une_erreur():
    """Un strip() est nécessaire : une garde naïve sur `== ""` raterait ce cas."""
    donnees = dict(_JSON_ATTENDU, reference="   ")
    with pytest.raises(ValueError, match="(?i)référence"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(donnees)))


def test_fonds_uniquement_blancs_leve_une_erreur():
    donnees = dict(_JSON_ATTENDU, fonds="\t \n")
    with pytest.raises(ValueError, match="(?i)fonds"):
        parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(donnees)))


def test_json_syntaxiquement_casse_leve_une_erreur_exploitable():
    """Le try/except JSONDecodeError doit être exercé : accolades trouvées,
    mais contenu non parsable (clé non quotée). La cause d'origine doit rester
    accessible pour un humain qui débogue un flux payant et non déterministe."""
    casse = "Voici : {fonds:}"
    with pytest.raises(ValueError, match="(?i)JSON invalide") as exc_info:
        parse_releve(COLLAGE_ROSE, llm=_LLMStub(casse))
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_code_fonds_est_stable_et_sobre():
    assert code_fonds("Cercle Généalogique du Haut-Berry") == "cercle-genealogique-du-haut-berry"


def test_code_fonds_tiret_et_espace_sont_equivalents():
    """Verrouille la décision : `fonds` est extrait par un LLM depuis du texte
    libre, sa ponctuation varie d'un appel à l'autre pour la MÊME association.
    Les distinguer réimporterait le même relevé en double — voir la docstring
    de code_fonds. Ce test doit continuer à passer même si un futur relecteur
    reproduit le raisonnement inverse."""
    assert (code_fonds("Cercle Généalogique du Haut-Berry")
            == code_fonds("Cercle Généalogique du Haut Berry"))


def test_code_fonds_supprime_la_ponctuation_parasite():
    """Un point ou une apostrophe surnuméraire ne doit pas distinguer deux
    graphies du même fonds — ce n'est pas une information de séparation."""
    assert code_fonds("C.G.H.B.") == code_fonds("CGHB")


def test_code_fonds_distingue_des_fonds_reellement_differents():
    """Garde contre une normalisation devenue trop agressive : deux fonds
    dont les mots diffèrent doivent rester distincts."""
    assert (code_fonds("Cercle Généalogique du Haut-Berry")
            != code_fonds("Cercle Généalogique du Berry"))


def test_code_fonds_retire_les_caracteres_qui_casseraient_le_marqueur():
    """':' et ']' structurent [genecrew:releve:<code_fonds>:<reference>] —
    s'ils survivaient dans code_fonds, un nom de fonds qui en contient
    casserait le marqueur d'idempotence."""
    code = code_fonds("Cercle [Test]: Berry")
    assert ":" not in code
    assert "]" not in code
    m = marqueur_releve("Cercle [Test]: Berry", "106710046161418286")
    assert m == f"[genecrew:releve:{code}:106710046161418286]"


def test_marqueur_porte_l_identite_jamais_la_date():
    m = marqueur_releve("Cercle Généalogique du Haut-Berry", "106710046161418286")
    assert m == "[genecrew:releve:cercle-genealogique-du-haut-berry:106710046161418286]"
    assert "2026" not in m


def test_deja_importe_detecte_le_marqueur_pose():
    m = marqueur_releve("CGHB", "106710046161418286")
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": [
            {"text": {"string": m + "\nRelevé — CGHB"}}]}}])
    assert deja_importe(_client(h), "I0001", m) is True


def test_deja_importe_faux_sur_une_autre_reference():
    autre = marqueur_releve("CGHB", "999")
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": [
            {"text": {"string": autre}}]}}])
    m = marqueur_releve("CGHB", "106710046161418286")
    assert deja_importe(_client(h), "I0001", m) is False


def test_deja_importe_faux_sans_note():
    def h(request):
        return httpx.Response(200, json=[{"extended": {"notes": []}}])
    assert deja_importe(_client(h), "I0001", marqueur_releve("CGHB", "1")) is False


def test_source_title_route_un_releve_de_cercle():
    titre, auteur = source_title_for("Relevé — Cercle Généalogique du Haut-Berry")
    assert titre == "Cercle Généalogique du Haut-Berry — relevés"
    assert auteur == "Cercle Généalogique du Haut-Berry"


@pytest.mark.parametrize("detail", ["Relevé — ", "Relevé —    "])
def test_source_title_leve_sur_un_releve_sans_cercle(detail):
    """Régression : `(.+?)` paresseux + `\\s*` gourmand capturaient UN espace au
    lieu d'échouer, rendant ("  — relevés", "") — un auteur VIDE écrit sans erreur."""
    with pytest.raises(ValueError, match="(?i)cercle"):
        source_title_for(detail)


def test_source_title_leve_toujours_sur_un_registre_inconnu():
    """Pas de repli silencieux sur l'INSEE : ce serait une fausse attribution."""
    with pytest.raises(ValueError):
        source_title_for("provenance mystérieuse")


def test_note_recopie_le_texte_brut():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net", gramps_id="I1",
                                             facteurs=["date complète", "lieu"],
                                             poids=8))
    assert COLLAGE_ROSE.strip() in corps


def test_note_porte_le_marqueur_en_tete_et_les_facteurs():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net", facteurs=["date complète"],
                                             poids=5))
    assert corps.startswith("[genecrew:releve:")
    assert "date complète" in corps


def test_note_dit_que_le_releve_est_une_source_derivee():
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    corps = corps_note_releve(r, Appariement(verdict="net"))
    assert "dérivée" in corps and "acte" in corps


# --- orchestration : collecte, appariement, écriture ---------------------------
#
# Les fixtures ci-dessous sont la forme JSON BRUTE que `person_from_json` sait
# lire (patronyme dans `primary_name.surname_list`, événements dans
# `extended.events` indexés par `birth_ref_index`/`death_ref_index`, lieux dans
# `profile`). Une fixture inventée rendrait toute la suite verte sur un moteur
# d'appariement inopérant : c'est la forme réelle qu'on recopie, pas une forme
# plausible.

def _personne(gramps_id, handle, *, prenom="Rose", nom="JACQUET",
              familles_parentales=()):
    return {
        "gramps_id": gramps_id, "handle": handle, "gender": 0,
        "primary_name": {"first_name": prenom,
                         "surname_list": [{"surname": nom}]},
        "birth_ref_index": 0, "death_ref_index": 1,
        "parent_family_list": list(familles_parentales),
        "extended": {"events": [
            {"type": "Birth", "date": {"dateval": [0, 0, 1821, False], "year": 1821,
                                       "sortval": 664000, "modifier": 3, "quality": 0}},
            {"type": "Death", "date": {"dateval": [10, 12, 1894, False], "year": 1894,
                                       "sortval": 692000, "modifier": 0, "quality": 0}},
        ]},
        "profile": {"death": {"place_name": "Saint-Martin-d'Auxigny"}},
    }


_ROSE_ARBRE = _personne("I0001", "h1")


def _handler_arbre(people_json, familles=None, notes=()):
    """Répond aux appels Gramps : /people/ paginé, /people/?gramps_id=, /families/<h>.

    La page 2 rend une liste vide : `iter_people_batches` pagine jusqu'à
    l'épuisement, et un mock qui renverrait toujours la même page boucle sans fin.
    """
    familles = familles or {}

    def h(request):
        chemin = request.url.path
        if chemin == "/api/people/":
            if "gramps_id" in request.url.params:
                # Lecture d'idempotence (`deja_importe`), pas la pagination.
                return httpx.Response(200, json=[{"extended": {"notes": list(notes)}}])
            if request.url.params.get("page", "1") != "1":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=list(people_json))
        if chemin.startswith("/api/families/"):
            return httpx.Response(200, json=familles[chemin.rsplit("/", 1)[-1]])
        return httpx.Response(200, json=[])

    return h


def _arbre(*people_json, familles=None, notes=()):
    return _client(_handler_arbre(people_json, familles, notes))


def _llm():
    return _LLMStub(json.dumps(_JSON_ATTENDU))


def test_simulation_par_defaut_n_ecrit_rien(monkeypatch):
    """GENECREW_DRY_RUN absent = on SIMULE : le verdict se lit, rien ne s'écrit."""
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    out = run_import_releve(_arbre(_ROSE_ARBRE), COLLAGE_ROSE, llm=_llm())
    assert out["dry_run"] is True
    assert out["ecrit"] is False
    assert out["raison"] == "simulation"
    assert out["appariement"].verdict == "net"
    assert out["releve"].reference == "106710046161418286"


def test_gris_n_ecrit_pas_meme_hors_simulation(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    jumeau = _personne("I0002", "h2")
    out = run_import_releve(_arbre(_ROSE_ARBRE, jumeau), COLLAGE_ROSE, llm=_llm())
    assert out["appariement"].verdict == "gris"
    assert out["ecrit"] is False
    assert out["raison"] == "gris — relecture requise"


def test_aucun_candidat_n_ecrit_pas(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    etranger = _personne("I0009", "h9", prenom="Jean", nom="DURAND")
    out = run_import_releve(_arbre(etranger), COLLAGE_ROSE, llm=_llm())
    assert out["appariement"].verdict == "aucun"
    assert out["ecrit"] is False
    assert "aucun candidat" in out["raison"]


def test_deuxieme_passage_n_ecrit_rien(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    m = marqueur_releve("Cercle Généalogique du Haut-Berry", "106710046161418286")
    out = run_import_releve(
        _arbre(_ROSE_ARBRE, notes=[{"text": {"string": m}}]), COLLAGE_ROSE, llm=_llm())
    assert out["ecrit"] is False
    assert out["raison"] == "déjà importée"


def test_pagination_reelle_collecte_les_pages_suivantes(monkeypatch):
    """`iter_people_batches` doit vraiment paginer : Rose est SEULE en page 2.

    Une implémentation qui ne lirait que la première page ne la verrait pas et
    conclurait « aucun candidat ».
    """
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)

    def h(request):
        if request.url.path == "/api/people/":
            if "gramps_id" in request.url.params:
                return httpx.Response(200, json=[{"extended": {"notes": []}}])
            page = request.url.params.get("page", "1")
            if page == "1":
                return httpx.Response(200, json=[_personne("I0009", "h9",
                                                           prenom="Jean", nom="DURAND")])
            if page == "2":
                return httpx.Response(200, json=[_ROSE_ARBRE])
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    out = run_import_releve(_client(h), COLLAGE_ROSE, llm=_llm())
    assert out["appariement"].verdict == "net"
    assert out["appariement"].gramps_id == "I0001"


# --- le type d'événement non géré -------------------------------------------

_FAMILLE_ROSE = {"gramps_id": "F0001", "handle": "f1",
                 "father_handle": "hp", "mother_handle": "hm",
                 "child_ref_list": [{"ref": "h1"}], "extended": {"events": []}}

_JSON_MARIAGE = dict(_JSON_ATTENDU, evenement_type="Marriage")


def _arbre_avec_parents(*, notes=()):
    rose = _personne("I0001", "h1", familles_parentales=["f1"])
    pere = _personne("I0002", "hp", prenom="Pierre", nom="JACQUET")
    mere = _personne("I0003", "hm", prenom="Marie Anne", nom="VILLEPELLET")
    return _arbre(rose, pere, mere, familles={"f1": _FAMILLE_ROSE}, notes=notes)


def test_parents_par_handle_passe_par_la_famille():
    """C'est la FAMILLE qui porte father_handle/mother_handle, pas la personne."""
    from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher

    client = _arbre_avec_parents()
    fetcher = FactsFetcher(client)
    people = fetcher.list_people_facts(1, 200)
    index = _parents_par_handle(fetcher, people)
    assert sorted(index["h1"]) == ["Marie Anne VILLEPELLET", "Pierre JACQUET"]
    assert index["hp"] == []


def _sans_deces_correlant(gramps_id, handle, *, prenom, nom, familles_parentales=()):
    """`_personne`, dont le décès ne concorde avec AUCUN relevé.

    Par défaut `_personne` donne à quiconque la MÊME date et le MÊME lieu de
    décès que `COLLAGE_ROSE` (10/12/1894, Saint-Martin-d'Auxigny) — pratique
    pour les tests qui veulent que ça concorde, piégeux pour ceux qui ne le
    veulent PAS. Sans cette variante, Rose toucherait elle-même « date
    complète » et « lieu » (8 points à eux seuls), et un père homonyme
    s'auto-qualifierait comme second candidat, avant même de parler de parents.

    `modifier=3` (« vers ») vide `_date_iso` : le facteur « date complète » ne
    se déclenche jamais, et — faute de date comparée — aucune divergence (veto)
    n'est produite non plus. Même logique pour le lieu, VIDÉ plutôt que changé :
    une valeur seulement différente déclencherait un veto au lieu de rien.
    """
    p = _personne(gramps_id, handle, prenom=prenom, nom=nom,
                 familles_parentales=familles_parentales)
    p["extended"]["events"][1]["date"]["modifier"] = 3
    p["profile"]["death"]["place_name"] = ""
    return p


def test_index_des_parents_borne_aux_candidats(monkeypatch):
    """L'index parental ne se construit QUE pour les candidats du blocage —
    mais la résolution handle → nom des parents, elle, doit couvrir l'arbre
    ENTIER : c'est ce que ce test vérifie, pas seulement le nombre de requêtes.

    `apparier` ne consulte l'index que pour les personnes retenues par
    `candidats_blocage` ; l'indexer sur l'arbre entier faisait ~1 requête
    `/families/` par famille parentale de l'arbre (~1 000 sur 2 100 personnes)
    pour n'en servir qu'une poignée. Au-delà du coût, la stack Gramps Web a un
    limiteur de débit : `get_family_facts` n'avale que les 404, un 429
    avorterait l'import.

    Rose a ses DEUX parents dans la fixture : un père Pierre JACQUET (même
    patronyme, donc CANDIDAT au blocage) et une mère Marie Anne VILLEPELLET
    (patronyme différent, donc HORS blocage) — le cas réaliste, une mère
    portant souvent un patronyme différent de son enfant. C'est précisément ce
    parent hors blocage que ce test surveille : si la résolution de son NOM se
    limitait aux candidats — comme la construction de l'index elle-même s'y
    limite légitimement —, son nom disparaîtrait de l'index, « deux parents
    nommés » (8 points, `SEUIL_NET` à lui seul) tomberait à « parent nommé »
    (5), et Rose basculerait silencieusement de `net` à `gris` : une
    correspondance perdue sans qu'aucune assertion ne le remarque.

    Les autres facteurs de Rose sont neutralisés (`_sans_deces_correlant`) pour
    que son `net` ne puisse venir QUE du facteur parental : sans lui elle ne
    totalise que prénom (1) + année approximative (1) = 2, bien en-deçà de
    `SEUIL_NET` (8) ; avec « deux parents nommés », 2 + 8 = 10.

    La propriété de comptage reste vérifiée : un seul JACQUET porteur d'une
    famille parentale (Rose — son père homonyme n'en a pas) contre cinq DURAND
    ayant chacun la leur : un seul GET `/families/` doit partir. Une
    implémentation qui réindexerait tout l'arbre en ferait six.
    """
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    familles_vues: list[str] = []

    rose = _sans_deces_correlant("I0001", "h1", prenom="Rose", nom="JACQUET",
                                 familles_parentales=["f1"])
    pere = _sans_deces_correlant("I0002", "hp", prenom="Pierre", nom="JACQUET")
    mere = _personne("I0003", "hm", prenom="Marie Anne", nom="VILLEPELLET")
    etrangers = [_personne(f"I01{i}", f"hd{i}", prenom="Jean", nom="DURAND",
                           familles_parentales=[f"f1{i}"]) for i in range(5)]
    familles = {"f1": _FAMILLE_ROSE}
    for i in range(5):
        familles[f"f1{i}"] = {"gramps_id": f"F01{i}", "handle": f"f1{i}",
                              "father_handle": "", "mother_handle": "",
                              "child_ref_list": [], "extended": {"events": []}}

    base = _handler_arbre([rose, pere, mere, *etrangers], familles)

    def h(request):
        if request.url.path.startswith("/api/families/"):
            familles_vues.append(request.url.path.rsplit("/", 1)[-1])
        return base(request)

    out = run_import_releve(_client(h), COLLAGE_ROSE, llm=_llm())
    assert familles_vues == ["f1"]
    assert out["appariement"].verdict == "net"
    assert out["appariement"].gramps_id == "I0001"
    # Le facteur parental doit être RÉELLEMENT présent — pas seulement le
    # verdict `net` atteint par un autre chemin — puisque c'est lui que ce
    # test protège : voir `_sans_deces_correlant` pour ce qui a été neutralisé
    # afin que ce soit garanti.
    assert "deux parents nommés" in out["appariement"].facteurs
    assert out["appariement"].poids == 10


def test_type_evenement_non_gere_refuse_d_ecrire(monkeypatch):
    """Un relevé de MARIAGE peut atteindre `net` par le seul facteur « deux
    parents nommés » (8 = SEUIL_NET), alors que le moteur n'a comparé AUCUN
    événement : `_evenement_compare` ne connaît que Death et Birth. Écrire là
    poserait une note sur un type que la chaîne ne sait pas traiter.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    out = run_import_releve(_arbre_avec_parents(), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_MARIAGE)))
    assert out["appariement"].verdict == "net"       # le piège est bien armé
    assert out["ecrit"] is False
    assert "Marriage" in out["raison"]


# --- l'écriture, quand tout concorde ----------------------------------------

def test_net_hors_simulation_pose_note_et_tag(monkeypatch, mocker):
    """Le chemin nominal complet : note créée, tag garanti, les deux AJOUTÉS,
    PUIS la citation posée sur le décès existant.

    La personne du mock porte DÉJÀ une note et un tag. C'est l'essentiel du
    test : l'append-only est un invariant structurel du projet — on annote, on
    n'écrase jamais ce qu'une personne porte déjà. Sur une personne vierge, un
    code qui remplacerait les listes par `[nouveau]` rendrait exactement le même
    PUT qu'un code qui ajoute : le test ne prouverait rien. Ici, l'assertion
    exige l'ANCIEN en premier et le neuf ajouté derrière.

    Le décès de Rose EXISTE dans l'arbre (handle `ev1`), donc la citation se
    pose : `raison == "importée"`. Le mock ne sert QUE l'endpoint PLURIEL
    `/api/events/ev1` — un `object_type="event"` singulier tomberait ici en 404,
    ce qui verrouille la forme réelle de la route contre une régression.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    vu = {"notes": [], "tags": [], "put": [], "citations": [], "event_put": []}

    def h(request):
        chemin = request.url.path
        if request.method == "POST" and chemin == "/api/notes/":
            vu["notes"].append(json.loads(request.content))
            return httpx.Response(201, json=[{"new": {"handle": "n1"}}])
        if request.method == "POST" and chemin == "/api/tags/":
            vu["tags"].append(json.loads(request.content))
            return httpx.Response(201, json=[{"new": {"handle": "t1"}}])
        if request.method == "PUT" and chemin == "/api/people/h1":
            vu["put"].append(json.loads(request.content))
            return httpx.Response(200, json={})
        if chemin == "/api/tags/":
            return httpx.Response(200, json=[])
        # --- la citation : source garantie, citation créée, rattachée à ev1 ---
        if (chemin == "/api/people/" and "gramps_id" in request.url.params
                and request.url.params.get("extend") == "event_ref_list"):
            return httpx.Response(200, json=[{
                "gramps_id": "I0001", "handle": "h1",
                "extended": {"events": [{"handle": "ev1", "type": "Death"}]}}])
        if request.method == "GET" and chemin == "/api/sources/":
            return httpx.Response(200, json=[])
        if request.method == "POST" and chemin == "/api/sources/":
            return httpx.Response(201, json=[{"handle": "s1"}])
        if request.method == "POST" and chemin == "/api/citations/":
            vu["citations"].append(json.loads(request.content))
            return httpx.Response(201, json=[{"handle": "c1"}])
        if request.method == "GET" and chemin == "/api/events/ev1":
            return httpx.Response(200, json={"_class": "Event", "handle": "ev1",
                                             "citation_list": []})
        if request.method == "PUT" and chemin == "/api/events/ev1":
            vu["event_put"].append(json.loads(request.content))
            return httpx.Response(200, json={})
        if chemin == "/api/people/h1":
            # Personne NON vierge : une note et un tag préexistants, que
            # l'écriture doit conserver.
            return httpx.Response(200, json={"gramps_id": "I0001", "handle": "h1",
                                             "note_list": ["n0"], "tag_list": ["t0"]})
        return _handler_arbre([_ROSE_ARBRE])(request)

    client = _client(h)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client)

    out = run_import_releve(client, COLLAGE_ROSE, llm=_llm())
    assert out["dry_run"] is False
    assert out["ecrit"] is True
    assert out["raison"] == "importée"
    assert COLLAGE_ROSE.strip() in vu["notes"][0]["text"]["string"]
    assert vu["notes"][0]["text"]["string"].startswith("[genecrew:releve:")
    assert vu["tags"][0]["name"] == TAG_RELEVE
    # L'ancien EN PREMIER, le neuf ajouté : un remplacement rendrait ["n1"].
    assert vu["put"][0]["note_list"] == ["n0", "n1"]
    assert vu["put"][0]["tag_list"] == ["t0", "t1"]
    # La citation : posée, confiance Normal (2), rattachée à l'événement plural.
    assert out["citation"]["posee"] is True
    assert vu["citations"][0]["confidence"] == 2
    assert vu["event_put"][0]["citation_list"] == ["c1"]


@pytest.mark.parametrize("casse", ["tags", "attache"])
def test_echec_apres_la_note_signale_l_orpheline(monkeypatch, mocker, casse):
    """Les trois écritures ne sont PAS atomiques : la note reste, il faut le dire.

    Si le tag ou le rattachement échoue après la création de la note, celle-ci
    subsiste dans l'arbre sans être rattachée à personne. `deja_importe` lit les
    notes DE LA PERSONNE : le marqueur n'y est pas, donc le réimport est autorisé
    — c'est le bon sens de l'échec — mais une DEUXIÈME orpheline s'ajouterait
    sans que rien ne le signale. La raison rendue doit donc nommer l'orpheline et
    son handle, pour qu'un humain puisse la retrouver et la supprimer.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")

    def h(request):
        chemin = request.url.path
        if request.method == "POST" and chemin == "/api/notes/":
            return httpx.Response(201, json=[{"new": {"handle": "n1"}}])
        if request.method == "POST" and chemin == "/api/tags/":
            if casse == "tags":
                return httpx.Response(500, json={"error": "boum"})
            return httpx.Response(201, json=[{"new": {"handle": "t1"}}])
        if request.method == "PUT" and chemin == "/api/people/h1":
            return httpx.Response(500, json={"error": "boum"})
        if chemin == "/api/tags/":
            return httpx.Response(200, json=[])
        if chemin == "/api/people/h1":
            return httpx.Response(200, json={"gramps_id": "I0001", "handle": "h1"})
        return _handler_arbre([_ROSE_ARBRE])(request)

    client = _client(h)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client)

    out = run_import_releve(client, COLLAGE_ROSE, llm=_llm())
    assert out["ecrit"] is False
    assert "orpheline" in out["raison"]
    assert "n1" in out["raison"]


def _espionner_les_outils(mocker) -> dict:
    """Enregistre les kwargs reçus par les trois outils d'écriture."""
    appels: dict[str, dict] = {}
    for classe in (GrampsCreateNoteTool, GrampsEnsureTagTool, GrampsAttachTool):
        original = classe._run

        def espion(self, *args, _classe=classe, _original=original, **kwargs):
            appels[_classe.__name__] = kwargs
            return _original(self, *args, **kwargs)

        mocker.patch.object(classe, "_run", espion)
    return appels


def test_dry_run_est_propage_aux_trois_outils(monkeypatch, mocker):
    """Défense en profondeur : l'invariant doit être LOCAL à chaque appel.

    Sans `dry_run=dry_run`, les trois outils ne consultent que
    `GENECREW_DRY_RUN`. Aujourd'hui la garde en amont de `run_import_releve`
    couvre le cas, mais si elle bougeait, un `run_import_releve(dry_run=True)`
    sous `GENECREW_DRY_RUN=false` écrirait pour de bon. Ce test ne peut pas
    exercer ce chemin (la garde rend `raison="simulation"` avant l'écriture) :
    il vérifie donc directement que l'argument PART, ce qui est exactement
    l'invariant à protéger.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")

    def h(request):
        chemin = request.url.path
        if request.method == "POST" and chemin == "/api/notes/":
            return httpx.Response(201, json=[{"new": {"handle": "n1"}}])
        if request.method == "POST" and chemin == "/api/tags/":
            return httpx.Response(201, json=[{"new": {"handle": "t1"}}])
        if request.method == "PUT" and chemin == "/api/people/h1":
            return httpx.Response(200, json={})
        if chemin == "/api/tags/":
            return httpx.Response(200, json=[])
        if chemin == "/api/people/h1":
            return httpx.Response(200, json={"gramps_id": "I0001", "handle": "h1"})
        return _handler_arbre([_ROSE_ARBRE])(request)

    client = _client(h)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client)
    appels = _espionner_les_outils(mocker)

    out = run_import_releve(client, COLLAGE_ROSE, llm=_llm(), dry_run=False)
    assert out["ecrit"] is True
    assert appels["GrampsCreateNoteTool"]["dry_run"] is False
    assert appels["GrampsEnsureTagTool"]["dry_run"] is False
    assert appels["GrampsAttachTool"]["dry_run"] is False


# --- la citation sur l'événement visé ---------------------------------------
#
# `_arbre_avec_evenement` rend la forme réelle d'un événement exposé sur une
# personne via `extend=event_ref_list` : sous `extended.events`, chaque événement
# est un dict complet dont `type` est une CHAÎNE (miroir de `facts._event_from_raw`,
# qui lit `raw.get("type", "")`) et qui porte son propre `handle`.

def _arbre_avec_evenement(type_="Death", handle="e1"):
    def h(request):
        if request.url.path == "/api/people/":
            return httpx.Response(200, json=[{
                "gramps_id": "I0001", "handle": "h1",
                "extended": {"events": [{"handle": handle, "type": type_}]},
            }])
        return httpx.Response(200, json=[])
    return _client(h)


def test_handle_evenement_trouve_le_deces():
    assert handle_evenement(_arbre_avec_evenement(), "I0001", "Death") == "e1"


def test_handle_evenement_rend_none_si_absent():
    assert handle_evenement(_arbre_avec_evenement("Birth"), "I0001", "Death") is None


def test_citation_non_posee_si_l_evenement_manque(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    app = Appariement(verdict="net", gramps_id="I0001", handle="h1")
    out = ecrire_citation(_arbre_avec_evenement("Birth"), r, app)
    assert out["posee"] is False
    assert "absent" in out["raison"]


def test_citation_porte_la_reference_et_une_confiance_normal(monkeypatch):
    """Un relevé est une source dérivée : jamais `High`, ou on ferait passer
    un dépouillement pour l'acte original."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    vus = {}

    class _Citation:
        def _run(self, **kw):
            vus.update(kw)
            return json.dumps({"success": True, "data": {"handle": "c1"}})

    monkeypatch.setattr("genecrew.releves_import.GrampsCreateCitationTool", _Citation)
    monkeypatch.setattr("genecrew.releves_import.GrampsEnsureSourceTool",
                        lambda: type("T", (), {"_run": lambda s, **k: json.dumps(
                            {"success": True, "data": {"handle": "s1"}})})())
    monkeypatch.setattr("genecrew.releves_import.GrampsAttachCitationTool",
                        lambda: type("T", (), {"_run": lambda s, **k: json.dumps(
                            {"success": True, "data": {}})})())

    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    app = Appariement(verdict="net", gramps_id="I0001", handle="h1")
    out = ecrire_citation(_arbre_avec_evenement(), r, app)
    assert out["posee"] is True
    assert "106710046161418286" in vus["page"]
    assert vus["confidence"] == 2


def _espionner_les_outils_citation(mocker) -> dict:
    """Enregistre les kwargs reçus par les trois outils de citation."""
    appels: dict[str, dict] = {}
    for classe in (GrampsEnsureSourceTool, GrampsCreateCitationTool,
                  GrampsAttachCitationTool):
        original = classe._run

        def espion(self, *args, _classe=classe, _original=original, **kwargs):
            appels[_classe.__name__] = kwargs
            return _original(self, *args, **kwargs)

        mocker.patch.object(classe, "_run", espion)
    return appels


def test_dry_run_est_propage_aux_trois_outils_de_citation(mocker):
    """Même défense en profondeur que `test_dry_run_est_propage_aux_trois_outils`,
    mais pour les trois outils que `ecrire_citation` appelle : source, citation,
    rattachement. `dry_run` doit PARTIR en argument explicite vers chacun — pas
    seulement se déduire de `GENECREW_DRY_RUN`.

    Le client mock répond aussi sur `/sources/` et `/events/e1` (au-delà de
    `/people/`) : `GrampsEnsureSourceTool` liste les sources existantes même en
    dry-run, et `GrampsAttachCitationTool` lit toujours l'objet cible avant
    d'écrire — `_arbre_avec_evenement` seul ne les couvre pas (ses chemins hors
    `/people/` rendent une liste vide, invalide pour ces deux lectures).
    """
    def h(request):
        chemin = request.url.path
        if chemin == "/api/people/":
            return httpx.Response(200, json=[{
                "gramps_id": "I0001", "handle": "h1",
                "extended": {"events": [{"handle": "e1", "type": "Death"}]},
            }])
        if chemin == "/api/sources/":
            return httpx.Response(200, json=[])
        if chemin == "/api/events/e1":
            return httpx.Response(
                200, json={"handle": "e1", "gramps_id": "I0001", "citation_list": []})
        return httpx.Response(200, json=[])

    client = _client(h)
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client)
    appels = _espionner_les_outils_citation(mocker)

    r = parse_releve(COLLAGE_ROSE, llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    app = Appariement(verdict="net", gramps_id="I0001", handle="h1")
    out = ecrire_citation(client, r, app, dry_run=True)

    assert out["posee"] is True
    assert appels["GrampsEnsureSourceTool"]["dry_run"] is True
    assert appels["GrampsCreateCitationTool"]["dry_run"] is True
    assert appels["GrampsAttachCitationTool"]["dry_run"] is True


# --- rapport lisible -----------------------------------------------------

def test_rapport_affiche_le_mode_effectif(monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    out = run_import_releve(_arbre(_ROSE_ARBRE), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    texte = format_import_releve(out)
    assert "simulation" in texte
    assert "I0001" in texte
    assert "date complète" in texte


def test_rapport_liste_les_candidats_d_un_gris(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    jumeau = _personne("I0002", "h2")
    out = run_import_releve(_arbre(_ROSE_ARBRE, jumeau), COLLAGE_ROSE,
                            llm=_LLMStub(json.dumps(_JSON_ATTENDU)))
    texte = format_import_releve(out)
    assert "I0001" in texte and "I0002" in texte
