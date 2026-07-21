"""Import d'un relevé collé : interprétation, appariement, écriture.

Le LLM LIT, il ne décide pas : il ne sert qu'à transformer un texte libre en
`ReleveIndexe`. L'appariement — le seul endroit où une erreur écrirait une
fausseté dans l'arbre — est déterministe et vit dans `releves.py`.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.analysis.gender import (
    infer_sex,
    load_prenoms_table,
)
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachCitationTool,
    GrampsAttachTool,
    GrampsCreateCitationTool,
    GrampsCreateNoteTool,
    GrampsEnsureSourceTool,
    GrampsEnsureTagTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.geo.registry import resolve_place
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts, ResolvedPlace
from crewai_custom_tools.tools.genealogy.standardize.places import parse_pname

from genecrew.batching import iter_people_batches
from genecrew.crew import build_llm
from genecrew.deces_apply import source_title_for
from genecrew.lieu_import import run_lieu_import
from genecrew.pistes import _normaliser
from genecrew.releves import (
    Appariement,
    ReleveIndexe,
    _commune,
    _evenement_compare,
    apparier,
    candidats_blocage,
    rarete_patronymes,
)

_LOG = logging.getLogger(__name__)

TAG_RELEVE = "ia-releve"

TAILLE_LOT = 200

TYPES_EVENEMENT_GERES = ("Death", "Birth")
"""Les seuls types que le moteur d'appariement sait comparer.

Miroir explicite de `releves._evenement_compare`, qui rend `None` pour tout
autre type : sur un relevé de mariage, aucun facteur d'ÉVÉNEMENT n'est tiré.
Voir la garde de `run_import_releve` pour ce que ça implique côté écriture.
"""

PROMPT_INTERPRETATION = """Tu interprètes un relevé généalogique copié depuis un site.

Rends UNIQUEMENT un objet JSON, sans commentaire, avec exactement ces clés :
  fonds            : le cercle ou l'organisme qui a fait le relevé
  reference        : le numéro de référence du relevé
  sujet_nom        : le PATRONYME du sujet, en majuscules
  sujet_prenom     : son prénom
  evenement_type   : "Death", "Birth" ou "Marriage"
  evenement_date   : la date de l'événement en ISO AAAA-MM-JJ, "" si absente
  evenement_lieu   : la commune de l'événement, sans le département ni le pays
  evenement_departement : le département/canton/échelon intermédiaire, "" si absent
  evenement_pays   : le PAYS de l'événement, "" si vraiment inconnu
  naissance_estimee: l'ANNÉE de naissance si elle est approximative, sinon null
  personnes_liees  : [{{"nom": …, "role": "père"|"mère"|"conjoint"|"témoin"|"autre",
                        "detail": …}}]

Règles :
- N'invente rien. Un champ absent du texte vaut "" ou null.
- Une date approximative ("vers 1821") ne va JAMAIS dans evenement_date.
- evenement_pays : renseigne-le quand le relevé le dit OU l'implique clairement
  par sa géographie — un département français (« Cher », « Isère ») implique
  "France" ; un canton suisse (« Vaud », « Berne ») implique "Suisse". Mais
  N'INVENTE JAMAIS un pays par DÉFAUT, et surtout PAS « France » : l'arbre
  contient des branches suisses et allemandes, et un défaut français rangerait à
  tort un lieu suisse sous la France — exactement la fausse concordance que le
  contrôle des lieux existe pour empêcher. Si rien n'indique ni n'implique le
  pays, laisse "". La commune (evenement_lieu) reste NUE, sans le pays.
- evenement_departement : recopie l'échelon intermédiaire quand le relevé le donne
  (« Cher », « Vaud »). Il sert à désambiguïser la commune lors de la création du
  lieu ; laisse "" si le relevé ne le mentionne pas. N'en invente pas.
