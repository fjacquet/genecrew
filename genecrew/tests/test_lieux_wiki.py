"""Offline tests for the verified-Wikipedia place enrichment."""

import json

import httpx
import pytest
import requests
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
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "lat": 36.1917,
            "lon": 7.7861,
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
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "lat": 36.1917,
            "lon": 7.7861,
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
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "lat": 36.1917,
            "lon": 7.7861,
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
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_page_info",
        lambda t, **kw: {
            "lat": 36.1917,
            "lon": 7.7861,
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


# --- résolution : le titre d'abord, la position ensuite ---


def _page(title, lat, lon, url=None):
    return {
        "title": title,
        "url": url or f"https://fr.wikipedia.org/wiki/{title}",
        "extract": "…",
        "image_url": "",
        "image_name": "",
        "lat": lat,
        "lon": lon,
    }


def test_resolve_article_tranche_sur_le_titre_sans_recherche(monkeypatch):
    """Le cas courant coûte UNE requête : le titre suffit, la position le confirme."""
    monkeypatch.setattr(
        lieux_wiki, "frwiki_page_info", lambda t, **kw: _page("Lyon", 45.76, 4.835)
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_search_geo",
        lambda *a, **kw: pytest.fail("recherche appelée alors que le titre suffisait"),
    )

    info, dist = lieux_wiki.resolve_article("Lyon", "45.7580", "4.8320")
    assert info["title"] == "Lyon"
    assert dist < 1000


def test_resolve_article_suit_la_redirection_vers_l_exonyme(monkeypatch):
    """'München' -> 'Munich' : la redirection porte une identité que la similarité rate.

    `similarity("München", "Munich")` tombe sous MIN_SIM. Tant que la résolution passait
    par la géorecherche + similarité, ces lieux étaient perdus par construction, quel que
    soit le nombre de candidats lus.
    """
    from crewai_custom_tools.tools.genealogy.geo.score import similarity

    assert similarity("München", "Munich") < lieux_wiki.MIN_SIM  # le piège, mesuré

    monkeypatch.setattr(
        lieux_wiki, "frwiki_page_info", lambda t, **kw: _page("Munich", 48.1372, 11.5755)
    )
    info, _ = lieux_wiki.resolve_article("München", "48.1351", "11.5820")
    assert info["title"] == "Munich"


def test_resolve_article_refuse_un_homonyme_au_mauvais_endroit(monkeypatch):
    """Paris (Texas) ne prend pas l'article de Paris : la position tranche."""
    monkeypatch.setattr(
        lieux_wiki, "frwiki_page_info", lambda t, **kw: _page("Paris", 48.8566, 2.3522)
    )
    monkeypatch.setattr(lieux_wiki, "frwiki_search_geo", lambda *a, **kw: [])

    assert lieux_wiki.resolve_article("Paris", "33.6609", "-95.5555") is None


def test_resolve_article_retombe_sur_la_recherche_sur_page_d_homonymie(monkeypatch):
    """'Valence' est une page d'homonymie : un titre, mais aucune position à vérifier."""
    pages = {
        "Valence": {**_page("Valence", None, None)},
        "Valence (Drôme)": _page("Valence (Drôme)", 44.9333, 4.8917),
    }
    monkeypatch.setattr(lieux_wiki, "frwiki_page_info", lambda t, **kw: pages[t])
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_search_geo",
        lambda *a, **kw: [
            {"title": "Bourg-lès-Valence", "lat": 44.9500, "lon": 4.8950},
            {"title": "Valence (Drôme)", "lat": 44.9333, "lon": 4.8917},
        ],
    )

    info, dist = lieux_wiki.resolve_article("Valence", "44.9333", "4.8917")
    assert info["title"] == "Valence (Drôme)"
    assert dist < 100


def test_resolve_article_abstient_quand_la_recherche_ne_rend_pas_un_homonyme(
    monkeypatch,
):
    """'El Arrouch' trouve Skikda à 1,6 km : au bon endroit, mauvais nom -> abstention.

    C'est la moitié « homonyme » de la doctrine : la proximité seule ne fait pas un lien.
    """
    monkeypatch.setattr(
        lieux_wiki, "frwiki_page_info", lambda t, **kw: _page(t, None, None)
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_search_geo",
        lambda *a, **kw: [{"title": "Skikda", "lat": 36.8790, "lon": 6.9060}],
    )

    assert lieux_wiki.resolve_article("El Arrouch", "36.8700", "6.9200") is None


def test_resolve_article_ecarte_un_candidat_hors_rayon(monkeypatch):
    """Un homonyme parfait mais lointain reste écarté avant même la similarité."""
    monkeypatch.setattr(
        lieux_wiki, "frwiki_page_info", lambda t, **kw: _page(t, None, None)
    )
    monkeypatch.setattr(
        lieux_wiki,
        "frwiki_search_geo",
        lambda *a, **kw: [{"title": "Tiffech", "lat": 48.8566, "lon": 2.3522}],
    )

    assert lieux_wiki.resolve_article("Tiffech", "36.1917", "7.7861") is None


