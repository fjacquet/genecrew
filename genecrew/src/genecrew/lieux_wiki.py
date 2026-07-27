"""Enrichissement Wikipédia des lieux : lien vérifié (nom + GPS) et image d'illustration.

Un lien n'est écrit que si l'article français est à la fois HOMONYME et AU BON ENDROIT —
jamais le nom seul. L'ordre des deux questions compte : on cherche PAR LE TITRE puis on
vérifie PAR LA POSITION. L'inverse (géorecherche autour du point, retenue jusqu'ici) trie
par distance et noie la ville sous ses propres rues : les dix articles les plus proches du
centre de Lyon sont des rues et des monuments, l'article « Lyon » n'y figure pas.

L'image est la miniature de l'article (Wikimedia Commons), importée avec attribution.
Append-only.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from crewai_custom_tools.tools.genealogy.geo.score import distance_m, similarity
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAddUrlTool,
    GrampsAttachMediaTool,
    GrampsUploadMediaTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.web.wikipedia import frwiki_page_info, frwiki_search_geo

from genecrew.logging_setup import get_logger

MIN_SIM = 0.85
AMBIGUITY_MARGIN = 0.05
MAX_DIST_M = 10_000  # rayon de vérification : l'article doit tomber sur le lieu
THROTTLE_S = 1.5  # politesse API Wikipédia (429 mesuré)
BACKOFF_429_S = (20, 60)  # une seule reprise se reprenait un 429 (mesuré en production)


def _with_backoff(fn, *args, **kwargs):
    """Reprises espacées quand Wikipédia répond 429 (mesuré en production)."""
    import requests as _requests

    for pause in (*BACKOFF_429_S, None):
        try:
            return fn(*args, **kwargs)
        except _requests.HTTPError as exc:
            if pause is None or getattr(exc.response, "status_code", None) != 429:
                raise
            time.sleep(pause)


def describe_error(exc: Exception) -> str:
    """Nom de l'exception ET code HTTP quand il existe.

    Le nom seul (« HTTPError ») a déjà fait passer une salve de 429 pour une panne
    indéterminée dans un rapport : le code est ce qui dit s'il faut ralentir ou corriger.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__} {status}" if status else type(exc).__name__


_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def title_core(title: str) -> str:
    """Titre d'article sans le désambiguïsateur final : 'Annaba (ville)' -> 'Annaba'. Pure."""
    return _PAREN_RE.sub("", title or "").strip()


def pick_article(place_name: str, candidates: list[dict]) -> dict | None:
    """Best geosearch candidate: similarity on the core title, ambiguity guard. Pure."""
    scored = [
        (c, similarity(place_name, title_core(c.get("title", "")))) for c in candidates
    ]
    scored = [(c, s) for c, s in scored if s >= MIN_SIM]
    if not scored:
        return None
    # `dist` absent -> tout en bas ; `dist == 0` (article pile sur le point) est la
    # meilleure distance possible, pas une distance manquante.
    scored.sort(
        key=lambda t: (-t[1], 1e9 if t[0].get("dist") is None else t[0]["dist"])
    )
    if len(scored) >= 2 and scored[0][1] - scored[1][1] < AMBIGUITY_MARGIN:
        return None  # deux articles aussi bons (homonymes) -> abstention
    return scored[0][0]


def _dist_or_none(lat, lon, article: dict) -> float | None:
    """Distance lieu ↔ article, ou None quand l'article n'a pas de position."""
    if article.get("lat") is None or article.get("lon") is None:
        return None
    return distance_m(
        float(lat), float(lon), float(article["lat"]), float(article["lon"])
    )


def resolve_article(name: str, lat, lon) -> tuple[dict, float] | None:
    """Article vérifié pour un lieu : le titre d'abord, la position ensuite.

    Étage 1 — le titre exact, redirections comprises. Il n'a pas à repasser par la
    similarité : le titre EST le nom demandé, ou la redirection que Wikipédia lui
    associe (`München` → `Munich`). Seule la position reste à vérifier, et c'est elle
    qui écarte Paris (Texas) d'un article sur Paris.

    Étage 2 — la recherche plein texte, pour les titres inexistants et les pages
    d'homonymie sans coordonnées (`Valence` → `Valence (Drôme)`). Le titre rendu n'est
    plus celui demandé : la similarité et la garde d'ambiguïté y reprennent la main.
    """
    info = _with_backoff(frwiki_page_info, name)
    dist = _dist_or_none(lat, lon, info)
    if info.get("url") and dist is not None and dist <= MAX_DIST_M:
        return info, dist

    candidates = []
    for hit in _with_backoff(frwiki_search_geo, name):
        hit_dist = _dist_or_none(lat, lon, hit)
        if hit_dist is not None and hit_dist <= MAX_DIST_M:
            candidates.append({**hit, "dist": hit_dist})
    best = pick_article(name, candidates)
    if best is None:
        return None
    info = _with_backoff(frwiki_page_info, best["title"])
    return (info, best["dist"]) if info.get("url") else None


