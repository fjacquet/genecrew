# ADR 0015 — Détection et fusion automatique des doublons de lieux

Date : 2026-07-22 — Statut : accepté

## Contexte

`apply places` ne traite que les lieux de type `Unknown` : sa boucle saute tout lieu déjà
structuré, au nom de l'idempotence. C'est aussi lui qui produit le YAML de fusions, et il ne
le compose que pour les lieux qu'il vient de résoudre. **Un doublon déjà typé n'entre donc
dans le champ d'aucune commande.**

Mesure du 2026-07-21 : 11 groupes de communes homonymes, tous de type `Municipality`, tous
invisibles au pipeline. Ils ont dû être fusionnés à la main, un par un.

`merge places` existait, mais seulement comme exécutant : `--yaml` requis. Son voisin
`merge people` a les deux modes depuis l'ADR 0013.

## Décision

`merge places --scope` détecte les doublons, fusionne ceux qui sont **prouvés**, et dépose le
reste en YAML d'arbitrage — que `merge places --yaml` exécute après relecture.

Deux lieux sont candidats s'ils portent le même **nom normalisé**. Un **veto** passe avant
tout : deux codes officiels non vides et différents interdisent la fusion. Hors veto, la
preuve est soit **des codes identiques** (un code officiel est canonique, il vaut entre types
différents), soit **le même type et des coordonnées identiques** (la voie des lieux sans code).

Les coordonnées ne prouvent **jamais** rien entre types différents. Paris existe en
`Department` (code 75) et en `Municipality` (code 75056) : deux entités administratives
réelles. Le chantier référentiel donnera des coordonnées aux départements, et un département
géocodé reçoit le point de son chef-lieu — sans cette garde, le piège deviendrait atteignable.

Le survivant est choisi par **richesse d'abord** (coordonnées, code, rattachement), puis
rétroliens, puis identifiant le plus petit. La fusion Gramps unionne les listes mais conserve
les champs simples du survivant : garder une coquille vide effacerait définitivement les
coordonnées de l'autre. Le rapport nomme ce que l'ordre inverse aurait perdu.

C'est la doctrine de l'ADR 0013 transposée : la ressemblance ne prouve jamais l'identité. Avec
un avantage que les personnes n'ont pas — une commune possède un identifiant canonique.

Trois points, imprévisibles avant l'implémentation, se sont révélés en cours de route et
tiennent la forme du code livré :

1. **Un `--limit` désactive les écritures.** Le veto de grappe (ci-dessous) raisonne sur le
   groupe entier d'homonymes ; `--limit` tronque la lecture, donc tronque les groupes, et fait
   tomber cette garde — le membre exclu par la troncature peut être justement celui qui portait
   la preuve du mélange. `run_places_detect` force donc la simulation dès que `limit` est posé,
   quel que soit `--dry-run`, et le rapport le dit explicitement (avertissement dédié). C'est
   **surprenant** : le guide recommande par ailleurs de borner un premier essai avec `--limit`
   (`merge people --scope all --limit 200`, `propose wikidata --limit 50`…), un réflexe qui pour
   `merge places` produit silencieusement une simulation.
2. **Une fusion automatique ne détruit jamais d'information.** Une preuve ne suffit pas à
   conclure « auto » : si l'absorbé porte un attribut simple que le survivant n'a pas —
   coordonnées, code, **type** — la proposition passe en arbitrage au lieu de s'exécuter. La
   liste des attributs surveillés n'est pas arbitraire : elle reprend exactement ce que la
   fusion Gramps écrase, à savoir les champs simples. Le rattachement (`placeref_list`) en est
   délibérément absent : c'est une liste de références, unionnée comme les autres, qui **survit**
   à la fusion.
3. **Le veto de grappe ne mord que sur les preuves non canoniques.** Une grappe d'homonymes qui
   contient deux codes officiels différents entre deux de ses membres dégrade en arbitrage les
   paires prouvées par coordonnées de ce groupe — mais pas celles prouvées par un code officiel
   identique : un code est canonique, et la présence d'un troisième code voisin ne fragilise en
   rien la preuve que deux lieux au même code sont le même lieu. Exemple réel verrouillé en
   test : quatre « Saint-Palais » dans une même grappe, deux au code 18205 et deux au code
   17398 — la paire 18205 reste `auto` malgré le veto porté par la grappe. Sur les grappes à
   deux entités, 92 % des paires dégradées par le veto de grappe étaient prouvées par un code
   identique — sans cette nuance, la commande aurait perdu son intérêt sur l'essentiel de son
   périmètre.

## Conséquences

Les doublons de lieux cessent d'être invisibles. La déduplication se fait en **une seule
passe** : le groupement par égalité de nom normalisé est une relation d'équivalence, et
fusionner deux lieux n'en renomme aucun autre — contrairement aux personnes, où une fusion
peut en révéler d'autres.

Contrepartie assumée : le comptage des rétroliens coûte un appel API par lieu. C'est la seule
mesure qui dise lequel de deux homonymes l'arbre utilise réellement.

Un lot borné par `--limit` ne fusionne jamais — la simulation forcée est **intentionnelle**,
pas une régression à corriger : documentée dans le rapport et dans le guide utilisateur pour
qu'elle ne se lise pas comme une panne.

Hors périmètre : créer ou compléter des lieux — c'est `apply places` et le chantier
référentiel.
