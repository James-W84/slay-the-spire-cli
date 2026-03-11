import builtins
import io
import os
import sys

import pytest

# ensure the package can be imported when running tests directly
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from spire2_pkg import main


def test_interactive_loop_found(monkeypatch, capsys):
    cards = [{"name": "Hidden Cache", "tier": "B"}]
    inputs = iter(["hidden cache", "exit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    main.interactive_tier_loop(cards)

    out = capsys.readouterr().out
    assert "This card is tier B." in out


def test_interactive_loop_not_found(monkeypatch, capsys):
    cards = [{"name": "Something Else", "tier": "A"}]
    inputs = iter(["foo", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(inputs))

    main.interactive_tier_loop(cards)

    out = capsys.readouterr().out
    assert "Card not found." in out


def test_interactive_loop_ctrlc(monkeypatch, capsys):
    cards = []
    # simulate Ctrl+C on first prompt
    def fake_input(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(builtins, "input", fake_input)

    # should exit cleanly without raising
    main.interactive_tier_loop(cards)
    out = capsys.readouterr().out
    assert out == "\n"  # just the newline printed by the handler
