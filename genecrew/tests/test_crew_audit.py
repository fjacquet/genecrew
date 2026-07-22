"""Offline tests for the crew-audit orchestration and its pure helpers.

No LLM, no network: ``collect_audit_findings`` is stubbed and the crew is a fake
factory whose ``kickoff`` returns a canned CrewOutput.
"""

import yaml
from crewai_custom_tools.tools.genealogy.models.domain import Anomaly, PersonFacts
from genecrew.crew_audit import (
    group_anomalies_by_person,
    render_anomalies_block,
    render_crew_report,
    run_crew_audit,
)

from genecrew import crew_audit


def _anom(rule, sev, gid, handle, msg):
    return Anomaly(rule=rule, severity=sev, gramps_id=gid, handle=handle, message=msg)


def _person(gid, handle, name):
    return PersonFacts(
        gramps_id=gid,
        handle=handle,
        name=name,
        surname=name.split()[-1],
        given=name.split()[0],
        sex="U",
    )


# --- group_anomalies_by_person (pure) ---


def test_group_preserves_order_and_resolves_names():
    people = [_person("I1", "hA", "Jean Dupont"), _person("I2", "hB", "Marie Curie")]
    anomalies = [
        _anom("R1", "haute", "I2", "hB", "âge impossible"),
        _anom("R6", "basse", "I1", "hA", "sans source"),
        _anom("R2", "moyenne", "I2", "hB", "dates incohérentes"),
    ]
    groups = group_anomalies_by_person(anomalies, people)
    assert [g.handle for g in groups] == ["hB", "hA"]  # first-seen order
    assert groups[0].name == "Marie Curie"  # resolved from people
    assert len(groups[0].anomalies) == 2  # both hB anomalies grouped


def test_group_falls_back_to_gramps_id_when_person_absent():
    groups = group_anomalies_by_person(
        [_anom("R1", "haute", "I9", "hZ", "x")], people=[]
    )
    assert groups[0].name == "I9"


# --- render_anomalies_block (pure) ---


def test_block_carries_ids_handle_and_rule_details():
    groups = group_anomalies_by_person(
        [_anom("R1", "haute", "I1", "hA", "âge impossible")],
        [_person("I1", "hA", "Jean Dupont")],
    )
    block = render_anomalies_block(groups)
    assert "gramps_id=I1" in block and "handle=hA" in block and "Jean Dupont" in block
    assert "[R1 / haute] âge impossible" in block


# --- render_crew_report (pure) ---


def test_report_shows_mode_counts_and_per_lot_sections():
    results = [
        {"index": 1, "n_persons": 2, "raw": "verdicts…", "tokens": 100},
        {"index": 2, "n_persons": 1, "raw": "autre lot", "tokens": 50},
    ]
    md = render_crew_report(
        "all", "2026-07-19", results, dry_run=True, n_persons=3, n_anomalies=4
    )
    assert "Mode : simulation (dry-run)" in md
    assert "Personnes signalées : 3" in md and "Anomalies déterministes : 4" in md
    assert "Coût total (tokens) : 150" in md
    assert "## Lot 1 — 2 personne(s), 100 tokens" in md and "verdicts…" in md
    assert "## Lot 2 — 1 personne(s), 50 tokens" in md


def test_report_handles_no_anomalies():
    md = render_crew_report(
        "all", "2026-07-19", [], dry_run=True, n_persons=0, n_anomalies=0
    )
    assert "rien à interpréter" in md


# --- run_crew_audit orchestration (offline) ---

from genecrew.crew import PropositionAudit, PropositionsLot  # noqa: E402


class _FakeUsage:
    total_tokens = 42


class _FakeTaskOutput:
    def __init__(self, pydantic=None):
        self.pydantic = pydantic
        self.json_dict = None


_PROPOSITION = PropositionAudit(
    type="date",
    gramps_id="I0300",
    handle="h300",
    personne="Odette Rippert",
    cible="événement décès de I0300",
    action="corriger la date en 2021-12-19",
    preuve_url="https://deces.matchid.io/id/PpcgyN6TffIa",
    preuve_detail="fichier INSEE, acte 1511",
    priorite="haute",
    confiance=2,
)


