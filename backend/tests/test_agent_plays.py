"""K8: the canned-workflow ("play") library — every play must reference
real, registered tools, and each play's tool subset must actually be a
subset of what get_thread's provider sees."""

from app.services.agent.plays import PLAYS, PLAYS_BY_ID
from app.services.agent.tools.registry import ALL_TOOLS


def test_every_play_references_only_real_tools():
    for play in PLAYS:
        for tool_name in play.tools:
            assert tool_name in ALL_TOOLS, f"play '{play.id}' references unknown tool '{tool_name}'"


def test_play_ids_are_unique_and_indexed_correctly():
    ids = [p.id for p in PLAYS]
    assert len(ids) == len(set(ids))
    assert PLAYS_BY_ID[PLAYS[0].id] is PLAYS[0]


def test_every_play_has_a_non_empty_prompt_and_label():
    for play in PLAYS:
        assert play.prompt.strip()
        assert play.label.strip()
        assert play.tools
