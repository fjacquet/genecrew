# CI/CD et documentation sur GitHub Pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner au dépôt une CI qui lance tests, lint et analyse de sécurité sur chaque PR,
et publier la documentation vivante sur `https://fjacquet.github.io/genecrew/`.

**Architecture :** Deux workflows GitHub Actions indépendants. `ci.yml` clone le dépôt voisin
`crewai-custom-tools` à l'emplacement que `uv.lock` attend (`../crewai_custom_tools`), ce qui
permet `uv sync --locked` sans toucher ni à `pyproject.toml` ni au lock. `docs.yml` construit
un site MkDocs Material qui exclut les archives datées, et le déploie sur Pages.

**Tech Stack :** GitHub Actions, uv, pytest, ruff, semgrep (via `uvx`), MkDocs Material.
Spec de référence : `docs/superpowers/specs/2026-07-20-ci-cd-et-doc-pages-design.md`.

## Global Constraints

- Tout se lance avec `uv` — jamais `pip` ni `python` direct.
- **Ne modifier ni `pyproject.toml` ni `uv.lock`.** Si une étape semble l'exiger, c'est que
  l'approche a dérivé — s'arrêter et le signaler.
- Le dépôt voisin doit être cloné en `crewai_custom_tools` (**souligné**), alors que le dépôt
  GitHub s'appelle `crewai-custom-tools` (**tiret**). C'est le `path:` de `actions/checkout`
  qui fait la conversion. Se tromper casse la résolution du lock.
- Versions d'actions vérifiées le 2026-07-20 : `actions/checkout@v7`, `astral-sh/setup-uv@v8`,
  `actions/upload-pages-artifact@v5`, `actions/deploy-pages@v5`.
- Versions PyPI vérifiées le 2026-07-20 : `mkdocs` 1.6.1, `mkdocs-material` 9.7.7,
  `semgrep` 1.170.0.
- GitHub Pages est **déjà** configuré en mode workflow (`build_type: workflow`,
  `https://fjacquet.github.io/genecrew/`). Aucun réglage de dépôt à changer.
- Les deux dépôts sont publics : **aucun secret** n'est nécessaire.
- Textes d'interface et commentaires en français, accents intacts.

## ⚠ Le dépôt voisin bouge en parallèle

Un chantier de rattrapage est en cours sur `crewai-custom-tools` **pendant** l'exécution de
ce plan. Deux conséquences concrètes :

1. **Les steps 1 et 2 de la Task 1 supposent le voisin en `0.16.0` et propre.** Commencer par
   `cd ../crewai_custom_tools && git status --porcelain && grep -m1 '^version' pyproject.toml`.
   Si la version diffère de `0.16.0` ou si l'arbre est sale, **ne pas jouer le step 2**
   (qui modifie puis restaure `pyproject.toml` : sur un arbre modifié, le `git checkout` de
   restauration écraserait du travail en cours). Adapter les valeurs attendues du step 1 à ce
   qu'on observe, et rapporter l'écart.
2. **La garde va probablement se déclencher pour de vrai, et bientôt.** Dès que le voisin
   bumpe sa version, `uv.lock` de genecrew devient périmé et la CI passe au rouge sur toutes
   les PR, y compris celles qui n'ont rien à voir. C'est le comportement conçu — le message
   de la garde dit quoi faire (`uv sync && git add uv.lock && git commit`). Ce n'est pas un
   défaut à corriger dans ce plan.

---

### Task 1: `ci.yml` — tests, lint, sécurité

Un workflow CI ne se teste pas en local : sa vérification est **son exécution réelle**. La
garde de cohérence, elle, est du shell et se teste localement — c'est la partie où une erreur
est plausible, donc c'est elle qu'on éprouve avant de pousser.

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `docs/BACKLOG.md` (ajouter la note sur Python 3.11 non vérifié)

**Interfaces:**
- Consumes: rien (première tâche).
- Produces: rien que la Task 2 consomme — les deux workflows sont indépendants.

- [ ] **Step 1: Éprouver la garde de cohérence en local, cas nominal**

Cette commande est le cœur de la garde. La lancer depuis la racine du dépôt :

```bash
LOCK_V=$(python3 -c "
import re, pathlib
t = pathlib.Path('uv.lock').read_text()
m = re.search(r'name = \"crewai-custom-tools\"\nversion = \"([^\"]+)\"', t)
print(m.group(1) if m else '')
")
LIB_V=$(python3 -c "
import re, pathlib
t = pathlib.Path('../crewai_custom_tools/pyproject.toml').read_text()
m = re.search(r'^version = \"([^\"]+)\"', t, re.M)
print(m.group(1) if m else '')
")
echo "lock=$LOCK_V lib=$LIB_V"
```

