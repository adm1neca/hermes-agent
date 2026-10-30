"""The change watcher does no disk work while nobody can receive its events.

A messaging gateway keeps the watcher thread after its last WS client leaves; on a
slow filesystem the signature probes then ran nonstop for events that were dropped.
"""

import pytest

from tui_gateway import server


@pytest.fixture()
def probes(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_broadcast_skin_if_changed", lambda: calls.append("skin"))
    monkeypatch.setattr(server, "_broadcast_watched_changes", lambda: calls.append("watched"))
    monkeypatch.setattr(server, "_live_transports", set())
    monkeypatch.setattr(server, "_stdio_is_rpc_channel", False)
    return calls


def test_no_client_skips_every_probe(probes):
    server._watch_pass()

    assert probes == []


def test_connected_ws_peer_runs_the_probes(probes):
    server._live_transports.add(object())

    server._watch_pass()

    assert probes == ["skin", "watched"]


def test_stdio_tui_runs_the_probes_without_ws_peers(probes, monkeypatch):
    monkeypatch.setattr(server, "_stdio_is_rpc_channel", True)

    server._watch_pass()

    assert probes == ["skin", "watched"]
