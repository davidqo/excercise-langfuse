from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str
    temperature: float


@dataclass(frozen=True)
class WorkflowConfig:
    max_revision_cycles: int
    default_platform: str


@dataclass(frozen=True)
class OutputConfig:
    runs_dir: str
    log_file: str


@dataclass(frozen=True)
class AppConfig:
    model: ModelConfig
    workflow: WorkflowConfig
    output: OutputConfig


def load_config(path: Path) -> AppConfig:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig(
        model=ModelConfig(**data["model"]),
        workflow=WorkflowConfig(**data["workflow"]),
        output=OutputConfig(**data["output"]),
    )
