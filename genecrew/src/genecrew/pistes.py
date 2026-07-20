"""Contrat de consignation des pistes de recherche (Phase 4, document-de-travail §6.3).

Une piste n'est jamais un fait : aucune citation n'est créée ici. Ce module définit
ce qui fait une piste forte, comment on l'identifie de façon stable dans le temps,
et comment on la consigne sans jamais écrire deux fois la même.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Literal

from crewai_custom_tools.tools.genealogy.models.domain import Piste  # noqa: F401

_LONGUEUR_CLE = 8


def evaluer_force(concordances: list[str],
                  divergences: list[str]) -> Literal["forte", "faible"]:
    """Forte = au moins DEUX facteurs concordants indépendants ET aucune divergence dure.

    Catégoriel, pas numérique. Un score peut valoir 1.0 en masquant une ambiguïté
    (mesuré sur le résolveur de lieux), et la règle projet « une année seule n'est
    jamais discriminante » est catégorielle par nature. L'appelant est responsable
    de ne PAS lister l'année seule comme concordance : elle qualifie une date, elle
    n'en constitue pas une.
    """
    if divergences:
        return "faible"
    return "forte" if len(concordances) >= 2 else "faible"


def _normaliser(valeur: str) -> str:
    """Casse, accents et espaces retirés — la même fiche doit donner la même clé."""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", valeur)
                          if unicodedata.category(c) != "Mn")
    return " ".join(sans_accent.split()).upper()


def cle_derivee(source: str, champs: list[str]) -> str:
    """Identité de repli quand la source ne fournit aucun identifiant stable.

    Ce n'est PAS une URL : elle ne s'affiche jamais comme preuve, elle sert
    uniquement à reconnaître une piste déjà consignée. Le pire qu'une collision
    puisse produire est un doublon manqué — pas un lien mort donné pour une source.

    `hashlib` et non `hash()` : ce dernier est salé à chaque exécution, ce qui
    casserait l'idempotence entre deux lancements du pipeline.
    """
    graine = "|".join([source] + [_normaliser(c) for c in champs])
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:_LONGUEUR_CLE]


def marqueur(source: str, identite: str, derivee: bool = False) -> str:
    """Marqueur d'idempotence, porté par le corps de la note.

    Il porte l'IDENTITÉ, jamais la date : le pipeline repasse sur les mêmes
    personnes pendant des mois, et un marqueur daté recréerait la même piste à
    chaque exécution.
    """
    return f"[genecrew:piste:{source}:{'k=' if derivee else ''}{identite}]"
