"""Appariement d'un relevé collé avec les personnes de l'arbre.

Le moteur est PUR : aucun appel réseau, aucune écriture. C'est ce qui le rend
testable hors-ligne et auditable ligne à ligne — un verdict doit toujours pouvoir
s'expliquer par les facteurs qui l'ont produit.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts
from pydantic import BaseModel, Field

from genecrew.pistes import _normaliser

FacteurReleve = Literal[
    "parent nommé", "date complète", "lieu", "patronyme rare",
    "prénom", "année approximative",
]
"""Vocabulaire fermé des facteurs qu'un appariement peut invoquer.

Clos volontairement, sur le procédé de `FacteurConcordance` : un relevé qui
voudrait faire valoir « né vers 1821 » se fait refuser par pydantic plutôt que
de gonfler son poids. L'année approximative y figure, mais comme facteur FAIBLE
et distinct de la date — une année seule n'est jamais discriminante.
"""

POIDS: dict[str, int] = {
    "parent nommé": 5,
    "date complète": 5,
    "lieu": 3,
    "patronyme rare": 3,
    "prénom": 1,
    "année approximative": 1,
}

FACTEURS_FORTS: frozenset[str] = frozenset(
    {"parent nommé", "date complète", "lieu", "patronyme rare"})

SEUIL_NET = 8
"""Poids minimal d'un verdict `net`. Atteignable par deux facteurs forts, jamais
par un empilement de faibles (voir `apparier`)."""

SEUIL_RARETE = 0.02


class PersonneLiee(BaseModel):
    """Une personne citée par le relevé sans en être le sujet."""

    nom: str
    role: str = Field(description="père | mère | conjoint | témoin | autre")
    detail: str = ""


class ReleveIndexe(BaseModel):
    """Le relevé, une fois interprété. Le texte brut est conservé intégralement."""

    fonds: str
    reference: str
    sujet_nom: str
    sujet_prenom: str
    evenement_type: str = Field(description="Death | Birth | Marriage")
    evenement_date: str = ""            # ISO "1894-12-10", "" si absente
    evenement_lieu: str = ""
    naissance_estimee: int | None = None
    personnes_liees: list[PersonneLiee] = Field(default_factory=list)
    texte_brut: str


class Appariement(BaseModel):
    """Le verdict, et surtout ce qui l'a produit."""

    verdict: Literal["net", "gris", "aucun"]
    gramps_id: str | None = None
    handle: str | None = None
    facteurs: list[FacteurReleve] = Field(default_factory=list)
    divergences: list[str] = Field(default_factory=list)
    poids: int = 0
    candidats: list[str] = Field(default_factory=list)


def rarete_patronymes(people: list[PersonFacts]) -> dict[str, float]:
    """Fréquence de chaque patronyme DANS L'ARBRE, normalisée casse et accents.

    Mesurée, jamais devinée : « JACQUET » dans le Cher n'a pas la valeur
    discriminante de « VILLEPELLET », et seul un comptage sur tes données peut
    le dire. Recalculé à chaque passage — l'arbre bouge.
    """
    noms = [_normaliser(p.surname) for p in people if p.surname]
    if not noms:
        return {}
    total = len(noms)
    return {nom: n / total for nom, n in Counter(noms).items()}


def est_rare(surname: str, rarete: dict[str, float],
             seuil: float = SEUIL_RARETE) -> bool:
    """Un patronyme absent de l'arbre n'est PAS déclaré rare.

    Absent veut dire non mesuré, pas exceptionnel. Lui accorder un facteur fort
    sur une non-mesure ferait basculer des verdicts sur du vide.
    """
    return rarete.get(_normaliser(surname), 1.0) <= seuil


VARIANTES: dict[str, str] = {
    "JAQUET": "JACQUET",
    "JACQUES": "JACQUET",
    "VILLEPELET": "VILLEPELLET",
    "VILAUDY": "VILLAUDY",
}
"""Graphies vues en relevé → forme retenue dans l'arbre.

Table volontairement explicite plutôt qu'un algorithme phonétique : Soundex est
calibré sur l'anglais et rapproche des patronymes français sans rapport. On
préfère rater une variante — visible au rapport — qu'en inventer.
"""


def _cle_blocage(surname: str) -> str:
    norme = _normaliser(surname)
    return VARIANTES.get(norme, norme)


def candidats_blocage(releve: ReleveIndexe,
                       people: list[PersonFacts]) -> list[PersonFacts]:
    """Les personnes qui méritent une comparaison fine.

    Sans cette étape, N relevés × 2 119 personnes explose. Le blocage est
    DÉLIBÉRÉMENT large : c'est la pondération qui tranche, pas lui. Un blocage
    trop serré ferait dire « absent de l'arbre » à une personne présente, et
    l'import créerait un doublon.
    """
    cle = _cle_blocage(releve.sujet_nom)
    return [p for p in people if _cle_blocage(p.surname) == cle]