- Les abréviations de relevé se lisent : prts=parents, prop=propriétaire,
  gdre=gendre, bfr=beau-frère, tem=témoin.
  (Cette liste vise les relevés FRANÇAIS — c'est un point de départ, pas une
  couverture complète : l'arbre contient aussi des branches suisses et
  allemandes, dont les relevés ont leurs propres abréviations. Ne pas inventer
  de correspondance pour un sigle absent de cette liste ; une abréviation non
  reconnue doit rester telle quelle plutôt que d'être devinée à tort.)

Le relevé :
---
{texte}
---"""

_BLOC_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_releve(texte: str, llm=None) -> ReleveIndexe:
    """Un appel LLM, un relevé. Le texte brut n'est JAMAIS celui du modèle.

    Le collage réel fait foi : c'est lui qu'on recopiera dans la note, pour que
    la source reste lisible même si l'interprétation a dérapé.
    """
    llm = llm or build_llm("standardisateur")
    brut = llm.call(PROMPT_INTERPRETATION.format(texte=texte))
    trouve = _BLOC_JSON.search(brut or "")
    if not trouve:
        raise ValueError(f"Réponse du modèle sans JSON exploitable : {brut!r}")
    try:
        donnees = json.loads(trouve.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide dans la réponse du modèle : {exc}") from exc
    # Le texte brut recopié dans l'arbre est TOUJOURS le collage réel, jamais
    # une valeur renvoyée par le LLM (même s'il en invente une sous cette clé) :
    # c'est la seule garantie que la source reste vérifiable par un humain.
    donnees["texte_brut"] = texte
    releve = ReleveIndexe.model_validate(donnees)
    # `fonds` et `reference` composent la clé d'idempotence écrite dans la note
    # de l'arbre : f"[genecrew:releve:{code_fonds(fonds)}:{reference}]". Aucun
    # des deux champs n'a de contrainte de longueur côté pydantic — un JSON
    # valide avec l'un des deux vide (ou fait uniquement de blancs) traverse
    # model_validate() sans broncher. Si ça arrivait, la clé dégénérerait en la
    # CONSTANTE "[genecrew:releve::]" : tout autre relevé mal interprété de la
    # même façon produirait le même marqueur, et deja_importe() conclurait à
    # tort « déjà importé » — un relevé réellement distinct serait alors
    # silencieusement sauté, sans erreur ni log. C'est une perte de donnée
    # invisible, le pire mode de défaillance possible ici : mieux vaut refuser
    # bruyamment un relevé mal interprété que le sauter en silence.
    if not releve.fonds.strip():
        raise ValueError(
            "Le fonds est vide ou ne contient que des blancs : un relevé sans "
            "fonds ne peut pas être identifié de façon stable."
        )
    if not releve.reference.strip():
        raise ValueError(
            "La référence est vide ou ne contient que des blancs : un relevé "
            "sans référence ne peut pas être identifié de façon stable."
        )
    return releve


def code_fonds(fonds: str) -> str:
    """Identifiant sobre et stable du fonds, pour le marqueur d'idempotence.

    `fonds` est extrait par un LLM depuis du texte libre : sa ponctuation
    varie d'un appel à l'autre pour la MÊME association. Deux choix
    délibérés en découlent — une revue avait recommandé l'inverse du
    premier, la décision retenue ici va sciemment à son encontre :

    1. Espace et tiret sont traités comme ÉQUIVALENTS (tous deux deviennent
       "-"). Les deux directions d'erreur ne coûtent pas la même chose : si
       on les distingue, la même association orthographiée « Haut-Berry »
       une fois et « Haut Berry » une autre fois produit deux marqueurs
       différents, donc le MÊME relevé est réimporté en double — ce cas est
       PROBABLE, vu la variabilité du LLM. Le risque symétrique — deux
       associations RÉELLEMENT différentes dont les noms ne diffèrent QUE
       par un tiret/espace, ET qui numérotent leurs relevés de façon
       identique — est quasi impossible. Le pouvoir discriminant du
       marqueur vient de `reference` (un identifiant long propre au
       relevé) ; `code_fonds` n'est qu'un espace de noms, pas le
       discriminant.
    2. Toute AUTRE suite de caractères non alphanumériques (apostrophes,
       points, virgules, mais aussi ':' et ']') est purement supprimée,
       sans devenir un nouveau tiret : elle ne porte pas d'information de
       séparation entre mots, contrairement à l'espace et au tiret.
       Bénéfice de sûreté indépendant : ':' et ']' sont justement les
       caractères qui structurent le marqueur
       `[genecrew:releve:<code_fonds>:<reference>]` — s'ils survivaient
       ici, un nom de fonds qui en contient casserait la forme du
       marqueur.

    Le dépouillement des accents se fait AVANT le nettoyage de ponctuation
    (NFD puis suppression des marques combinantes 'Mn'), pour ne pas casser
    les lettres accentuées ou les trémas (branches suisses/allemandes de
    l'arbre) en les traitant comme de la ponctuation à jeter.
    """
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", fonds)
                          if unicodedata.category(c) != "Mn")
    # Ponctuation parasite (apostrophes, points, virgules, ':', ']', …) :
    # supprimée purement, elle ne délimite jamais un mot.
    sans_ponctuation = re.sub(r"[^\w\s-]", "", sans_accent, flags=re.UNICODE)
    # Espace et tiret : seuls séparateurs reconnus, équivalents entre eux.
    morceaux = re.split(r"[\s-]+", sans_ponctuation.lower())
    return "-".join(m for m in morceaux if m)


def marqueur_releve(fonds: str, reference: str) -> str:
    """Marqueur d'idempotence : il porte l'IDENTITÉ, jamais la date.

    Même procédé que les pistes. La référence du relevé est un identifiant
    externe stable — donc pas de clé dérivée ici. Recoller le même relevé
    n'écrit rien.
    """
    return f"[genecrew:releve:{code_fonds(fonds)}:{reference}]"


def corps_note_releve(releve: ReleveIndexe, appariement: Appariement) -> str:
    """Le corps de la note posée sur la personne.

    Deux exigences priment sur la mise en forme :
    - c'est une source DÉRIVÉE (un dépouillement de cercle, pas l'acte d'état
      civil original) — le dire explicitement évite qu'un futur lecteur de
      l'arbre prenne le relevé pour l'acte lui-même ;
    - le texte brut du relevé est recopié INTÉGRALEMENT, pour que la source
      reste vérifiable par un humain quoi qu'il arrive à l'interprétation LLM.
    Le marqueur d'idempotence (`marqueur_releve`) ouvre la note : c'est lui que
    `deja_importe` recherche en tête de note existante.

    Une troisième exigence s'ajoute pour un rattachement FORCÉ (`--person`) :
    `run_import_releve` construit alors `Appariement(verdict="net", facteurs=[])`
    — un « NET (poids 0) / facteurs — » qui, lu des années plus tard, est
    indiscernable d'un bug du moteur. Or un `net` MESURÉ ne peut structurellement
    PAS avoir `facteurs=[]` : `_verdict_candidat` (releves.py) exige qu'au moins
    un facteur FORT soit présent avant même de comparer le poids à `SEUIL_NET` —
    la combinaison (verdict net, facteurs vides) est donc la signature fiable
    d'une décision humaine, jamais d'une mesure. On ne peut pas l'écrire dans
    `Appariement.facteurs` (`Literal` fermé, hors du champ de cette correction),
    alors on l'affirme ici, dans le corps de note, pour que la provenance reste
    lisible directement dans l'arbre sans avoir à déduire quoi que ce soit d'un
    zéro opaque.
    """
    lignes = [
        marqueur_releve(releve.fonds, releve.reference),
        f"Relevé — {releve.fonds}",
        f"Référence : {releve.reference}",
        "",
        f"Appariement : {appariement.verdict.upper()} (poids {appariement.poids})",
        f"  facteurs   : {', '.join(appariement.facteurs) or '—'}",
        f"  divergences: {', '.join(appariement.divergences) or '—'}",
    ]
    if appariement.verdict == "net" and not appariement.facteurs:
        lignes.append(
            "  Rattachement forcé par l'opérateur (option --person) : ce lien "
            "n'est pas le produit d'un appariement mesuré.")
    lignes += [
        "",
        "Source dérivée : un relevé est un dépouillement, pas l'acte original.",
        "",
        "Texte relevé tel que copié :",
        releve.texte_brut.strip(),
    ]
    return "\n".join(lignes)


def deja_importe(client: GrampsClient, gramps_id: str, marqueur: str) -> bool:
    """Ce relevé a-t-il déjà été posé sur cette personne ?

    Un seul appel, pour une personne : filtre serveur sur `gramps_id` et
    `extend=note_list` (même lecture que `pistes.marqueurs_existants`).
    """
    gens = client.get_json("/people/", params={"gramps_id": gramps_id,
                                               "extend": "note_list"}) or []
    if not gens:
        return False
    notes = (gens[0].get("extended") or {}).get("notes") or []
    return any((n.get("text") or {}).get("string", "").startswith(marqueur)
               for n in notes)


def _parents_par_handle(fetcher: FactsFetcher, people: list[PersonFacts],
                        sujets: list[PersonFacts] | None = None,
                        ) -> dict[str, list[str]]:
    """handle → noms complets des parents, pour le facteur « parent nommé ».

    Passe par `get_family_facts` : c'est la FAMILLE qui porte `father_handle` et
    `mother_handle` ; `PersonFacts` ne connaît que les handles de ses familles
    parentales (`parent_family_handles`), jamais l'identité des parents. Le
    fetcher met les familles en cache, donc une famille partagée par une fratrie
    n'est lue qu'une fois.

    Deux listes, deux rôles, et il faut les tenir pour distincts :
    - `sujets` (par défaut : tout `people`) est l'ensemble des personnes DONT on
      indexe les parents. C'est lui qui coûte des requêtes réseau, une par
      famille parentale — d'où l'intérêt de le restreindre aux seuls candidats
      du blocage, les seuls que `apparier` consultera jamais ;
    - `people` reste l'arbre ENTIER, et sert uniquement à retrouver le NOM d'un
      parent depuis son handle. Le restreindre aussi serait un bug : le père
      d'une candidate ne partage pas forcément le patronyme du relevé, donc il
      n'est pas nécessairement candidat lui-même.

    Aucune requête personne supplémentaire n'est faite : un parent absent du lot
    collecté (arbre partiel, borné par `--limit` un jour) est simplement ignoré
    — mieux vaut un facteur non tiré qu'un aller-retour réseau par candidat.

    LIMITE CONNUE — ces « parents » ne sont PAS forcément les parents
    biologiques, malgré ce que le nom du facteur laisse croire.
    `parent_family_list` de Gramps liste TOUTES les familles où la personne
    figure comme enfant, quel que soit le type de lien : biologique, adopté,
    beau-fils/belle-fille, famille d'accueil. Le qualificatif existe côté Gramps
    (dans les `child_ref` de la famille) mais `FamilyFacts` ne le transporte pas,
    donc on ne peut pas filtrer ici sans modifier la bibliothèque voisine.

    Conséquence à connaître avant de faire confiance à un verdict : un parent
    adoptif, ou le nouveau conjoint d'une mère remariée, alimente le facteur
    « deux parents nommés » — lequel pèse 8, soit `SEUIL_NET` à lui seul. Un
    relevé qui nommerait les parents adoptifs peut donc atteindre `net` sur un
    fondement partiellement faux. À revoir le jour où `FamilyFacts` portera le
    type de filiation.

    Construit ici, côté orchestration : le moteur d'appariement le reçoit tout
    fait, ce qui lui permet de rester pur et testable sans réseau.
    """
    par_handle = {p.handle: p for p in people}
    index: dict[str, list[str]] = {}
    for p in (people if sujets is None else sujets):
        noms: list[str] = []
        for fam_handle in p.parent_family_handles:
            famille = fetcher.get_family_facts(fam_handle)
            if famille is None:
                continue
            for parent_handle in (famille.father_handle, famille.mother_handle):
                parent = par_handle.get(parent_handle) if parent_handle else None
                if parent is not None:
                    noms.append(parent.name)
        index[p.handle] = noms
    return index


def _orpheline(raison: str, note_handle: str) -> str:
    """Complète une raison d'échec par le handle de la note restée orpheline.

    Le handle est indispensable : c'est la seule prise qu'un humain aura pour
    retrouver la note dans Gramps et la supprimer.
    """
    return (f"{raison} — note orpheline laissée dans l'arbre "
            f"(handle {note_handle}), à supprimer à la main")


def handle_evenement(client: GrampsClient, gramps_id: str, type_: str) -> str | None:
    """Le handle de l'événement de ce type sur cette personne, s'il existe DÉJÀ.

    `extend=event_ref_list` rend les événements complets en UN appel pour UNE
    personne (gotcha documenté dans CLAUDE.md) : sous `extended.events`, chaque
    événement est un dict dont `type` est une chaîne (même lecture que
    `facts._event_from_raw`, `raw.get("type", "")`) et qui porte son `handle`.

    Rendre `None` n'est PAS un échec : c'est le signal, consommé par
    `ecrire_citation`, qu'aucun événement de ce type n'est dans l'arbre. La
    citation ne pose jamais un événement manquant — elle le rapporte.
    """
    gens = client.get_json("/people/", params={"gramps_id": gramps_id,
                                               "extend": "event_ref_list"}) or []
    if not gens:
        return None
    for ev in (gens[0].get("extended") or {}).get("events") or []:
        if ev.get("type") == type_:
            return ev.get("handle")
    return None


def ecrire_citation(client: GrampsClient, releve: ReleveIndexe,
                    appariement: Appariement, *, dry_run: bool = False) -> dict:
    """Pose la citation du relevé sur l'événement visé. Ne CRÉE jamais l'événement.

    Limite v1 assumée — même posture qu'`apply citations` (ADR 0011) : si
    l'événement du relevé (le décès, la naissance) n'est pas déjà dans l'arbre,
    on le RAPPORTE, on ne le crée pas. Créer un événement est une surface
    d'écriture qui mérite sa propre décision, pas un effet de bord d'un import.
    Le dict rendu le dit explicitement (`posee=False`, raison « absent »).

    ÉCRITURES NON ATOMIQUES — trois appels successifs : garantir la source,
    créer la citation, la rattacher à l'événement. Gramps Web n'offre pas de
    transaction ; un échec en cours de route est RENDU VISIBLE dans le dict
    (`posee=False` + la raison nomme l'étape fautive) plutôt que masqué en
    succès partiel.

    `dry_run` est passé EXPLICITEMENT aux trois outils (comme pour les écritures
    de note/tag) : l'invariant de simulation reste local à chaque appel et ne
    dépend pas de la seule variable d'environnement.
    """
    dry_run = effective_dry_run(dry_run)
    cible = handle_evenement(client, appariement.gramps_id, releve.evenement_type)
    if not cible:
        return {"posee": False,
                "raison": f"événement {releve.evenement_type} absent de l'arbre — "
                          "à créer à la main, l'import ne crée pas d'événement"}

    titre, auteur = source_title_for(f"Relevé — {releve.fonds}")
    source = json.loads(GrampsEnsureSourceTool()._run(
        title=titre, author=auteur, dry_run=dry_run))
    if not source["success"]:
        return {"posee": False, "raison": f"source refusée : {source['error']}"}

    # Confiance Gramps `Normal` (entier 2), JAMAIS `High` : un relevé de cercle
    # est un dépouillement, une source DÉRIVÉE — pas l'acte original. Le marquer
    # plus haut ferait passer un relevé pour un acte d'état civil. La valeur 2 est
    # confirmée contre `GrampsCreateCitationTool`, qui plafonne d'ailleurs à 2.
    citation = json.loads(GrampsCreateCitationTool()._run(
        source_handle=source["data"]["handle"],
        page=f"Relevé n° {releve.reference}",
        confidence=2,
        dry_run=dry_run))
    if not citation["success"]:
        return {"posee": False, "raison": f"citation refusée : {citation['error']}"}

    # `object_type="events"` au PLURIEL : l'outil fait `GET/PUT /{object_type}/…`
    # et l'endpoint réel de Gramps Web est `/api/events/<handle>`. Un singulier
    # « event » viserait `/event/<handle>` (404) — écriture inopérante.
    attache = json.loads(GrampsAttachCitationTool()._run(
        object_type="events", handle=cible,
        citation_handle=citation["data"]["handle"], dry_run=dry_run))
    if not attache["success"]:
        return {"posee": False, "raison": f"rattachement refusé : {attache['error']}"}
    return {"posee": True, "raison": "citation posée"}


def handle_personne(client: GrampsClient, gramps_id: str) -> str | None:
    """Le handle de la personne DÉSIGNÉE par son gramps_id, ou None si elle n'existe pas.

    Sert le forçage par `--person`. Le principe qui prime : `--person` force QUI
    on rattache, JAMAIS le DROIT d'écrire. Court-circuiter le blocage et la
    pondération est légitime (c'est comme ça qu'on tranche un `gris`), mais poser
    une note sur un gramps_id qui n'existe pas serait un écrit dans le vide — on
    vérifie donc l'existence AVANT de construire quoi que ce soit dessus.

    Un seul appel, même patron de lecture que `deja_importe` / `handle_evenement` :
    filtre serveur sur `gramps_id`. Le handle est indispensable — c'est lui, pas
    l'ID, que le rattachement (`GrampsAttachTool`) consomme.
    """
    gens = client.get_json("/people/", params={"gramps_id": gramps_id}) or []
    if not gens:
        return None
    return gens[0].get("handle")


_PREFIXES_PAYS: dict[str, str] = {
    "France": "FR",
    "Allemagne": "DE",
    "États-Unis": "US",
    "Suisse": "CH",
}

_TYPES_COMMUNE: frozenset[str] = frozenset({"Municipality", "City"})
"""Les seuls `place_type` que la bibliothèque géographique rend pour une COMMUNE.

« Municipality » côté France/Allemagne/Suisse/Nominatim, « City » côté USA. Tout
autre type (Department, Region, State…) désigne un échelon plus large : son code
serait INCOMPARABLE à celui d'une commune (voir le contrat de granularité de
`code_commune_prefixe`).
"""


def _raw_lieu(releve: ReleveIndexe) -> str:
    """« commune, département, pays » pour la CASCADE de création de lieux.

    C'est l'entrée de `run_lieu_import` (donc de `parse_pname`/`resolve_place`),
    pas une clé d'appariement : on assemble ici la chaîne QUALIFIÉE que le
    résolveur géographique attend, en sautant les échelons vides. Sans commune il
    n'y a rien à résoudre — on rend "" pour que la cascade ne parte pas sur un
    « Cher, France » qui résoudrait le département comme s'il était une commune.
    """
    commune = (releve.evenement_lieu or "").strip()
    if not commune:
        return ""
    echelons = [commune, (releve.evenement_departement or "").strip(),
                (releve.evenement_pays or "").strip()]
    return ", ".join(e for e in echelons if e)


_TABLE_PRENOMS: dict | None = None

SEUIL_GENRE = 0.98
"""Ratio minimal pour poser un genre sur un sujet CRÉÉ.

Même exigence que `apply gender` : sous ce seuil le prénom est trop ambigu pour
trancher, on laisse Inconnu (U) plutôt que d'inscrire un fait douteux. Le genre
reste réversible, mais on ne le pose pas à la légère.
"""


def _table_prenoms() -> dict:
    """Table INSEE+OFS des prénoms, chargée une fois (coûteuse) et mémorisée."""
    global _TABLE_PRENOMS
    if _TABLE_PRENOMS is None:
        _TABLE_PRENOMS = load_prenoms_table()
    return _TABLE_PRENOMS


def genre_infere(prenom: str) -> int:
    """Genre Gramps (0=F, 1=M, 2=U) inféré du prénom, U hors table ou sous le seuil.

    Réutilise l'inférence de `propose gender` (table INSEE+OFS). On ne pose F/M que
    si le ratio franchit `SEUIL_GENRE` ; sinon Inconnu — cohérent avec l'asymétrie
    de tout l'import : on crée du réversible, jamais un fait tranché sans base.
    """
    inf = infer_sex(prenom or "", _table_prenoms())
    if inf.sex and inf.ratio >= SEUIL_GENRE:
        return 0 if inf.sex == "F" else 1
    return 2


def resoudre_ou_creer_lieu(client: GrampsClient, releve: ReleveIndexe, *,
                           dry_run: bool = False) -> str | None:
    """Handle du lieu de l'événement, créé en cascade si absent ; None si non résolu.

    Délègue à `run_lieu_import` (mêmes résolveurs que `propose places`) sur la chaîne
    qualifiée `_raw_lieu`. Rend le handle de la feuille quand la résolution autorise
    l'écriture (créée OU déjà présente), sinon None : commune absente, résolution
    ambiguë ou score sous le seuil. Un None fait poser l'événement SANS lieu (rapporté)
    — jamais un lieu faux. En dry-run le handle rendu est synthétique (`DRYRUN:…`),
    que `GrampsCreateEventTool` ignore de toute façon.
    """
    raw = _raw_lieu(releve)
    if not raw:
        return None
    out = run_lieu_import(client, raw, dry_run=dry_run)
    return out.get("handle")


def _prefixe_pays(country: str) -> str | None:
    """Le préfixe pays d'un code de commune, ou None hors des pays connus.

    `country` est le label normalisé de `parse_pname(...).country` (« France »,
    « Suisse », « Allemagne », « États-Unis »). Ce préfixe empêche un code
    français de se confondre avec un code étranger de même numéro : un INSEE
    `18209` et un numéro OFS suisse `18209` sont deux chaînes ÉGALES sans être la
    même commune — sans préfixe, le moteur y verrait une concordance et écrirait
    une fausseté. Tout pays hors table (chaîne vide, « Italie »…) rend None.
    """
    return _PREFIXES_PAYS.get(country)


def code_commune_prefixe(country: str, resolved: ResolvedPlace | None) -> str | None:
    """« <PREFIXE>:<code> » d'une commune résolue, ou None si le moindre doute.

    `country` est le label issu de `parse_pname(...).country`. On ne rend un code
    QUE si TOUT tient : une résolution non nulle et non ambiguë, un `place_type`
    qui est bien celui d'une COMMUNE (contrat de granularité — un lieu résolu au
    département ou au hameau donnerait un code incomparable à une commune, donc un
    veto sur une ABSENCE et non sur une contradiction), un code non vide, et un
    pays dont on connaît le préfixe.

    Le pourquoi de cette prudence est une ASYMÉTRIE des coûts d'erreur. Une entrée
    ABSENTE de `lieux_resolus` est sûre : `_comparer_lieux` retombe sur l'égalité
    de chaîne et ne produit jamais de veto. Une entrée FAUSSE, elle, produit un
    veto faux — et un candidat vetoé ne revient JAMAIS devant le relecteur humain.
    Dans le doute, on n'ajoute donc RIEN : on ne peuple `lieux_resolus` que de ce
    qu'on sait démontrablement être une commune.
    """
    if resolved is None or resolved.ambiguous:
        return None
    if resolved.place_type not in _TYPES_COMMUNE:
        return None
    if not resolved.code:
        return None
    prefixe = _prefixe_pays(country)
    if prefixe is None:
        return None
    return f"{prefixe}:{resolved.code}"


def construire_lieux_resolus(
    lieux: dict[str, str],
    resolveur: Callable[[str], ResolvedPlace | None] | None = None,
) -> dict[str, str]:
    """Construit le dictionnaire `lieux_resolus` que le moteur d'appariement lit.

    Le paramètre est un dict `{clé_nue: chaîne_de_résolution}`, et cette
    DISSOCIATION est le cœur de la correction du veto. Le moteur (`_comparer_lieux`)
    cherche ses codes par la commune NUE — `_normaliser(releve.evenement_lieu)`
    d'un côté, `_normaliser(_commune(ev))` de l'autre — donc la CLÉ du dict rendu
    DOIT rester la commune nue. Mais une commune nue ne porte pas de pays :
    `parse_pname` en tirerait `country=''`, `code_commune_prefixe` rendrait None,
    et le veto resterait inerte (le défaut historique). On envoie donc au résolveur
    une chaîne QUALIFIÉE (commune + pays côté relevé, hiérarchie complète de l'arbre
    côté candidat), seule à porter le pays — tout en gardant la clé nue.

    Pour chaque paire, on lit le pays par `parse_pname(chaîne)` (pur) et on demande
    la résolution de la même `chaîne` au `resolveur` (réseau, INJECTÉ pour la
    testabilité — le défaut appelle le vrai registre géographique). Le code n'est
    retenu que s'il passe `code_commune_prefixe` (asymétrie : absent = sûr, faux =
    veto faux). La clé du dict rendu est `_normaliser(clé_nue)` IMPÉRATIVEMENT : une
    clé posée autrement ne matcherait jamais, et le veto serait silencieusement
    inerte.

    ROBUSTESSE : chaque résolution est enveloppée dans un try/except large. Une
    exception réseau (timeout, 429 du limiteur de débit) sur UN lieu le fait
    SAUTER — journalisée en warning — sans jamais avorter l'import : perdre un
    code fait retomber ce lieu sur l'égalité de chaîne (sûr), avorter l'import
    perdrait tout.
    """
    if resolveur is None:
        resolveur = lambda chaine: resolve_place(parse_pname(chaine))  # noqa: E731
    resultat: dict[str, str] = {}
    for cle_nue, chaine in lieux.items():
        if not cle_nue or not cle_nue.strip():
            continue
        if not chaine or not chaine.strip():
            continue
        try:
            parsed = parse_pname(chaine)
            resolved = resolveur(chaine)
        except Exception as exc:  # réseau : timeout, 429… — on saute ce lieu
            _LOG.warning("Résolution du lieu %r ignorée (%s)", chaine, exc)
            continue
        code = code_commune_prefixe(parsed.country, resolved)
        if code:
            resultat[_normaliser(cle_nue)] = code
    return resultat


def run_import_releve(client: GrampsClient, texte: str, *, llm=None,
                      dry_run: bool = False, person: str | None = None,
                      resolveur_lieux: Callable[[str], ResolvedPlace | None] | None = None,
                      ) -> dict:
    """Interprète, apparie, écrit si le verdict est net. Rend le verdict ET sa raison.

    `person` (un gramps_id) est le forçage manuel de `--person` : le propriétaire
    de l'arbre a lu les candidats d'un `gris` et désigne le bon. Ce forçage
    court-circuite l'appariement — le blocage et la pondération — mais SURTOUT
    PAS les gardes de sûreté : `--person` force QUI on rattache, jamais le DROIT
    d'écrire. Un import forcé passe donc, comme le chemin normal, par l'existence
    de la personne, la garde de type d'événement, l'idempotence et la simulation
    par défaut, et REJOINT le même chemin d'écriture (il ne le duplique pas).

    Le dict rendu porte toujours les cinq mêmes clés (`releve`, `appariement`,
    `ecrit`, `raison`, `dry_run`) : l'appelant n'a jamais à deviner pourquoi
    rien n'a été écrit, et c'est ce qui rendra les verdicts lisibles en lot
    avant qu'un humain lâche la main.

    ÉCRITURES NON ATOMIQUES — l'écriture se fait en trois appels successifs :
    création de la note, garantie du tag, rattachement des deux à la personne.
    Gramps Web n'offre pas de transaction qui les couvrirait, donc un échec au
    deuxième ou au troisième laisse la note DÉJÀ CRÉÉE, non rattachée : une
    orpheline.

    L'ordre reste celui-là à dessein, parce que le sens de l'échec est correct.
    `deja_importe` lit les notes DE LA PERSONNE ; le marqueur n'y étant pas, un
    nouveau passage réessaiera l'import au lieu de le sauter — ce qui est le bon
    comportement, l'annotation n'ayant jamais atteint la personne. Le prix est
    qu'un deuxième passage qui échouerait au même endroit ajouterait une
    deuxième orpheline.

    Ce n'est donc pas rattrapé, c'est rendu VISIBLE : dans ce cas la `raison`
    nomme explicitement l'orpheline et donne son handle, seule prise permettant
    à un humain de la retrouver et de la supprimer. Un nettoyage automatique
    demanderait un DELETE — la chaîne d'import est délibérément append-only et
    ne détruit rien.

    `apparier` reçoit un `lieux_resolus` peuplé par `construire_lieux_resolus` :
    c'est ce qui ACTIVE le veto sur les lieux (une commune franchement AUTRE
    écarte le candidat). Le coût réseau est borné aux CANDIDATS du blocage, pas à
    l'arbre — voir plus bas. `resolveur_lieux` n'existe que pour la testabilité :
    None (le défaut) déclenche la résolution réseau réelle ; un stub permet aux
    tests d'injecter des codes sans réseau.
    """
    dry_run = effective_dry_run(dry_run)
    releve = parse_releve(texte, llm=llm)

    if person is not None:
        # Chemin FORCÉ. On ne charge pas l'arbre entier : ni la rareté des
        # patronymes ni la pondération n'ont de sens quand un humain a déjà
        # tranché QUI. On vérifie seulement que la personne désignée EXISTE —
        # forcer QUI n'autorise pas à écrire dans le vide (voir handle_personne).
        handle = handle_personne(client, person)
        if not handle:
            return {"releve": releve, "appariement": None, "ecrit": False,
                    "raison": f"personne {person} introuvable", "dry_run": dry_run}
        # On REMPLACE le résultat de l'appariement par un `net` ciblé, puis on
        # rejoint le chemin d'écriture commun. `facteurs` reste vide : ce net ne
        # vient d'aucun facteur mesuré mais d'une décision humaine — la note le
        # dira honnêtement (« poids 0 », facteurs « — »).
        appariement = Appariement(verdict="net", gramps_id=person, handle=handle,
                                  facteurs=[])
    else:
        fetcher = FactsFetcher(client)
        # `iter_people_batches` pagine réellement : on aplatit, l'appariement a
        # besoin de l'arbre ENTIER (la rareté des patronymes est mesurée dessus,
        # et un candidat manquant ferait conclure « absent de l'arbre »).
        people = [p for lot in iter_people_batches(client, fetcher, "all", TAILLE_LOT, None)
                  for p in lot]
        # L'index parental ne se construit que pour les CANDIDATS du blocage : c'est
        # la seule chose que `apparier` en consultera, et chaque personne indexée
        # coûte une requête `/families/` par famille parentale. Sur l'arbre entier
        # (~2 100 personnes) c'était ~1 000 requêtes par relevé importé, pour n'en
        # servir qu'une poignée — assez pour réveiller le limiteur de débit Redis de
        # Gramps Web, et `get_family_facts` n'avale que les 404 : un 429 avorterait
        # l'import. `candidats_blocage` est pure et refaite à l'identique par
        # `apparier`, donc le verdict est inchangé.
        candidats = candidats_blocage(releve, people)
        # On ACTIVE le veto sur les lieux : le lieu du relevé et la commune de
        # chaque candidat sont résolus en code de commune, et une divergence de
        # code écarte le candidat. Le coût réseau est borné aux CANDIDATS du
        # blocage (pas à l'arbre entier) — les seuls lieux que `apparier`
        # comparera jamais.
        #
        # DEUX CÔTÉS, DEUX MÉCANISMES, une seule règle : CLÉ = commune NUE (ce que
        # le moteur cherche), CHAÎNE DE RÉSOLUTION = qualifiée (seule à porter le
        # pays que `parse_pname` lira). Sans cette dissociation, une commune nue
        # rend `country=''` et le veto reste inerte (le défaut historique).
        #  - Côté relevé : la commune est nue par construction (le prompt l'exige),
        #    le pays vient du champ `evenement_pays` extrait par le LLM. La chaîne
        #    de résolution est « commune, pays » quand le pays est connu, sinon la
        #    commune seule (qui ne résoudra pas → repli sûr sur l'égalité de chaîne,
        #    aucun veto sur une absence).
        #  - Côté candidat : `ev.place` porte la hiérarchie complète de l'arbre
        #    (« Saint-Martin-d'Auxigny, Cher, France »), donnée autoritaire de
        #    Gramps où `parse_pname` lira le pays ; la clé reste la commune nue de
        #    `_commune(ev)`. On se rabat sur la commune nue si `ev.place` est vide.
        lieux: dict[str, str] = {}
        pays = releve.evenement_pays.strip()
        if releve.evenement_lieu and releve.evenement_lieu.strip():
            lieux[releve.evenement_lieu] = (
                f"{releve.evenement_lieu}, {pays}" if pays else releve.evenement_lieu)
        for c in candidats:
            ev = _evenement_compare(c, releve.evenement_type)
            commune = _commune(ev)
            if commune and commune.strip():
                lieux[commune] = ev.place if (ev and ev.place) else commune
        lieux_resolus = construire_lieux_resolus(lieux, resolveur_lieux)
        appariement = apparier(releve, people, rarete_patronymes(people),
                               _parents_par_handle(fetcher, people, candidats),
                               lieux_resolus=lieux_resolus)

    out = {"releve": releve, "appariement": appariement, "ecrit": False,
           "raison": "", "dry_run": dry_run}

    # Garde de type, AVANT tout le reste et POUR LES DEUX CHEMINS (apparié comme
    # forcé) : sur un type que le moteur ne compare pas (tout sauf Death/Birth —
    # voir TYPES_EVENEMENT_GERES), aucun facteur d'événement n'est tiré, et
    # pourtant « deux parents nommés » pèse 8 à lui seul, c'est-à-dire exactement
    # SEUIL_NET. Un relevé de mariage peut donc sortir `net` sans qu'on ait jamais
    # regardé le mariage — et un `--person` forcerait ce net directement. Écrire là
    # poserait une note sur un type que la chaîne ne sait pas traiter : on refuse,
    # en le disant. C'est ici que se prouve que `--person` force QUI, pas le DROIT
    # d'écrire.
    if releve.evenement_type not in TYPES_EVENEMENT_GERES:
        out["raison"] = (
            f"type d'événement non géré : {releve.evenement_type} "
            f"(seuls {', '.join(TYPES_EVENEMENT_GERES)} sont comparés)")
        return out

    if appariement.verdict == "gris":
        out["raison"] = "gris — relecture requise"
        return out
    if appariement.verdict == "aucun":
        out["raison"] = "aucun candidat — création du sujet différée"
        return out

    marqueur = marqueur_releve(releve.fonds, releve.reference)
    if deja_importe(client, appariement.gramps_id, marqueur):
        out["raison"] = "déjà importée"
        return out
    if dry_run:
        out["raison"] = "simulation"
        return out

    # `dry_run` est passé EXPLICITEMENT aux trois outils. La garde ci-dessus le
    # rend redondant aujourd'hui, mais elle est distante : sans cet argument, un
    # outil ne consulterait que `GENECREW_DRY_RUN` et un appel
    # `run_import_releve(dry_run=True)` sous `GENECREW_DRY_RUN=false` écrirait
    # pour de bon si la garde venait à bouger. L'invariant reste local.
    note = json.loads(GrampsCreateNoteTool()._run(
        text=corps_note_releve(releve, appariement), note_type="Research",
        dry_run=dry_run))
    if not note["success"]:
        out["raison"] = f"note refusée : {note['error']}"
        return out
    # À partir d'ici la note EXISTE dans l'arbre. Tout échec ultérieur la laisse
    # orpheline : `_orpheline` le dit, avec son handle, pour qu'un humain la
    # retrouve. Voir la docstring pour pourquoi l'ordre n'est pas changé.
    note_handle = note["data"]["handle"]
    tag = json.loads(GrampsEnsureTagTool()._run(name=TAG_RELEVE, dry_run=dry_run))
    if not tag["success"]:
        out["raison"] = _orpheline(f"tag refusé : {tag['error']}", note_handle)
        return out
    attache = json.loads(GrampsAttachTool()._run(
        handle=appariement.handle, note_handle=note_handle,
        tag_handle=tag["data"]["handle"], dry_run=dry_run))
    if not attache["success"]:
        out["raison"] = _orpheline(
            f"rattachement refusé : {attache['error']}", note_handle)
        return out

    # La citation vient APRÈS le rattachement de la note/tag : c'est un ajout, pas
    # une condition du succès de l'import. Elle ne se pose que sur un événement
    # EXISTANT (voir `ecrire_citation`) — quand l'événement manque, l'import reste
    # « écrit » mais la raison le dit, pour que l'opérateur voie la citation
    # manquante sans avoir à fouiller le dict.
    citation = ecrire_citation(client, releve, appariement, dry_run=dry_run)
    out["citation"] = citation

    out["ecrit"] = True
    out["raison"] = ("importée" if citation["posee"]
                     else f"importée sans citation ({citation['raison']})")
    return out


def format_import_releve(resultat: dict) -> str:
    """Rapport lisible d'un import. Le mode affiché est le mode EFFECTIF.

    On lit `resultat["dry_run"]` (le dry-run que `run_import_releve` a réellement
    appliqué, env inclus), jamais le dry-run demandé : un rapport ne doit jamais
    annoncer une écriture qui n'a pas eu lieu.

    `resultat["appariement"]` peut valoir `None` — UN SEUL cas : `--person`
    désigne un `gramps_id` ABSENT de l'arbre (voir `handle_personne` /
    `run_import_releve`). C'est un refus gracieux, pas un appariement raté —
    il n'y a donc rien à décrire côté `Appariement`. `releve_import_cmd`
    (main.py) appelle TOUJOURS cette fonction, y compris sur ce refus : sans
    cette garde, le parcours nominal — qui invite justement l'utilisateur à
    relancer avec `--person <ID>` sur un verdict gris — plante dès que l'ID
    saisi est mauvais, au lieu d'afficher la `raison` déjà calculée par
    `run_import_releve`.
    """
    if resultat["appariement"] is None:
        releve = resultat["releve"]
        return "\n".join([
            f"Relevé {releve.reference} — {releve.fonds}",
            f"Sujet : {releve.sujet_prenom} {releve.sujet_nom} "
            f"({releve.evenement_type} {releve.evenement_date or 'sans date'})",
            "",
            f"Résultat : non écrit ({resultat['raison']})",
        ])
    releve, app = resultat["releve"], resultat["appariement"]
    mode = ("simulation (dry-run, aucune écriture)" if resultat["dry_run"]
            else "écritures appliquées")
    lignes = [
        f"Relevé {releve.reference} — {releve.fonds}",
        f"Sujet : {releve.sujet_prenom} {releve.sujet_nom} "
        f"({releve.evenement_type} {releve.evenement_date or 'sans date'})",
        f"Mode : {mode}",
        "",
        f"Verdict : {app.verdict.upper()} (poids {app.poids})",
        f"  facteurs    : {', '.join(app.facteurs) or '—'}",
        f"  divergences : {', '.join(app.divergences) or '—'}",
        f"  candidats   : {', '.join(app.candidats) or '—'}",
        "",
        f"Résultat : {'écrit' if resultat['ecrit'] else 'non écrit'} "
        f"({resultat['raison']})",
    ]
    if app.verdict == "gris":
        lignes += ["", "Relis les candidats, puis relance en désignant le bon :",
                   "  genecrew import releve --file <fichier> --person <ID>"]
    return "\n".join(lignes)
