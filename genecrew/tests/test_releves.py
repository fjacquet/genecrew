"""Tests hors-ligne du moteur d'appariement des relevés (pur, sans réseau)."""

from typing import get_args

import pytest
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from pydantic import ValidationError

from genecrew.releves import (
    FACTEURS_FORTS,
    POIDS,
    Appariement,
    FacteurReleve,
    PersonneLiee,
    ReleveIndexe,
    candidats_blocage,
    est_rare,
    rarete_patronymes,
)


def _p(gramps_id, surname, given, **kw):
    return PersonFacts(gramps_id=gramps_id, handle=f"h{gramps_id}",
                       name=f"{given} {surname}", surname=surname, given=given,
                       sex=kw.pop("sex", "U"), **kw)


def test_releve_indexe_minimal():
    r = ReleveIndexe(
        fonds="Cercle Généalogique du Haut-Berry", reference="106710046161418286",
        sujet_nom="JACQUET", sujet_prenom="Rose", evenement_type="Death",
        texte_brut="Rose JACQUET\nLe 10 décembre 1894",
    )
    assert r.evenement_date == ""
    assert r.personnes_liees == []


def test_personne_liee_porte_son_role():
    p = PersonneLiee(nom="Pierre JACQUET", role="père", detail="décédé avant 1894")
    assert p.role == "père"


def test_facteur_hors_vocabulaire_refuse():
    """Vocabulaire fermé : « né en 1821 » ne doit pas pouvoir gonfler un score."""
    with pytest.raises(ValidationError):
        Appariement(verdict="net", facteurs=["né en 1821"])


def test_annee_approximative_est_un_facteur_distinct_de_la_date():
    """Règle projet : une année seule n'est jamais discriminante."""
    a = Appariement(verdict="gris", facteurs=["année approximative"])
    assert "date complète" not in a.facteurs


def test_vocabulaire_des_facteurs_reste_synchronise():
    """`FacteurReleve`, `POIDS` et `FACTEURS_FORTS` répètent le même vocabulaire à
    trois endroits ; un renommage ou un accent oublié dans un seul des trois ferait
    calculer des poids faux sans qu'aucune erreur ne se déclenche ailleurs."""
    vocabulaire = set(get_args(FacteurReleve))
    assert set(POIDS.keys()) == vocabulaire
    assert FACTEURS_FORTS <= vocabulaire


def test_rarete_est_une_fraction_de_l_arbre():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "JACQUET", "Pierre"),
              _p("I3", "JACQUET", "Jean"), _p("I4", "VILLEPELLET", "Marie")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 0.75
    assert r["VILLEPELLET"] == 0.25


def test_rarete_ignore_casse_et_accents():
    people = [_p("I1", "Jacquet", "Rose"), _p("I2", "JACQUET", "Pierre")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 1.0


def test_est_rare_distingue_le_courant_du_rare():
    r = {"JACQUET": 0.75, "VILLEPELLET": 0.01}
    assert est_rare("VILLEPELLET", r) is True
    assert est_rare("JACQUET", r) is False


def test_patronyme_absent_de_l_arbre_n_est_pas_rare():
    """Absent ≠ rare : sans mesure, on n'accorde pas de poids fort."""
    assert est_rare("INCONNU", {"JACQUET": 0.75}) is False


def _releve(**kw):
    base = dict(fonds="CGHB", reference="106710046161418286", sujet_nom="JACQUET",
                sujet_prenom="Rose", evenement_type="Death", texte_brut="…")
    base.update(kw)
    return ReleveIndexe(**base)


def test_blocage_retient_le_patronyme_et_rejette_le_reste():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "VILLEPELLET", "Marie")]
    assert [c.gramps_id for c in candidats_blocage(_releve(), people)] == ["I1"]


def test_blocage_tolere_casse_et_accents():
    people = [_p("I1", "Jacquèt", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JACQUET"), people)) == 1


def test_blocage_suit_les_variantes_de_graphie():
    """Sans table de variantes, « absent » voudrait dire « mal cherché »."""
    people = [_p("I1", "JACQUET", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JAQUET"), people)) == 1


def test_blocage_vide_quand_le_patronyme_est_inconnu():
    people = [_p("I1", "JACQUET", "Rose")]
    assert candidats_blocage(_releve(sujet_nom="MARTIN"), people) == []
