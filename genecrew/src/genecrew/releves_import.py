"""Import d'un relevé collé : interprétation, appariement, écriture.

Le LLM LIT, il ne décide pas : il ne sert qu'à transformer un texte libre en
`ReleveIndexe`. L'appariement — le seul endroit où une erreur écrirait une
fausseté dans l'arbre — est déterministe et vit dans `releves.py`.
"""

from __future__ import annotations

import json
import re
import unicodedata

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachCitationTool,
    GrampsAttachTool,
    GrampsCreateCitationTool,
    GrampsCreateNoteTool,
    GrampsEnsureSourceTool,
    GrampsEnsureTagTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.genealogy.models.domain import PersonFacts

from genecrew.batching import iter_people_batches
from genecrew.crew import build_llm
from genecrew.deces_apply import source_title_for
from genecrew.releves import (
    Appariement,
    ReleveIndexe,
    apparier,
    candidats_blocage,
    rarete_patronymes,
)

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
  evenement_lieu   : la commune de l'événement, sans le département
  naissance_estimee: l'ANNÉE de naissance si elle est approximative, sinon null
  personnes_liees  : [{{"nom": …, "role": "père"|"mère"|"conjoint"|"témoin"|"autre",
                        "detail": …}}]

Règles :
- N'invente rien. Un champ absent du texte vaut "" ou null.
- Une date approximative ("vers 1821") ne va JAMAIS dans evenement_date.
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
    """
    lignes = [
        marqueur_releve(releve.fonds, releve.reference),
        f"Relevé — {releve.fonds}",
        f"Référence : {releve.reference}",
        "",
        f"Appariement : {appariement.verdict.upper()} (poids {appariement.poids})",
        f"  facteurs   : {', '.join(appariement.facteurs) or '—'}",
        f"  divergences: {', '.join(appariement.divergences) or '—'}",
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


def run_import_releve(client: GrampsClient, texte: str, *, llm=None,
                      dry_run: bool = False) -> dict:
    """Interprète, apparie, écrit si le verdict est net. Rend le verdict ET sa raison.

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

    `apparier` est appelé SANS `lieux_resolus` : peupler ce dictionnaire
    demande d'appeler les résolveurs géographiques (réseau), ce qui fera l'objet
    d'un chantier dédié. Sa valeur par défaut est sûre — le moteur retombe sur
    une comparaison de chaînes et ne produit jamais de veto sur un lieu.
    """
    dry_run = effective_dry_run(dry_run)
    releve = parse_releve(texte, llm=llm)
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
    appariement = apparier(releve, people, rarete_patronymes(people),
                           _parents_par_handle(fetcher, people, candidats))
    out = {"releve": releve, "appariement": appariement, "ecrit": False,
           "raison": "", "dry_run": dry_run}

    # Garde de type, AVANT tout le reste : sur un type que le moteur ne compare
    # pas (tout sauf Death/Birth — voir TYPES_EVENEMENT_GERES), aucun facteur
    # d'événement n'est tiré, et pourtant « deux parents nommés » pèse 8 à lui
    # seul, c'est-à-dire exactement SEUIL_NET. Un relevé de mariage peut donc
    # sortir `net` sans qu'on ait jamais regardé le mariage. Écrire là poserait
    # une note sur un type que la chaîne ne sait pas traiter : on refuse, en le
    # disant.
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
    """
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
