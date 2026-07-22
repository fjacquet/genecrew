import httpx
import pytest
import yaml
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig
from genecrew.places_merge import run_places_merge

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(calls):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "POST" and "/merge/" in request.url.path:
            calls.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _write_fusions(tmp_path):
    p = tmp_path / "fusions.yaml"
    p.write_text(
        yaml.safe_dump(
            [
                {
                    "gramps_id_keep": "P0001",
                    "handle_keep": "h1",
                    "gramps_id_merge": "P0002",
                    "handle_merge": "h2",
                    "canonical": "Bourges",
                    "reason": "même lieu",
                }
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return p


def test_merge_executes_from_reviewed_yaml(tmp_path, mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    report = run_places_merge(
        _client(calls),
        _write_fusions(tmp_path),
        tmp_path,
        date="2026-07-19",
        dry_run=False,
    )
    assert calls == ["/api/places/h1/merge/h2"]
    assert "Bourges" in report.read_text(encoding="utf-8")


def test_merge_dry_run_executes_nothing(tmp_path, mocker):
    calls = []
    mocker.patch.object(write_tools, "get_client", return_value=_client(calls))
    run_places_merge(
        _client(calls),
        _write_fusions(tmp_path),
        tmp_path,
        date="2026-07-19",
        dry_run=True,
    )
    assert calls == []
