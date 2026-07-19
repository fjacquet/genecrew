# Résolveur Allemagne autoritaire (gazetteer AGS embarqué)

> Conception validée le 2026-07-19. Extension du chantier lieux GeneCrew, sur le patron du
> résolveur **US Census embarqué** + **France-par-nom**. Objectif : résoudre les lieux
> allemands de façon **autoritaire** (AGS + coordonnées officielles) au lieu du repli
> Nominatim/OSM, qui choisit parfois le mauvais homonyme (ex. « Waldeck » résolu en Thuringe
> au lieu de la Hesse).

## 1. Contexte

Aujourd'hui l'Allemagne n'a **pas** de résolveur autoritaire (`_BY_COUNTRY` = France, Suisse,
États-Unis) : elle bascule sur Nominatim/OSM. Sur la chaîne réelle
`, Waldeck, 06635021, 34513, Regierungsbezirk Kassel, Hesse, Germany` :

- le parser met l'**AGS `06635021`** (clé communale officielle) dans `departement`, et **perd
  le Land `Hesse`** (tail plein) ;
- Nominatim résout « Waldeck » aux coordonnées `50.911, 11.782` (**Thuringe**, mauvais Waldeck ;
  celui de Hesse est vers `51.2, 9.06`) — retenu en proposition seulement grâce au garde-fou
  d'ambiguïté.

Or la chaîne contient tout pour lever l'ambiguïté : l'**AGS** (préfixe `06` = Land Hessen), le
**Land Hesse**, le **code postal**. Un gazetteer allemand embarqué, indexé par AGS + nom/Land,
résout ce cas de façon autoritaire.

## 2. Source de données (vérifiée)

**OpenDataSoft `georef-germany-gemeinde@public`** (dérivé du **VG250 officiel du BKG**,
Bundesamt für Kartographie und Geodäsie), ~11 000 communes. Champs utiles :