Expected: `lock=0.16.0 lib=0.16.0` — deux valeurs non vides et **égales**.

Si l'une est vide, ne pas continuer : le format de `uv.lock` ou du `pyproject` voisin a
changé et la garde doit être adaptée avant d'être écrite dans le workflow.

- [ ] **Step 2: Éprouver la garde, cas de dérive**

Simuler un bump du voisin, vérifier que la garde le détecte, puis **restaurer immédiatement** :

```bash
cd ../crewai_custom_tools
sed -i '' 's/^version = "0.16.0"/version = "0.17.0"/' pyproject.toml
grep -m1 '^version' pyproject.toml          # doit afficher 0.17.0
cd ../genecrew
# relancer le bloc du Step 1
```

Expected: `lock=0.16.0 lib=0.17.0` — valeurs différentes, donc la garde déclencherait.

Restaurer sans délai :

```bash
cd ../crewai_custom_tools && git checkout pyproject.toml && git status --porcelain
cd ../genecrew && uv sync --locked
```

Expected: `git status --porcelain` ne sort rien, et `uv sync --locked` réussit.

- [ ] **Step 3: Écrire `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

# Un nouveau push sur la même branche annule le run en cours.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    name: tests et lint
    runs-on: ubuntu-latest
    steps:
      - name: checkout genecrew
        uses: actions/checkout@v7
        with:
          path: genecrew

      # uv.lock verrouille `source = { editable = "../crewai_custom_tools" }`.
      # Le dépôt s'appelle crewai-custom-tools (tiret) mais DOIT atterrir dans un
      # répertoire à souligné, sinon la résolution du lock échoue.
      - name: checkout crewai-custom-tools
        uses: actions/checkout@v7
        with:
          repository: fjacquet/crewai-custom-tools
          ref: main
          path: crewai_custom_tools

      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true

      # `uv sync --locked` échoue sur une dérive de version, mais son message ne
      # nomme ni la dépendance en cause ni le fait que la PR n'y est pour rien.
      # Cette étape le dit à sa place.
      - name: cohérence uv.lock / bibliothèque voisine
        working-directory: genecrew
        run: |
          LOCK_V=$(python3 -c "
          import re, pathlib
          t = pathlib.Path('uv.lock').read_text()
          m = re.search(r'name = \"crewai-custom-tools\"\nversion = \"([^\"]+)\"', t)
          print(m.group(1) if m else '')
          ")
          LIB_V=$(python3 -c "
          import re, pathlib
          t = pathlib.Path('../crewai_custom_tools/pyproject.toml').read_text()
          m = re.search(r'^version = \"([^\"]+)\"', t, re.M)
          print(m.group(1) if m else '')
          ")
          echo "uv.lock attend : ${LOCK_V:-INTROUVABLE}"
          echo "voisin main    : ${LIB_V:-INTROUVABLE}"
          if [ -z "$LOCK_V" ] || [ -z "$LIB_V" ]; then
            echo "::error::Version illisible — le format de uv.lock ou du pyproject voisin a changé."
            exit 1
          fi
          if [ "$LOCK_V" != "$LIB_V" ]; then
            echo "::error::crewai-custom-tools main est en $LIB_V, uv.lock attend $LOCK_V."
            echo "::error::Ce n'est pas un défaut de cette PR."
            echo "::error::Corriger : uv sync && git add uv.lock && git commit"
            exit 1
          fi

      - name: installation
        working-directory: genecrew
        run: uv sync --locked

      - name: tests
        working-directory: genecrew
        run: uv run python -m pytest genecrew/tests/ -q

      - name: lint
        working-directory: genecrew
        run: uv run ruff check .

  security:
    name: sécurité (informatif)
    runs-on: ubuntu-latest
    # Informatif : les constats sont publiés, la PR n'est pas bloquée.
    # À passer bloquant une fois les alertes Dependabot existantes traitées.
    continue-on-error: true
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8

      # `--config=auto` exige d'activer la télémétrie Semgrep ; des rulesets
      # explicites s'en passent, donc rien n'est envoyé à l'extérieur.
      - name: semgrep
        run: >
          uvx semgrep@1.170.0 scan
          --config=p/python
          --config=p/secrets
          --metrics=off
          --error
          genecrew/src/
```

