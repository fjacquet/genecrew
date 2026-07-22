---
name: etat-des-branches
description: Inventorie ce qui dort hors de main dans genecrew et crewai_custom_tools — branches non fusionnées, commits non poussés, tags qui ne pointent pas sur main. Utiliser en début de session, ou avant de publier.
disable-model-invocation: true
---

# Ce qui dort hors de `main`

Ces deux dépôts sont travaillés par plusieurs sessions en parallèle, sur des clones partagés. Une
session peut changer la branche du clone sous les pieds d'une autre, et du travail fini peut rester
invisible pendant des jours.

Relevé réel d'une seule matinée : **trois chantiers terminés** dormaient hors de `main` — un paquet
complet dans la bibliothèque, un commit de modèle dont dépendait genecrew sans que personne ne le
sache, et vingt-trois commits jamais poussés implémentant une commande que le `CLAUDE.md` documentait
déjà comme livrée. Un tag de version pointait par ailleurs sur un commit ne contenant pas le travail
qu'on croyait publier.

## Inventaire

Pour **chacun** des deux dépôts — `.` et le voisin `../crewai_custom_tools` (ou le worktree
correspondant) :

```bash
git fetch -q --tags origin

echo "=== branche courante et HEAD"
git branch --show-current && git log --oneline -1

echo "=== branches non fusionnées dans main"
for b in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
  n=$(git rev-list --count origin/main.."$b" 2>/dev/null) || continue
  [ "$n" -gt 0 ] && echo "$b : $n commits d'avance"
done

echo "=== branches locales jamais poussées"
git for-each-ref --format='%(refname:short) %(upstream)' refs/heads/ | awk '$2 == "" {print $1}'

echo "=== tags qui ne pointent pas dans main"
for t in $(git tag -l 'v*'); do
  git merge-base --is-ancestor "$t^{commit}" origin/main 2>/dev/null || echo "$t hors de main"
done

echo "=== version déclarée sur main contre dernier tag"
git show origin/main:pyproject.toml | grep -m1 '^version'
git tag -l 'v*' --sort=-creatordate | head -1
```

## Comment lire le résultat

- **Branche non fusionnée avec beaucoup de commits** : regarde si ses derniers commits sont des
  correctifs de relecture et de la documentation. C'est la signature d'un travail *fini* qui attend,
  pas d'un travail en cours. Vérifie aussi si le `CLAUDE.md` ou un ADR documente déjà la
  fonctionnalité : si oui, la documentation ment tant que la branche n'est pas entrée.
- **Trou dans la numérotation des ADR** : `docs/adr/` doit être continu. Un saut signale une décision
  écrite sur une branche non fusionnée.
- **Tag hors de `main`** : le contenu publié sous ce numéro n'est pas celui de `main`. Ne déplace pas
  le tag — prends le numéro suivant.
- **Version de `main` égale au dernier tag alors que `main` a avancé depuis** : le tag ne contient pas
  tout ce que la version annonce.

## Garde-fou

Cette compétence **inventorie**, elle ne fusionne rien. Toute fusion, poussée ou pose de tag demande
une décision humaine explicite.
