#!/usr/bin/env bash
# Construit le site MkDocs à partir du README et de docs/.
#
# Recette partagée par .github/workflows/ci.yml (job `docs`, build de
# vérification uniquement, sans déploiement) et .github/workflows/docs.yml
# (déploiement GitHub Pages) — un seul endroit pour que les deux workflows
# ne dérivent pas l'un de l'autre.
#
# `sed -i` sans argument est du GNU sed : c'est ce qui tourne tel quel sur
# les runners ubuntu-latest. Sur macOS, `/usr/bin/sed` est du BSD sed et son
# `-i` exige un argument de suffixe (comportement différent, pas seulement
# une histoire de flag) — un développeur macOS doit installer GNU sed
# (`brew install gnu-sed`, fournit le binaire `gsed`) et l'indiquer via la
# variable SED, par exemple :
#   SED=gsed ./scripts/build-docs.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SED="${SED:-sed}"

# README.md vit à la racine, hors de docs_dir : MkDocs ne le voit pas.
# On le copie en page d'accueil au build ; la copie n'est jamais commitée.
#
# Le README est rendu depuis deux racines différentes : celle du dépôt
# sur GitHub (où les liens absolus vers github.com sont les seuls qui
# fonctionnent) et celle de docs/ une fois copié en page d'accueil du
# site publié. Depuis le site, un lien absolu vers une page qui y est
# elle-même publiée fait sortir le visiteur vers le Markdown brut de
# GitHub au lieu de le garder sur la page du site (thème, recherche,
# sommaire). On ne réécrit donc que les liens dont la cible est une PAGE
# du site — USER_GUIDE.md et BACKLOG.md. Restent en URL absolue :
#   - CHANGELOG.md          : hors de docs/, jamais publié
#   - document-de-travail   : exclu du site par exclude_docs
#   - adr/                  : c'est un RÉPERTOIRE, pas une page. MkDocs ne
#     génère pas de site/adr/index.html, donc un lien interne « adr/ »
#     serait mort (404). Les 12 ADR restent atteignables par la navigation
#     latérale. Le jour où docs/adr/index.md existera, ce lien pourra
#     devenir interne.
#
# Le critère est « la cible est-elle une page du site ? », pas « le lien
# est-il absolu ? ». Attention : `mkdocs build --strict` ne rattrape PAS
# un lien interne mort de ce type — il le signale en INFO, pas en warning.
# Pour vérifier après avoir ajouté une page, comparer les deux listes :
#   find site -name index.html
#   grep -o 'https://github.com/fjacquet/genecrew/[a-z]*/main/[^)]*' README.md
cp README.md docs/index.md
"$SED" -i \
  -e 's|https://github.com/fjacquet/genecrew/blob/main/docs/USER_GUIDE.md|USER_GUIDE.md|g' \
  -e 's|https://github.com/fjacquet/genecrew/blob/main/docs/BACKLOG.md|BACKLOG.md|g' \
  docs/index.md

uvx --with mkdocs-material==9.7.7 mkdocs@1.6.1 build --strict
