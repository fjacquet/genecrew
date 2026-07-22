"""Offline tests for deces-apply (INSEE citations on existing death events)."""

import json

import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.deces_apply import (
    SOURCE_TITLE,
    citation_page,
    run_deces_apply,
    source_title_for,
)

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(handler):
    def _h(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        return handler(request)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(_h))


def _yaml(tmp_path, props):
    p = tmp_path / "props.yaml"
    p.write_text(
        yaml.safe_dump({"propositions": props}, allow_unicode=True), encoding="utf-8"
    )
    return p


PROP = {
    "type": "source",
    "gramps_id": "I0300",
    "handle": "H300",
    "personne": "Odette Rippert",
    "cible": "décès de I0300 (2021-12-19, sans source)",
    "action": "Ajouter la source INSEE…",
    "preuve_url": "https://deces.matchid.io/id/PpcgyN6TffIa",
    "preuve_detail": "Fichier des décès INSEE : 2021-12-19 à Bourges, acte 1511 — "
    "fichier INSEE 2021, ligne 610579 (score 1.000).",
    "priorite": "basse",
    "confiance": 2,
}

PERSON = {
    "handle": "H300",
    "gramps_id": "I0300",
    "death_ref_index": 1,
    "event_ref_list": [{"ref": "EV_B"}, {"ref": "EV_D"}],
}
EVENT = {
    "_class": "Event",
    "handle": "EV_D",
    "gramps_id": "E0607",
    "type": "Death",
    "citation_list": [],
}


def test_source_title_routed_per_register():
    assert source_title_for(PROP["preuve_detail"]) == (SOURCE_TITLE, "INSEE")
    t, a = source_title_for("Mémoire des hommes (Guerre 1914-1918) : décès 1915-09-28…")
    assert t == "Mémoire des hommes — Guerre 1914-1918" and a == "Ministère des Armées"
    t, a = source_title_for("Presse Gallica : L'Écho d'Oran du 7 juin 1955, p. 10.")
    assert t.startswith("Gallica") and "nationale" in a


def test_source_title_for_raises_on_unrecognized_register():
    with pytest.raises(ValueError, match="Base Léonore"):
        source_title_for("Base Léonore : dossier LH/123/45")


def test_apply_militaires_prop_creates_mdh_source(tmp_path, mocker):
    mdh_prop = {
        **PROP,
        "preuve_detail": "Mémoire des hommes (Guerre 1914-1918) : décès 1915-09-28 à Neuville "
        "(score 1.000).",
        "preuve_url": "https://www.memoiredeshommes.sga.defense.gouv.fr/ark/x",
    }
    state = {"source_posts": [], "citation_posts": [], "event_puts": []}
    client = _client(_full_handler(state))
    mocker.patch.object(write_tools, "get_client", return_value=client)
    run_deces_apply(
        client, _yaml(tmp_path, [mdh_prop]), tmp_path, date="2026-07-19", dry_run=False
    )
    assert state["source_posts"][0]["title"] == "Mémoire des hommes — Guerre 1914-1918"
    assert state["source_posts"][0]["author"] == "Ministère des Armées"
    assert "ark/x" in state["citation_posts"][0]["page"]


def test_citation_page_strips_score_keeps_reference():
    page = citation_page(PROP["preuve_detail"], PROP["preuve_url"])
    assert "acte 1511" in page and "ligne 610579" in page
    assert "score" not in page
    assert page.endswith("https://deces.matchid.io/id/PpcgyN6TffIa")


