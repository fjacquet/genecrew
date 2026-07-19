"""The GeneCrew audit crew: two LLM agents over the deterministic findings.

Détective-Corrélateur — reads Gramps + Wikipedia, judges the anomalies, holds NO
write tool. Chroniqueur-Greffier — the only writer, holds ONLY the append-only note/
tag tools. Write isolation is structural (tool wiring), not a prompt promise.

LLM: read from the `MODEL` env (OpenRouter/LiteLLM, e.g. openrouter/z-ai/glm-5.2).
"""

from __future__ import annotations

import os

from crewai import LLM, Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

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
from crewai_custom_tools.tools.web.wikipedia import (
    WikipediaArticleTool,
    WikipediaSearchTool,
)

DEFAULT_MODEL = "openrouter/z-ai/glm-5.2"


def build_llm() -> LLM:
    """Build the crew LLM from the MODEL env (OpenRouter via LiteLLM)."""
    return LLM(model=os.environ.get("MODEL", DEFAULT_MODEL))


@CrewBase
class Genecrew:
    """GeneCrew audit crew: Détective (read + Wikipedia, no write) → Chroniqueur (write only)."""

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
            llm=build_llm(),
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
            llm=build_llm(),
            verbose=True,
        )

    @task
    def interpreter_anomalies(self) -> Task:
        return Task(config=self.tasks_config["interpreter_anomalies"])  # type: ignore[index]

    @task
    def rediger_annotations(self) -> Task:
        return Task(config=self.tasks_config["rediger_annotations"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        """Creates the GeneCrew audit crew (sequential: Détective then Chroniqueur)."""
        return Crew(
            agents=self.agents,  # created by the @agent decorators
            tasks=self.tasks,  # created by the @task decorators
            process=Process.sequential,
            verbose=True,
        )
