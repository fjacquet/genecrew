# CI/CD et publication de la documentation sur GitHub Pages

**Date** : 2026-07-20
**Statut** : validé, prêt pour plan d'implémentation

## Problème

Le dépôt n'a **aucune CI** : pas de `.github/`. Les 161 tests et `ruff` ne tournent que
lorsqu'on pense à les lancer à la main. Sur le chantier CLI qui vient de s'achever, chaque
vérification a été déclenchée manuellement — et une PR a été ouverte sur une base périmée
sans que rien ne le signale.

La documentation (README, guide utilisateur, 12 ADR) n'est lisible que dans le dépôt, en
Markdown brut. Le dépôt est **public** et GitHub Pages y est déjà activé en mode workflow
(`https://fjacquet.github.io/genecrew/`), sans qu'aucun workflow ne publie quoi que ce soit.

### L'obstacle qui structure tout

```toml
[tool.uv.sources]
crewai-custom-tools = { path = "../crewai_custom_tools", editable = true }
```

`crewai-custom-tools` **n'est pas sur PyPI** (404 vérifié) ; elle vit sur GitHub
(`fjacquet/crewai-custom-tools`). Et `uv.lock` verrouille le **chemin relatif** :

```
source = { editable = "../crewai_custom_tools" }
```

Un runner GitHub n'a pas de dépôt voisin : sans traitement, `uv sync` échoue à la première
seconde. Deux issues étaient possibles :

- remplacer la source par une URL git dans `pyproject.toml` — impose de reverrouiller **et**
  supprime l'édition locale en parallèle des deux dépôts, sur laquelle le flux de travail
  repose (`CLAUDE.md` : « After bumping the library version, run `uv sync` ») ;
- **cloner le dépôt voisin dans le runner, à l'emplacement que le lock attend.** Retenu.

```
$GITHUB_WORKSPACE/
  genecrew/              ← checkout fjacquet/genecrew
  crewai_custom_tools/   ← checkout fjacquet/crewai-custom-tools (ref: main)
```

Depuis `genecrew/`, `../crewai_custom_tools` résout et `uv sync --locked` fonctionne **sans
modifier ni `pyproject.toml` ni `uv.lock`**. Les deux dépôts étant publics, aucun secret
n'est nécessaire.

Attention au nom : le dépôt s'appelle `crewai-custom-tools` (tiret), le chemin attendu est
`crewai_custom_tools` (souligné). C'est le paramètre `path:` de `actions/checkout` qui fait
la conversion.

## Décision

Deux workflows indépendants, qui ne partagent rien.

### `ci.yml` — tests, lint, sécurité

Déclencheurs : `pull_request`, et `push` sur `main`.

| job | contenu | bloquant |
| --- | --- | --- |
| `test` | double checkout, `setup-uv`, `uv sync --locked`, `uv run python -m pytest genecrew/tests/ -q` | **oui** |
| `test` | `uv run ruff check .` | **oui** |
| `security` | semgrep sur le code du dépôt | **non** (`continue-on-error`) |

Python **3.12 uniquement**. `pyproject` déclare pourtant `>=3.11,<3.13` : cette promesse
restera non vérifiée, et part au BACKLOG plutôt que de rester implicite.

#### Le job sécurité est informatif, et c'est délibéré

