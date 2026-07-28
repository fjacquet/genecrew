"""Nommage des rapports : un run n'efface jamais le compte rendu du précédent.

Tous les rapports sont datés au jour (`<date>_<verbe>_<portée>.md`). Deux passages du
même verbe le même jour, sur le même périmètre, visaient donc le même fichier — et le
second gagnait en silence. Mesuré le 2026-07-27 : un `enrich wiki` de 15 lieux a effacé
le compte rendu du run qui venait d'en illustrer 591.

Le dégât ne se limite pas au récit. Les YAML de propositions suivent la même règle de
nommage et sont **relus par un humain puis consommés par `apply`** : les écraser fait
disparaître l'arbitrage qui autorisait l'écriture.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


def chemin_libre(chemin: Path, *, horloge: Callable[[], time.struct_time] | None = None) -> Path:
    """`chemin` s'il est libre, sinon une variante horodatée qui ne l'écrase pas.

    Le cas courant — premier run de la journée — rend le chemin **inchangé** : pas de
    bruit dans les noms tant qu'il n'y a rien à protéger. L'heure n'apparaît que lorsque
    le fichier existe déjà, c'est-à-dire exactement quand elle devient nécessaire pour
    distinguer deux runs.

    L'heure seule ne suffit pas : deux passages bornés peuvent se terminer dans la même
    seconde, d'où le compteur de secours. Ne crée aucun répertoire — décider d'un nom et
    préparer son accueil sont deux responsabilités distinctes.
    """
    if not chemin.exists():
        return chemin
    heure = time.strftime("%H%M%S", (horloge or time.localtime)())
    candidat = chemin.with_name(f"{chemin.stem}_{heure}{chemin.suffix}")
    rang = 2
    while candidat.exists():
        candidat = chemin.with_name(f"{chemin.stem}_{heure}-{rang}{chemin.suffix}")
        rang += 1
    return candidat
