import httpx

from genecrew.batching import iter_people_batches
from crewai_custom_tools.tools.genealogy.gramps.facts import FactsFetcher
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

PERSON = {
    "gramps_id": "I0001",
    "handle": "h1",
    "gender": 1,
    "citation_list": ["c"],
    "family_list": [],
    "parent_family_list": [],
    "birth_ref_index": -1,
    "death_ref_index": -1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Test"}]},
    "profile": {},
    "event_ref_list": [],
    "extended": {"events": []},
}


def test_iter_all_scope_bulk():
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=[PERSON] if page == 1 else [])

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(handler))
    batches = list(iter_people_batches(client, FactsFetcher(client), "all", 25, None))
    assert len(batches) == 1 and batches[0][0].gramps_id == "I0001"
