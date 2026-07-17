"""Tests of the pure stats formatting (no network, no client)."""

from genecrew.stats import format_stats


def test_format_stats_aligns_and_orders():
    out = format_stats("Famille Jacquet", {"people": 1234, "tags": 7})
    lines = out.splitlines()
    assert lines[0] == "Arbre : Famille Jacquet"
    assert lines[2] == "people    1234"
    assert lines[3] == "tags         7"


def test_format_stats_unknown_tree_name():
    out = format_stats(None, {"people": 1})
    assert out.splitlines()[0] == "Arbre : (sans nom)"
