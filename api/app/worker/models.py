"""Which model a structured call uses, and how hard it thinks."""

from dataclasses import dataclass
from typing import Any, Literal

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
