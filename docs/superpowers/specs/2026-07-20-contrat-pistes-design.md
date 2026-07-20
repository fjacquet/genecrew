# Contrat de consignation des pistes de recherche

> Conception validée le 2026-07-20. Premier sous-projet de la **Phase 4 — Pistes de recherche**
> (`document-de-travail.md` §6.3). Objectif : définir **le contrat de sortie** que toutes les
> sources de pistes respecteront, et le prouver sur une source déjà en place. Ni Gallica, ni
> Wikidata, ni détection de lacunes : ce sont les sous-projets suivants, et ils consommeront ce
> contrat.

## 1. Contexte

La Phase 3 (standardisation) est franchie. La Phase 4 est spécifiée au §6.3 :

> **Tâches** : T1 identifier les lacunes par personne ; T2 interroger les API (MatchID pour les
> décès France ≥ 1970 en recherche floue ; Gallica SRU pour la presse et les registres matricules ;
> Wikidata ; DHS pour la Suisse ; Scriptorium pour la presse vaudoise ; recherche web) ; T3
> consigner : note `piste` par personne (URL, requête exacte rejouable, degré de correspondance) +
> tag `ia-piste` ; T4 rapport de pistes classées par probabilité.
>
> **Règle de preuve** : une piste n'est jamais un fait — **aucune citation créée à ce stade**.

### 1.1 Le mot « piste » n'existe pas dans le code

Vérifié : `piste` n'apparaît que dans les prompts de la crew (`config/tasks/audit.yaml`,
`config/agents.yaml`), jamais dans un module. Aucune note `piste`, aucun tag `ia-piste`, aucune
notion de degré de correspondance consigné.

### 1.2 Ce qui existe relève d'un autre workflow

`propose deaths` (`deces.py`, MatchID) et `propose military` (`militaires.py`, Mémoire des hommes)
produisent des **propositions de citation**, appliquées ensuite par `apply citations`. Ce sont donc
des **faits candidats** — Workflow 4 (fiabilisation), pas Workflow 3.

Le §6.3 interdit explicitement la citation au stade piste. La Phase 4 introduit par conséquent un
**type de sortie réellement nouveau**, et non une variante de l'existant.

### 1.3 Périmètre trop large pour une seule spec

Le §6.3 empile quatre sous-systèmes indépendants : détection de lacunes, sources, consignation,
classement. Chacun aura sa spec, son plan, son cycle. **Celui-ci traite la consignation** — retenu
en premier parce qu'il est le contrat que les trois autres devront respecter : le définir en dernier
laisserait chaque source inventer son format.

## 2. Décisions actées (avec l'utilisateur)

1. **Une note par piste**, autonome, marquée par sa source. Append-only strict : une nouvelle piste
   s'ajoute sans toucher aux précédentes, une piste infirmée se supprime seule. Écarté :
   la note agrégée par personne, qui imposerait de relire et réécrire (donc de casser
   l'append-only et de compliquer l'idempotence), et le rattachement à l'événement visé —
   impossible pour une lacune, puisque l'événement manquant est précisément ce qu'on cherche.

2. **L'identité d'une piste est l'identifiant externe de sa source** — ark Gallica, id MatchID,
   Q-item Wikidata. Pas la date du passage : le pipeline retournera sur les mêmes personnes
   pendant des mois, et un marqueur daté recréerait la même piste à chaque exécution.

3. **Sans identifiant stable : une clé composée des champs identifiants**, marquée comme dérivée.
   Mesuré le 2026-07-20 : **68,8 % des fiches Mémoire des hommes n'ont pas de permalien**
   (1 798 071 lignes sur 2 613 297) ; les bases 1939-1945, Indochine, Algérie et TOE sont à
   **100 % sans lien**. Les exclure reviendrait à n'émettre aucune piste militaire hors 1914-1918.

4. **Écriture directe**, note append-only + tag. L'ADR 0001 l'autorise pour les annotations qui ne
   modifient aucune donnée cœur ; c'est déjà ce que fait la crew d'audit. Aucune question posée à
   l'utilisateur sur ce point : la politique du projet le tranche.

5. **Les fortes dans l'arbre, les faibles dans le rapport seulement.** L'arbre reste sobre, rien
   n'est perdu. Coût assumé : deux endroits à consulter pour le tableau complet.

6. **Aucun nouveau verbe CLI dans ce sous-projet.** Le verbe arrivera avec la première source
   complète, quand on aura vu deux sources plutôt qu'une — figer la grammaire maintenant serait
   prématuré.

7. **`propose deaths` reste inchangé** dans son comportement actuel. Il gagne seulement l'émission
   de pistes en amont : ses candidats faibles, aujourd'hui jetés en silence, deviennent des pistes
   rapportées.

## 3. Distinction entre URL fabriquée et clé dérivée

Le backlog est catégorique sur les permaliens MdH :

