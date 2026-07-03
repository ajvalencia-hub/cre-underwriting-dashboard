"""Parity case registry: the two built-in synthetic cases plus any drop-in
real templates under corpus/dropin/<name>/{template.xlsx, mapping.json,
inputs.json} (gitignored — put real firm templates there locally)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tests.parity import builders

CORPUS_DIR = Path(__file__).parent / "corpus"
DROPIN_DIR = CORPUS_DIR / "dropin"


@dataclass
class ParityCase:
    name: str
    inputs: dict
    mapping: dict
    # Exactly one of the two is set: a builder for synthetic templates, or a
    # path to a real drop-in xlsx.
    builder: Callable[[Path], None] | None = None
    template_path: Path | None = None

    def materialize_template(self, workdir: Path) -> Path:
        if self.template_path is not None:
            return self.template_path
        path = workdir / f"{self.name}.xlsx"
        assert self.builder is not None
        self.builder(path)
        return path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_builtin_cases() -> list[ParityCase]:
    return [
        ParityCase(
            name="acquisition_io",
            inputs=_load_json(CORPUS_DIR / "acquisition_io" / "inputs.json"),
            mapping=_load_json(CORPUS_DIR / "acquisition_io" / "mapping.json"),
            builder=builders.build_acquisition_template,
        ),
        ParityCase(
            name="development_ltv",
            inputs=_load_json(CORPUS_DIR / "development_ltv" / "inputs.json"),
            mapping=_load_json(CORPUS_DIR / "development_ltv" / "mapping.json"),
            builder=builders.build_development_template,
        ),
    ]


def load_dropin_cases() -> list[ParityCase]:
    cases: list[ParityCase] = []
    if not DROPIN_DIR.exists():
        return cases
    for case_dir in sorted(DROPIN_DIR.iterdir()):
        template = case_dir / "template.xlsx"
        mapping = case_dir / "mapping.json"
        inputs = case_dir / "inputs.json"
        if template.exists() and mapping.exists() and inputs.exists():
            cases.append(
                ParityCase(
                    name=f"dropin:{case_dir.name}",
                    inputs=_load_json(inputs),
                    mapping=_load_json(mapping),
                    template_path=template,
                )
            )
    return cases


def load_all_cases() -> list[ParityCase]:
    return load_builtin_cases() + load_dropin_cases()