def has_wikipedia_url(place: dict) -> bool:
    return any(
        "wikipedia.org" in (u.get("path") or "") for u in (place.get("urls") or [])
    )


def run_lieux_wiki(
    client: GrampsClient,
    output_dir,
    *,
    date: str,
    limit: int | None = None,
    images: bool = True,
    dry_run: bool = False,
) -> Path:
    """Enrich GPS-bearing places with a verified frwiki link (+ article image)."""
    dry_run = effective_dry_run(dry_run)
    # Filtrage page par page : `--limit` doit borner le trafic Gramps, pas seulement la
    # liste finale — sur un arbre de plusieurs centaines de lieux, tout paginer avant de
    # trancher ferait de la borne une promesse creuse.
    targets, page = [], 1
    while True:
        batch = client.get_json("/places/", params={"page": page, "pagesize": 200})
        if not batch:
            break
        targets.extend(
            p
            for p in batch
            if p.get("lat") and p.get("long") and not has_wikipedia_url(p)
        )
        if limit and len(targets) >= limit:
            break
        page += 1

    if limit:
        targets = targets[:limit]

    url_tool, up_tool, at_tool = (
        GrampsAddUrlTool(),
        GrampsUploadMediaTool(),
        GrampsAttachMediaTool(),
    )
    linked, imaged, skipped, errors = [], 0, 0, []
    for p in targets:
        name = (p.get("name") or {}).get("value", "")
        if not name or name.startswith(","):
            skipped += 1
            continue
        time.sleep(THROTTLE_S)
        try:
            resolved = resolve_article(name, p["lat"], p["long"])
            if resolved is None:
                skipped += 1
                continue
            info, dist = resolved
            u = json.loads(
                url_tool._run(
                    object_type="places",
                    handle=p["handle"],
                    url=info["url"],
                    description="Wikipédia",
                    dry_run=dry_run,
                )
            )
            if not u["success"]:
                errors.append((name, u["error"]))
                continue
            linked.append(
                (p.get("gramps_id", ""), name, info["title"], round(dist), info["url"])
            )
            if images and info.get("image_url"):
                m = json.loads(
                    up_tool._run(
                        file_url=info["image_url"],
                        description=f"{info['title']} — Wikipédia/Wikimedia Commons "
                        f"({info['url']})",
                        dry_run=dry_run,
                    )
                )
                # Un échec ici laisse le lien posé mais l'image perdue : le rapport doit
                # le dire, sinon il tait une écriture partielle.
                if not m["success"]:
                    errors.append((name, f"image non importée : {m['error']}"))
                else:
                    a = json.loads(
                        at_tool._run(
                            object_type="places",
                            handle=p["handle"],
                            media_handle=m["data"]["handle"],
                            dry_run=dry_run,
                        )
                    )
                    if not a["success"]:
                        errors.append((name, f"image non attachée : {a['error']}"))
                    elif a["data"]["changed"]:
                        imaged += 1
        except Exception as exc:
            get_logger().warning("lieux-wiki: échec pour %s", name, exc_info=True)
            errors.append((name, describe_error(exc)))

    mode = "simulation (dry-run)" if dry_run else "écritures appliquées"
    lines = [
        f"# Enrichissement Wikipédia des lieux — {date}",
        "",
        f"Mode : {mode}.",
        "",
        f"- Lieux candidats (GPS, sans lien wiki) : {len(targets)}",
        f"- Liens vérifiés posés : {len(linked)}",
        f"- Images importées : {imaged}",
        f"- Sans article vérifiable (abstention) : {skipped}",
        f"- Erreurs : {len(errors)}",
        "",
    ]
    if linked:
        lines += ["| Lieu | Article | Distance | URL |", "|---|---|---|---|"]
        lines += [f"| {gid} {n} | {t} | {d} m | {u} |" for gid, n, t, d, u in linked]
    if errors:
        lines += ["", "## Erreurs", ""] + [f"- {n} : {e}" for n, e in errors]
    lines.append("")
    out = Path(output_dir) / "lieux"
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{date}_lieux_wiki.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