# --- 429 : reprises et diagnostic ---


def test_backoff_reprend_deux_fois_avant_d_abandonner(monkeypatch):
    """Une seule reprise se reprenait un 429 en production (deux 429 par lieu au log)."""
    monkeypatch.setattr(lieux_wiki, "BACKOFF_429_S", (0, 0))
    appels = {"n": 0}

    def _429():
        appels["n"] += 1
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(response=response)

    with pytest.raises(requests.HTTPError):
        lieux_wiki._with_backoff(_429)
    assert appels["n"] == 3


def test_backoff_ne_retente_pas_une_erreur_qui_n_est_pas_un_429(monkeypatch):
    monkeypatch.setattr(lieux_wiki, "BACKOFF_429_S", (0, 0))
    appels = {"n": 0}

    def _404():
        appels["n"] += 1
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError(response=response)

    with pytest.raises(requests.HTTPError):
        lieux_wiki._with_backoff(_404)
    assert appels["n"] == 1


def test_describe_error_porte_le_code_http():
    """« HTTPError » nu a déjà fait passer une salve de 429 pour une panne indéterminée."""
    response = requests.Response()
    response.status_code = 429
    assert lieux_wiki.describe_error(requests.HTTPError(response=response)) == (
        "HTTPError 429"
    )
    assert lieux_wiki.describe_error(ValueError("x")) == "ValueError"


# --- rattrapage d'image : un lien déjà posé ne doit pas condamner l'illustration ---


def test_titre_depuis_url_decode_et_deseparne():
    """Le titre se relit du lien, sans réinterroger Wikipédia pour le retrouver."""
    t = lieux_wiki.titre_depuis_url
    assert t("https://fr.wikipedia.org/wiki/Tournus") == "Tournus"
    assert t("https://fr.wikipedia.org/wiki/Cosne-d%27Allier") == "Cosne-d'Allier"
    assert t("https://fr.wikipedia.org/wiki/Pays_de_Galles") == "Pays de Galles"
    assert t("https://fr.wikipedia.org/wiki/Sussex_de_l%27Est") == "Sussex de l'Est"


def test_url_wikipedia_rend_le_lien_ou_rien():
    u = lieux_wiki.url_wikipedia
    assert u({"urls": [{"path": "https://autre.org"},
                       {"path": "https://fr.wikipedia.org/wiki/X"}]}) == (
        "https://fr.wikipedia.org/wiki/X")
    assert u({"urls": [{"path": "https://autre.org"}]}) is None
    assert u({}) is None


def test_a_enrichir_vise_aussi_un_lieu_lie_sans_image():
    """Un lien posé et une image manquée sortaient le lieu du champ pour toujours.

    C'est ce qui a rendu 597 lieux inatteignables : le critère confondait « il manque
    un lien » et « il manque une image ».
    """
    lie_sans_image = {"lat": "1", "long": "2",
                      "urls": [{"path": "https://fr.wikipedia.org/wiki/X"}],
                      "media_list": []}
    lie_avec_image = {"lat": "1", "long": "2",
                      "urls": [{"path": "https://fr.wikipedia.org/wiki/X"}],
                      "media_list": [{"ref": "M1"}]}
    nu = {"lat": "1", "long": "2", "urls": [], "media_list": []}
    sans_gps = {"urls": [], "media_list": []}

    assert lieux_wiki.a_enrichir(lie_sans_image, images=True) is True
    assert lieux_wiki.a_enrichir(lie_avec_image, images=True) is False
    assert lieux_wiki.a_enrichir(nu, images=True) is True
    assert lieux_wiki.a_enrichir(sans_gps, images=True) is False


def test_a_enrichir_sans_images_revient_au_critere_du_lien():
    """`--no-images` ne doit pas retenir des lieux dont il ne ferait rien."""
    lie_sans_image = {"lat": "1", "long": "2",
                      "urls": [{"path": "https://fr.wikipedia.org/wiki/X"}],
                      "media_list": []}
    assert lieux_wiki.a_enrichir(lie_sans_image, images=False) is False
    assert lieux_wiki.a_enrichir({"lat": "1", "long": "2"}, images=False) is True


