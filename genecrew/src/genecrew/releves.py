"""Appariement d'un relevé collé avec les personnes de l'arbre.

Le moteur est PUR : aucun appel réseau, aucune écriture. C'est ce qui le rend
testable hors-ligne et auditable ligne à ligne — un verdict doit toujours pouvoir
s'expliquer par les facteurs qui l'ont produit.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from pydantic import BaseModel, Field

from genecrew.pistes import _normaliser

FacteurReleve = Literal[
    "parent nommé", "deux parents nommés", "date complète", "lieu",
    "patronyme rare", "prénom", "année approximative",
]
"""Vocabulaire fermé des facteurs qu'un appariement peut invoquer.

Clos volontairement, sur le procédé de `FacteurConcordance` : un relevé qui
voudrait faire valoir « né vers 1821 » se fait refuser par pydantic plutôt que
de gonfler son poids. L'année approximative y figure, mais comme facteur FAIBLE
et distinct de la date — une année seule n'est jamais discriminante.

« parent nommé » et « deux parents nommés » sont deux facteurs DISTINCTS,
jamais les deux à la fois pour le même candidat : un père homonyme ne prouve
presque rien (un JACQUET peut avoir un père Pierre par pur hasard dans une
région où le patronyme est courant), alors qu'un couple de parents tous deux
nommément concordants est une coïncidence beaucoup plus rare. Les confondre
sous un même facteur reviendrait à accorder à l'homonymie isolée le poids
d'une preuve bien plus forte.
"""

POIDS: dict[str, int] = {
    "parent nommé": 5,
    "deux parents nommés": 8,
    "date complète": 5,
    "lieu": 3,
    "patronyme rare": 3,
    "prénom": 1,
    "année approximative": 1,
}

FACTEURS_FORTS: frozenset[str] = frozenset(
    {"parent nommé", "deux parents nommés", "date complète", "lieu",
     "patronyme rare"})

SEUIL_NET = 8
"""Poids minimal d'un verdict `net`. Atteignable par deux facteurs forts, jamais
par un empilement de faibles (voir `apparier`)."""

SEUIL_RARETE = 0.02

MARGE_EX_AEQUO = 2
"""Écart de poids en deçà duquel deux candidats sont tenus pour ex aequo.

Départager sur l'égalité EXACTE des poids est un piège dans un arbre qui
contient des doublons : deux personnes partageant date et lieu de décès pèsent
9 et 8 dès que l'une des deux a son prénom orthographié autrement. Élire la
première, c'est écrire dans l'arbre sur la foi d'un point de prénom, entre deux
candidats appuyés par la même preuve. Un point d'écart n'est pas une décision —
c'est du bruit, et ça se relit à la main.
"""

FENETRE_ANNEE_APPROX = 2
"""Écart d'années toléré pour le facteur faible « année approximative ».

Nommé plutôt qu'écrit en dur : une année déduite d'un âge au décès (« 73 ans »)
se décale d'un an selon que l'anniversaire est passé ou non, et les relevés
eux-mêmes arrondissent. Deux ans absorbent ce jeu sans rapprocher des
générations différentes."""


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

    Exception volontaire à ce parti pris de largeur : un patronyme vide n'est
    jamais bloqué, même contre une personne à patronyme également vide (filiation
    inconnue, enfant naturel — cas courant en généalogie). Une chaîne vide n'est
    pas une graphie du nom, c'est l'absence de la donnée ; la traiter comme une
    clé ordinaire ferait apparier deux absences entre elles, et ces candidats
    alimenteraient ensuite une pondération capable de conclure à un verdict net
    — qui écrit dans l'arbre. Mieux vaut ne bloquer sur rien que bloquer sur du
    vide.
    """
    cle = _cle_blocage(releve.sujet_nom)
    if not cle:
        return []
    return [p for p in people if _cle_blocage(p.surname) == cle]


