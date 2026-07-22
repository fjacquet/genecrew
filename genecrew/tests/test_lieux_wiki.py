"""Offline tests for the verified-Wikipedia place enrichment."""

import json

import httpx
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.lieux_wiki import (
    has_wikipedia_url,
    pick_article,
    run_lieux_wiki,
    title_core,
)

from genecrew import lieux_wiki

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


# --- helpers purs ---


def test_title_core_strips_disambiguator():
    assert title_core("Annaba (ville)") == "Annaba"
    assert title_core("Tiffech") == "Tiffech"


def test_pick_article_verifies_name_and_prefers_distance():
    cands = [{"title": "Hanancha", "dist": 5066.3}, {"title": "Tiffech", "dist": 3.8}]
    assert pick_article("Tiffech", cands)["title"] == "Tiffech"
    # nom seul insuffisant : rien d'homonyme au bon endroit -> None
    assert pick_article("Bourges", cands) is None


def test_pick_article_abstains_on_two_distinct_matches():
    cands = [
        {"title": "Sidi Fredj", "dist": 100.0},
        {"title": "Sidi Fredj (Alger)", "dist": 120.0},
    ]
    assert pick_article("Sidi Fredj", cands) is None


def test_pick_article_treats_an_exact_match_as_nearest(monkeypatch):
    """`dist == 0` (article pile sur les coordonnées) n'est pas une distance manquante.

    La garde d'ambiguïté masque le défaut aujourd'hui : la distance ne départage que des
    similarités identiques, cas où l'on s'abstient de toute façon. On neutralise donc la
    garde pour exercer le classement lui-même — c'est la condition dans laquelle le piège
    mordrait si le seuil venait à bouger.
    """
    monkeypatch.setattr(lieux_wiki, "AMBIGUITY_MARGIN", 0.0)
    cands = [{"title": "Tiffech", "dist": 5000.0}, {"title": "Tiffech", "dist": 0.0}]
    assert pick_article("Tiffech", cands)["dist"] == 0.0


def test_pick_article_still_ranks_a_missing_distance_last(monkeypatch):
    monkeypatch.setattr(lieux_wiki, "AMBIGUITY_MARGIN", 0.0)
    cands = [{"title": "Tiffech"}, {"title": "Tiffech", "dist": 42.0}]
    assert pick_article("Tiffech", cands)["dist"] == 42.0


def test_has_wikipedia_url():
    assert has_wikipedia_url({"urls": [{"path": "https://fr.wikipedia.org/wiki/X"}]})
    assert not has_wikipedia_url({"urls": [{"path": "https://autre.org"}]})
    assert not has_wikipedia_url({})


# --- orchestration hors-ligne ---

PLACE = {
    "handle": "HT",
    "gramps_id": "P0358",
    "name": {"value": "Tiffech"},
    "lat": "36.1917",
    "long": "7.7861",
    "urls": [],
    "media_list": [],
    "_class": "Place",
    "place_type": "Municipality",
}