- [ ] **Step 4: Vérifier la syntaxe YAML avant de pousser**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML valide')"
```
Expected: `YAML valide`

- [ ] **Step 5: Reproduire localement ce que fera le job sécurité**

```bash
uvx semgrep@1.170.0 scan --config=p/python --config=p/secrets --metrics=off genecrew/src/
```
Expected: aucun constat (mesuré le 2026-07-20 : scan propre). Si des constats
apparaissent, les rapporter — ne pas les corriger dans cette tâche, le job est informatif.

- [ ] **Step 6: Noter au BACKLOG la promesse Python non vérifiée**

Dans `docs/BACKLOG.md`, ajouter en fin de la section `## Robustesse / données cœur` :

```markdown
- **`>=3.11` promis mais jamais vérifié** — `pyproject.toml` déclare
  `requires-python = ">=3.11,<3.13"` ; la CI ne teste que 3.12 (pas de matrice, choix
  assumé au 2026-07-20). Soit ajouter `3.11` à une matrice `strategy.matrix.python`, soit
  restreindre la déclaration à `>=3.12`. En l'état, la promesse est invérifiée.
```

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml docs/BACKLOG.md
git commit -m "ci: tests, lint et sécurité sur chaque PR

Le runner clone crewai-custom-tools à l'emplacement que uv.lock attend
(../crewai_custom_tools), ce qui permet uv sync --locked sans reverrouiller ni
perdre l'édition locale des deux dépôts en parallèle.

Une garde compare la version du voisin à celle du lock avant de synchroniser :
uv échoue correctement sur une dérive, mais sans nommer la cause ni signaler que
la PR n'y est pour rien.

Sécurité informative : semgrep publie ses constats sans bloquer, le temps que les
alertes Dependabot existantes soient traitées."
```

- [ ] **Step 8: Pousser sur une branche et OBSERVER le run réel**

C'est la seule vérification qui compte pour un workflow.

```bash
git push -u origin <branche>
gh pr create --fill
gh run watch
```

Expected: job `tests et lint` **vert** (161 tests, ruff propre) ; job `sécurité` vert
également (scan propre au 2026-07-20). Rapporter l'URL du run et le résultat de chaque job.

Si le job `tests et lint` échoue sur `uv sync`, vérifier en premier le nom du répertoire du
checkout voisin : `crewai_custom_tools` avec un **souligné**.

---

### Task 2: `docs.yml` et `mkdocs.yml` — la doc vivante sur Pages

Contrairement au workflow, le site **se construit en local** : c'est là qu'on vérifie que
les exclusions fonctionnent, avant de dépendre d'un run distant.

**Files:**
- Create: `mkdocs.yml` (racine du dépôt)
- Create: `.github/workflows/docs.yml`
- Modify: `.gitignore` (ignorer `site/` et `docs/index.md`)
- Modify: `README.md` (badges CI et documentation)

**Interfaces:**
- Consumes: rien de la Task 1 — les deux workflows sont indépendants.
- Produces: rien.

- [ ] **Step 1: Écrire `mkdocs.yml`**

À la racine du dépôt :

```yaml
site_name: GeneCrew
site_description: Équipe d'agents IA pour la généalogie (Gramps Web)
site_url: https://fjacquet.github.io/genecrew/
repo_url: https://github.com/fjacquet/genecrew
edit_uri: edit/main/docs/

theme:
  name: material
  language: fr
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      toggle:
        icon: material/weather-night
        name: Passer au thème sombre
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      toggle:
        icon: material/weather-sunny
        name: Passer au thème clair
  features:
    - navigation.sections
    - navigation.top
    - content.code.copy
    - search.suggest

markdown_extensions:
  - admonition
  - tables
  - toc:
      permalink: true
  - pymdownx.superfences

# Archives datées et données brutes : présentes dans le dépôt, hors du site.
# Un plan de juillet décrit ce qui était vrai à sa date ; le publier comme
# documentation courante ferait croire à un lecteur qu'il lit l'état du code.
# Voir docs/adr/0012-cli-grammaire-verbes.md.
# Syntaxe .gitignore, disponible depuis MkDocs 1.6.
exclude_docs: |
  superpowers/
  document-de-travail.md
  swagger/
