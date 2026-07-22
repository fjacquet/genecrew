"""Appariement d'un relevé collé avec les personnes de l'arbre.

Le moteur est PUR : aucun appel réseau, aucune écriture. C'est ce qui le rend
testable hors-ligne et auditable ligne à ligne — un verdict doit toujours pouvoir
s'expliquer par les facteurs qui l'ont produit.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal, NamedTuple

from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from pydantic import BaseModel, Field

from genecrew.pistes import _normaliser

FacteurReleve = Literal[
    "parent nommé",
    "deux parents nommés",
    "date complète",
    "lieu",
    "patronyme rare",
    "prénom",
    "année approximative",
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
    {"parent nommé", "deux parents nommés", "date complète", "lieu", "patronyme rare"}
)

SEUIL_NET = 8
"""Poids minimal d'un verdict `net`.

Atteignable par deux facteurs forts, ou par le seul « deux parents nommés »
(8) — un couple de parents nommément concordants est une coïncidence assez rare
pour se suffire. Jamais, en revanche, par un empilement de faibles : la garde
`FACTEURS_FORTS` de `_verdict_candidat` l'interdit avant même de comparer au
seuil."""

SEUIL_RARETE = 0.02

MARGE_EX_AEQUO = 3
"""Écart de poids en deçà duquel deux candidats sont tenus pour ex aequo.

Départager sur l'égalité EXACTE des poids est un piège dans un arbre qui
contient des doublons : deux personnes partageant date et lieu de décès pèsent
9 et 8 dès que l'une des deux a son prénom orthographié autrement. Élire la
première, c'est écrire dans l'arbre sur la foi d'un point de prénom, entre deux
candidats appuyés par la même preuve. Un point d'écart n'est pas une décision —
c'est du bruit, et ça se relit à la main.

**Pourquoi 3 et pas 2.** Sur les poids réels, un écart de 3 laisse encore élire
un gagnant seul, et le scénario qui produit exactement 3 est le plus dangereux
du moteur :

    I1 : date complète (5) + lieu (3) + prénom (1) = 9  → net, écriture
    I2 : date complète (5)            + prénom (1) = 6  → écart 3

Les deux partagent la MÊME date de décès complète — la signature d'un doublon
d'arbre. Le seul différenciateur est le facteur « lieu » : hors `lieux_resolus`,
c'est une simple égalité de chaîne, dont `_comparer_lieux` établit par ailleurs
qu'une inégalité ne prouve rien (« absent de la mesure ne veut pas dire
contredit »). Il suffit que I2 ait sa commune saisie autrement — « Saint Martin
d'Auxigny » sans les tirets — pour perdre ses 3 points, et l'écriture
automatique se retrouve arbitrée par une GRAPHIE. Trois est donc la plus petite
valeur qui refuse de trancher ce cas.

Au-delà de 3 on n'achète plus rien : 4 engloberait un concurrent qui n'a pas la
date, c'est-à-dire une preuve franchement moindre, et transformerait en `gris`
des appariements légitimement nets.
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
    evenement_date: str = ""  # ISO "1894-12-10", "" si absente
    evenement_lieu: str = ""  # commune NUE (sert de CLÉ dans lieux_resolus)
    # Le PAYS de l'événement, extrait par le LLM quand le relevé l'indique ou
    # l'implique clairement (un département français implique la France, un canton
    # suisse la Suisse). Vide si vraiment inconnu — JAMAIS un défaut « France » :
    # l'arbre a des branches suisses/allemandes, et un défaut français rangerait
    # un lieu suisse sous « FR: », la fausse concordance de codes que le veto sur
    # les lieux existe pour empêcher. `evenement_lieu` reste la commune nue (la
    # clé) ; c'est ce champ qui QUALIFIE la chaîne envoyée au résolveur géo, seule
    # à porter le pays que `parse_pname` lira. Défaut "" → rétrocompatible.
    evenement_pays: str = ""
    # Le DÉPARTEMENT/échelon intermédiaire (« Cher »), extrait quand le relevé le
    # donne. Il ne sert PAS l'appariement (le veto compare des codes commune) mais la
    # CASCADE de création de lieux : « commune, département, pays » est ce que le
    # résolveur géographique attend pour désambiguïser une commune homonyme en France.
    # Sans lui, la création d'un décès pour un sujet créé retombe sur une résolution
    # ambiguë — donc pas de lieu posé. Défaut "" → rétrocompatible.
    evenement_departement: str = ""
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


