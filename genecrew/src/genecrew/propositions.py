"""Shared proposition models — re-exported from the library (single vocabulary).

`PropositionAudit`/`PropositionsLot` live in crewai_custom_tools domain since the pure
D-rules emit them too; every genecrew import keeps working through this shim.
"""

from crewai_custom_tools.tools.genealogy.models.domain import (
    PropositionAudit,
    PropositionsLot,
)
