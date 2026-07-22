"""The GeneCrew audit crew: four LLM agents over the deterministic findings.

Chain (Process.sequential): Détective (judges the anomalies) → Historien (hunts external
proof: INSEE deaths, Gallica, Wikidata, Wikipedia) → Standardisateur (turns verdict+proof
into precise, structured propositions — output_pydantic, never free-text parsing) →
Chroniqueur (the ONLY writer: append-only note/tag tools). Write isolation is structural
(tool wiring), not a prompt promise.

LLM: `build_llm(role)` reads MODEL_<ROLE> (e.g. MODEL_HISTORIEN) with fallback on MODEL
(OpenRouter/LiteLLM, e.g. openrouter/z-ai/glm-5.2).
"""

from __future__ import annotations

import os

from crewai import LLM, Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from crewai_custom_tools.tools.genealogy.analysis.tools import (
    GenealogyCheckPersonTool,
    GenealogyFindDuplicatesTool,
)
from crewai_custom_tools.tools.genealogy.geo.tools import GenealogyResolvePlaceTool
from crewai_custom_tools.tools.genealogy.gramps.read_tools import (
    GrampsGetObjectTool,
    GrampsSearchTool,
    GrampsTimelineTool,
)
from crewai_custom_tools.tools.genealogy.gramps.write_tools import (
    GrampsAttachTool,
    GrampsCreateNoteTool,
    GrampsEnsureTagTool,
)
from crewai_custom_tools.tools.genealogy.matchid import InseeDecesSearchTool
from crewai_custom_tools.tools.web.gallica import GallicaSearchTool
from crewai_custom_tools.tools.web.wikidata import WikidataSparqlTool
from crewai_custom_tools.tools.web.wikipedia import (
    WikipediaArticleTool,
    WikipediaSearchTool,
)

from genecrew.propositions import PropositionAudit, PropositionsLot

DEFAULT_MODEL = "openrouter/z-ai/glm-5.2"


def build_llm(role: str | None = None) -> LLM:
    """Build an agent LLM: MODEL_<ROLE> env override, fallback on MODEL.

    For openrouter/* models, OPENROUTER_PROVIDER_ORDER (comma-separated, e.g. "Z.AI")
    pins the serving provider with allow_fallbacks=false — OpenRouter routing drifts
    hour to hour and some routed providers reject our tool JSON schemas (400 "Invalid
    structured output syntax").
    """
    model = os.environ.get("MODEL", DEFAULT_MODEL)
    if role:
        model = os.environ.get(f"MODEL_{role.upper()}", model)
    kwargs: dict = {}
    provider_order = os.environ.get("OPENROUTER_PROVIDER_ORDER", "").strip()
    if provider_order and model.startswith("openrouter/"):
        kwargs["extra_body"] = {
            "provider": {
                "order": [p.strip() for p in provider_order.split(",") if p.strip()],
                "allow_fallbacks": False,
            }
        }
    # is_litellm: CrewAI's native OpenAI-compatible provider hardcodes "strict": true on
    # every tool schema, which Mistral's API rejects (400 "Invalid structured output
    # syntax"). The LiteLLM path builds plain tool schemas that every provider accepts.
    return LLM(model=model, is_litellm=True, **kwargs)


@CrewBase
class Genecrew:
    """Audit chain: Détective → Historien → Standardisateur → Chroniqueur (only writer)."""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks/audit.yaml"

    @agent
    def detective(self) -> Agent:
        """Reads and correlates; deliberately has no write tool."""
        return Agent(
            config=self.agents_config["detective"],  # type: ignore[index]
            tools=[
                GrampsGetObjectTool(),
                GrampsTimelineTool(),
                GrampsSearchTool(),
                WikipediaSearchTool(),
                WikipediaArticleTool(),
            ],
            llm=build_llm("detective"),
            verbose=True,
        )

    @agent
    def historien(self) -> Agent:
        """Hunts external proof (free archives APIs); no write tool."""
        return Agent(
            config=self.agents_config["historien"],  # type: ignore[index]
            tools=[
                InseeDecesSearchTool(),
                GallicaSearchTool(),
                WikidataSparqlTool(),
                WikipediaSearchTool(),
                WikipediaArticleTool(),
                GrampsGetObjectTool(),
            ],
            llm=build_llm("historien"),
            verbose=True,
        )

    @agent
    def standardisateur(self) -> Agent:
        """Formulates precise propositions; analysis tools only, no write tool."""
        return Agent(
            config=self.agents_config["standardisateur"],  # type: ignore[index]
            tools=[
                GenealogyCheckPersonTool(),
                GenealogyFindDuplicatesTool(),
                GenealogyResolvePlaceTool(),
                GrampsGetObjectTool(),
            ],
            llm=build_llm("standardisateur"),
            verbose=True,
        )

    @agent
    def chroniqueur(self) -> Agent:
        """The only writer; holds only the append-only note/tag tools."""
        return Agent(
            config=self.agents_config["chroniqueur"],  # type: ignore[index]
            tools=[
                GrampsEnsureTagTool(),
                GrampsCreateNoteTool(),
                GrampsAttachTool(),
            ],
            llm=build_llm("chroniqueur"),
            verbose=True,
        )

    @task
    def interpreter_anomalies(self) -> Task:
        return Task(config=self.tasks_config["interpreter_anomalies"])  # type: ignore[index]

    @task
    def rechercher_preuves(self) -> Task:
        return Task(config=self.tasks_config["rechercher_preuves"])  # type: ignore[index]

    @task
    def formuler_propositions(self) -> Task:
        # Pas d'output_pydantic natif : via OpenRouter, le response_format JSON-schema
        # n'a pas d'endpoint (Z.AI) ou est rejeté selon le fournisseur routé. Le prompt
        # impose du JSON strict, validé par PropositionsLot dans l'orchestrateur.
        return Task(config=self.tasks_config["formuler_propositions"])  # type: ignore[index]

    @task
    def rediger_annotations(self) -> Task:
        return Task(config=self.tasks_config["rediger_annotations"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        """Creates the audit chain (sequential, 4 agents)."""
        return Crew(
            agents=self.agents,  # created by the @agent decorators
            tasks=self.tasks,  # created by the @task decorators
            process=Process.sequential,
            verbose=True,
        )
