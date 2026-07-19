"""Durable logging for the GeneCrew CLI.

Every `genecrew <command>` invocation appends to a daily log under
`<output>/logs/<date>_genecrew.log`, capturing our own code's events (the `genecrew`
and `crewai_custom_tools` namespaces) — API calls, dry-run notices, errors — without
the litellm/crewai console noise. The CLI's own `print` output to the console is left
untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path

CAPTURED_NAMESPACES = ("genecrew", "crewai_custom_tools")
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_HANDLER_ATTR = "_genecrew_log_tag"


def configure_logging(output_dir: Path | str, *, date: str) -> Path:
    """Attach one append file handler to the genecrew + cct loggers; return its path.

    Idempotent: calling it again for the same path does not add a duplicate handler,
    so repeated calls in one process (or in tests) stay clean.
    """
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date}_genecrew.log"
    tag = f"genecrew-file:{log_path}"

    if not _handler_exists(tag):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _HANDLER_ATTR, tag)
        for namespace in CAPTURED_NAMESPACES:
            lg = logging.getLogger(namespace)
            lg.setLevel(logging.INFO)
            lg.addHandler(handler)
    return log_path


def _handler_exists(tag: str) -> bool:
    for namespace in CAPTURED_NAMESPACES:
        for handler in logging.getLogger(namespace).handlers:
            if getattr(handler, _HANDLER_ATTR, None) == tag:
                return True
    return False


def get_logger() -> logging.Logger:
    """The CLI's own logger (`genecrew`)."""
    return logging.getLogger("genecrew")
