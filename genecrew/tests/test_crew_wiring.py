"""Offline wiring test: agents, tools, write-isolation, LLM from MODEL env.

No network — instantiating the crew only builds config objects; the LLM is only
called at kickoff, which this test never does.
"""

from crewai import Process

from genecrew.crew import DEFAULT_MODEL, Genecrew, build_llm

WRITE_TOOL_NAMES = {"gramps_create_note", "gramps_ensure_tag", "gramps_attach"}
READ_TOOL_NAMES = {"gramps_get_object", "gramps_person_timeline", "gramps_search"}
WIKIPEDIA_TOOL_NAMES = {"Wikipedia Search", "Wikipedia Article Fetcher"}


def _tool_names(agent):
    return {t.name for t in agent.tools}


def test_detective_reads_and_correlates_but_cannot_write():
    detective = Genecrew().detective()
    names = _tool_names(detective)
    assert names == READ_TOOL_NAMES | WIKIPEDIA_TOOL_NAMES
    # Write isolation is structural: the Détective simply has no write tool.
    assert names.isdisjoint(WRITE_TOOL_NAMES)


def test_chroniqueur_holds_only_the_append_only_write_tools():
    chroniqueur = Genecrew().chroniqueur()
    assert _tool_names(chroniqueur) == WRITE_TOOL_NAMES


def test_crew_is_sequential_with_two_agents_and_two_tasks():
    crew = Genecrew().crew()
    assert crew.process == Process.sequential
    assert len(crew.agents) == 2
    assert len(crew.tasks) == 2


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
