"""Tests hors-ligne de l'import de relevés (LLM stubbé, Gramps via MockTransport)."""

import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.deces_apply import source_title_for
from genecrew.releves import Appariement
from genecrew.releves_import import (
    code_fonds,
    corps_note_releve,
    deja_importe,
    marqueur_releve,
    parse_releve,
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