def test_lieu_deja_lie_recoit_son_image_sans_reposer_l_url(tmp_path, monkeypatch, mocker):
    """Rattrapage : on lit le titre du lien existant, on ne re-résout pas, on ne re-lie pas.

    Réinterroger la géolocalisation risquerait de désigner un AUTRE article que celui
    qu'un humain — ou le référentiel — a déjà validé.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(
        lieux_wiki,
        "resolve_article",
        lambda *a, **kw: pytest.fail("résolution appelée alors que le lien existait"),
    )
    titres_demandes = []

    def _page_info(titre, **kw):
        titres_demandes.append(titre)
        return {"title": titre, "url": "https://fr.wikipedia.org/wiki/Tiffech",
                "extract": "…", "image_url": "https://upload.wikimedia.org/x.png",
                "image_name": "x.png", "lat": 36.19, "lon": 7.78}

    monkeypatch.setattr(lieux_wiki, "frwiki_page_info", _page_info)
    mocker.patch("requests.get", return_value=mocker.MagicMock(
        content=b"PNG", headers={"Content-Type": "image/png"},
        raise_for_status=lambda: None))

    deja_lie = dict(PLACE, urls=[{"path": "https://fr.wikipedia.org/wiki/Tiffech"}])
    puts = []

    def h(request):
        pth, m = request.url.path, request.method
        if m == "GET" and pth == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(200, json=[dict(deja_lie)] if page == 1 else [])
        if m == "GET" and pth == "/api/places/HT":
            return httpx.Response(200, json=dict(deja_lie))
        if m == "POST" and pth == "/api/media/":
            return httpx.Response(201, json=[{"type": "add", "handle": "MED1"}])
        if m == "GET" and pth == "/api/media/MED1":
            return httpx.Response(200, json={"handle": "MED1", "mime": "image/png"})
        if m == "PUT":
            puts.append((pth, json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_lieux_wiki(client, tmp_path, date="2026-07-27")

    assert titres_demandes == ["Tiffech"], titres_demandes
    md = report.read_text(encoding="utf-8")
    assert "Images importées : 1" in md
    assert "Liens vérifiés posés : 0" in md      # rien à lier, tout à illustrer
    place_puts = [b for p_, b in puts if p_ == "/api/places/HT"]
    assert all(len(b.get("urls", [])) <= 1 for b in place_puts), "URL reposée en double"


def _monter_rattrapage(monkeypatch, mocker):
    """Un lieu déjà lié, sans image, dont l'article porte une miniature."""
    monkeypatch.setattr(lieux_wiki, "THROTTLE_S", 0)
    monkeypatch.setattr(lieux_wiki, "THROTTLE_MEDIA_S", 0)
    monkeypatch.setattr(lieux_wiki, "frwiki_page_info", lambda t, **kw: {
        "title": t, "url": "https://fr.wikipedia.org/wiki/Tiffech", "extract": "…",
        "image_url": "https://upload.wikimedia.org/x.png", "image_name": "x.png",
        "lat": 36.19, "lon": 7.78})
    mocker.patch("requests.get", return_value=mocker.MagicMock(
        content=b"PNG", headers={"Content-Type": "image/png"},
        raise_for_status=lambda: None))
    deja_lie = dict(PLACE, urls=[{"path": "https://fr.wikipedia.org/wiki/Tiffech"}])

    def h(request):
        pth, m = request.url.path, request.method
        if m == "GET" and pth == "/api/places/":
            page = int(request.url.params.get("page"))
            return httpx.Response(200, json=[dict(deja_lie)] if page == 1 else [])
        if m == "GET" and pth == "/api/places/HT":
            return httpx.Response(200, json=dict(deja_lie))
        if m == "POST" and pth == "/api/media/":
            return httpx.Response(201, json=[{"type": "add", "handle": "MED1"}])
        if m == "GET" and pth == "/api/media/MED1":
            return httpx.Response(200, json={"handle": "MED1", "mime": "image/png"})
        if m == "PUT":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    return client


def test_la_simulation_previsualise_les_images(tmp_path, monkeypatch, mocker):
    """Un dry-run muet sur les images n'est pas un aperçu.

    L'import rend un handle `DRYRUN:` que l'attachement compte comme inchangé : les
    images ne se comptaient donc jamais en simulation, alors que les liens, eux, se
    comptent. Sur un run de rattrapage pur, l'aperçu affichait zéro partout.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    client = _monter_rattrapage(monkeypatch, mocker)
    report = run_lieux_wiki(client, tmp_path, date="2026-07-27", dry_run=True)
    md = report.read_text(encoding="utf-8")
    assert "simulation (dry-run)" in md
    assert "Images importées : 1" in md, md


def test_le_rapport_porte_le_mode_dans_son_nom(tmp_path, monkeypatch, mocker):
    """Une simulation ne doit pas écraser le compte rendu de l'écriture qui l'a suivie.

    C'est arrivé : un `--dry-run` de contrôle a effacé le rapport d'un run réel de
    41 liens, les deux écrivant `<date>_lieux_wiki.md`.
    """
    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    client = _monter_rattrapage(monkeypatch, mocker)
    simule = run_lieux_wiki(client, tmp_path, date="2026-07-27", dry_run=True)

    monkeypatch.setenv("GENECREW_DRY_RUN", "false")
    client = _monter_rattrapage(monkeypatch, mocker)
    ecrit = run_lieux_wiki(client, tmp_path, date="2026-07-27")

    assert simule != ecrit, "les deux modes écrivent le même fichier"
    assert simule.exists() and ecrit.exists()
    assert "simulation" in simule.name and "ecritures" in ecrit.name
