"""Tests for the agent loop helpers."""
from code_assassin.agent import Agent


def test_looks_like_action_imperatives():
    assert Agent._looks_like_action("Add a status command to cli.py")
    assert Agent._looks_like_action("Run the CLI tests")
    assert Agent._looks_like_action("Please read the parser")
    assert Agent._looks_like_action("fix the bug in agent.py")


def test_looks_like_action_conversational():
    assert not Agent._looks_like_action("My name is Nadine")
    assert not Agent._looks_like_action("Please address me as Nadine")
    assert not Agent._looks_like_action("What does the parser do?")