def test_run_lieux_wiki_links_and_images_verified(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_geosearch",
        lambda lat, lon, **kw: [{"title": "Tiffech", "dist": 3.8}],
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "title": "Tiffech",
            "url": "https://fr.wikipedia.org/wiki/Tiffech",
            "extract": "…",
            "image_url": "https://upload.wikimedia.org/x.png",
            "image_name": "x.png",
        },
    )
    mocker.patch(
        "requests.get",
        return_value=mocker.MagicMock(
            content=b"PNG",
            headers={"Content-Type": "image/png"},
            raise_for_status=lambda: None,
        ),
    )

    state = {"puts": [], "media_created": 0}

    def h(request):
        pth, m = request.url.path, request.method
        if m == "GET" and pth == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(200, json=[dict(PLACE)] if page == 1 else [])
        if m == "GET" and pth == "/api/places/HT":
            return httpx.Response(200, json=dict(PLACE))
        if m == "POST" and pth == "/api/media/":
            state["media_created"] += 1
            return httpx.Response(201, json=[{"type": "add", "handle": "MED1"}])
        if m == "GET" and pth == "/api/media/MED1":
            return httpx.Response(200, json={"handle": "MED1", "mime": "image/png"})
        if m == "PUT":
            state["puts"].append((pth, json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_lieux_wiki(client, tmp_path, date="2026-07-19")

    md = report.read_text(encoding="utf-8")
    assert "Liens vérifiés posés : 1" in md and "Images importées : 1" in md
    place_puts = [b for p_, b in state["puts"] if p_ == "/api/places/HT"]
    assert any(
        u.get("path") == "https://fr.wikipedia.org/wiki/Tiffech"
        for b in place_puts
        for u in b.get("urls", [])
    )
    assert any(
        any(r.get("ref") == "MED1" for r in b.get("media_list", [])) for b in place_puts
    )
    media_put = [b for p_, b in state["puts"] if p_ == "/api/media/MED1"]
    assert "Wikimedia Commons" in media_put[0]["desc"]  # attribution


def test_limit_bounds_the_gramps_fetch_not_only_the_filter(
    tmp_path, monkeypatch, mocker
):
    """`--limit` doit borner le trafic API, pas seulement l'affichage.

    L'arbre réel dépasse 300 lieux ; une pagination complète avant filtrage ferait de
    `--limit` une promesse creuse (CLAUDE.md : « iterate with --limit »).
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_geosearch",
        lambda lat, lon, **kw: [{"title": "Tiffech", "dist": 3.8}],
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "title": "Tiffech",
            "url": "https://fr.wikipedia.org/wiki/Tiffech",
            "extract": "…",
            "image_url": None,
        },
    )

    pages_fetched = []

    def h(request):
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page"))
            pages_fetched.append(page)
            # trois pages pleines : sans bornage, les trois seraient lues
            return httpx.Response(200, json=[dict(PLACE)] if page <= 3 else [])
        if request.method == "GET" and request.url.path == "/api/places/HT":
            return httpx.Response(200, json=dict(PLACE))
        return httpx.Response(200, json={})

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    run_lieux_wiki(client, tmp_path, date="2026-07-19", limit=1)

    assert pages_fetched == [1], f"pagination non bornée : pages lues {pages_fetched}"


def test_failed_image_upload_is_reported_not_swallowed(tmp_path, monkeypatch, mocker):
    """Lien posé mais image perdue : le rapport doit le dire, pas rester muet."""
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_geosearch",
        lambda lat, lon, **kw: [{"title": "Tiffech", "dist": 3.8}],
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "title": "Tiffech",
            "url": "https://fr.wikipedia.org/wiki/Tiffech",
            "extract": "…",
            "image_url": "https://upload.wikimedia.org/x.png",
            "image_name": "x.png",
        },
    )

    def h(request):
        pth, m = request.url.path, request.method
        if m == "GET" and pth == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(200, json=[dict(PLACE)] if page == 1 else [])
        if m == "GET" and pth == "/api/places/HT":
            return httpx.Response(200, json=dict(PLACE))
        if m == "POST" and pth == "/api/media/":
            return httpx.Response(500, json={"error": "stockage média indisponible"})
        if m == "PUT":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    mocker.patch(
        "requests.get",
        return_value=mocker.MagicMock(
            content=b"PNG",
            headers={"Content-Type": "image/png"},
            raise_for_status=lambda: None,
        ),
    )
    report = run_lieux_wiki(client, tmp_path, date="2026-07-19")

    md = report.read_text(encoding="utf-8")
    assert "Liens vérifiés posés : 1" in md  # le lien, lui, est bien passé
    assert "Images importées : 0" in md
    assert "- Erreurs : 1" in md
    assert "## Erreurs" in md and "Tiffech" in md.split("## Erreurs")[1]


def test_run_lieux_wiki_dry_run_writes_nothing(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_geosearch",
        lambda lat, lon, **kw: [{"title": "Tiffech", "dist": 3.8}],
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "title": "Tiffech",
            "url": "https://fr.wikipedia.org/wiki/Tiffech",
            "extract": "",
            "image_url": "https://upload.wikimedia.org/x.png",
            "image_name": "",
        },
    )

    def h(request):
        if request.method == "GET" and request.url.path == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(200, json=[dict(PLACE)] if page == 1 else [])
        if request.method == "GET" and request.url.path == "/api/places/HT":
            return httpx.Response(200, json=dict(PLACE))
        if request.method in ("PUT", "POST"):
            raise AssertionError("dry-run : aucune écriture attendue")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_lieux_wiki(client, tmp_path, date="2026-07-19", dry_run=True)
    assert "simulation (dry-run)" in report.read_text(encoding="utf-8")
