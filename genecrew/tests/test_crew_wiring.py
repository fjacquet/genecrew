"""Offline wiring test: 4 agents, tool isolation, LLM per-role from env.

No network — instantiating the crew only builds config objects; the LLM is only
called at kickoff, which this test never does.
"""

from crewai import Process

from genecrew.crew import DEFAULT_MODEL, Genecrew, build_llm

WRITE_TOOL_NAMES = {"gramps_create_note", "gramps_ensure_tag", "gramps_attach"}
READ_TOOL_NAMES = {"gramps_get_object", "gramps_person_timeline", "gramps_search"}
WIKIPEDIA_TOOL_NAMES = {"Wikipedia Search", "Wikipedia Article Fetcher"}
HISTORIEN_API_NAMES = {"insee_deces_search", "gallica_search", "wikidata_sparql"}
ANALYSIS_TOOL_NAMES = {"genealogy_check_person", "genealogy_find_duplicates",
                       "genealogy_resolve_place"}


def _tool_names(agent):
    return {t.name for t in agent.tools}


def test_detective_reads_and_correlates_but_cannot_write():
    names = _tool_names(Genecrew().detective())
    assert names == READ_TOOL_NAMES | WIKIPEDIA_TOOL_NAMES
    assert names.isdisjoint(WRITE_TOOL_NAMES)


def test_historien_hunts_proof_but_cannot_write():
    names = _tool_names(Genecrew().historien())
    assert names == HISTORIEN_API_NAMES | WIKIPEDIA_TOOL_NAMES | {"gramps_get_object"}
    assert names.isdisjoint(WRITE_TOOL_NAMES)


def test_standardisateur_analyzes_but_cannot_write():
    names = _tool_names(Genecrew().standardisateur())
    assert names == ANALYSIS_TOOL_NAMES | {"gramps_get_object"}
    assert names.isdisjoint(WRITE_TOOL_NAMES)


def test_chroniqueur_holds_only_the_append_only_write_tools():
    assert _tool_names(Genecrew().chroniqueur()) == WRITE_TOOL_NAMES


def test_crew_is_sequential_with_four_agents_and_four_tasks():
    crew = Genecrew().crew()
    assert crew.process == Process.sequential
    assert len(crew.agents) == 4
    assert len(crew.tasks) == 4


class _FakeLLM:
    """Captures the model string without CrewAI's provider-prefix parsing."""

    def __init__(self, model):
        self.model = model


def test_build_llm_reads_model_from_env(monkeypatch):
    monkeypatch.setattr("genecrew.crew.LLM", _FakeLLM)
    monkeypatch.setenv("MODEL", "openrouter/z-ai/glm-5.2")
    assert build_llm().model == "openrouter/z-ai/glm-5.2"


def test_build_llm_falls_back_to_default_when_env_absent(monkeypatch):
    monkeypatch.setattr("genecrew.crew.LLM", _FakeLLM)
    monkeypatch.delenv("MODEL", raising=False)
    assert build_llm().model == DEFAULT_MODEL


def test_build_llm_role_override_and_fallback(monkeypatch):
    monkeypatch.setattr("genecrew.crew.LLM", _FakeLLM)
    monkeypatch.setenv("MODEL", "openrouter/z-ai/glm-5.2")
    monkeypatch.setenv("MODEL_HISTORIEN", "openrouter/pas-cher/mini")
    assert build_llm("historien").model == "openrouter/pas-cher/mini"
    # rôle sans override -> repli sur MODEL
    assert build_llm("chroniqueur").model == "openrouter/z-ai/glm-5.2"
