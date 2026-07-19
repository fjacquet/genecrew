"""Shared proposition models — one schema for every producer (crew LLM or pure rules).

Neutral module (no crewai import): the deterministic enrichers must not pay the cost
of the crew stack to emit a proposal.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PropositionAudit(BaseModel):
    """One precise, human-applicable correction proposal (confidence capped at 2/4)."""

    type: str = Field(description="date | lieu | relation | nom | source | doublon | autre")
    gramps_id: str
    handle: str
    personne: str
    cible: str = Field(description="Objet Gramps visé (ex. 'événement E0607 de I0010').")
    action: str = Field(description="Le changement exact à appliquer, en une phrase.")
    preuve_url: str = Field(default="", description="URL/référence de la preuve, si preuve.")
    preuve_detail: str = Field(default="", description="Ce que la preuve établit.")
    priorite: str = Field(description="haute | moyenne | basse")
    confiance: int = Field(ge=1, le=2, description="1 plausible, 2 preuve concordante.")


class PropositionsLot(BaseModel):
    """Structured batch of propositions."""

    propositions: list[PropositionAudit] = Field(default_factory=list)