class _FakeOutput:
    raw = "verdict simulé"
    token_usage = _FakeUsage()

    def __init__(self):
        self.tasks_output = [
            _FakeTaskOutput(),  # détective
            _FakeTaskOutput(),  # historien
            _FakeTaskOutput(PropositionsLot(propositions=[_PROPOSITION])),
            _FakeTaskOutput(),  # chroniqueur
        ]


class _FakeCrew:
    kickoff_inputs = []
    log_files = []

    def kickoff(self, inputs):
        _FakeCrew.kickoff_inputs.append(inputs)
        _FakeCrew.log_files.append(getattr(self, "output_log_file", None))
        return _FakeOutput()


class _FakeFactory:
    def crew(self):
        return _FakeCrew()


def test_run_crew_audit_batches_writes_report_and_pins_dry_run(tmp_path, monkeypatch):
    _FakeCrew.kickoff_inputs = []
    _FakeCrew.log_files = []
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    people = [_person(f"I{i}", f"h{i}", f"Pers {i}") for i in range(3)]
    anomalies = [_anom("R1", "haute", f"I{i}", f"h{i}", f"souci {i}") for i in range(3)]
    monkeypatch.setattr(
        crew_audit,
        "collect_audit_findings",
        lambda *a, **k: (anomalies, [], people, []),
    )

    report = run_crew_audit(
        client=None,
        scope="all",
        output_dir=tmp_path,
        date="2026-07-19",
        batch_size=2,
        dry_run=True,
        crew_factory=_FakeFactory,
    )

    # Simulation forced onto the global switch so LLM tool calls also simulate.
    assert __import__("os").environ["GENECREW_DRY_RUN"] == "true"
    # 3 persons / batch 2 → 2 kickoffs, each fed an anomalies_block + date.
    assert len(_FakeCrew.kickoff_inputs) == 2
    assert set(_FakeCrew.kickoff_inputs[0]) == {"anomalies_block", "date"}

    # Every batch's crew gets the durable trace file wired (same file, append mode;
    # .log.txt because CrewAI's FileHandler only accepts .txt/.json).
    assert (
        _FakeCrew.log_files
        == [str(report.parent / "2026-07-19_crew_audit_all.log.txt")] * 2
    )

    md = report.read_text(encoding="utf-8")
    assert "Mode : simulation (dry-run)" in md
    assert "## Lot 1" in md and "## Lot 2" in md and "verdict simulé" in md

    summary = yaml.safe_load(
        (report.parent / report.name.replace(".md", ".yaml")).read_text()
    )
    assert summary["personnes_signalees"] == 3 and summary["anomalies"] == 3
    assert summary["tokens_total"] == 84 and summary["dry_run"] is True
    assert summary["propositions"] == 2  # 1 par lot × 2 lots

    # YAML des propositions actionnables écrit à côté du rapport (relu par l'humain)
    props = yaml.safe_load(
        (report.parent / "2026-07-19_propositions_audit_all.yaml").read_text()
    )
    assert len(props["propositions"]) == 2
    p = props["propositions"][0]
    assert p["gramps_id"] == "I0300" and p["confiance"] == 2
    assert p["action"] == "corriger la date en 2021-12-19"
    assert "Propositions actionnables : 2" in md


class _UnstructuredOutput:
    raw = "texte libre sans structure"
    token_usage = _FakeUsage()
    tasks_output = [_FakeTaskOutput(), _FakeTaskOutput()]  # aucun PropositionsLot


class _UnstructuredCrew:
    output_log_file = None

    def kickoff(self, inputs):
        return _UnstructuredOutput()


class _UnstructuredFactory:
    def crew(self):
        return _UnstructuredCrew()


