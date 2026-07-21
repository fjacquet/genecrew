"""Tests offline de la brique partagée de création d'événement."""

import json

import pytest

from genecrew import evenements
from genecrew.evenements import creer_evenement_source, dateval_iso


@pytest.fixture(autouse=True)
def _real_writes(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def test_dateval_sur_date_complete():
    assert dateval_iso("2021-12-23") == [23, 12, 2021]


def test_dateval_refuse_annee_seule():
    """Une année seule n'est jamais discriminante : pas de date inventée."""
    assert dateval_iso("2021") is None


def test_dateval_refuse_chaine_vide_ou_batarde():
    assert dateval_iso("") is None
    assert dateval_iso("le 23 décembre") is None


def _stub_outil(monkeypatch, payload):
    class _Outil:
        def _run(self, **kwargs):
            _Outil.vu = kwargs
            return json.dumps(payload)

    monkeypatch.setattr(evenements, "GrampsCreateEventTool", _Outil)
    return _Outil


def test_evenement_cree_et_rattache(monkeypatch):
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV1", "created": True, "attached": True}})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res == {"posee": True, "event_handle": "EV1", "attache": True,
                   "raison": "Death créé"}


def test_orphelin_signale_avec_son_handle(monkeypatch):
    """Événement créé mais non rattaché : le handle est la seule prise pour le retrouver."""
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV_ORPH", "created": True, "attached": False,
        "attach_error": "timeout"}})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res["posee"] is True
    assert res["attache"] is False
    assert "EV_ORPH" in res["raison"]
    assert "orphelin" in res["raison"].lower()


def test_simulation_n_est_pas_un_orphelin(monkeypatch):
    """En simulation l'outil rend `attached: False` sans avoir rien écrit.

    Ce False ne désigne pas un objet perdu mais une écriture qui n'a pas eu lieu.
    Le lire comme un orphelin rendait l'aperçu — celui sur lequel l'humain
    s'appuie avant d'autoriser des écritures irréversibles — alarmant et
    inexploitable, et court-circuitait chez l'appelant tout ce qui suit la
    création (note, tag), qui n'était donc jamais simulé.
    """
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "DRYRUN:event", "dry_run": True,
        "created": False, "attached": False}})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021],
                                 dry_run=True)
    assert res["posee"] is True
    assert res["attache"] is True
    assert "orphelin" not in res["raison"].lower()
    assert "simulé" in res["raison"]


def test_handle_synthetique_seul_suffit_a_reconnaitre_la_simulation(monkeypatch):
    """Le drapeau `dry_run` de la charge est le marqueur nominal, mais un handle
    « DRYRUN: » ne désigne jamais un vrai objet : s'y fier aussi évite de relire
    une simulation comme un orphelin si la charge de l'outil changeait."""
    _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "DRYRUN:event", "created": False, "attached": False}})
    res = creer_evenement_source("H1", event_type="Death", dry_run=True)
    assert res["attache"] is True
    assert "orphelin" not in res["raison"].lower()


def test_creation_refusee(monkeypatch):
    _stub_outil(monkeypatch, {"success": False, "error": "500"})
    res = creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021])
    assert res["posee"] is False
    assert res["event_handle"] is None
    assert "refusée" in res["raison"]


def test_parametres_transmis_a_l_outil(monkeypatch):
    outil = _stub_outil(monkeypatch, {"success": True, "data": {
        "handle": "EV1", "created": True, "attached": True}})
    creer_evenement_source("H1", event_type="Death", dateval=[23, 12, 2021],
                           place_handle="P9", citation_handle="C7", dry_run=True)
    assert outil.vu["person_handle"] == "H1"
    assert outil.vu["event_type"] == "Death"
    assert outil.vu["dateval"] == [23, 12, 2021]
    assert outil.vu["place_handle"] == "P9"
    assert outil.vu["citation_handle"] == "C7"
    assert outil.vu["dry_run"] is True