```

Aucune section `nav:` : MkDocs génère la navigation depuis l'arborescence, donc un ADR
ajouté apparaît sans retoucher la configuration. L'ordre est alphabétique, `index` en tête,
et les ADR étant numérotés ils se rangent naturellement.

- [ ] **Step 2: Construire le site en local et vérifier les exclusions**

```bash
cp README.md docs/index.md
uvx --with mkdocs-material==9.7.7 mkdocs@1.6.1 build --strict
```
Expected: build réussi, sans warning (`--strict` transforme tout warning en échec).

Puis vérifier que les exclusions ont bien mordu :

```bash
test -d site/superpowers && echo "ÉCHEC : superpowers publié" || echo "ok superpowers exclu"
test -e site/document-de-travail && echo "ÉCHEC : doc de travail publiée" || echo "ok doc de travail exclue"
test -d site/swagger && echo "ÉCHEC : swagger publié" || echo "ok swagger exclu"
test -e site/index.html && echo "ok accueil présent" || echo "ÉCHEC : pas d'accueil"
ls site/adr/ | wc -l | xargs echo "pages ADR publiées :"
```
Expected: trois `ok … exclu`, `ok accueil présent`, et **12** pages ADR.

Si `--strict` échoue sur un lien mort, rapporter le lien exact : il pointe probablement vers
une archive exclue, et c'est une décision (corriger le lien ou publier la cible), pas une
correction mécanique.

- [ ] **Step 3: Ignorer les artefacts de build**

Ajouter à `.gitignore` :

```gitignore

# Documentation (MkDocs) — site construit et accueil copié depuis README au build
site/
docs/index.md
```

Vérifier que la copie n'est pas suivie :

```bash
git status --porcelain docs/index.md site
```
Expected: aucune sortie.

- [ ] **Step 4: Écrire `.github/workflows/docs.yml`**

```yaml
name: Documentation

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'README.md'
      - 'mkdocs.yml'
      - '.github/workflows/docs.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

# Un seul déploiement à la fois, sans annuler celui en cours.
concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    name: construction du site
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true

      # README.md vit à la racine, hors de docs_dir : MkDocs ne le voit pas.
      # On le copie en page d'accueil au build ; la copie n'est jamais commitée.
      - name: page d'accueil depuis le README
        run: cp README.md docs/index.md

      - name: build
        run: uvx --with mkdocs-material==9.7.7 mkdocs@1.6.1 build --strict

      - uses: actions/upload-pages-artifact@v5
        with:
          path: site

  deploy:
    name: déploiement Pages
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v5
```

- [ ] **Step 5: Vérifier la syntaxe YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml')); print('YAML valide')"
```
Expected: `YAML valide`

- [ ] **Step 6: Ajouter les badges au README**

Juste sous le titre principal de `README.md` :

```markdown
[![CI](https://github.com/fjacquet/genecrew/actions/workflows/ci.yml/badge.svg)](https://github.com/fjacquet/genecrew/actions/workflows/ci.yml)
[![Documentation](https://github.com/fjacquet/genecrew/actions/workflows/docs.yml/badge.svg)](https://fjacquet.github.io/genecrew/)
```

- [ ] **Step 7: Commit**

```bash
git add mkdocs.yml .github/workflows/docs.yml .gitignore README.md
git commit -m "docs: publier la doc vivante sur GitHub Pages

Site MkDocs Material déployé sur https://fjacquet.github.io/genecrew/ à chaque
push sur main touchant la documentation.

Sont exclus les plans et specs datés, le document de travail et les specs
d'API (610 Ko) : un plan daté décrit ce qui était vrai à sa date, le publier
comme documentation courante induirait en erreur (ADR 0012). Les archives
restent dans le dépôt, elles ne sont pas mises en vitrine.

Le README sert de page d'accueil, copié au build plutôt que dupliqué."
```

- [ ] **Step 8: Vérifier le déploiement réel**

Après merge sur `main` :

```bash
gh run watch
curl -s -o /dev/null -w "%{http_code}\n" https://fjacquet.github.io/genecrew/
curl -s https://fjacquet.github.io/genecrew/adr/0012-cli-grammaire-verbes/ | grep -c "grammaire de verbes"
curl -s -o /dev/null -w "%{http_code}\n" https://fjacquet.github.io/genecrew/document-de-travail/
```
Expected: `200` pour l'accueil, au moins `1` occurrence pour l'ADR 0012, et **`404`** pour le
document de travail — c'est la preuve que l'exclusion tient en production, pas seulement en
local.

---

## Ordre

Task 1 → Task 2, ou les deux en parallèle : les workflows sont indépendants et ne partagent
aucun fichier. Le seul couplage est le README de la Task 2, qui référence le badge du
workflow créé en Task 1 — un badge pointant vers un workflow inexistant s'afficherait
« no status » sans rien casser.

## Vérification, et ses limites

Un workflow ne se teste pas hors de GitHub. Ce plan met donc en local tout ce qui peut l'être
— la garde de cohérence (Task 1, steps 1-2), le scan semgrep (step 5), la construction du
site et ses exclusions (Task 2, step 2) — et s'en remet à l'observation du run réel pour le
reste. Les deux tâches se terminent sur cette observation, jamais sur « le YAML a l'air
correct ».