def _full_handler(state):
    def h(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/api/sources/":
            # Scénario « aucune source existante » : vide sur toute page, à
            # l'image du même idiome de pagination utilisé ailleurs dans la
            # suite (`X if page == 1 else []`) — ici X est vide aussi, d'où
            # une seule branche. `page` reste lu pour exiger le paramètre,
            # comme partout ailleurs.
            int(request.url.params.get("page"))
            return httpx.Response(200, json=[])
        if m == "POST" and p == "/api/sources/":
            state["source_posts"].append(json.loads(request.content))
            return httpx.Response(201, json=[{"handle": "SRC1"}])
        if m == "GET" and p == "/api/people/H300":
            return httpx.Response(200, json=PERSON)
        if m == "GET" and p == "/api/events/EV_D":
            return httpx.Response(200, json=dict(EVENT))
        if m == "POST" and p == "/api/citations/":
            state["citation_posts"].append(json.loads(request.content))
            return httpx.Response(201, json=[{"handle": "CIT1"}])
        if m == "PUT" and p == "/api/events/EV_D":
            state["event_puts"].append(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return h


def test_apply_writes_source_citation_and_attaches(tmp_path, mocker):
    state = {"source_posts": [], "citation_posts": [], "event_puts": []}
    client = _client(_full_handler(state))
    mocker.patch.object(write_tools, "get_client", return_value=client)

    report = run_deces_apply(
        client, _yaml(tmp_path, [PROP]), tmp_path, date="2026-07-19", dry_run=False
    )

    assert state["source_posts"][0]["title"] == SOURCE_TITLE
    assert state["citation_posts"][0]["source_handle"] == "SRC1"
    assert state["citation_posts"][0]["confidence"] == 2
    assert "acte 1511" in state["citation_posts"][0]["page"]
    assert state["event_puts"][0]["citation_list"] == ["CIT1"]
    md = report.read_text(encoding="utf-8")
    assert "Citations posées : 1" in md and "I0300" in md


def test_apply_is_idempotent_when_source_already_cited(tmp_path, mocker):
    cited_event = {**EVENT, "citation_list": ["C_X"]}

    def h(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/api/sources/":
            page = int(request.url.params.get("page"))
            return httpx.Response(
                200,
                json=[{"title": SOURCE_TITLE, "handle": "SRC1"}] if page == 1 else [],
            )
        if m == "GET" and p == "/api/people/H300":
            return httpx.Response(200, json=PERSON)
        if m == "GET" and p == "/api/events/EV_D":
            return httpx.Response(200, json=cited_event)
        if m == "GET" and p == "/api/citations/C_X":
            return httpx.Response(200, json={"handle": "C_X", "source_handle": "SRC1"})
        if m in ("POST", "PUT"):
            raise AssertionError(f"écriture inattendue: {m} {p}")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_deces_apply(
        client, _yaml(tmp_path, [PROP]), tmp_path, date="2026-07-19", dry_run=False
    )
    assert "Déjà citées (ignorées, idempotent) : 1" in report.read_text(
        encoding="utf-8"
    )


def test_apply_filters_scope_and_flags_missing_death(tmp_path, mocker):
    date_prop = {
        **PROP,
        "type": "date",
        "cible": "décès absent",
        "action": "Renseigner le décès…",
    }
    low_conf = {**PROP, "confiance": 1}
    no_death = {**PROP, "gramps_id": "I0002", "handle": "H2"}

    def h(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/api/sources/":
            page = int(request.url.params.get("page"))
            return httpx.Response(
                200,
                json=[{"title": SOURCE_TITLE, "handle": "SRC1"}] if page == 1 else [],
            )
        if m == "GET" and p == "/api/people/H2":
            return httpx.Response(
                200,
                json={
                    "handle": "H2",
                    "gramps_id": "I0002",
                    "death_ref_index": -1,
                    "event_ref_list": [],
                },
            )
        if m in ("POST", "PUT"):
            raise AssertionError("aucune écriture attendue")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_deces_apply(
        client,
        _yaml(tmp_path, [date_prop, low_conf, no_death]),
        tmp_path,
        date="2026-07-19",
        dry_run=False,
    )
    md = report.read_text(encoding="utf-8")
    assert "Hors périmètre v1 (type ≠ source ou confiance < 2) : 2" in md
    assert "aucun événement décès" in md


def test_apply_dry_run_writes_nothing(tmp_path, mocker):
    def h(request):
        p, m = request.url.path, request.method
        if m == "GET" and p == "/api/sources/":
            page = int(request.url.params.get("page"))
            return httpx.Response(
                200,
                json=[{"title": SOURCE_TITLE, "handle": "SRC1"}] if page == 1 else [],
            )
        if m == "GET" and p == "/api/people/H300":
            return httpx.Response(200, json=PERSON)
        if m == "GET" and p == "/api/events/EV_D":
            return httpx.Response(200, json=dict(EVENT))
        if m in ("POST", "PUT"):
            raise AssertionError("dry-run : aucune écriture attendue")
        return httpx.Response(404)

    client = _client(h)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    report = run_deces_apply(
        client, _yaml(tmp_path, [PROP]), tmp_path, date="2026-07-19", dry_run=True
    )
    md = report.read_text(encoding="utf-8")
    assert "simulation (dry-run" in md and "Citations posées : 1" in md
