"""Judge versions: a hash of rubric, prompts, models and forms identifies each one (§6.11, §12.14)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from conversation_analyzer.judge import forms
from conversation_analyzer.settings import REPO_ROOT, get_settings

VERSIONS_DIR = REPO_ROOT / "judge_versions"
FORMS = (forms.Stage1Form, forms.EvidenceCheckForm, forms.Stage2Phrasings, forms.Stage2Form, forms.SessionGradeForm)


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:12]


def _read_dir(path: Path) -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(path.glob("*.md"))}


@dataclass(frozen=True)
class JudgeVersion:
    name: str
    version_id: str
    rubric_version: str
    prompt_version: str
    form_version: str
    stage1_model: str
    stage2_model: str
    rubrics: dict[str, str]
    prompts: dict[str, str]

    def system(self, task: str, rubric: str) -> str:
        """Task instructions, then the rubric in English and Polish (§6.5)."""
        return "\n\n".join(
            [self.prompts[f"{task}.md"], self.rubrics[f"{rubric}.en.md"], self.rubrics[f"{rubric}.pl.md"]]
        )


@lru_cache(maxsize=8)
def load(name: str) -> JudgeVersion:
    base = VERSIONS_DIR / name
    rubrics = _read_dir(base / "rubric")
    prompts = _read_dir(base / "prompts")
    models = yaml.safe_load((base / "models.yaml").read_text())
    form_schemas = json.dumps([f.model_json_schema() for f in FORMS], sort_keys=True)
    rubric_version = "rb-" + _hash(*(k + v for k, v in rubrics.items()))
    prompt_version = "pr-" + _hash(*(k + v for k, v in prompts.items()))
    form_version = "fm-" + _hash(form_schemas)
    version_id = f"{name}-" + _hash(rubric_version, prompt_version, form_version, models["stage1"], models["stage2"])
    return JudgeVersion(
        name=name,
        version_id=version_id,
        rubric_version=rubric_version,
        prompt_version=prompt_version,
        form_version=form_version,
        stage1_model=models["stage1"],
        stage2_model=models["stage2"],
        rubrics=rubrics,
        prompts=prompts,
    )


def current() -> JudgeVersion:
    return load(get_settings().judge.current_version)


def previous() -> JudgeVersion | None:
    name = get_settings().judge.previous_version
    return load(name) if name else None