def test_run_crew_audit_survives_missing_structured_output(tmp_path, monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    monkeypatch.setattr(
        crew_audit,
        "collect_audit_findings",
        lambda *a, **k: (
            [_anom("R1", "haute", "I1", "h1", "x")],
            [],
            [_person("I1", "h1", "A B")],
            [],
        ),
    )
    report = run_crew_audit(
        client=None,
        scope="all",
        output_dir=tmp_path,
        date="2026-07-19",
        dry_run=True,
        crew_factory=_UnstructuredFactory,
    )
    md = report.read_text(encoding="utf-8")
    assert "Propositions actionnables : 0" in md
    assert "Sortie structurée du Standardisateur absente" in md
    props = yaml.safe_load(
        (report.parent / "2026-07-19_propositions_audit_all.yaml").read_text()
    )
    assert props["propositions"] == []  # YAML écrit, vide


class _RawJsonOutput:
    """Le Standardisateur rend du JSON strict en texte (chemin OpenRouter)."""

    raw = "récapitulatif final du chroniqueur"
    token_usage = _FakeUsage()
    tasks_output = [
        _FakeTaskOutput(),
        _FakeTaskOutput(),
        type(
            "T",
            (),
            {
                "pydantic": None,
                "json_dict": None,
                "raw": '```json\n{"propositions": [{"type": "date", "gramps_id": "I0300", '
                '"handle": "h300", "personne": "Odette Rippert", '
                '"cible": "événement décès", "action": "corriger la date", '
                '"preuve_url": "", "preuve_detail": "", "priorite": "haute", '
                '"confiance": 2}]}\n```',
            },
        )(),
        _FakeTaskOutput(),
    ]


class _RawJsonCrew:
    output_log_file = None

    def kickoff(self, inputs):
        return _RawJsonOutput()


class _RawJsonFactory:
    def crew(self):
        return _RawJsonCrew()


def test_run_crew_audit_parses_strict_json_from_raw_text(tmp_path, monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    monkeypatch.setattr(
        crew_audit,
        "collect_audit_findings",
        lambda *a, **k: (
            [_anom("R1", "haute", "I1", "h1", "x")],
            [],
            [_person("I1", "h1", "A B")],
            [],
        ),
    )
    report = run_crew_audit(
        client=None,
        scope="all",
        output_dir=tmp_path,
        date="2026-07-19",
        dry_run=True,
        crew_factory=_RawJsonFactory,
    )
    props = yaml.safe_load(
        (report.parent / "2026-07-19_propositions_audit_all.yaml").read_text()
    )
    assert props["propositions"][0]["personne"] == "Odette Rippert"
    assert "Propositions actionnables : 1" in report.read_text(encoding="utf-8")


class _CrashingCrew:
    output_log_file = None

    def kickoff(self, inputs):
        raise RuntimeError("400 fournisseur LLM")


class _CrashingFactory:
    def crew(self):
        return _CrashingCrew()


def test_run_crew_audit_survives_a_crashing_batch(tmp_path, monkeypatch):
    monkeypatch.delenv("GENECREW_DRY_RUN", raising=False)
    monkeypatch.setattr(
        crew_audit,
        "collect_audit_findings",
        lambda *a, **k: (
            [_anom("R1", "haute", "I1", "h1", "x")],
            [],
            [_person("I1", "h1", "A B")],
            [],
        ),
    )
    report = run_crew_audit(
        client=None,
        scope="all",
        output_dir=tmp_path,
        date="2026-07-19",
        dry_run=True,
        crew_factory=_CrashingFactory,
    )
    md = report.read_text(encoding="utf-8")
    assert "Lot en échec" in md  # rapport écrit quand même
    assert "Propositions actionnables : 0" in md


def test_run_crew_audit_real_write_mode_leaves_switch_untouched(tmp_path, monkeypatch):
    _FakeCrew.kickoff_inputs = []
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")  # operator opted into writes
    monkeypatch.setattr(
        crew_audit,
        "collect_audit_findings",
        lambda *a, **k: (
            [_anom("R1", "haute", "I1", "h1", "x")],
            [],
            [_person("I1", "h1", "A B")],
            [],
        ),
    )

    run_crew_audit(
        client=None,
        scope="all",
        output_dir=tmp_path,
        date="2026-07-19",
        dry_run=False,
        crew_factory=_FakeFactory,
    )
    # effective_dry_run is False → we must NOT override the operator's switch.
    assert __import__("os").environ["GENECREW_DRY_RUN"] == "false"