| Champ OpenDataSoft | Exemple | Usage |
|---|---|---|
| `gem_code` | `146270060060` (ARS, 12 chiffres) | → **AGS 8 chiffres** = `ars[:5] + ars[-3:]` (= `14627060`) |
| `gem_name_short` | `["Großenhain"]` | nom sans préfixe Stadt/Gemeinde (prendre `[0]`) |
| `lan_name` | `["Sachsen"]` | Land (prendre `[0]`) |
| `geo_point_2d` | `{lat: 51.32, lon: 13.52}` | centroïde **WGS84** (comme l'INTPT du Census US) |

Export CSV téléchargeable via l'API v2.1 OpenDataSoft
(`/api/explore/v2.1/catalog/datasets/georef-germany-gemeinde@public/exports/csv`). Le centroïde
de commune comme point-lieu est cohérent avec le patron US Census (`INTPTLAT/INTPTLONG`).

**Note AGS/ARS** : l'ARS 12 chiffres = 2 (Land) + 1 (RB) + 2 (Kreis) + 4 (Gemeindeverband) + 3
(Gemeinde) ; l'AGS 8 chiffres = 2+1+2+3, obtenu par `ars[:5] + ars[-3:]`. Le préfixe 2 chiffres
identifie le Land (01 Schleswig-Holstein … 06 Hessen … 16 Thüringen).

## 3. Décisions actées (avec l'utilisateur)

1. **Gazetteer embarqué** (patron US Census) — pas d'appel réseau à la résolution ; le script de
   provisioning télécharge le fichier officiel.
2. **Politique miroir de la France** :
   - **AGS présent** (dans la chaîne) → lookup autoritaire par AGS (le code EST l'identité).
   - **nom + Land** → `(nom, Land)` : unique → autoritaire ; >1 → proposition ; 0 → None.
   - **nom seul** → unique en Allemagne → autoritaire ; collision → proposition ; 0 → None
     (repli Nominatim).
3. **Source VG250/BKG** validée (centroïde comme point-lieu).
4. Périmètre : `crewai_custom_tools` (parser + résolveur + données + une ligne registre) ; **un
   champ ajouté** au modèle `ParsedPlace`. Aucun changement de contrat d'écriture ni d'API
   `genecrew`.

## 4. Correctifs / ajouts

### §1 — Données : `data/de_communes.csv` + `scripts/build_de_gazetteer.py`

`build_de_gazetteer.py` (patron `build_us_gazetteer.py`) : télécharge l'export CSV OpenDataSoft
(URL épinglée, override `--local <path>` pour offline/test, parsing tolérant : détecte le
délimiteur, gère les champs tableau `["…"]` et le point `{lat,lon}`), dérive l'AGS
(`ars[:5]+ars[-3:]`), écrit `data/de_communes.csv` avec colonnes `ags,name,land,lat,long`
(un rang par commune). Si le sandbox bloque le téléchargement : commiter un placeholder (en-tête
+ quelques communes réelles, dont Waldeck/Hessen) et le noter — le résolveur et les tests
n'en dépendent pas (fixtures injectées).

### §2 — Parser : reconnaître l'AGS 8 chiffres (`standardize/places.py`, `models/domain.py`)

- `models/domain.py` : ajouter `ags: str | None = None` à `ParsedPlace`.
- `parse_pname` : `AGS_RE = re.compile(r"^\d{8}$")` ; un segment de 8 chiffres exacts est un AGS
  (distinct de l'INSEE/postal 5 chiffres). Le détecter, remplir `parsed.ags`, et **exclure son
  index du tail** (comme l'INSEE) — effet de bord : le Land cesse d'être perdu (passe en
  `region`). Ne pas toucher la détection INSEE/Corse/postal existante.

### §3 — Résolveur `geo/allemagne.py` `resolve_de(parsed, table=None)`

- `load_de_gazetteer() -> {"by_ags": {ags: entry}, "by_name": {norm: [entries]}}` (`@lru_cache`),
  `entry = {"name","land","ags","lat","long"}`. Collision de nom conservée dans la liste `by_name`.
- **Normalisation allemande** `_norm_de(s)` : expanse d'abord `ß→ss`, `ä→ae`, `ö→oe`, `ü→ue`
  (avant le strip d'accents, sinon `ü→u`), puis applique le `_norm` de base (majuscules, sans
  accents). Utilisée des DEUX côtés (requête et gazetteer) → « München »/« Muenchen » matchent.
- `_LAENDER` : ensemble des 16 Länder normalisés (`_norm_de`), pour distinguer un vrai Land
  (« Hesse »/« Hessen ») d'un segment comme « Regierungsbezirk Kassel ».
- `resolve_de(parsed, table=None)` :
  1. `table = table or load_de_gazetteer()`.
  2. Si `parsed.ags` et `parsed.ags in table["by_ags"]` → **autoritaire** (score 1.0,
     `ambiguous=False`, `code=ags`, chaîne `Allemagne › <Land>`, `place_type="Municipality"`,
     lat/lon WGS84, source `« BKG VG250 (AGS) »`).
  3. Sinon `candidates = table["by_name"].get(_norm_de(parsed.commune), [])`. Si vide → `None`.
  4. Land de contexte = premier de `(parsed.region, parsed.departement)` dont `_norm_de(x) in
     _LAENDER`. Si présent et `len(candidates) > 1` → filtrer aux `land` correspondants ; ne
     garder le filtre que s'il laisse ≥1.
  5. **1 candidat → autoritaire** ; **>1 → proposition** (`ambiguous=True`, premier pour
     l'affichage, preuve = nb d'homonymes) ; (0 est déjà géré au point 3).
- **Registry** : `geo/registry.py` `_BY_COUNTRY["Allemagne"] = lambda p: resolve_de(p)`.
  `normalize_country` mappe déjà `Germany/Deutschland → Allemagne`.

### §4 — GPS

Le gazetteer donne `geo_point_2d = {lat, lon}` (WGS84). ResolvedPlace : `lat=<lat>`,
`long=<lon>` — pas d'inversion. (Pas de GeoJSON `[lon,lat]` ici, contrairement à geo.api.gouv.fr :
OpenDataSoft expose déjà `lat`/`lon` nommés.)

## 5. Tests

Par **classe**, hors-ligne, fixtures synthétiques (gazetteer injecté via `table=`), jamais
d'extraits de l'arbre :

- **Parser** : `parse_pname(", Waldeck, 06635021, 34513, Regierungsbezirk Kassel, Hesse, Germany")`
  → `ags == "06635021"`, `commune == "Waldeck"`, `country == "Allemagne"`, Land présent dans
  `region` (plus perdu) ; un segment 5 chiffres reste INSEE/postal (non-régression).
- **Normalisation** : `_norm_de("Großenhain") == _norm_de("Grossenhain")` ;
  `_norm_de("München") == _norm_de("Muenchen")`.
- **Résolveur** (table injectée) : AGS présent → autoritaire (score 1.0, code, GPS lat/lon,
  chaîne `Allemagne › Land`) ; nom+Land unique → autoritaire ; homonyme (« Waldeck » en Hesse
  ET Thuringe) sans Land → `ambiguous=True` ; avec Land Hesse → autoritaire (le bon) ; nom absent
  → `None` ; `resolve_de` honore une table injectée sans réseau.
- **Registry** : `"Allemagne"` routé vers `resolve_de` ; tests existants (France/Suisse/US)
  restent verts.

### Validation réelle
Depuis `genecrew`, `lieux --scope all --dry-run` : mesurer combien des **12 lieux Allemagne** de
l'arbre passent en autoritaire (dont Waldeck+AGS → Waldeck/Hesse, coordonnées correctes) ; zéro
écriture indue ; les homonymes sans Land restent propositions.

## 6. Hors périmètre

Communes **historiques/dissoutes** (fusions allemandes) absentes du VG250 courant → repli
Nominatim/proposition, comme les communes FR fusionnées. Pas de résolution par code postal
(l'AGS et le nom+Land suffisent). Autriche/Suisse alémanique hors sujet (la Suisse a déjà
swisstopo).

## 7. Critère de sortie

(a) Waldeck + AGS `06635021` → Waldeck (Hesse) autoritaire, GPS correct (pas la Thuringe) ;
(b) un homonyme allemand sans Land reste proposition ; (c) `ß`/umlauts normalisés ;
(d) tests par classe verts + registre France/Suisse/US inchangé ; (e) aucun changement du
contrat d'écriture ni de l'API `genecrew` ; (f) le dry-run réel montre des lieux Allemagne
autoritaires non nuls.
