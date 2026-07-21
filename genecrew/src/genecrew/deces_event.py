"""`apply deaths` — création d'événements décès sourcés depuis un YAML relu.

La v2 de l'ADR 0011 : là où `apply citations` pose une citation sur un décès qui
existe déjà (`type: source`), cette commande écrit le décès ABSENT de l'arbre
(`type: date`). Elle crée donc une donnée cœur, ce que l'ADR 0011 s'interdisait —
voir l'ADR 0014 pour ce que ça relâche et ce qui l'encadre.

L'écriture elle-même est déléguée à `evenements.creer_evenement_source` ; ce module
tient le filtre, la résolution de lieu, l'orchestration et le rapport.
"""

from __future__ import annotations

import re
import unicodedata

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient

TAG_DECES = "genecrew:deces"


def normaliser_lieu(nom: str) -> str:
    """Nom de commune → clé de comparaison : sans accents, minuscule, séparateurs unifiés.

    « Nohant-en-Goût », « nohant en gout » et « NOHANT-EN-GOUT » désignent la même
    commune ; l'INSEE et l'arbre ne les écrivent pas pareil.
    """
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", nom or "")
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-']+", " ", sans_accents).strip().lower()


def index_lieux(client: GrampsClient) -> dict[str, str | None]:
    """Index `{nom normalisé -> handle}` des lieux de l'arbre ; `None` si homonymes.

    Le `None` est porteur d'information : il distingue l'AMBIGU (clé présente, valeur
    None) de l'INCONNU (clé absente). Les deux mènent au même geste — un événement sans
    lieu — mais pas au même diagnostic dans le rapport.
    """
    index: dict[str, str | None] = {}
    page = 1
    while True:
        batch = client.get_json("/places/", params={"page": page, "pagesize": 200})
        if not batch:
            break
        for place in batch:
            if not isinstance(place, dict):
                continue
            cle = normaliser_lieu((place.get("name") or {}).get("value", ""))
            if not cle:
                continue
            # Deuxième occurrence (ou plus) du même nom : on écrase par None. Choisir
            # au hasard rattacherait un décès à la mauvaise commune, en silence.
            index[cle] = None if cle in index else place.get("handle")
        page += 1
    return index


def resoudre_lieu(index: dict[str, str | None], nom: str) -> str | None:
    """Handle du lieu nommé, ou None s'il est inconnu ou ambigu. Pur."""
    return index.get(normaliser_lieu(nom))
