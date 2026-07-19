import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.batching import iter_places

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")
PLACES = [{"handle": f"h{i}", "gramps_id": f"P{i:04d}",
           "name": {"value": f"L{i}"}, "place_type": "Unknown"} for i in range(3)]


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    if request.url.path == "/api/places/":
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=PLACES if page == 1 else [])
    return httpx.Response(404)


def test_iter_places_paginates_and_limits():
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    batches = list(iter_places(client, "all", batch_size=25, limit=2))
    flat = [p for b in batches for p in b]
    assert [p["handle"] for p in flat] == ["h0", "h1"]     # limit respecté


def test_iter_places_rejects_unsupported_scope():
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    with pytest.raises(NotImplementedError):
        list(iter_places(client, "person:I0001", batch_size=25, limit=None))
