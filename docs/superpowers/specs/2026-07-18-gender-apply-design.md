# `gender-apply` — application des corrections de genre — Design

> Statut : approuvé (brainstorming) — 2026-07-18
> Portée : un incrément autonome de GeneCrew. **Premier outil qui écrit un FAIT** dans Gramps.
> Relâche l'ADR 0008 de façon bornée (nouvel ADR 0009).

## 1. Contexte & objectif

`genecrew gender` (lecture seule) produit des propositions de genre à partir de la table
prénom→sexe **INSEE+OFS** (~85 500 prénoms). Sur l'arbre réel, il révèle notamment une erreur
systématique d'import (plusieurs « Philippe » marqués `F`). L'utilisateur veut **appliquer** ces
corrections — c'est-à-dire **écrire** le genre dans Gramps — automatiquement au-dessus d'un seuil
de confiance, sans curation manuelle.

C'est le **write le plus sensible du projet** : il modifie une donnée cœur (un *fait*), ce que
l'ADR 0008 réservait à des propositions. La table enrichie INSEE+OFS a supprimé les faux positifs
franco-suisses connus (« Ami », « Marie-Joseph » abstiennent désormais au niveau donnée), ce qui
rend l'auto-application défendable au-dessus d'un seuil élevé.

### Décisions actées (brainstorming)

1. **Source = re-inférence live** sur un périmètre. `gender-apply` rescanne l'arbre et recalcule
   l'inférence sur données FRAÎCHES ; il n'écrit jamais sur une info périmée. Le YAML de
   `genecrew gender` reste un aperçu humain, non consommé.
2. **Types écrits = contradictions ET genres inconnus** : corrige les genres posés mais contredits
   (Philippe=F → M) ET remplit les genres inconnus (U → M/F).