def _evenement_compare(person: PersonFacts, type_: str) -> EventFact | None:
    """L'événement de l'arbre comparable au relevé, `None` s'il n'y en a pas.

    Le mariage est HORS PÉRIMÈTRE à ce stade : il vit sur la famille, pas sur
    la personne, et `PersonFacts` n'en porte aucune trace. C'est pourquoi tout
    type autre que « Death » et « Birth » rend `None` plutôt que de retomber
    sur la naissance. Un tel repli comparerait un relevé de mariage à un acte
    de naissance ; comme naître et se marier dans la même commune est le cas
    ordinaire, le lieu concorderait souvent — et on tirerait un facteur fort
    d'une comparaison qui n'a jamais regardé le mariage.
    """
    if type_ == "Death":
        return person.death
    if type_ == "Birth":
        return person.birth
    return None


def _date_iso(ev: EventFact | None) -> str:
    """La date de l'événement en AAAA-MM-JJ, "" si elle n'est pas complète.

    `EventFact` ne porte pas de date texte : la source est `dateval`, au format
    Gramps `[jour, mois, année, slash]`, où 0 signale une composante inconnue.
    Une date n'est COMPLÈTE que si les trois composantes sont non nulles — c'est
    exactement ce qui sépare le facteur fort « date complète » du facteur faible
    « année approximative ».

    Seul `modifier == 0` (date EXACTE) est accepté. La sémantique Gramps est
    `0 exact, 1 before, 2 after, 3 about, 4 range, 5 span, 6 text` : dans tous
    les autres cas la source ne s'engage pas sur le jour exact. En tirer le
    facteur fort « date complète » — ou pire un veto s'il diffère — affirmerait
    une précision que le document ne donne pas, et c'est exactement ce qui
    inscrirait une fausseté dans l'arbre.

    Le cas des intervalles (4) et durées (5) est le plus traître : Gramps y met
    DEUX dates dans `dateval` (huit éléments), si bien qu'un garde de longueur
    ne suffit pas — les trois premières composantes se lisent comme une date
    exacte alors qu'elles ne sont qu'une borne. Filtrer sur `modifier` couvre
    ce cas comme les autres.
    """
    if ev is None or ev.modifier != 0 or len(ev.dateval) < 3:
        return ""
    jour, mois, annee = ev.dateval[0], ev.dateval[1], ev.dateval[2]
    if not (jour and mois and annee):
        return ""
    return f"{annee:04d}-{mois:02d}-{jour:02d}"


def _commune(ev: EventFact | None) -> str:
    """La COMMUNE de l'événement, "" si elle est introuvable.

    `EventFact` porte deux champs de lieu : `place` est la hiérarchie complète
    (« Saint-Martin-d'Auxigny, Cher, France ») et `place_name` la commune seule.
    Le relevé, lui, ne cite qu'une commune. Comparer la hiérarchie à la commune
    rend l'égalité systématiquement fausse sur les données réelles — le facteur
    « lieu » ne se déclencherait jamais en production. On lit donc `place_name`,
    et on se rabat sur le premier segment de `place` quand la fiche ne l'a pas
    renseigné : c'est là que Gramps range la commune.
    """
    if ev is None:
        return ""
    if ev.place_name:
        return ev.place_name
    return ev.place.split(",")[0].strip()


