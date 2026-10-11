"""Which model runs each stage of notes generation, and how hard it thinks."""

from dataclasses import dataclass
from typing import Any, Literal

from app.worker.config import WorkerSettings

Effort = Literal["low", "medium", "high", "xhigh"]


@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: Effort | None = None
    max_tokens: int = 32000

    def parameters(self) -> dict[str, Any]:
        reasoning = {"effort": self.effort} if self.effort else {"enabled": True}
        return {"max_tokens": self.max_tokens, "reasoning": reasoning}

    def describe(self) -> str:
        return f"{self.model} ({self.effort or 'adaptive'})"


@dataclass(frozen=True)
class NotesModels:
    planner: ModelSpec
    coverage: ModelSpec
    selector: ModelSpec
    writer: ModelSpec
    verifier: ModelSpec
    escalation: ModelSpec
    consistency: ModelSpec

    @classmethod
    def from_settings(cls, settings: WorkerSettings) -> "NotesModels":
        return cls(
            planner=ModelSpec(settings.notes_planner_model, "medium"),
            coverage=ModelSpec(settings.notes_planner_model, "high"),
            selector=ModelSpec(settings.notes_selector_model, "low", 16000),
            writer=ModelSpec(settings.notes_writer_model, "medium", 40000),
            verifier=ModelSpec(settings.notes_verifier_model, "high"),
            escalation=ModelSpec(settings.notes_escalation_model, "high"),
            consistency=ModelSpec(settings.notes_writer_model, "medium", 40000),
        )

    def summary(self) -> dict[str, str]:
        return {stage: spec.describe() for stage, spec in vars(self).items()}