GitHub signale 5 vulnérabilités Dependabot sur la branche par défaut (1 critique, 4 hautes ;
l'API `dependabot/alerts` ne les retourne pas avec le jeton courant — à consulter dans
l'onglet Security). Rendre le job bloquant immédiatement mettrait `main` au rouge dès le
premier run, pour des problèmes antérieurs à toute PR. **Une CI qui démarre rouge est une CI
qu'on apprend à ignorer** — le pire résultat possible. Le job publie ses constats et laisse
passer ; il devient bloquant une fois les alertes existantes traitées.

#### La dérive de version, et la garde qui la rend lisible

État au 2026-07-20, vérifié : voisin local = distant = `3693f36`, version `0.16.0` des deux
côtés, lock à `0.16.0`, `uv sync --locked` passe. **La CI est verte dès le premier run.**

Le lock épingle `0.16.0` et la CI teste contre `main` du voisin. Un bump côté bibliothèque
fait donc échouer l'installation — comportement voulu : la dérive devient bruyante au lieu
d'être découverte à l'usage.

Échec reproduit expérimentalement (version du voisin passée à `0.17.0`, puis restaurée) :

```
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
hint: To update the lockfile, run `uv lock`.
```

Message exact, mais **muet sur la cause** : il ne nomme ni la dépendance qui a dérivé, ni le
fait que la PR en cours n'y est pour rien. Une étape préalable comble ce trou :

```bash
LOCK_V=$(…)   # version lue dans uv.lock
LIB_V=$(…)    # version lue dans ../crewai_custom_tools/pyproject.toml
[ "$LOCK_V" = "$LIB_V" ] || {
  echo "::error::crewai-custom-tools main est en $LIB_V, uv.lock attend $LOCK_V."
  echo "::error::Ce n'est pas un défaut de cette PR."
  echo "::error::Corriger : uv sync && git add uv.lock && git commit"
  exit 1
}
```

Cinq lignes qui transforment une erreur cryptique en tâche à faire.

Deux options ont été écartées. **`uv sync` sans `--locked`** : la CI ne rougirait jamais,
mais cesserait de tester ce qu'un développeur installe réellement, et le lock deviendrait
décoratif. **Épingler un SHA du voisin + job hebdomadaire** : plus rigoureux, mais les tags
du voisin sont abandonnés (dernier `v0.11.0` pour une version `0.16.0`), donc aucun point
d'ancrage naturel — le SHA se mettrait à jour à la main et rouillerait.

### `docs.yml` — la doc vivante sur Pages

Déclencheurs : `push` sur `main` touchant la documentation, et lancement manuel
(`workflow_dispatch`).

Générateur : **MkDocs Material** — installable par `uv` comme le reste, rendu correct du
français, et une navigation qui met les 12 ADR en valeur.

| publié | source |
| --- | --- |
| accueil | `README.md` (racine du dépôt) |
| guide | `docs/USER_GUIDE.md` |
| PRD, BACKLOG | `docs/PRD.md`, `docs/BACKLOG.md` |
| décisions | `docs/adr/*.md` (12) |

| **exclu** | raison |
| --- | --- |
| `docs/superpowers/**` | plans et specs **datés** |
| `docs/document-de-travail.md` | 36 Ko de notes de travail |

L'exclusion applique la doctrine actée par l'ADR 0012 : un plan daté décrit ce qui était vrai
à sa date. Le publier comme documentation courante ferait croire à un lecteur qu'il lit
l'état du code. Les archives restent dans le dépôt, consultables ; elles ne sont pas mises
en vitrine.

#### Le mécanisme d'exclusion, vérifié

Contrôlé contre la documentation officielle MkDocs (pas déduit). `exclude_docs` est natif
depuis la 1.6 et suit la syntaxe `.gitignore` :

```yaml
exclude_docs: |
  superpowers/
  document-de-travail.md
```

Le `README.md`, situé hors de `docs_dir`, est copié en `docs/index.md` par une ligne du job
avant le build (fichier non commité).

Le coût total de l'exclusion est donc de **quatre lignes**. La question « si c'est trop
compliqué, on n'exclut pas » a été posée et tranchée : ce n'est pas compliqué, et quatre
lignes sont un prix dérisoire pour éviter qu'un lecteur prenne un plan daté de juillet pour
la description du code courant.

### Vie privée : vérifiée, non bloquante

Le dépôt est public et le projet manipule des données généalogiques réelles. Contrôle fait
avant toute décision : les seules occurrences ressemblant à des identifiants dans `docs/`
sont `I0042`, un exemple. **Aucune donnée personnelle de tiers.** Les données réelles vivent
dans `output/`, gitignoré — la discipline du projet tient. La publication n'expose rien.

## Ce que ce chantier n'est pas

- Pas de déploiement applicatif. `genecrew` est une CLI lancée en local contre une pile
  Gramps locale ; il n'y a pas de cible de déploiement. Le « CD » ici, c'est la publication
  de la documentation.
- Pas de traitement des 5 vulnérabilités Dependabot — la CI les rend visibles, les corriger
  est un chantier distinct.
- Pas de matrice Python. La promesse `>=3.11` reste à vérifier un jour, au BACKLOG.
- Pas de modification de `pyproject.toml` ni de `uv.lock`. Si un plan propose d'y toucher,
  c'est que l'approche a dérivé.
