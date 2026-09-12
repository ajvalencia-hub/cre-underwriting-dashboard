"""K3: the full agent tool surface, tagged read vs write. The runner (K4)
dispatches every tool call through this registry rather than calling tool
functions directly, so privilege enforcement lives in exactly one place."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.services.agent.providers.types import ToolSpec
from app.services.agent.tools import read_tools, write_tools

_NUM = {"type": "number"}
_STR = {"type": "string"}


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    privilege: Literal["read", "write"]
    fn: Callable


_READ_TOOLS: list[ToolDef] = [
    ToolDef(
        name="get_deal",
        description=(
            "Fetch the CURRENT deal's status and full input values. Always scoped to the "
            "deal this conversation is about — takes no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        privilege="read",
        fn=read_tools.get_deal,
    ),
    ToolDef(
        name="list_scenarios",
        description=(
            "List the saved scenarios for the CURRENT deal (id, name, kind only) — takes "
            "no arguments."
        ),
        parameters={"type": "object", "properties": {}},
        privilege="read",
        fn=read_tools.list_scenarios,
    ),
    ToolDef(
        name="get_scenario",
        description="Fetch one saved scenario's full inputs and outputs by id.",
        parameters={"type": "object", "properties": {"scenarioId": _STR}, "required": ["scenarioId"]},
        privilege="read",
        fn=read_tools.get_scenario,
    ),
    ToolDef(
        name="compute",
        description=(
            "Run the pro-forma engine on a full set of input values and return every "
            "computed output metric (IRR, equity multiple, DSCR, yield on cost, etc.). "
            "This is the ONLY source of truth for metrics — never state a number that "
            "didn't come from this tool (or solve/run_sensitivity/run_tornado below)."
        ),
        parameters={
            "type": "object",
            "properties": {"values": {"type": "object", "description": "Full input field id -> value map."}},
            "required": ["values"],
        },
        privilege="read",
        fn=read_tools.compute,
    ),
    ToolDef(
        name="solve",
        description=(
            "Goal-seek: find the value of ONE numeric input that makes ONE output metric hit a "
            "target — 'what exit cap / price / rent gets me to X% IRR'. Scans the input across "
            "`bounds` (default: the field's schema min/max, else ±80% of its current value), "
            "bisects the crossing nearest the current value, and returns solvedValue + "
            "achievedMetric; when the metric never crosses the target it returns solvedValue=null "
            "with a reason instead of guessing. `values` defaults to the CURRENT deal's inputs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "values": {
                    "type": "object",
                    "description": "Full input field id -> value map to solve over. Omit to use the current deal's inputs.",
                },
                "targetInput": {
                    "type": "string",
                    "description": "Numeric input field id to solve for (e.g. exitCapRatePct, purchasePrice).",
                },
                "outputMetric": {
                    "type": "string",
                    "description": "Output metric id to hit (e.g. leveredIrr, minDscr, yieldOnCost).",
                },
                "targetValue": {
                    "type": "number",
                    "description": "Target for the metric, in the metric's own units (0.15 for a 15% IRR).",
                },
                "bounds": {
                    "type": "array",
                    "items": _NUM,
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Optional [low, high] scan range for the input.",
                },
            },
            "required": ["targetInput", "outputMetric", "targetValue"],
        },
        privilege="read",
        fn=read_tools.solve,
    ),
    ToolDef(
        name="run_tornado",
        description="Perturbation sensitivity: which single driver (rent, exit cap, cost, opex, rate, vacancy) moves a given metric the most.",
        parameters={
            "type": "object",
            "properties": {"values": {"type": "object"}, "metric": _STR},
            "required": ["values"],
        },
        privilege="read",
        fn=read_tools.run_tornado,
    ),
    ToolDef(
        name="run_sensitivity",
        description="Grid sensitivity: sweep 1-2 input drivers across a list of values each and return the resulting output metrics at every combination.",
        parameters={
            "type": "object",
            "properties": {
                "baseValues": {"type": "object"},
                "drivers": {"type": "array", "items": {"type": "object"}},
                "outputFieldIds": {"type": "array", "items": _STR},
            },
            "required": ["baseValues", "drivers", "outputFieldIds"],
        },
        privilege="read",
        fn=read_tools.run_sensitivity,
    ),
    ToolDef(
        name="get_market_context",
        description="Fetch market/submarket context data (demographics, rates, pricing benchmarks) for a given market and property type.",
        parameters={
            "type": "object",
            "properties": {"market": _STR, "submarket": _STR, "propertyType": _STR},
            "required": ["market"],
        },
        privilege="read",
        fn=read_tools.get_market_context,
    ),
    ToolDef(
        name="list_comps",
        description="List saved sale or rent comps, optionally filtered by market.",
        parameters={
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["sale", "rent"]}, "market": _STR},
            "required": ["kind"],
        },
        privilege="read",
        fn=read_tools.list_comps,
    ),
    ToolDef(
        name="get_schema",
        description="List every valid input/output field id, label, and type — use this to check a field id is real before proposing changes to it.",
        parameters={"type": "object", "properties": {}},
        privilege="read",
        fn=read_tools.get_schema,
    ),
]

_WRITE_TOOLS: list[ToolDef] = [
    ToolDef(
        name="propose_input_changes",
        description=(
            "Propose changes to a deal's input values for the user to review and approve. "
            "This NEVER applies the changes — it only returns a proposal with a computed "
            "preview. Always call this instead of telling the user to change a value "
            "themselves when you're recommending a specific edit."
        ),
        parameters={
            "type": "object",
            "properties": {
                "currentValues": {"type": "object"},
                "changes": {"type": "object", "description": "field id -> new value, only the fields being changed"},
                "rationale": _STR,
            },
            "required": ["currentValues", "changes", "rationale"],
        },
        privilege="write",
        fn=write_tools.propose_input_changes,
    ),
    ToolDef(
        name="propose_scenario",
        description="Propose a new named scenario (a variant set of input changes) for the user to review and save. Never applies it directly.",
        parameters={
            "type": "object",
            "properties": {
                "name": _STR,
                "currentValues": {"type": "object"},
                "changes": {"type": "object"},
                "rationale": _STR,
            },
            "required": ["name", "currentValues", "changes", "rationale"],
        },
        privilege="write",
        fn=write_tools.propose_scenario,
    ),
]

ALL_TOOLS: dict[str, ToolDef] = {t.name: t for t in (*_READ_TOOLS, *_WRITE_TOOLS)}


def to_tool_specs(names: list[str] | None = None) -> list[ToolSpec]:
    """The subset (or all) tools, as vendor-neutral ToolSpecs for the
    provider layer. `names=None` returns the full surface."""
    tools = ALL_TOOLS.values() if names is None else (ALL_TOOLS[n] for n in names)
    return [ToolSpec(name=t.name, description=t.description, parameters=t.parameters) for t in tools]