> Fabriquer une URL par motif produirait des liens morts écrits dans Gramps *comme preuves* — le
> pire résultat possible pour une base généalogique.

La clé dérivée de la décision 3 **n'est pas une URL** et ne s'affiche jamais comme source. C'est un
identifiant interne, opaque, dont le seul rôle est de reconnaître une piste déjà consignée. La
distinction doit rester explicite dans le code comme dans la note :

| | URL fabriquée | Clé dérivée |
| --- | --- | --- |
| Rôle | se présente comme preuve | reconnaître un doublon |
| Visible par l'utilisateur | oui, cliquable | non, dans le marqueur |
| Si elle est fausse | lien mort donné pour une source | doublon, sans plus |
| Statut | **interdit** | retenu |

Une note dont l'identité est dérivée **doit le dire** et indiquer comment retrouver la fiche à la
main.

## 4. Le modèle `Piste`

Vit dans `crewai_custom_tools/tools/genealogy/models/domain.py`, aux côtés de `Proposition` et
`PropositionAudit`, avec un ré-export depuis `genecrew/pistes.py` — même patron que
`genecrew/propositions.py`, et pour la même raison : les futures sources (Gallica SRU, Wikidata)
seront des outils de bibliothèque et devront émettre ce type.

```python
class Piste(BaseModel):
    """Une piste de recherche : ce qu'une source suggère, jamais ce qu'elle prouve."""

    gramps_id: str                    # la personne visée
    handle: str
    source: str                       # "matchid" | "mdh" | "gallica" | "wikidata" | …
    identite: str                     # identifiant externe stable, OU clé dérivée
    identite_derivee: bool = False    # True -> la note dira que le permalien est absent
    url: str | None = None            # None si la source n'en donne pas — JAMAIS fabriquée
    requete: str                      # la requête exacte, rejouable telle quelle
    concordances: list[str]           # ce qui colle
    divergences: list[str]            # ce qui ne colle pas
    force: Literal["forte", "faible"]
```

Le champ `force` est **dérivé**, pas saisi : il est calculé par la règle du §5 et jamais fourni par
l'appelant. Il est typé `Literal` et non `str` libre — le backlog demande ce durcissement pour les
champs à ensemble fermé, *« pour que Pydantic garantisse le contrat du premier émetteur, avant que
le pattern se répande »*. C'est ici le premier émetteur.

### 4.1 Composition de la clé dérivée

Les champs qui composent la clé sont **déclarés par la source**, pas devinés par `pistes.py` : seule
la source sait ce qui identifie une de ses fiches. Le contrat impose seulement qu'ils soient
**stables** (jamais un rang de résultat, jamais une date de consultation) et **normalisés** avant
hachage (casse, accents, espaces) — sans quoi la même fiche produirait deux clés selon
l'orthographe rendue.

Pour Mémoire des hommes : `nom | prénom | date de décès | unité`. Le hachage doit être
déterministe **entre processus** — donc `hashlib`, jamais `hash()`, qui est salé à chaque
exécution.

## 5. Ce qui fait une piste forte

**Au moins deux facteurs concordants indépendants, et aucune divergence dure.**

Délibérément **catégoriel, pas numérique**. Trois raisons, toutes tirées de l'expérience du dépôt :

- Un score de 1.0 peut masquer une ambiguïté — mesuré aujourd'hui sur le résolveur de lieux, où
  Nominatim rendait `score=1.0` sur un homonyme.
- La règle projet « une année seule n'est jamais discriminante » est catégorielle par nature :
  un nom + une année ne font pas deux facteurs indépendants, un nom + une date complète oui.
- Un seuil flottant devient un jugement caché dans le code, que personne ne relit — alors qu'une
  règle catégorielle s'énonce dans la note elle-même.

**Facteurs indépendants** : le nom, le prénom, une date complète, un lieu, une unité militaire, une
profession. L'année seule n'en est pas un ; elle qualifie une date sans la constituer.

**Divergence dure** : une contradiction que rien ne peut expliquer — départements incompatibles,
décès antérieur à la naissance, écart d'âge impossible. Une divergence dure dégrade en `faible`
quelles que soient les concordances.

Le calcul est une **fonction pure**, testable sans réseau ni Gramps.

## 6. Le marqueur

```
[genecrew:piste:<source>:<identite>]
```

Exemples réels :

```
[genecrew:piste:matchid:a1b2c3d4]
[genecrew:piste:gallica:ark:/12148/bpt6k9764895t]
[genecrew:piste:wikidata:Q25398054]
[genecrew:piste:mdh:k=6f2a91c4]              ← identité dérivée
```

Le préfixe `k=` signale une clé dérivée, lisible d'un coup d'œil dans Gramps.

**Idempotence** : avant d'écrire, on lit les notes déjà rattachées à la personne et on cherche le
marqueur. S'il existe, on n'écrit rien. C'est ce qui rend le pipeline rejouable pendant des mois
sans accumuler de doublons.

