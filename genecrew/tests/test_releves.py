"""Tests hors-ligne du moteur d'appariement des relevés (pur, sans réseau)."""

from typing import get_args

import pytest
from pydantic import ValidationError

from genecrew.releves import FACTEURS_FORTS, POIDS, Appariement, FacteurReleve, PersonneLiee, ReleveIndexe


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
