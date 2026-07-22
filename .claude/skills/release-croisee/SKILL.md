---
name: release-croisee
description: Publie une version de crewai_custom_tools et aligne genecrew dessus, dans l'ordre que la CI impose. Utiliser quand un changement de bibliothèque doit devenir consommable par genecrew.
disable-model-invocation: true
---

# Publier la bibliothèque et aligner genecrew

La CI de genecrew checkoute la bibliothèque sur le **tag** `v<version>` lu dans `uv.lock`, pas sur
`main`. Un travail fusionné mais non tagué est donc invisible pour elle, et l'échec se présente comme
un `uv sync --locked` qui refuse le lock — très loin de sa cause.

Cette friction est **délibérée** : c'est un contrôle qualité. Ne propose jamais de la supprimer.

## Les trois manières de se tromper, toutes observées

1. **Oublier `__version__`.** La version vit à deux endroits, `pyproject.toml` et
   `src/crewai_custom_tools/__init__.py`. Bumper l'un sans l'autre fait rougir la CI sur
   `test_version_matches_pyproject`. Un hook du projet le détecte désormais, mais vérifie quand même.
2. **Taguer un commit qui ne contient pas le travail.** Un tag posé sur une branche avant sa fusion ne
   contient pas ce qui a été fusionné après. C'est arrivé : `v0.24.0` pointait dans une branche
   latérale, et une CI qui l'aurait résolu aurait récupéré une bibliothèque amputée.
3. **Lancer les tests avant le bump et annoncer le résultat après.** Une suite verte mesurée avant le
   changement de version ne dit rien sur l'état publié.

## Séquence

1. **Vérifier l'accord des deux versions**, dans le worktree de la bibliothèque :

```bash
grep -m1 '^version' pyproject.toml && grep -m1 '__version__' src/crewai_custom_tools/__init__.py
```

2. **Vérifier qu'aucun tag ne prend déjà le numéro visé**, et où il pointe :

```bash
git fetch --tags origin && git tag -l 'v*' --sort=-creatordate | head -5
```

Si le numéro est pris par un autre travail — une session concurrente, par exemple — **ne déplace pas
le tag publié** : prends le numéro suivant. Un tag résolu par un consommateur ne doit jamais changer
de contenu.

3. **Compléter le journal** (`CHANGELOG.md`), en disant les décisions et leurs raisons, pas seulement
   les fichiers touchés.

4. **Lancer la suite complète APRÈS le bump**, jamais avant :

```bash
uv run python -m pytest tests/ -q && uv run ruff check .
```

5. **Pousser la branche, ouvrir la PR, attendre la CI.** Ne fusionne pas sur une CI incomplète : lint
   vert et tests en cours n'est pas un feu vert.

6. **Fusionner, puis taguer le commit de fusion** — pas la tête de la branche. Le dépôt exige des tags
   annotés :

```bash
git fetch origin && git tag -a v<version> <sha-de-la-fusion> -m "<version> — <résumé>"
git push origin v<version>
```

7. **Aligner genecrew** depuis son worktree :

```bash
uv sync
uv run python -c "import importlib.metadata as m; print(m.version('crewai-custom-tools'))"
grep -A2 'name = "crewai-custom-tools"' uv.lock | head -3
uv run python -m pytest genecrew/tests/ -q
```

Puis commiter `uv.lock` avec un message qui dit **pourquoi** cette version est nécessaire.

## Garde-fou

Un agent ne fusionne, ne pousse ni ne tague **sans demande explicite de l'humain**. Cette compétence
décrit la séquence ; elle n'autorise pas à l'exécuter d'office.
