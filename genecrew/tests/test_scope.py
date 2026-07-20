import httpx
import pytest

from genecrew.scope import parse_scope, resolve_handles
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def test_parse_scope_variants():
    assert parse_scope("all") == ("all", None)
    assert parse_scope("person:I0042") == ("person", "I0042")
    assert parse_scope("branch:I0042") == ("branch", "I0042")


def test_resolve_person_scope_single():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        assert request.url.params["gramps_id"] == "I0042"
        return httpx.Response(200, json=[{"handle": "h42", "gramps_id": "I0042"}])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    assert resolve_handles(client, "person:I0042") == [("h42", "I0042")]


def test_resolve_all_paginates_until_empty_and_respects_limit():
    pages = {1: [{"handle": f"h{i}", "gramps_id": f"I{i}"} for i in range(25)],
             2: [{"handle": f"h{i}", "gramps_id": f"I{i}"} for i in range(25, 40)],
             3: []}

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages.get(page, []))

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    got = resolve_handles(client, "all", limit=30)
    assert len(got) == 30 and got[0] == ("h0", "I0")


def test_branch_scope_not_implemented():
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "t"})))
    with pytest.raises(NotImplementedError):
        resolve_handles(client, "branch:I0042")


def test_parse_scope_accepts_place():
    assert parse_scope("place:P0080") == ("place", "P0080")


def test_resolve_handles_rejects_place_scope():
    # parse_scope est partagé ; sans garde explicite, "place:" retomberait sur la
    # branche "all" et paginerait TOUTES les personnes en silence.
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"access_token": "t"})))
    with pytest.raises(NotImplementedError):
        resolve_handles(client, "place:P0080")