def facteurs_et_divergences(
    releve: ReleveIndexe, person: PersonFacts, rarete: dict[str, float],
    parents_par_handle: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """Ce qui concorde et ce qui contredit, sans encore trancher."""
    facteurs: list[str] = []
    divergences: list[str] = []
    ev = _evenement_compare(person, releve.evenement_type)

    date_arbre = _date_iso(ev)
    if releve.evenement_date and date_arbre:
        if date_arbre == releve.evenement_date:
            facteurs.append("date complète")
        else:
            divergences.append(f"date {date_arbre} ≠ relevé {releve.evenement_date}")

    # Un lieu qui concorde est un facteur ; un lieu qui NE concorde PAS n'est
    # rien du tout. Une inégalité de chaîne n'est pas une contradiction :
    # « Saint Martin d'Auxigny » contre « Saint-Martin-d'Auxigny » est une
    # graphie, pas une autre commune, et ce moteur pur n'a aucun résolveur de
    # lieux pour trancher. En faire une divergence — donc un veto — écarterait
    # de bons candidats sur une simple différence de tiret. Le veto reste
    # réservé aux dates, qui sont des entiers non ambigus.
    commune = _commune(ev)
    if (releve.evenement_lieu and commune
            and _normaliser(commune) == _normaliser(releve.evenement_lieu)):
        facteurs.append("lieu")

    if est_rare(releve.sujet_nom, rarete):
        facteurs.append("patronyme rare")

    if _normaliser(person.given) == _normaliser(releve.sujet_prenom):
        facteurs.append("prénom")

    # Même exigence, plus lâche d'un cran : une année n'est comparable à ±2 que
    # si la source la donne (0 = exact) ou l'approche (3 = about). « Avant
    # 1821 » (1), « après » (2) ou un intervalle (4/5) ne désignent aucune
    # année en particulier — les compter reviendrait à fabriquer une
    # concordance à partir d'une borne.
    naissance = person.birth
    if naissance is not None and naissance.modifier in (0, 3):
        annee_arbre = naissance.year
        if (releve.naissance_estimee and annee_arbre
                and abs(annee_arbre - releve.naissance_estimee) <= FENETRE_ANNEE_APPROX):
            facteurs.append("année approximative")

    parents_arbre = {_normaliser(n) for n in parents_par_handle.get(person.handle, [])}
    parents_releve = {_normaliser(pl.nom) for pl in releve.personnes_liees
                      if pl.role in ("père", "mère")}
    concordants = parents_arbre & parents_releve
    # Un seul parent qui concorde (un homonyme, une coïncidence sur un
    # patronyme courant) n'est pas la même preuve qu'un couple qui concorde
    # en entier — d'où deux facteurs distincts, jamais les deux ensemble : le
    # cumuler reviendrait à compter la même preuve deux fois (5+8=13).
    if len(concordants) >= 2:
        facteurs.append("deux parents nommés")
    elif len(concordants) == 1:
        facteurs.append("parent nommé")

    return facteurs, divergences


def _verdict_candidat(facteurs: list[str], divergences: list[str]) -> tuple[str, int]:
    """Poids et éligibilité d'UN candidat. La divergence est un veto."""
    if divergences:
        return "aucun", 0
    poids = sum(POIDS[f] for f in facteurs)
    if not (set(facteurs) & FACTEURS_FORTS):
        return "aucun", poids       # un faible ne suffit jamais, même à plusieurs
    return ("net" if poids >= SEUIL_NET else "gris"), poids


def apparier(releve: ReleveIndexe, people: list[PersonFacts],
             rarete: dict[str, float],
             parents_par_handle: dict[str, list[str]]) -> Appariement:
    """Le verdict, motivé. `gris` est un état EXPLICITE, pas un effet de seuil.

    C'est ce qui borne la facture : le nombre de lignes qui partiront au LLM est
    connu avant le moindre appel.
    """
    evalues = []
    for p in candidats_blocage(releve, people):
        facteurs, divergences = facteurs_et_divergences(
            releve, p, rarete, parents_par_handle)
        verdict, poids = _verdict_candidat(facteurs, divergences)
        evalues.append((verdict, poids, p, facteurs, divergences))

    retenus = [e for e in evalues if e[0] != "aucun"]
    if not retenus:
        div = [d for e in evalues for d in e[4]]
        return Appariement(verdict="aucun", divergences=div)

    retenus.sort(key=lambda e: e[1], reverse=True)
    meilleur = retenus[0]
    # « Comparables », pas « égaux » : tout candidat à moins de MARGE_EX_AEQUO
    # du meilleur reste en lice, et s'ils sont plusieurs le verdict est gris
    # avec la liste COMPLÈTE — le relecteur doit voir le concurrent, pas
    # seulement le gagnant.
    ex_aequo = [e for e in retenus if meilleur[1] - e[1] <= MARGE_EX_AEQUO]

    if len(ex_aequo) > 1:
        return Appariement(verdict="gris", poids=meilleur[1],
                           facteurs=meilleur[3],
                           candidats=[e[2].gramps_id for e in ex_aequo])

    verdict, poids, person, facteurs, _ = meilleur
    return Appariement(verdict=verdict, gramps_id=person.gramps_id,
                       handle=person.handle, facteurs=facteurs, poids=poids,
                       candidats=[person.gramps_id])
