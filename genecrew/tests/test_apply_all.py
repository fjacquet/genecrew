"""Tests de la commande parapluie apply-all (orchestration casse + genre)."""

import json

import httpx
import pytest

from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.apply_all import run_apply_all

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")

# Personne en CAPITALES (déclenche la casse) au prénom nettement féminin (déclenche le genre).
PEOPLE = [
    {"handle": "h1", "gramps_id": "I0001", "gender": 2,
     "primary_name": {"first_name": "SUZANNE", "surname_list": [{"surname": "MARTIN"}]}},
]


@pytest.fixture(autouse=True)
def _no_global_dry_run(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")   # défaut réel = simuler ; ici on écrit


@pytest.fixture(autouse=True)
def _small_table(monkeypatch):
    # Le volet genre appelle load_prenoms_table() ; on injecte une petite table hors-ligne.
    monkeypatch.setattr("genecrew.gender_apply.load_prenoms_table",
                        lambda: {"SUZANNE": (9990, 10)})


def _patch_write_client(mocker, client):
    # Les outils d'écriture (nom + genre) résolvent leur client via write_tools.get_client().
    mocker.patch(
        "crewai_custom_tools.tools.genealogy.gramps.write_tools.get_client",
        return_value=client)


def _handler(on_put):
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "GET" and request.url.path == "/api/people/":
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=PEOPLE if page == 1 else [])
        if request.method == "GET" and request.url.path.startswith("/api/people/"):
            return httpx.Response(200, json=PEOPLE[0])          # fetch mono-personne (outils write)
        if request.method == "PUT":
            return on_put(request)
        return httpx.Response(404)
    return handler


def test_run_apply_all_runs_both_steps(tmp_path, mocker):
    puts = []

    def on_put(request):
        puts.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler(on_put)))
    _patch_write_client(mocker, client)
    paths = run_apply_all(client, "all", tmp_path, date="2026-07-18",
                          min_ratio=0.98, dry_run=False)
    assert set(paths) == {"names", "incomplete", "gender"}
    assert all(p.exists() for p in paths.values())
    # casse appliquée (SUZANNE -> Suzanne) ET genre écrit (U -> F = 0)
    assert paths["names"].read_text(encoding="utf-8").count("Suzanne") >= 1
    assert "Genres écrits : 1" in paths["gender"].read_text(encoding="utf-8")
    genders = [p["primary_name"]["first_name"] for p in puts if "primary_name" in p]
    assert "Suzanne" in genders                                  # un PUT a recasé le prénom
    assert any(p.get("gender") == 0 for p in puts)               # un PUT a écrit le genre F


def test_run_apply_all_dry_run_writes_nothing(tmp_path, mocker):
    def on_put(request):
        raise AssertionError("aucun PUT attendu en dry-run")

    client = GrampsClient(CONFIG, transport=httpx.MockTransport(_handler(on_put)))
    _patch_write_client(mocker, client)
    paths = run_apply_all(client, "all", tmp_path, date="2026-07-18", dry_run=True)
    assert set(paths) == {"names", "incomplete", "gender"}
    assert all(p.exists() for p in paths.values())               # rapports produits, rien écrit
