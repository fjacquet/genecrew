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

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path


def _candidats(chemin: Path, heure: str) -> Iterator[Path]:
    """Le chemin demandé, puis ses variantes horodatées, indéfiniment.

    L'heure seule ne suffit pas : deux runs bornés peuvent se terminer dans la même
    seconde, d'où le rang qui prend le relais.
    """
    yield chemin
    yield chemin.with_name(f"{chemin.stem}_{heure}{chemin.suffix}")
    rang = 2
    while True:
        yield chemin.with_name(f"{chemin.stem}_{heure}-{rang}{chemin.suffix}")
        rang += 1


def chemin_libre(
    chemin: Path, *, horloge: Callable[[], time.struct_time] | None = None
) -> Path:
    """Réserve un chemin libre et rend celui-ci, vide, prêt à être écrit.

    Le cas courant — premier run de la journée — rend le chemin **inchangé** : pas de
    bruit dans les noms tant qu'il n'y a rien à protéger. L'heure n'apparaît que lorsque
    le fichier existe déjà, c'est-à-dire exactement quand elle devient nécessaire.

    La réservation est **atomique** (`O_CREAT | O_EXCL`) et non un simple `exists()`.
    Regarder puis écrire plus tard laisse une fenêtre pendant laquelle deux runs qui se
    terminent ensemble choisissent le même nom — précisément le dégât que ce module
    existe pour empêcher. Réserver crée donc le fichier, vide, et par conséquent son
    répertoire : décider d'un nom et le tenir ne se séparent pas.

    Un run interrompu entre la réservation et l'écriture laisse un fichier vide. C'est
    voulu : un rapport vide se remarque, un rapport écrasé non.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    heure = time.strftime("%H%M%S", (horloge or time.localtime)())
    for candidat in _candidats(chemin, heure):
        try:
            os.close(os.open(candidat, os.O_CREAT | os.O_EXCL, 0o644))
        except FileExistsError:
            continue
        return candidat
    raise AssertionError("unreachable: `_candidats` est infini")  # pragma: no cover