def est_rare(
    surname: str, rarete: dict[str, float], seuil: float = SEUIL_RARETE
) -> bool:
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


def candidats_blocage(
    releve: ReleveIndexe, people: list[PersonFacts]
) -> list[PersonFacts]:
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

    DEUX champs qualifient la date, et il faut exiger les deux — ils sont
    ORTHOGONAUX dans Gramps, aucun n'implique l'autre :

    - `modifier` (`0 exact, 1 before, 2 after, 3 about, 4 range, 5 span,
      6 text`) dit la FORME de la date : la source s'engage-t-elle sur un jour
      précis, ou seulement sur une borne, un « vers », un texte libre ?
    - `quality` (`0 normal, 1 estimated, 2 calculated`) dit sa PROVENANCE : la
      date a-t-elle été lue dans un acte, ou reconstruite par le généalogiste ?

    Ne filtrer que sur `modifier` laisse passer le cas le plus courant de date
    non attestée : une naissance CALCULÉE depuis un âge au décès (« Âge :
    73 ans ») porte `modifier == 0` — elle n'est ni approximative ni bornée,
    elle est simplement déduite — ET un `dateval` complet. Elle traverserait le
    garde et vaudrait le facteur fort « date complète » (5 points) sur une date
    qu'aucune source n'affirme ; pire, si elle diffère du relevé elle
    produirait une DIVERGENCE, donc un veto, et un candidat vetoé ne revient
    jamais devant le relecteur humain.

    On exige donc `modifier == 0` ET `quality == 0`. Dans tous les autres cas,
    en tirer le facteur fort — ou un veto — affirmerait une précision que le
    document ne donne pas, et c'est exactement ce qui inscrirait une fausseté
    dans l'arbre.

    Le cas des intervalles (4) et durées (5) est le plus traître côté
    `modifier` : Gramps y met DEUX dates dans `dateval` (huit éléments), si
    bien qu'un garde de longueur ne suffit pas — les trois premières
    composantes se lisent comme une date exacte alors qu'elles ne sont qu'une
    borne. Filtrer sur `modifier` couvre ce cas comme les autres.
    """
    if ev is None or ev.modifier != 0 or ev.quality != 0 or len(ev.dateval) < 3:
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


def _identifiant_resolu(
    lieux_resolus: dict[str, str], lieu_normalise: str
) -> str | None:
    """Lit `lieux_resolus`, en imposant le contrat de préfixe pays.

    Une valeur SANS préfixe pays (pas de `:`, par exemple un code INSEE nu comme
    `"18209"`) est IGNORÉE : elle vaut `None`, exactement comme si le lieu
    n'avait jamais été résolu. C'est un garde-fou STRUCTUREL, vérifiable par le
    code, pas un simple commentaire qu'on espère voir relu.

    La raison : un code national seul ne désigne pas une commune de façon
    univoque entre pays. Un code INSEE français `18209` et un numéro OFS suisse
    `18209` sont deux chaînes ÉGALES sans être la même commune — les comparer
    nus fabriquerait une concordance entre deux communes de deux pays
    différents, pousserait vers le facteur « lieu », et de là vers un verdict
    `net` : une ÉCRITURE FAUSSE dans l'arbre. Retomber sur le statut « non
    résolu » est en revanche toujours sûr : `_comparer_lieux` n'en tire jamais
    de veto, seulement un repli sur l'égalité de chaîne (voir sa branche 3). Le
    repli est sûr ; faire confiance à un code nu ne l'est pas.

    Un simple test de présence du `:` ne suffit pas : il laisse passer `"FR:"`,
    `":18209"` et surtout `"FR:None"`. `ResolvedPlace.code` est typé
    `str | None` dans la bibliothèque, et l'orchestration construit
    `lieux_resolus` par une f-string du genre `f"{pays}:{place.code}"` — dès
    qu'une résolution échoue partiellement, elle produit littéralement la
    chaîne `"FR:None"`. Sans ce garde, DEUX COMMUNES DIFFÉRENTES et non codées
    rendraient la même chaîne `"FR:None"` : le moteur y verrait deux
    identifiants résolus et ÉGAUX, fabriquant le facteur « lieu » entre deux
    communes jamais comparées — et de là un verdict `net` avec une écriture
    fausse dans l'arbre. Symétriquement, `"FR:None"` contre un identifiant
    réellement résolu produirait un veto sur une pure absence de donnée, et un
    candidat vetoé ne revient jamais devant le relecteur humain. `partition`
    impose que les DEUX moitiés autour du `:` soient non vides, et la moitié
    droite ne vaut jamais (insensible à la casse) `"none"`.

    La casse du préfixe pays est normalisée (`"fr:18209"` et `"FR:18209"`
    désignent la même commune) : sans ça, deux saisies de la même résolution
    diffèreraient par un simple accident de casse, perdant le facteur « lieu »
    ou pire, fabriquant un veto entre deux graphies de la MÊME commune. La
    partie numérique, elle, N'EST PAS touchée — certains codes sont
    alphanumériques et sensibles à la casse (communes corses, ex. `"2A004"`).
    """
    code = lieux_resolus.get(lieu_normalise)
    if not code:
        return None
    pays, separateur, numero = code.partition(":")
    if not separateur or not pays or not numero:
        return None
    if numero.strip().lower() == "none":
        return None
    return f"{pays.upper()}:{numero}"


def _comparer_lieux(
    lieu_releve: str, commune_arbre: str, lieux_resolus: dict[str, str]
) -> tuple[bool, str]:
    """Concordance des lieux : `(facteur, divergence)`.

    Règle à TROIS branches, dans cet ordre :

    1. Les DEUX lieux sont résolus en identifiant canonique de commune — un
       code national PRÉFIXÉ par le pays (`"FR:18209"`, `"CH:2701"`,
       `"DE:06531000"`) — et les identifiants sont ÉGAUX → facteur « lieu ».
       C'est plus fort que l'égalité de chaîne : « Saint Martin d'Auxigny » et
       « Saint-Martin-d'Auxigny » rendent le même identifiant, et la graphie
       cesse de faire perdre un facteur.
    2. Les DEUX sont résolus et les identifiants DIFFÈRENT → divergence, donc
       veto. C'est légitime, et c'est le seul cas où ça l'est : deux
       identifiants canoniques distincts désignent démontrablement deux
       communes distinctes, pas deux façons d'écrire la même — y compris
       quand seul le préfixe pays diffère (`"FR:18209"` contre `"CH:18209"`) :
       ce ne sont PAS deux graphies de la même commune, ce sont deux communes.
    3. Au moins un des deux n'est PAS résolu — absent de `lieux_resolus`, OU
       présent mais sans préfixe pays valide, voir `_identifiant_resolu` — →
       repli sur l'égalité de la chaîne normalisée : facteur si elles
       concordent, RIEN si elles diffèrent. Jamais de veto.

    Le pourquoi de la troisième branche est exactement celui d'`est_rare` face à
    un patronyme absent de l'arbre : **absent de la mesure ne veut pas dire
    contredit**. Un lieu non résolu, c'est une comparaison qui n'a pas eu lieu —
    l'orchestration n'a pas su le géocoder, le lieu est écrit d'une façon que le
    résolveur ignore, ou la valeur reçue ne respecte pas le contrat de préfixe.
    Accorder un veto là-dessus écarterait de vraies correspondances sur du
    vide, et un candidat écarté ne revient jamais devant le relecteur.

    La fonction reste PURE : le dictionnaire `lieux_resolus` arrive tout
    construit de l'orchestration, aucune résolution réseau n'a lieu ici.
    """
    if not (lieu_releve and commune_arbre):
        return False, ""
    code_releve = _identifiant_resolu(lieux_resolus, _normaliser(lieu_releve))
    code_arbre = _identifiant_resolu(lieux_resolus, _normaliser(commune_arbre))
    if code_releve and code_arbre:
        if code_releve == code_arbre:
            return True, ""
        return False, (
            f"lieu {commune_arbre} ({code_arbre}) "
            f"≠ relevé {lieu_releve} ({code_releve})"
        )
    return _normaliser(commune_arbre) == _normaliser(lieu_releve), ""


def facteurs_et_divergences(
    releve: ReleveIndexe,
    person: PersonFacts,
    rarete: dict[str, float],
    parents_par_handle: dict[str, list[str]],
    lieux_resolus: dict[str, str] | None = None,
) -> tuple[list[FacteurReleve], list[str]]:
    """Ce qui concorde et ce qui contredit, sans encore trancher.

    Le premier membre est typé `FacteurReleve`, pas `str` : c'est le vocabulaire
    fermé, et l'annoter ainsi fait relever une faute de frappe par le
    vérificateur de types plutôt que par un `KeyError` dans `POIDS` — ou, pire,
    par un poids silencieusement faux.

    `lieux_resolus` associe un lieu brut NORMALISÉ (via `_normaliser`) à son
    identifiant canonique de commune — un code national préfixé par le pays
    (ex. `"FR:18209"`), jamais un code nu, voir `_identifiant_resolu`. Optionnel :
    absent, la comparaison de lieux se réduit à son repli sur les chaînes,
    c'est-à-dire au comportement d'avant. Voir `_comparer_lieux`.
    """
    lieux_resolus = lieux_resolus or {}
    facteurs: list[FacteurReleve] = []
    divergences: list[str] = []
    ev = _evenement_compare(person, releve.evenement_type)

    date_arbre = _date_iso(ev)
    if releve.evenement_date and date_arbre:
        if date_arbre == releve.evenement_date:
            facteurs.append("date complète")
        else:
            divergences.append(f"date {date_arbre} ≠ relevé {releve.evenement_date}")

    # Trois branches, détaillées dans `_comparer_lieux` : identifiants
    # canoniques égaux → facteur ; identifiants différents → veto (deux
    # communes démontrées distinctes, y compris sur un simple écart de
    # préfixe pays) ; lieu non résolu d'un côté ou de l'autre → repli sur la
    # chaîne, sans jamais de veto sur une non-mesure.
    facteur_lieu, divergence_lieu = _comparer_lieux(
        releve.evenement_lieu, _commune(ev), lieux_resolus
    )
    if facteur_lieu:
        facteurs.append("lieu")
    if divergence_lieu:
        divergences.append(divergence_lieu)

    if est_rare(releve.sujet_nom, rarete):
        facteurs.append("patronyme rare")

    if _normaliser(person.given) == _normaliser(releve.sujet_prenom):
        facteurs.append("prénom")

    # Même exigence sur `modifier`, plus lâche d'un cran : une année n'est
    # comparable à ±2 que si la source la donne (0 = exact) ou l'approche
    # (3 = about). « Avant 1821 » (1), « après » (2) ou un intervalle (4/5) ne
    # désignent aucune année en particulier — les compter reviendrait à
    # fabriquer une concordance à partir d'une borne.
    #
    # CHOIX EXPLICITE sur `quality`, à l'inverse de `_date_iso` : on ne le
    # filtre PAS ici. Une année estimée (1) ou calculée (2) reste un signal
    # FAIBLE acceptable, et pour deux raisons. D'abord, le facteur ne pèse
    # qu'un point et n'est pas fort : il ne peut à lui seul ni faire un `net`
    # ni provoquer un veto, donc l'accepter à tort ne fait pas écrire dans
    # l'arbre. Ensuite, une naissance calculée depuis un âge au décès est
    # précisément le genre de donnée que la fenêtre ±2 de
    # `FENETRE_ANNEE_APPROX` est faite pour absorber — l'écarter reviendrait à
    # jeter le seul indice disponible sur les personnes dont on n'a que l'âge.
    # Le raisonnement de `_date_iso` ne s'applique pas : ce qui y est en jeu,
    # c'est un facteur fort et un veto.
    naissance = person.birth
    if naissance is not None and naissance.modifier in (0, 3):
        annee_arbre = naissance.year
        if (
            releve.naissance_estimee
            and annee_arbre
            and abs(annee_arbre - releve.naissance_estimee) <= FENETRE_ANNEE_APPROX
        ):
            facteurs.append("année approximative")

    parents_arbre = {_normaliser(n) for n in parents_par_handle.get(person.handle, [])}
    parents_releve = {
        _normaliser(pl.nom)
        for pl in releve.personnes_liees
        if pl.role in ("père", "mère")
    }
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


def _verdict_candidat(
    facteurs: list[FacteurReleve], divergences: list[str]
) -> tuple[str, int]:
    """Poids et éligibilité d'UN candidat. La divergence est un veto.

    `facteurs` est typé `FacteurReleve` et non `str`, par cohérence avec
    `facteurs_et_divergences` qui le produit déjà ainsi : c'est le vocabulaire
    fermé, et l'annoter ici fait relever une faute de frappe par le vérificateur
    de types plutôt que par un `KeyError` dans `POIDS` — ou, pire, par un poids
    silencieusement faux.
    """
    if divergences:
        return "aucun", 0
    poids = sum(POIDS[f] for f in facteurs)
    if not (set(facteurs) & FACTEURS_FORTS):
        return "aucun", poids  # un faible ne suffit jamais, même à plusieurs
    return ("net" if poids >= SEUIL_NET else "gris"), poids


class _Evalue(NamedTuple):
    """Un candidat et le résultat de son évaluation.

    Nommé plutôt qu'un 5-uplet indexé : `apparier` est la fonction qui décide
    d'écrire ou non dans l'arbre de quelqu'un, elle doit se relire sans compter
    les positions. `e[4]` ne dit pas qu'on parle des divergences.
    """

    verdict: str
    poids: int
    person: PersonFacts
    facteurs: list[FacteurReleve]
    divergences: list[str]


def apparier(
    releve: ReleveIndexe,
    people: list[PersonFacts],
    rarete: dict[str, float],
    parents_par_handle: dict[str, list[str]],
    lieux_resolus: dict[str, str] | None = None,
) -> Appariement:
    """Le verdict, motivé.

    `lieux_resolus` (lieu brut normalisé → identifiant canonique de commune,
    préfixé par le pays — ex. `"FR:18209"`, `"CH:2701"`, `"DE:06531000"`) est
    construit par l'orchestration et traversé tel quel jusqu'à `_comparer_lieux` :
    c'est ce qui permet de vetoer sur une commune franchement AUTRE sans
    renoncer à la pureté du moteur, qui ne résout toujours rien lui-même.

    `gris` a deux sources distinctes, et il faut les tenir pour telles : c'est
    un effet de seuil quand un candidat unique reste sous `SEUIL_NET`
    (`_verdict_candidat`), et un état EXPLICITE quand plusieurs candidats se
    tiennent à moins de `MARGE_EX_AEQUO` l'un de l'autre — là, aucun poids si
    élevé soit-il ne fait un `net`, parce que le moteur ne sait pas lequel
    choisir et que deviner écrirait dans l'arbre.

    C'est ce qui borne la facture : le nombre de lignes qui partiront au LLM est
    connu avant le moindre appel.
    """
    evalues: list[_Evalue] = []
    for p in candidats_blocage(releve, people):
        facteurs, divergences = facteurs_et_divergences(
            releve, p, rarete, parents_par_handle, lieux_resolus
        )
        verdict, poids = _verdict_candidat(facteurs, divergences)
        evalues.append(_Evalue(verdict, poids, p, facteurs, divergences))

    retenus = [e for e in evalues if e.verdict != "aucun"]
    if not retenus:
        # Chaque divergence est préfixée du `gramps_id` qui l'a produite : sans
        # ça, une liste issue de plusieurs candidats ne dit pas laquelle vient
        # de qui, et le relecteur ne peut pas remonter à la fiche.
        div = [f"{e.person.gramps_id} : {d}" for e in evalues for d in e.divergences]
        if len(evalues) == 1:
            # Un seul candidat écarté : aucune ambiguïté sur qui a été vu, donc
            # on remonte son identité et ce qui concordait chez lui — le
            # relecteur n'a pas à refaire l'analyse pour comprendre le rejet.
            seul = evalues[0]
            return Appariement(
                verdict="aucun",
                gramps_id=seul.person.gramps_id,
                handle=seul.person.handle,
                facteurs=seul.facteurs,
                divergences=div,
            )
        return Appariement(verdict="aucun", divergences=div)

    retenus.sort(key=lambda e: e.poids, reverse=True)
    meilleur = retenus[0]
    # « Comparables », pas « égaux » : tout candidat à moins de MARGE_EX_AEQUO
    # du meilleur reste en lice, et s'ils sont plusieurs le verdict est gris
    # avec la liste COMPLÈTE — le relecteur doit voir le concurrent, pas
    # seulement le gagnant.
    ex_aequo = [e for e in retenus if meilleur.poids - e.poids <= MARGE_EX_AEQUO]

    if len(ex_aequo) > 1:
        return Appariement(
            verdict="gris",
            poids=meilleur.poids,
            facteurs=meilleur.facteurs,
            candidats=[e.person.gramps_id for e in ex_aequo],
        )

    verdict, poids, person, facteurs, _ = meilleur
    return Appariement(
        verdict=verdict,
        gramps_id=person.gramps_id,
        handle=person.handle,
        facteurs=facteurs,
        poids=poids,
        candidats=[person.gramps_id],
    )