## 7. Le corps de la note

La note **rapporte, elle ne conclut pas**. Aucun verdict, aucune formulation qui laisserait croire
à un fait établi.

```
[genecrew:piste:matchid:a1b2c3d4]
Piste de décès — MatchID / INSEE

Correspondance : FORTE
  concordent : nom (SOULAT), prénom (Kléber), date de naissance complète (05/07/1888)
  divergent  : —

URL : https://deces.matchid.io/id/a1b2c3d4
Requête rejouable : nom=SOULAT&prenom=Kleber&date_naissance=1888-07-05

Une piste n'est pas un fait : à vérifier avant toute citation.
```

Pour une source sans permalien :

```
[genecrew:piste:mdh:k=6f2a91c4]
Piste militaire — Mémoire des hommes

Correspondance : FAIBLE
  concordent : nom (SOULAT), prénom (Hoche)
  divergent  : —
  absent     : date de décès dans l'arbre, donc non recoupable

Permalien ABSENT de la source (68,8 % des fiches).
Pour retrouver la fiche : memoiredeshommes.defense.gouv.fr,
recherche par nom + date de décès.
Requête rejouable : nom=SOULAT&prenom=Hoche

Une piste n'est pas un fait : à vérifier avant toute citation.
```

(Cette seconde note, étant `faible`, n'irait **pas** dans l'arbre — elle est montrée ici pour
illustrer la mention d'absence de permalien, qui s'applique aussi aux pistes fortes sans URL.)

## 8. Où ça s'écrit

| Force | Arbre Gramps | Rapport Markdown |
| --- | --- | --- |
| `forte` | note `Research` + tag `ia-piste` sur la personne | oui |
| `faible` | **rien** | oui |

Rapport : `output/pistes/<date>_pistes.md`, avec les deux populations séparées et, pour chacune, le
détail concordances/divergences. Le tag `ia-piste` est obtenu par `GrampsEnsureTagTool`
(idempotent, ne crée jamais de doublon).

Le mode simulation suit la convention du dépôt : `--dry-run` par commande **ou** `GENECREW_DRY_RUN`,
via `effective_dry_run`. Le rapport annonce le mode **effectif**, donc il ne prétend jamais avoir
écrit ce qui a été simulé.

## 9. Découpage des modules

| Fichier | Responsabilité |
| --- | --- |
| `crewai_custom_tools/.../models/domain.py` | le modèle `Piste` (les sources de bibliothèque l'émettront) |
| `genecrew/src/genecrew/pistes.py` | la règle de force (pure), le marqueur, la lecture d'idempotence, l'écriture note+tag, le rendu du rapport |
| `genecrew/src/genecrew/deces.py` | émet des `Piste` en plus de ses propositions existantes |

`pistes.py` reste petit et sans état : entrées explicites, sorties explicites, aucun accès réseau
en dehors du client Gramps qu'on lui passe.

## 10. Tests

Offline, sur client Gramps mocké. Les cinq qui comptent :

1. **Idempotence** — deux passages sur la même piste n'écrivent qu'une note. C'est le test qui
   justifie tout le §6.
2. **Une faible ne touche jamais l'arbre** — elle apparaît au rapport, aucun POST note ni tag.
3. **Aucune URL fabriquée** — une source sans permalien produit `url is None` et une note qui le
   dit ; rien dans le corps ne ressemble à un lien.
4. **La clé dérivée est stable** — mêmes champs d'entrée, même clé, entre deux exécutions et deux
   processus (donc pas de `hash()` Python, qui est salé par exécution).
5. **Une divergence dure dégrade** — une piste par ailleurs bien concordante passe en `faible` dès
   qu'une contradiction irréductible apparaît.

Plus la règle de force elle-même, testée comme fonction pure : un facteur ne suffit pas, l'année
seule ne compte pas comme facteur, deux facteurs indépendants suffisent.

## 11. Hors périmètre (YAGNI)

- **La détection de lacunes** — sous-projet suivant. Ici, l'appelant fournit la personne et la
  piste ; on ne cherche pas qui a besoin de quoi.
- **Gallica, Wikidata, DHS, Scriptorium** — chacun sa spec. Ce contrat existe précisément pour
  qu'ils n'aient pas à réinventer leur format.
- **Le classement par probabilité** (§6.3, T4) — le rapport sépare fortes et faibles, sans les
  ordonner finement. Un classement suppose une échelle, donc un score, donc exactement ce que le
  §5 écarte pour l'instant. À rouvrir quand plusieurs sources coexisteront et qu'on aura de quoi
  comparer.
- **Un verbe CLI** — cf. décision 6.
- **La reprise sur checkpoint** — `checkpoint.py` existe et sera branché quand une source parcourra
  tout l'arbre. Ici, le volume est celui que l'appelant fournit.
