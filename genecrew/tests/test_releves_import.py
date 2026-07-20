"""Tests hors-ligne de l'import de relevés (LLM stubbé, Gramps via MockTransport)."""

import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.deces_apply import source_title_for
from genecrew.releves import Appariement
from genecrew.releves_import import (
    TAG_RELEVE,
    _parents_par_handle,
    code_fonds,
    corps_note_releve,
    deja_importe,
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
    """Le chemin nominal : note créée, tag garanti, les deux AJOUTÉS.

    La personne du mock porte DÉJÀ une note et un tag. C'est l'essentiel du
    test : l'append-only est un invariant structurel du projet — on annote, on
    n'écrase jamais ce qu'une personne porte déjà. Sur une personne vierge, un
    code qui remplacerait les listes par `[nouveau]` rendrait exactement le même
    PUT qu'un code qui ajoute : le test ne prouverait rien. Ici, l'assertion
    exige l'ANCIEN en premier et le neuf ajouté derrière.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    vu = {"notes": [], "tags": [], "put": []}

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
