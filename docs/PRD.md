# GeneCrew — PRD (Product Requirements Document)

| | |
|---|---|
| **Source** | dérivé de `docs/document-de-travail.md`, §1 |
| **Statut** | Validé pour implémentation |
| **Périmètre** | France & Suisse (romande en priorité) |

Ce document ne réinvente rien : il extrait le « pourquoi/quoi » produit du document de
travail (source de vérité, §1). Pour l'architecture, les personas, les workflows et le
phasage, se référer à `docs/document-de-travail.md`.

---

## 1. Mission

> Assister — jamais remplacer — le généalogiste dans son devoir de mémoire. La généalogie
> est une discipline de preuve : **aucune donnée non sourcée n'entre dans l'arbre comme fait
> établi**. Les agents IA préparent, vérifient, proposent et consignent ; l'humain décide.

(document-de-travail.md, §1.1)

## 2. Les quatre objectifs

1. **Nettoyer** les données existantes : doublons, incohérences de dates, âges impossibles,
   liens familiaux aberrants.
2. **Standardiser** : lieux (communes fusionnées FR/CH, hiérarchie, coordonnées GPS), dates
   (format Gramps normalisé), noms (variantes de patronymes), titres de sources.
3. **Trouver des pistes de recherche** via les API publiques (INSEE décès, Gallica, Wikidata,
   DHS, Scriptorium…), chaque piste étant sourcée et rejouable.
4. **Fiabiliser** : ne consigner comme vérifié que ce qui est recoupé et cité ; produire des
   notices biographiques à partir des seuls faits prouvés.

(document-de-travail.md, §1.2)

## 3. Contrainte d'échelle

L'arbre compte entre 1 000 et 5 000 personnes. Le travail est massif et s'étalera sur des mois. Tout le pipeline est donc conçu pour tourner
**par lots**, être **interrompu et repris** sans perte, et **maîtriser le coût LLM** en
confiant le gros du volume à des règles déterministes gratuites.

(document-de-travail.md, §1.3)

En phase 0, relevé `genecrew stats` du 2026-07-17 sur l'arbre « My Family Tree » : 2 119 personnes.

## 4. Non-objectifs

- **Pas de modification autonome des données cœur** : suppression, fusion, ou modification de
  tout champ existant d'une personne, famille, événement ou lieu (dates, noms, liens de
  parenté, hiérarchies de lieux…) reste **toujours en proposition pour revue humaine** — jamais
  une écriture directe de l'IA. Voir la politique d'« écriture directe encadrée »
  (document-de-travail.md, §2.1, et ADR `docs/adr/0001-ecriture-directe-encadree.md`).
- **Pas de publication externe des données familiales** : le pipeline lit et écrit
  exclusivement dans l'instance Gramps Web locale de l'utilisateur ; aucune donnée
  généalogique n'est publiée, partagée ou envoyée à un service tiers en dehors des recherches
  documentaires strictement nécessaires (interrogations en lecture seule d'API publiques comme
  INSEE décès, Gallica, Wikidata, DHS, Scriptorium — jamais de dépôt de données de l'arbre chez
  ces tiers).

## 5. Utilisateurs

Le généalogiste propriétaire de l'arbre Gramps Web, seul décideur des écritures sur les
données cœur (voir la politique d'écriture encadrée, §2.1 du document de travail) et
responsable de la revue humaine des propositions produites à chaque workflow.

## 6. Pour aller plus loin

- Architecture générale, personas, workflows, phasage : `docs/document-de-travail.md`.
- Décisions structurantes tracées individuellement : `docs/adr/`.
- Mode d'emploi courant, complété à chaque phase : `docs/USER_GUIDE.md`.
