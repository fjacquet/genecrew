"""Enrichissement Wikipédia des lieux : lien vérifié (nom + GPS) et image d'illustration.

Un lien n'est écrit que si l'article français est à la fois HOMONYME (similarité ≥ seuil)
et AU BON ENDROIT (géorecherche autour du GPS du lieu) — jamais le nom seul. L'image est
la miniature de l'article (Wikimedia Commons), importée avec attribution. Append-only.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from crewai_custom_tools.tools.genealogy.geo.score import similarity
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAddUrlTool,
    GrampsAttachMediaTool,
    GrampsUploadMediaTool,
    effective_dry_run,
)
from crewai_custom_tools.tools.web.wikipedia import frwiki_geosearch, frwiki_page_info

from genecrew.logging_setup import get_logger

MIN_SIM = 0.85
AMBIGUITY_MARGIN = 0.05
THROTTLE_S = 1.5                                   # politesse API Wikipédia (429 mesuré)
BACKOFF_429_S = 20


def _with_backoff(fn, *args, **kwargs):
    """One retry after a pause when Wikipedia answers 429 (measured live)."""
    import requests as _requests
    try:
        return fn(*args, **kwargs)
    except _requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 429:
            time.sleep(BACKOFF_429_S)
            return fn(*args, **kwargs)
        raise
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def title_core(title: str) -> str:
    """Titre d'article sans le désambiguïsateur final : 'Annaba (ville)' -> 'Annaba'. Pure."""
    return _PAREN_RE.sub("", title or "").strip()


def pick_article(place_name: str, candidates: list[dict]) -> dict | None:
    """Best geosearch candidate: similarity on the core title, ambiguity guard. Pure."""
    scored = [(c, similarity(place_name, title_core(c.get("title", ""))))
              for c in candidates]
    scored = [(c, s) for c, s in scored if s >= MIN_SIM]
    if not scored:
        return None
    # `dist` absent -> tout en bas ; `dist == 0` (article pile sur le point) est la
    # meilleure distance possible, pas une distance manquante.
    scored.sort(key=lambda t: (-t[1], 1e9 if t[0].get("dist") is None else t[0]["dist"]))
    if len(scored) >= 2 and scored[0][1] - scored[1][1] < AMBIGUITY_MARGIN:
        return None            # deux articles aussi bons (homonymes) -> abstention
    return scored[0][0]


def has_wikipedia_url(place: dict) -> bool:
    return any("wikipedia.org" in (u.get("path") or "")
               for u in (place.get("urls") or []))


def run_lieux_wiki(client: GrampsClient, output_dir, *, date: str,
                   limit: int | None = None, images: bool = True,
                   dry_run: bool = False) -> Path:
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
        targets.extend(p for p in batch
                       if p.get("lat") and p.get("long") and not has_wikipedia_url(p))
        if limit and len(targets) >= limit:
            break
        page += 1

    if limit:
        targets = targets[:limit]

    url_tool, up_tool, at_tool = GrampsAddUrlTool(), GrampsUploadMediaTool(), GrampsAttachMediaTool()
    linked, imaged, skipped, errors = [], 0, 0, []
    for p in targets:
        name = (p.get("name") or {}).get("value", "")
        if not name or name.startswith(","):
            skipped += 1
            continue
        time.sleep(THROTTLE_S)
        try:
            candidates = _with_backoff(frwiki_geosearch, p["lat"], p["long"])
            best = pick_article(name, candidates)
            if best is None:
                skipped += 1
                continue
            info = _with_backoff(frwiki_page_info, best["title"])
            if not info.get("url"):
                skipped += 1
                continue
            u = json.loads(url_tool._run(object_type="places", handle=p["handle"],
                                         url=info["url"], description="Wikipédia",
                                         dry_run=dry_run))
            if not u["success"]:
                errors.append((name, u["error"]))
                continue
            linked.append((p.get("gramps_id", ""), name, best["title"],
                           round(best.get("dist") or 0), info["url"]))
            if images and info.get("image_url"):
                m = json.loads(up_tool._run(
                    file_url=info["image_url"],
                    description=f"{info['title']} — Wikipédia/Wikimedia Commons "
                                f"({info['url']})",
                    dry_run=dry_run))
                # Un échec ici laisse le lien posé mais l'image perdue : le rapport doit
                # le dire, sinon il tait une écriture partielle.
                if not m["success"]:
                    errors.append((name, f"image non importée : {m['error']}"))
                else:
                    a = json.loads(at_tool._run(object_type="places", handle=p["handle"],
                                                media_handle=m["data"]["handle"],
                                                dry_run=dry_run))
                    if not a["success"]:
                        errors.append((name, f"image non attachée : {a['error']}"))
                    elif a["data"]["changed"]:
                        imaged += 1
        except Exception as exc:
            get_logger().warning("lieux-wiki: échec pour %s", name, exc_info=True)
            errors.append((name, type(exc).__name__))

    mode = "simulation (dry-run)" if dry_run else "écritures appliquées"
    lines = [f"# Enrichissement Wikipédia des lieux — {date}", "",
             f"Mode : {mode}.", "",
             f"- Lieux candidats (GPS, sans lien wiki) : {len(targets)}",
             f"- Liens vérifiés posés : {len(linked)}",
             f"- Images importées : {imaged}",
             f"- Sans article vérifiable (abstention) : {skipped}",
             f"- Erreurs : {len(errors)}", ""]
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
