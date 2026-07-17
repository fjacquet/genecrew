# 0001 — Écriture directe encadrée

| | |
|---|---|
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §2.1 |

## Contexte

La généalogie est une discipline de preuve : « aucune donnée non sourcée n'entre dans l'arbre
comme fait établi » (document-de-travail.md, §1.1). Le principe directeur « Preuve avant
tout » exige une politique explicite définissant ce que les agents IA peuvent écrire dans
Gramps sans validation humaine préalable, et ce qui doit toujours rester une proposition.

## Décision

Politique d'écriture directe encadrée, telle que définie en §2.1 :

> - **Écritures autonomes autorisées** : notes, sources, citations, tags qualité — et leur
>   **rattachement append-only** à des objets existants (§ 4.5).
> - **Interdites aux agents, toujours en proposition pour revue humaine** : suppression,
>   fusion, modification de tout champ existant d'une personne, famille, événement ou lieu
>   (dates, noms, liens de parenté, hiérarchies de lieux…).
> - La garantie est **structurelle, pas rédactionnelle** : les outils dangereux n'existent pas
>   dans la bibliothèque. Aucune injection de prompt ne peut faire faire à un agent ce que ses
>   outils ne permettent pas.
> - Ceinture supplémentaire (optionnelle, validée dans les docs CrewAI) : un hook global
>   `@before_tool_call` (module `crewai.hooks`) peut bloquer par liste noire tout nom d'outil
>   d'écriture pour les crews qui n'en ont pas besoin.

Le moindre privilège est en outre réalisé par le jeu d'outils par persona : trois agents sur
cinq (Détective, Standardisateur, Historien) n'ont aucun outil d'écriture ; seul le
Chroniqueur écrit (document-de-travail.md, §5).

## Conséquences

- Aucun outil de suppression, de fusion, ni de modification de champ existant n'est jamais
  implémenté dans `crewai_custom_tools` — la garantie ne dépend d'aucun prompt ni d'aucune
  revue de sortie LLM.
- Le seul outil de rattachement (`GrampsAttachTool`) implémente strictement la séquence
  GET → append (jamais de retrait) → PUT sans modifier aucun autre champ (§4.5).
- Toute citation créée par l'IA est plafonnée à la confiance 2/4 (§8.2) ; toute proposition de
  modification d'un champ cœur (lieu, date, nom, parenté) passe par le format `Proposition`
  YAML/Markdown pour revue humaine (§8.4), jamais par une écriture directe.
- Le hook `@before_tool_call` reste une ceinture optionnelle et n'est pas la garantie
  principale : celle-ci est structurelle (absence de l'outil dangereux dans la bibliothèque).
