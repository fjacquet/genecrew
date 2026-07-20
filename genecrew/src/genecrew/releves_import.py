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

from genecrew.crew import build_llm
from genecrew.releves import ReleveIndexe

TAG_RELEVE = "ia-releve"

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
