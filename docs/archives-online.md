# Archives Online — consommer `archives-online.org/Search` sans navigateur

[Archives Online](https://www.archives-online.org/) est le portail fédérateur d'une
cinquantaine d'archives suisses (dont les **Archives d'État de Genève**, `AEG`). Il n'expose
**aucune API** : ni REST, ni OAI-PMH, ni rien d'annoncé sur sa page *Informations*. Son
formulaire est néanmoins pilotable sans navigateur, à condition de parler son protocole.

Protocole relevé et vérifié de bout en bout le **2026-07-28**. Aucune authentification, aucune
clé, aucun jeton anti-CSRF ; `robots.txt` dit `Allow: /`.

## Ce n'est pas une API REST

Une recherche est **asynchrone et fédérée**. Le navigateur ouvre une socket **ASP.NET SignalR
2.x** (hub `searchHub`, monté sur `/signalr`, WebSockets activés), puis déclenche la recherche
par un GET ordinaire. Le portail interroge alors chaque archive participante, et **chaque
réponse est poussée** sur la socket au fur et à mesure. L'appel de recherche lui-même ne rend
pas de résultats.

C'est la conséquence à retenir : **la socket doit être ouverte avant de lancer la recherche**,
sur le même cookie de session. Une recherche lancée sans socket part quand même, répond `200`,
et ses résultats sont poussés à personne.

## Séquence

L'ordre n'est pas négociable.

| # | Appel | Ce qu'on en tire |
|---|---|---|
| 1 | `GET /Search` | cookie de session ASP.NET |
| 2 | `GET /signalr/negotiate?clientProtocol=2.1&connectionData=[{"name":"searchhub"}]` | `ConnectionToken`, `TryWebSockets` |
| 3 | `WSS /signalr/connect?transport=webSockets&clientProtocol=2.1&connectionToken=…&connectionData=…` | la socket, **même cookie** en en-tête |
| 4 | `GET /signalr/start?transport=webSockets&…` | la socket devient active |
| 5 | `GET /Search/ExecuteSearch?SearchModel.…` | seulement `{DefaultCaption, PermanentUrl}` |
| 6 | *(rien à appeler)* | trames `UpdateSearchStatus` poussées sur la socket |

### Paramètres de recherche

Tous préfixés `SearchModel.` sur l'appel `ExecuteSearch` :

`FulltextSearch`, `Archives`, `SearchOption`, `SearchGroups`, `UseTopoTerm`, `YearFrom`,
`YearTo`.

`Archives` est une liste de codes séparés par des virgules (`AEG`, `ACV`, `StAZH`,
`swisscollections`…). La liste complète que le portail envoie lui-même quand rien n'est
décoché se lit dans le `PermanentUrl` que rend `ExecuteSearch` — c'est la source à recopier
plutôt qu'une liste écrite à la main, qui vieillirait.

### Charge utile poussée

Chaque trame `UpdateSearchStatus` porte un objet à quatre clés :

- `GridData` — les lignes de résultat, **de forme variable** (voir piège 5)
- `AllCountText` — la légende, p. ex. `"Alle (4)"`
- `TreeData` — l'arbre des filtres par archive
- `SearchComplete` — booléen, **à ne pas croire** (voir plus bas)

Champs d'une ligne : `ArchiveId`, `Archive`, `Reference`, `Title`, `Date`, `BeginDateISO`,
`BeginApprox`, `EndDateISO`, `EndApprox`, `DescriptionLevel`, `Extent`, `Creator`,
`HasDigitizedItems`, `DetailUrl`, `RecordId`, `RecordPosition`, `Relevancy`, `Timestamp`.

`DetailUrl` pointe directement dans le catalogue de l'archive d'origine
(`dls.staatsarchiv.lu.ch`, `archivportal.tg.ch`, `swisscollections.ch`…), pas dans le portail.

## Cinq pièges, tous mesurés

1. **La socket avant la recherche.** Détaillé ci-dessus.
2. **`SearchModel.Archives` est obligatoire.** Sans lui : socket connectée, `ExecuteSearch`
   à `200`, et **zéro trame**. Aucun message d'erreur — l'absence de résultat ressemble à
   une recherche qui ne trouve rien.
3. **La casse des noms SignalR.** Le fil annonce `SearchHub` / `UpdateSearchStatus` ; le proxy
   JavaScript généré par ASP.NET les met en minuscules (`$.connection.searchHub`,
   `on("updateSearchStatus")`). Un client écrit d'après le JavaScript du site ne reconnaît
   donc aucune trame. Comparer sans tenir compte de la casse.
4. **`SearchComplete` ne bascule pas.** Mesuré à `False` pendant 35 s sur deux essais, alors
   que le nombre de lignes était figé à sa valeur finale au bout de 2 s. Attendre ce drapeau
   fait attendre indéfiniment : il faut une heuristique d'inactivité (plus de nouvelle ligne
   depuis N secondes) et une borne dure.
