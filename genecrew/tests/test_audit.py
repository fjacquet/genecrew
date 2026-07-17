import httpx

from genecrew.audit import run_audit
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

# Une personne avec naissance (1850) APRÈS décès (1820) → R1 attendu.
PERSON = {
    "gramps_id": "I0001", "handle": "h1", "gender": 1, "citation_list": ["c"],
    "family_list": [], "parent_family_list": [], "birth_ref_index": 0, "death_ref_index": 1,
    "primary_name": {"first_name": "Jean", "surname_list": [{"surname": "Test"}]},
    "profile": {"birth": {"citations": 1}, "death": {"citations": 1}},
    "event_ref_list": [{"ref": "e1"}, {"ref": "e2"}],
    "extended": {"events": [
        {"type": "Birth", "citation_list": ["c"],
         "date": {"sortval": 2396758, "year": 1850, "dateval": [1, 1, 1850, False], "modifier": 0, "quality": 0}},
        {"type": "Death", "citation_list": ["c"],
         "date": {"sortval": 2385800, "year": 1820, "dateval": [1, 1, 1820, False], "modifier": 0, "quality": 0}},
    ]},
}


def _handler(request):
    if request.url.path == "/api/token/":
        return httpx.Response(200, json={"access_token": "t"})
    path = request.url.path
    if path == "/api/people/" and "gramps_id" not in request.url.params:
        page = int(request.url.params.get("page", 1))
        # liste de scope (sans profile) page 1 = [I0001], page 2 = []
        if "profile" not in request.url.params:
            return httpx.Response(200, json=[{"handle": "h1", "gramps_id": "I0001"}] if page == 1 else [])
        # liste de faits (avec profile) — non utilisée ici car get_person_facts va par handle
        return httpx.Response(200, json=[PERSON] if page == 1 else [])
    if path == "/api/people/h1":
        return httpx.Response(200, json=PERSON)
    return httpx.Response(200, json=[])


def test_run_audit_writes_report_with_r1(tmp_path):
    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler))
    report_path = run_audit(client, "all", tmp_path, date="2026-07-17", batch_size=25)
    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "R1" in text and "I0001" in text
