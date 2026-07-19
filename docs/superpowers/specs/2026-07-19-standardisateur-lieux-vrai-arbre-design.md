# Standardisateur de lieux — correctifs pour le vrai arbre (noms à plat)

> Conception validée le 2026-07-19. Suite de `2026-07-19-standardisateur-lieux-design.md`
> (P1–P6). Objectif : rendre le Standardisateur **opérationnel sur le vrai arbre Gramps**,
> dont les lieux sont majoritairement des noms « à plat » sans code INSEE.

## 1. Contexte et diagnostic

Après restauration de l'arbre (255 lieux), un `lieux-apply --dry-run` complet donne
**0 écriture / 145 déjà structurés / 110 propositions / 0 erreur**. Le compteur « écrit »
compte pourtant les écritures *simulées* : 0 signifie qu'**aucun lieu n'atteint le seuil
d'auto-écriture**. Ce n'est pas de la prudence — ce sont trois défauts, tous dans
`crewai_custom_tools`, révélés en confrontant l'outil au vrai arbre (il passe ses tests
synthétiques à chaînes hiérarchiques riches, mais l'arbre stocke des noms plats).

Répartition réelle des 110 lieux à plat (parse hors-ligne) :

- **0/110** portent un code INSEE embarqué → le résolveur France (INSEE seul) ne résout rien.
- Segments : 20 à 1 segment, le reste en forme GEDCOM `, , commune, , , dept, region, pays`
  (27 à 5 segments, 35 à 6).
- Pays détectés : **France 39, Suisse 25, Allemagne 12, Algérie 8**, + Pologne, Vaud, et du
  bruit (dates, URL, descriptions) tombé dans le champ pays.
- « Commune vide » après parse : **20**, un mélange de vraies communes tronquées à droite
  (`, , BOURGES, , ,` → tout après la commune est vide → « BOURGES » lu comme pays) **et** de
  garbage (`1790 ( avant)`, `1877`, `http://archives18.fr/...`, `Dans l'église St Martin`).

### Les trois défauts (vérifiés)

- **D1 — Parser.** `parse_pname` prend toujours le *dernier segment non vide* comme pays.
  Quand un seul segment est rempli, il devient le pays et la commune reste vide →
  indécidable. Vérifié : `parse_pname("Bourges") -> commune='', country='Bourges'`.
- **D2 — Scoring plombé par les décorations.** `fuzzy_score = provider_conf × similarity`,
  et la similarité compare la commune au **libellé décoré** retourné. Vérifié :
  `fuzzy_score(1.0,'Lausanne','Lausanne (VD)') = 0.762`, `('Bern','Bern (BE)') = 0.615` — des
  correspondances **exactes** plafonnées sous 0.90. Nominatim aggrave : il multiplie par
  l'`importance` OSM (métrique de notoriété, souvent 0.2–0.5) et compare à un `display_name`
  multi-scripts (`Annaba ⵄⴻⵍⵃⴰⴲⴰ عنابة` → 0.264).
- **D3 — France par code INSEE seulement.** `resolve_fr` renvoie `None` sans code INSEE
  embarqué. Or 0/110 en portent → toutes les communes françaises basculent sur Nominatim
  avec un score faible → proposition. geo.api.gouv.fr sait chercher par **nom** ; ce levier
  n'est pas branché.

## 2. Décisions actées (avec l'utilisateur)

1. **France par nom** : *nom exact unique* → écriture autoritaire (INSEE) ; homonymes →
   proposition ; le **département/région présent dans la chaîne départage d'abord**.
2. **Le score décide pour toutes les sources**, Nominatim/OSM inclus — pas de barrière
   « source autoritaire seule ». Le garde-fou d'ambiguïté reste la protection.
3. **Contrat d'écriture inchangé** : dry-run par défaut (`effective_dry_run`), idempotence
   (index de parents réamorcé, lieux déjà structurés ignorés), garde-fou d'ambiguïté
   (marge <0.10 sur le top-2), revue humaine pour toute proposition, fusions jamais auto.
4. Périmètre : `crewai_custom_tools` uniquement (parser, score, france, suisse, nominatim).
   Aucun changement de contrat côté `genecrew`.

## 3. Correctifs

### §1 — Parser : le dernier segment n'est le pays que s'il EST un pays connu

`crewai_custom_tools/.../standardize/places.py` `parse_pname`.

Règle : le segment « pays » candidat (dernier non vide) n'est retenu comme `country` que si
`normalize_country` le reconnaît (retourne un label canonique de la table `_COUNTRY`). Sinon,
si **aucune commune** n'a été trouvée par la logique existante, ce segment devient la
**commune** et `country=""`.

