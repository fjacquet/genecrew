# 0004 — Spec-first : specs vendorées + modèles Pydantic générés

| | |
| --- | --- |
| **Statut** | Accepté |
| **Date** | 2026-07-17 |
| **Source** | `docs/document-de-travail.md`, §4.2 et §4.2.1 (principe « Spec-first », §2) |

## Contexte

Chaque API consommée (Gramps Web, MatchID décès, Géoplateforme, API Géo…) publie une
déclaration OpenAPI/Swagger. Écrire les modèles Pydantic à la main pour ~125 chemins Gramps
(et les API externes) serait redondant et sujet à dérive par rapport à la spec réelle. Le
principe directeur « Spec-first » (§2) impose : « Chaque API dotée d'une déclaration OpenAPI a
sa spec copiée dans `docs/swagger/` ; les modèles Pydantic sont générés par
`datamodel-code-generator`. »

## Décision

> - Spec faisant autorité : `docs/swagger/openapi.json` (Gramps Web API 3.17.0, 125 chemins).
> - Modèles Pydantic **générés** depuis la spec :
>
> ```bash
> uv run --with datamodel-code-generator datamodel-codegen \
>   --input docs/swagger/openapi.json --input-file-type openapi \
>   --output src/crewai_custom_tools/tools/genealogy/models/gramps_generated.py
> ```
>
> - Les schémas de `gramps-mcp/src/gramps_mcp/models/parameters/` servent de base aux
>   `args_schema` des outils (plus compacts que les modèles générés complets).

(document-de-travail.md, §4.2)

Emplacement des modèles (§4.2.1) :

> Tous dans `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/models/` :
>
> | Fichier | Contenu | Origine |
> | --- | --- | --- |
> | `gramps_generated.py` | objets Gramps Web (Person, Family, Event, Place, Source, Citation, Note, Tag…) | généré depuis `openapi.json` |
> | `matchid_generated.py` | requête/réponse MatchID décès | généré depuis `deces-matchid.swagger.json` |
> | `geoplateforme_generated.py` | géocodage Géoplateforme | généré depuis `geoplateforme-geocodage.openapi.yaml` |
> | `apigeo_generated.py` | communes API Géo | généré depuis `api-geo.definition.yml` |
> | `domain.py` | modèles métier écrits à la main : `Proposition`, `Anomalie`, `CandidatDoublon`, `Piste`, `Checkpoint` | manuel |
>
> Règles :
>
> - Les fichiers `*_generated.py` portent un en-tête « généré — ne pas éditer » et se
>   régénèrent par la commande documentée ci-dessus (les specs font foi dans
>   `genecrew/docs/swagger/` ; dépôts frères, chemin relatif `../genecrew/docs/swagger/`).
> - Les `args_schema` de chaque outil restent définis à côté de la classe de l'outil
>   (convention existante de la bibliothèque) — volontairement plus compacts que les modèles
>   générés, qu'ils réutilisent par import quand c'est pertinent.

## Conséquences

- Toute spec OpenAPI/Swagger consommée est vendorée dans `genecrew/docs/swagger/` avant
  d'écrire le moindre outil qui en dépend (déjà fait pour `openapi.json`,
  `deces-matchid.swagger.json`, `api-geo.definition.yml`,
  `geoplateforme-geocodage.openapi.yaml`).
- Les fichiers `*_generated.py` ne sont jamais édités à la main ; toute évolution de schéma
  passe par une régénération depuis la spec vendorée.
- Les `domain.py` (modèles métier sans équivalent OpenAPI : `Proposition`, `Anomalie`,
  `CandidatDoublon`, `Piste`, `Checkpoint`) restent la seule catégorie de modèles écrite à la
  main, et vivent au même endroit que les modèles générés pour un point d'entrée unique.
