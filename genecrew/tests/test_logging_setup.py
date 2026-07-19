"""Tests for the durable CLI logging setup."""

import logging

from genecrew.logging_setup import (
    CAPTURED_NAMESPACES,
    configure_logging,
    get_logger,
)


def _detach_all():
    """Remove genecrew-tagged handlers so each test starts clean."""
    for ns in CAPTURED_NAMESPACES:
        lg = logging.getLogger(ns)
        for h in list(lg.handlers):
            if hasattr(h, "_genecrew_log_tag"):
                lg.removeHandler(h)
                h.close()


def test_configure_writes_captured_namespaces_to_dated_file(tmp_path):
    _detach_all()
    try:
        log_path = configure_logging(tmp_path, date="2026-07-19")
        assert log_path == tmp_path / "logs" / "2026-07-19_genecrew.log"

        get_logger().info("commande audit lancée")
        logging.getLogger("crewai_custom_tools.gramps").warning("API 404 sur un handle")
        for h in logging.getLogger("genecrew").handlers:
            h.flush()

        content = log_path.read_text(encoding="utf-8")
        assert "commande audit lancée" in content
        assert "API 404 sur un handle" in content              # cct namespace captured
    finally:
        _detach_all()


def test_configure_is_idempotent(tmp_path):
    _detach_all()
    try:
        configure_logging(tmp_path, date="2026-07-19")
        configure_logging(tmp_path, date="2026-07-19")
        tagged = [h for h in logging.getLogger("genecrew").handlers
                  if hasattr(h, "_genecrew_log_tag")]
        assert len(tagged) == 1                                # no duplicate handler
    finally:
        _detach_all()


def test_unrelated_namespace_is_not_captured(tmp_path):
    _detach_all()
    try:
        log_path = configure_logging(tmp_path, date="2026-07-19")
        logging.getLogger("litellm").info("bruit litellm qu'on ne veut pas")
        for h in logging.getLogger("genecrew").handlers:
            h.flush()
        assert "bruit litellm" not in log_path.read_text(encoding="utf-8")
    finally:
        _detach_all()
