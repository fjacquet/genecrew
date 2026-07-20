# Première crew CrewAI — workflow Audit avec écritures encadrées

> Conception validée le 2026-07-19. Première tranche de la vraie crew d'agents LLM de GeneCrew,
> au-dessus du socle déterministe déjà livré (audit R1–R10, standardisateur lieux/genre/casse).

## 1. Contexte

Tout le socle **déterministe** de GeneCrew est en CLI pur. Le cœur du projet — l'**équipe
d'agents LLM de jugement** — n'existe pas : `crew.py`/`agents.yaml`/`tasks.yaml` sont le template
stock (`researcher`/`{topic}`). On construit la **première tranche** : le workflow **Audit** en
crew à **2 agents** qui interprète les anomalies déterministes et écrit des annotations
**encadrées** dans Gramps. Elle prouve toute la plomberie crew (LLM via OpenRouter/LiteLLM,
`agents.yaml`, câblage des outils, lots, coût) **et** l'infra d'écriture **append-only** —
réutilisées par toutes les crews suivantes.

## 2. Décisions actées (avec l'utilisateur)

1. Première tranche = **Audit + écritures encadrées** (pas la lecture seule).
2. **Wikipedia** est un outil du Détective (outils `WikipediaSearchTool`/`WikipediaArticleTool`
   déjà dans `crewai_custom_tools/tools/web/` — réutilisés).
3. **LLM = OpenRouter** (via LiteLLM), modèle **`openrouter/z-ai/glm-5.2`** (lu depuis `MODEL`
   dans `.env` ; runs live → `OPENROUTER_API_KEY`). **Pas Gemini** (le `CLAUDE.md` disant
   « currently Gemini » est périmé — à corriger dans ce chantier).
4. **2 agents, isolation d'écriture** : le Détective n'a **aucun** outil d'écriture ; seul le
   Chroniqueur écrit.
5. **Dry-run par défaut**, **append-only strict**.

## 3. Périmètre

- Workflow **Audit** uniquement. Par personne signalée : une **note** interprétée marquée
  `[genecrew:audit:<date>:detective]` + un **tag** qualité (`ia-anomalie` = anomalie ferme /
  `ia-a-verifier` = à vérifier).
- **Hors périmètre** (tranches suivantes) : sources/citations (Phase 5), fusion de doublons
  (donnée cœur → reste proposition), les 3 autres workflows et personas, le compte Gramps Editor
  réel (prérequis ops de l'écriture *réelle* seulement — le dry-run n'en a pas besoin).

## 4. Composants

### A. `crewai_custom_tools` — outils d'écriture append-only (manquants)

`src/crewai_custom_tools/tools/genealogy/gramps/write_tools.py` (append) +
`tests/test_genealogy_note_tag_tools.py`. Patrons réutilisés du fichier : `effective_dry_run`,
`get_client`, `_created_handle` (POST = array), GET→modify→PUT de `GrampsUpdateNameTool`.

- `GrampsCreateNoteTool` — POST `/api/notes/` (`text`, `type`), handle client uuid, gated dry-run
  → handle synthétique. Modèle : `GrampsCreatePlaceTool`.
- `GrampsEnsureTagTool` — **idempotent** : cherche un tag par `name` (GET `/api/tags/`), le crée
  sinon (POST ; `Tag` = `name`/`color`/`priority`). Renvoie le handle (existant ou créé).
- `GrampsAttachTool` — **append-only strict** : GET `/api/people/{handle}` → ajoute le handle de
  note à `note_list` et/ou de tag à `tag_list` (dédup), PUT en ne touchant **que** ces deux listes
  (invariant qui refuse tout autre changement). Gated dry-run.

### B. `genecrew` — exposer les findings déterministes

`genecrew/src/genecrew/audit.py` : extraire la collecte en `collect_audit_findings(client, scope,
*, batch_size, limit) -> tuple[list[Anomaly], list[DuplicateCandidate], list[PersonFacts]]` ;
`run_audit` l'appelle puis rend le rapport (CLI inchangé). La crew consomme les `Anomaly`
**structurés en mémoire** (pas de parsing du `.md`).

### C. `genecrew` — la vraie crew (remplace le template)

- `config/agents.yaml` (réécrit) : `detective` (Corrélateur ; consigne : n'écrit jamais, recoupe
  via lecture Gramps + Wikipedia) + `chroniqueur` (rédige les annotations, append-only, marqueur).
  LLM = `MODEL` env (OpenRouter/glm-5.2).
- `config/tasks/audit.yaml` (créer) : `interpreter_anomalies` (Détective → sortie structurée par
  personne : verdict + priorité + texte de note + niveau de tag) → `rediger_annotations`
  (Chroniqueur : `EnsureTag` → `CreateNote` → `Attach` par personne signalée).
- `crew.py` (réécrit) : `@CrewBase Genecrew` — `detective`/`chroniqueur`, write tools **UNIQUEMENT**
  sur le chroniqueur, `Process.sequential`.

### D. `genecrew` — orchestration + CLI

- `src/genecrew/crew_audit.py` (créer) : `run_crew_audit(client, scope, output_dir, *, date,
  batch_size=25, limit=None, dry_run=False)` — findings (B) → lots → `Genecrew().crew().kickoff(
  inputs=…)` par lot → agrège les annotations (dry-run : listées, non écrites) → rapport MD + YAML ;
  checkpoint de reprise ; `effective_dry_run`.
- `main.py` : sous-commande `genecrew crew-audit --scope --limit --batch-size --dry-run --date`.

## 5. Garde-fous

Dry-run par défaut ; write tools structurellement absents du Détective ; append-only (invariant) ;
marqueur `[genecrew:audit:<date>:detective]` ; `--limit` pour borner le coût LLM ; compte Editor
dédié = prérequis ops de l'écriture réelle.

## 6. Tests & validation

- Par **classe** (`httpx.MockTransport`, offline) : les 3 write tools (create note/tag ;
  `EnsureTag` idempotent ; `Attach` append-only refuse tout autre champ ; dry-run n'écrit rien) ;
  wiring crew avec **LLM mocké** ; orchestration **dry-run** (aucune écriture HTTP, rapport produit).
- **Bout-en-bout dry-run** (~25 personnes) : `GENECREW_DRY_RUN=true uv run genecrew crew-audit
  --scope all --limit 25` → rapport interprété + notes/tags simulés cohérents ; **coût/lot mesuré**.
  Puis, sur go explicite + compte Editor + `OPENROUTER_API_KEY`, un lot réel → historique Gramps =
  **uniquement** POST notes/tags + PUT append-only.
- **Critère de sortie** : rapport correct sur ~25 personnes, faux positifs acceptables, coût/lot
  mesuré, écritures = annotations encadrées seulement.

## 7. Exécution

Inline (limite de 200 subagents de session atteinte) : TDD direct, commits par composant, branche
dédiée par dépôt (`feat/crew-audit` côté genecrew, `feat/crew-write-tools` côté cct).