5. **`GridData` change de forme d'une trame à l'autre** : tantôt la liste des lignes
   directement, tantôt un objet Kendo `{"Data": [...], "Total": n}`. Un client qui suppose
   l'une des deux tombe en `AttributeError` au milieu de la recherche, après avoir déjà
   collecté des lignes — l'échec ne se voit donc pas au premier essai.

Détail Python, sans rapport avec le portail : `websockets` lit le magasin de certificats du
système, vide sur macOS. Lui passer explicitement le paquet de `certifi`, celui-là même
qu'utilise `httpx`, sinon la poignée de main TLS échoue en
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`.

## Ce que le portail sait trouver — et ce qu'il ne sait pas

C'est la limite décisive, et elle n'a rien de technique.

Le portail indexe des **descriptions archivistiques** au sens ISAD(G) — fonds, séries,
articles — **pas des personnes**. Il n'y a pas d'index nominatif derrière.

Mesures du 2026-07-28 :

- `Pagan Chastel` → 4 lignes : *Luzerner Kantonsblatt 2000*, trois inventaires de la
  bibliothèque cantonale de Thurgovie. Aucun rapport avec la famille.
- `Petit-Saconnex` → bruit schaffhousois et bâlois.
- **`AEG` n'a renvoyé aucune ligne dans l'un ou l'autre essai**, alors que les Archives d'État
  de Genève sont un participant déclaré du portail.

Donc : ce portail ne répondra jamais à « Jean Pagan a-t-il épousé Pernette Chastel ». Il sert
à trouver **quelle cote** couvre une paroisse et une période, et si elle est numérisée
(`HasDigitizedItems` + `DetailUrl`) — c'est-à-dire exactement ce qui alimente une source et
une citation Gramps. Pour Genève, il ne remplace pas le catalogue propre de l'AEG.

## Place éventuelle dans GeneCrew

Rien n'est câblé à ce jour. Si ça l'était :

- côté **bibliothèque** (`crewai_custom_tools`), à côté des résolveurs d'archives, jamais dans
  `genecrew` qui ne tient que l'orchestration ;
- en **lecture seule**, produisant des Pistes relues par un humain — comme `propose wikidata`
  et `propose dhs`, qui ne créent aucune citation d'eux-mêmes ;
- coût à peser : un client SignalR asynchrone dans une base par ailleurs `httpx` synchrone,
  pour une source qui ne rend que des cotes.

Courtoisie : une seule recherche éventaille l'appel sur une cinquantaine d'archives. Ne pas
boucler dessus sans temporisation.

## Client minimal

```python
import asyncio, json, ssl, urllib.parse
import certifi, httpx, websockets

BASE = "https://www.archives-online.org"
HUB = json.dumps([{"name": "searchhub"}], separators=(",", ":"))
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


async def search(query: str, archives: str, idle: float = 8.0, cap: float = 60.0) -> list[dict]:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0, follow_redirects=True) as http:
        await http.get("/Search")                                    # cookie de session

        common = {"clientProtocol": "2.1", "connectionData": HUB}
        token = (await http.get("/signalr/negotiate", params=common)).json()["ConnectionToken"]
        transport = {"transport": "webSockets", "connectionToken": token, **common}
        ws_url = f"wss://www.archives-online.org/signalr/connect?{urllib.parse.urlencode(transport)}"
        cookie = "; ".join(f"{k}={v}" for k, v in http.cookies.items())

        # La socket AVANT la recherche : sinon les résultats sont poussés à personne.
        async with websockets.connect(ws_url, additional_headers={"Cookie": cookie},
                                      ssl=SSL_CONTEXT) as socket:
            await http.get("/signalr/start", params=transport)
            await http.get("/Search/ExecuteSearch", params={
                "SearchModel.FulltextSearch": query,
                "SearchModel.Archives": archives,       # obligatoire, sinon zéro trame
                "SearchModel.SearchOption": "0",
                "SearchModel.UseTopoTerm": "false",
            }, headers={"X-Requested-With": "XMLHttpRequest"})

            rows: dict[str, dict] = {}
            loop = asyncio.get_running_loop()
            hard_stop, last_row = loop.time() + cap, loop.time()
            # `SearchComplete` reste faux : on s'arrête sur l'inactivité, pas sur le drapeau.
            while loop.time() < hard_stop and loop.time() - last_row < idle:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=idle)
                except (TimeoutError, asyncio.TimeoutError):
                    break
                for message in json.loads(raw).get("M") or []:
                    if (message.get("M") or "").lower() != "updatesearchstatus":
                        continue                        # le fil dit `UpdateSearchStatus`
                    grid = message["A"][0].get("GridData") or []
                    # Tantôt la liste, tantôt {"Data": [...]} : accepter les deux formes.
                    for row in (grid.get("Data") if isinstance(grid, dict) else grid) or []:
                        if row["RecordId"] not in rows:
                            rows[row["RecordId"]] = row
                            last_row = loop.time()
            return list(rows.values())
```

`archives` se recopie du `PermanentUrl` rendu par `ExecuteSearch`, ou se restreint à ce qui
intéresse (`"AEG"`, `"AEG,ACV,AEN"`…).