3. **Seuil = `ratio ≥ 0.98`** (en plus du `≥ 50` de base d'`infer_sex`). **Aucun garde-fou
   supplémentaire** : la table INSEE+OFS enrichie + le seuil suffisent. Limite résiduelle assumée :
   un prénom rare/étranger à fort ratio et faible volume (≥ 50) pourrait être écrit à tort.
4. **Déterministe (CLI)**, pas d'agent LLM : l'application d'un genre est mécanique ; le
   déterminisme est une sécurité sur donnée cœur. `GrampsUpdateGenderTool` est néanmoins un
   `BaseTool` réutilisable plus tard par un agent Chroniqueur.
5. **Commande distincte** `genecrew gender-apply` ; `genecrew gender` reste strictement lecture seule.

## 2. Composants

### 2.1 `GrampsUpdateGenderTool` (dans `crewai_custom_tools`, `gramps/write_tools.py`)

Deuxième outil d'écriture, même patron que `GrampsUpdateNameTool` (GET → modifie → PUT).

```python
class GrampsUpdateGenderInput(BaseModel):
    handle: str
    gender: int          # 0=F, 1=M, 2=U (représentation Gramps)
    dry_run: bool = False

class GrampsUpdateGenderTool(BaseTool):
    name = "gramps_update_gender"
    @api_tool(provider="GrampsWeb", endpoint="UpdateGender")
    def _run(self, handle, gender, dry_run=False):
        dry_run = dry_run or os.environ.get("GENECREW_DRY_RUN","").strip().lower() in ("1","true","yes")
        person = client.get_object("people", handle)
        old = person.get("gender", 2)
        change = {"handle": handle, "gramps_id": person.get("gramps_id"),
                  "old": old, "new": gender, "dry_run": dry_run}
        if gender == old:                       # no-op : rien à écrire
            change["noop"] = True
            return ok(change)
        person["gender"] = gender
        if not dry_run:
            client.request("PUT", f"/people/{handle}", json=person)
        return ok(change)
```

- Gardé par le paramètre `dry_run` **ET** le global `GENECREW_DRY_RUN` (défaut = simulation),
  exactement comme `GrampsUpdateNameTool` (l'env ne peut que *forcer* la simulation).
- **No-op** si le genre demandé égale l'actuel (aucun PUT).
- Écriture **réversible** : Gramps Web journalise les écritures API dans l'historique des
  transactions (`/api/transactions/history`, undo disponible) — non implémenté ici, filet manuel.
- Exporté dans `__all__` (comme `GrampsUpdateNameTool`) → réutilisable par un futur agent.

### 2.2 Orchestration (dans `genecrew`, `gender_apply.py`)

```python
_SEX_TO_INT = {"F": 0, "M": 1}          # infer_sex renvoie "F"/"M" ; Gramps 0/1

def run_gender_apply(client, scope, output_dir, *, date, min_ratio=0.98,
                     batch_size=25, limit=None, dry_run=False,
                     table=None) -> Path:
    table = table if table is not None else load_prenoms_table()
    tool = GrampsUpdateGenderTool()
    applied, below, errors = [], [], []
    for batch in iter_people_batches(client, fetcher, scope, batch_size, limit):
        for p in batch:
            inf = infer_sex(p.given, table)
            if inf.sex is None:
                continue
            if inf.ratio < min_ratio:
                if p.sex == "U" or inf.sex != p.sex:
                    below.append((p, inf))      # aurait qualifié mais sous le seuil
                continue
            if p.sex != "U" and inf.sex == p.sex:
                continue                          # déjà correct
            payload = json.loads(tool._run(handle=p.handle,
                                           gender=_SEX_TO_INT[inf.sex], dry_run=dry_run))
            (applied if payload["success"] else errors).append((p, inf, payload))
    # écrit un rapport Markdown dans output/inference/<date>_genres_appliques_<scope>.md
```

- Réutilise `iter_people_batches` + `FactsFetcher` + `infer_sex` (aucune nouvelle logique
  d'inférence). `table` injectable pour les tests.
- Rapport pur (`render_apply_report`) : tableau des **appliqués** (id, personne, ancien→nouveau,
  ratio, type inconnu/contradiction), un compte des **sous le seuil**, et les **erreurs**.

### 2.3 CLI (`genecrew/src/genecrew/main.py`)

`genecrew gender-apply [--scope all] [--min-ratio 0.98] [--limit N] [--dry-run] [--date]`.
Usage recommandé : lancer d'abord en `--dry-run` (ou avec `GENECREW_DRY_RUN=true`, le défaut du
`.env`), relire le rapport, puis écrire pour de vrai.

## 3. Flux de données

```
Gramps (live) --FactsFetcher--> PersonFacts(given, sex)
   --infer_sex(given, table)--> GenderInference(sex, ratio, total)
   --filtre: sex≠None, ratio≥min_ratio, (U ou inf.sex≠sex)-->
   GrampsUpdateGenderTool(handle, _SEX_TO_INT[sex]) --PUT--> Gramps
   --> rapport appliqués / sous-seuil / erreurs
```

## 4. Gestion d'erreur

- Personne au prénom vide ou non couvert → `infer_sex` abstient → ignorée.
- Genre déjà correct → skip (pas de no-op inutile côté API : le filtre l'exclut avant l'appel).
- Échec d'écriture (PUT en erreur) → enveloppe `err` → consignée dans `errors[]`, **ne casse pas
  le lot** ; les autres continuent.
- `GENECREW_DRY_RUN=true` (défaut) → aucun PUT, le rapport indique « simulation ».

## 5. ADR 0009 — écritures de genre bornées à haute confiance

Nouvel ADR qui **relâche** l'ADR 0008 (« genre = fait → proposition ») pour ce cas précis :
au-dessus de `min_ratio` (0.98) sur la table INSEE+OFS, le genre peut être **écrit** en direct
(auto), réversible et gated par le double switch dry-run. Justification : la table souveraine
enrichie rend la confiance mesurable et les faux positifs connus ont été supprimés au niveau
donnée. 0008 reste la règle par défaut ; 0009 est l'exception encadrée. Documente la limite
résiduelle (rares/étrangers, faible volume).

## 6. Tests

### 6.1 `GrampsUpdateGenderTool` (cct, mock httpx)
- écrit le genre via PUT (`gender` int correct dans le payload) ;
- `dry_run=True` → **aucun** PUT ; `GENECREW_DRY_RUN=true` force la simulation même si `dry_run=False` ;
- no-op si `gender == old` (aucun PUT, `noop=True`).

### 6.2 `run_gender_apply` (genecrew, mock httpx, table injectée)
- personne `U` + prénom ≥ 0.98 → PUT du bon genre ;
- contradiction (`M` + prénom `F` ≥ 0.98) → PUT ;
- prénom entre 0.95 et 0.98 → **pas** de PUT (listé « sous le seuil ») ;
- genre déjà correct → **pas** de PUT ;
- `dry_run=True` → **aucun** PUT (le mock lève sur PUT), le rapport liste quand même les cibles ;
- contenu du rapport (appliqués / sous-seuil / erreurs).

## 7. Fichiers touchés

**`crewai_custom_tools`**
- `src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` (+`GrampsUpdateGenderTool`)
- `src/crewai_custom_tools/__init__.py` (`__all__` + bump `0.10.0` → `0.11.0`)
- `pyproject.toml`, `tests/test_scaffold.py` (bump lockstep)
- `tests/test_genealogy_write_tools.py` (tests du nouvel outil)

**`genecrew`**
- `genecrew/src/genecrew/gender_apply.py` (nouveau : `run_gender_apply` + rendu pur)
- `genecrew/src/genecrew/main.py` (sous-commande `gender-apply`)
- `genecrew/tests/test_gender_apply.py`, `genecrew/tests/test_cli_gender_apply.py`
- `uv.lock` (sync 0.11.0)

**Docs**
- `docs/adr/0009-ecritures-genre-haute-confiance.md`
- `docs/USER_GUIDE.md` (section « Appliquer les corrections de genre »)

## 8. Hors périmètre (YAGNI)

- Undo automatique (on s'appuie sur l'historique des transactions Gramps).
- Écriture d'autres faits (dates, relations) — restent en propositions (ADR 0008).
- Curation interactive / agent LLM (déterministe assumé).
- Consommer/valider le YAML de `genecrew gender` (re-inférence live à la place).