- `', , BOURGES, , ,'` → `commune="BOURGES", country=""` → routé Nominatim monde.
- `'Lausanne, Vaud, Suisse'` → « Suisse » reconnu → inchangé (`commune="Lausanne"`).
- `'Bourges, Cher, Centre-Val de Loire, France'` → « France » reconnu → inchangé.
- Garbage (`1790 ( avant)`, URL, description) → devient commune → Nominatim ne trouve rien →
  **reste indécidable** (comportement correct : ce ne sont pas des lieux).

Le champ `shifted` reste `country == "France" and insee is None`. Ne touche pas la détection
de code (Corse / double-5-chiffres) ni l'exclusion par index existantes.

### §2 — Scoring : comparer au *nom-cœur*, pas au libellé décoré

`crewai_custom_tools/.../geo/score.py` + les trois mappers.

Introduire une similarité « cœur » **monotone** (jamais inférieure à l'actuelle) : la
meilleure similarité entre la chaîne demandée et un ensemble de *formes* du libellé retourné.

```
formes(label) = { label,
                  label sans suffixe parenthésé   (retire " (VD)", " (68)", …),
                  chaque jeton (split espaces) de label,
                  chaque jeton de label-sans-parenthèses }
best_similarity(asked, label) = max( similarity(asked, f) for f in formes(label) )
```

`max`-sur-formes garantit qu'on ne fait jamais pire que le libellé complet, et qu'on récupère
les cas décorés : `best_similarity("Lausanne","Lausanne (VD)") = 1.0`,
`best_similarity("Annaba","Annaba ⵄⴻⵍⵃⴰⴲⴰ عنابة") = 1.0`.

Application dans les résolveurs :

- **Suisse** (`geo/suisse.py` `map_swiss`) : score = `best_similarity(commune, label_cœur)` ;
  **prendre le meilleur résultat** (argmax des scores) au lieu de `results[0]` ; restreindre
  la requête swisstopo aux communes (`origins=gg25`) pour écarter écoles/POI
  (« Geneva → Geneva English School »). `is_ambiguous` reste calculé sur tous les scores.
- **Nominatim** (`geo/nominatim.py` `map_nominatim`) : score = `best_similarity(commune,
  display_name.split(",")[0])` avec **provider_conf = 1.0** (ne plus multiplier par
  `importance`, qui n'est pas une confiance de correspondance) ; argmax + `is_ambiguous`
  inchangés.
- **US** (`geo/usa.py`) : peut réutiliser `best_similarity` ; les fixtures exactes restent à
  1.0 (monotonie), donc pas de régression attendue.

Note tests : les tests qui asseyaient les **scores dépréciés** (ex. 0.762) doivent être mis à
jour vers les nouvelles valeurs — c'est l'objet du correctif. Les tests de correspondance
**exacte** (déjà à 1.0) et d'ambiguïté restent verts.

### §3 — Résolveur France par nom

`crewai_custom_tools/.../geo/france.py` `resolve_fr`.

Priorité inchangée : si `parsed.insee` est présent → lookup autoritaire `/communes/{insee}`
(comportement actuel). **Nouveau** : sinon, si `parsed.commune` est non vide, chercher par nom.

Contrat geo.api.gouv.fr (vérifié en direct) — la recherche `nom` est **floue** (`nom=Sainte-Marie`
renvoie aussi « Saintes-Maries-de-la-Mer ») :

```
GET /communes?nom=<commune>&fields=nom,code,centre,departement,region&boost=population&limit=10
```

1. Récupérer les candidats.
2. **Filtrer aux noms EXACTS** : `_norm(c["nom"]) == _norm(commune)` (accents/casse via le
   `_strip_accents`/`_norm` existant).
3. Si `parsed.departement` ou `parsed.region` est présent → filtrer d'abord les candidats par
   correspondance de département/région (nom normalisé ou `code`).
4. Décision :
   - **exactement 1** candidat exact → `ResolvedPlace(score=1.0, ambiguous=False,
     place_type="Municipality", code=<INSEE>, source="geo.api.gouv.fr",
     chains=[France › Région › Département])` → `ecrire`.
   - **>1** candidat exact (vrais homonymes non départagés) → `ambiguous=True` (→ proposition) ;
     retenir le plus peuplé (`boost=population`, premier) pour l'affichage ; la preuve indique
     le nombre d'homonymes.
   - **0** candidat exact (abréviations « St Georges », fautes) → `resolve_fr` renvoie `None`
     → le registre bascule sur Nominatim (fuzzy → proposition, jamais écrit sans preuve).

`map_commune` (mapping d'un lot `/communes/{insee}`) est réutilisé/adapté pour le mapping d'un
candidat nommé (les champs `nom,code,centre,departement,region` sont identiques). `_http_get`
reste le point HTTP monkeypatché en test.

## 4. Fichiers touchés

Tous dans `crewai_custom_tools/src/crewai_custom_tools/tools/genealogy/` :

- `standardize/places.py` — `parse_pname` (D1).
- `geo/score.py` — `best_similarity` (+ helper de formes) ; `fuzzy_score` peut l'utiliser ou
  un `core_fuzzy_score` dédié (choix d'implémentation, tranché par les tests).
- `geo/suisse.py` — `map_swiss` (argmax + best_similarity) ; `resolve_ch` (`origins=gg25`).
- `geo/nominatim.py` — `map_nominatim` (best_similarity, provider_conf=1.0).
- `geo/france.py` — `resolve_fr` (+ mapping d'un candidat nommé).
- `geo/usa.py` — bascule optionnelle sur `best_similarity` (monotone, sans régression).

Tests associés dans `crewai_custom_tools/tests/` (par classe, fixtures synthétiques,
`httpx.MockTransport` / mappers purs, offline).

`genecrew` : aucun changement de code. Seule la **validation réelle** (re-run dry-run) s'y fait.

## 5. Tests

Par **classe**, hors-ligne, fixtures synthétiques (jamais d'extraits de l'arbre) :

- **Parser (D1)** : troncature droite (`', , BOURGES, , ,'` → `commune="BOURGES"`,
  `country=""`) ; pays connu en dernier inchangé ; garbage (date/URL) → commune → laissé au
  résolveur ; chaînes riches multi-segments inchangées ; `shifted` inchangé.
- **Scoring (D2)** : `best_similarity` monotone (≥ `similarity`) ; suffixe canton → 1.0 ;
  multi-scripts → 1.0 ; `map_swiss` prend l'argmax (fixture avec un meilleur match en
  position ≠ 0) ; Nominatim ne multiplie plus par `importance` (fixture importance basse +
  nom exact → score ≥ seuil) ; `is_ambiguous` toujours déclenché sur top-2 serrés.
- **France par nom (D3)** : 1 exact → `score=1.0`, `ambiguous=False`, code INSEE, chaîne
  France›Région›Département ; >1 exact → `ambiguous=True` ; filtre exact écarte le flou
  (`Sainte-Marie` n'avale pas `Saintes-Maries-de-la-Mer`) ; filtre département départage ;
  0 exact → `None` (fallback) ; code INSEE présent → chemin autoritaire inchangé prioritaire.
- **Invariants GPS** inchangés : WGS84, GeoJSON `[lon,lat]`, swisstopo `lat`/`lon` jamais `x`/`y`.

### Validation réelle (la leçon « valider sur le vrai arbre »)

Après implémentation, depuis `genecrew` : `uv run genecrew lieux --scope all --dry-run` et
`lieux-apply --scope all --dry-run`. Attendu : les correspondances autoritaires passent en
`ecrire` (ordre de grandeur ~25 CH + jusqu'à ~39 FR selon homonymes) ; **zéro** écriture
indue ; **zéro** doublon de parent (idempotence : re-run = 0 écrit).

## 6. Risques et hors-périmètre

- **Risque (assumé)** : `provider_conf=1.0` pour Nominatim augmente les auto-écritures à
  l'étranger (Allemagne, Algérie, Pologne, Italie) sans source autoritaire. Conforme à la
  décision « le score décide, toute source » ; garde-fous = filtre nom-exact impossible ici
  donc **garde d'ambiguïté** (marge <0.10) + seuil `min_score` 0.90. À surveiller au dry-run.
- **Risque** : `best_similarity` par jetons peut sur-noter un match partiel exotique ; la
  monotonie borne le pire cas au libellé complet et l'ambiguïté protège les homonymes.
- **Hors périmètre** : aucun nouveau pays ; pas de refonte des transitions datées (P5) ;
  **pas de correction des données garbage** (dates/URL/descriptions dans le champ nom) — elles
  restent indécidables, non réécrites ; pas de section rapport « data-quality » (écartée, YAGNI).

## 7. Critère de sortie

Le correctif est bon si : (a) le dry-run réel montre des passages en `ecrire` non nuls pour la
France (par nom) et la Suisse (score corrigé) ; (b) zéro écriture indue et idempotence prouvée
(re-run = 0) ; (c) les homonymes FR restent des propositions ; (d) les tests par classe
couvrent D1/D2/D3 et les invariants GPS restent verts ; (e) aucun changement du contrat
d'écriture ni de l'API `genecrew`.
