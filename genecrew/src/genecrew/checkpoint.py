"""Resumable batch checkpoints for long-running workflows (JSON on disk)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    workflow: str
    scope: str
    done_handles: set[str] = field(default_factory=set)


def load_checkpoint(path: Path) -> Checkpoint | None:
    """Load a checkpoint, or None if the file does not exist."""
    if not Path(path).exists():
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Checkpoint(
        workflow=data["workflow"],
        scope=data["scope"],
        done_handles=set(data.get("done_handles", [])),
    )


def save_checkpoint(path: Path, cp: Checkpoint) -> None:
    """Persist a checkpoint atomically-enough for a single-writer CLI."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(
            {
                "workflow": cp.workflow,
                "scope": cp.scope,
                "done_handles": sorted(cp.done_handles),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
