"""K8: prompted-workflow library ("plays") — a canned intent bundled with a
restricted tool subset, so a one-click suggestion in the UI gets a more
focused, reliable turn than a fully freeform message. Restricting the tool
subset also narrows what the K5 provenance checker needs to reconcile
against, since the turn can only ground claims in whichever tools it was
given."""

from dataclasses import dataclass


@dataclass
class Play:
    id: str
    label: str
    prompt: str
    tools: list[str]


PLAYS: list[Play] = [
    Play(
        id="screen",
        label="Screen this deal",
        prompt=(
            "Screen this deal: compute its key return metrics, give a clear verdict "
            "(pursue / pass / needs more info), and if useful, run 2-3 solve-for-target "
            "checks (e.g. what exit cap or price would be needed for a reasonable "
            "return) to show how much cushion there is."
        ),
        tools=["get_deal", "compute", "solve", "get_schema"],
    ),
    Play(
        id="explain_metric",
        label="What's driving the levered IRR?",
        prompt=(
            "Explain what's driving this deal's levered IRR the most — run a tornado "
            "sensitivity and walk through the top 2-3 drivers."
        ),
        tools=["get_deal", "compute", "run_tornado"],
    ),
    Play(
        id="stress_test",
        label="Stress-test this deal",
        prompt=(
            "Stress-test this deal against a higher exit cap rate, a higher interest "
            "rate, and higher vacancy — run a sensitivity grid and summarize how bad "
            "it gets in the worst case."
        ),
        tools=["get_deal", "compute", "run_sensitivity", "run_tornado"],
    ),
    Play(
        id="find_target",
        label="What exit cap gets me to a 15% IRR?",
        prompt=(
            "What exit cap rate would this deal need to hit a 15% levered IRR? Use "
            "the solve tool rather than guessing."
        ),
        tools=["get_deal", "compute", "solve"],
    ),
]

PLAYS_BY_ID: dict[str, Play] = {p.id: p for p in PLAYS}
