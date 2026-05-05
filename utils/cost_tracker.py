"""Cost tracking for LLM API calls.

Tracks token usage per file, per stage, and overall budget.
"""
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StageCost:
    """Cost for a single pipeline stage."""
    stage_name: str
    tokens_used: int = 0
    estimated_cost: float = 0.0  # in USD (approximate)


@dataclass
class FileCost:
    """Cost breakdown for a single file review."""
    file_path: str
    stages: list[StageCost] = field(default_factory=list)
    total_tokens: int = 0
    estimated_cost: float = 0.0


# Rough pricing per 1K tokens (USD) for deepseek-v4-flash
DEFAULT_PRICING = {
    "input_per_1k": 0.00014,   # ~$0.14/M tokens
    "output_per_1k": 0.00028,  # ~$0.28/M tokens
}


class CostTracker:
    """Tracks API costs across all files and stages."""

    def __init__(self, pricing: Optional[dict] = None, budget: Optional[float] = None):
        self.pricing = pricing or DEFAULT_PRICING
        self.budget = budget  # Optional budget limit in USD
        self.files: list[FileCost] = []
        self._lock = threading.Lock()

    def record_stage(
        self,
        file_path: str,
        stage_name: str,
        tokens_used: int,
    ) -> None:
        """Record token usage for a stage."""
        with self._lock:
            # Find or create file cost entry
            file_cost = next(
                (f for f in self.files if f.file_path == file_path), None
            )
            if file_cost is None:
                file_cost = FileCost(file_path=file_path)
                self.files.append(file_cost)

            # Record stage
            stage_cost = StageCost(
                stage_name=stage_name,
                tokens_used=tokens_used,
                estimated_cost=self._estimate_cost(tokens_used),
            )
            file_cost.stages.append(stage_cost)
            file_cost.total_tokens += tokens_used
            file_cost.estimated_cost += stage_cost.estimated_cost

    def get_total_tokens(self) -> int:
        """Get total tokens used across all files."""
        return sum(f.total_tokens for f in self.files)

    def get_total_cost(self) -> float:
        """Get estimated total cost in USD."""
        return sum(f.estimated_cost for f in self.files)

    def get_file_cost(self, file_path: str) -> Optional[FileCost]:
        """Get cost breakdown for a specific file."""
        return next((f for f in self.files if f.file_path == file_path), None)

    def is_over_budget(self) -> bool:
        """Check if we've exceeded the budget."""
        if self.budget is None:
            return False
        return self.get_total_cost() >= self.budget

    def get_remaining_budget(self) -> Optional[float]:
        """Get remaining budget in USD."""
        if self.budget is None:
            return None
        return max(0.0, self.budget - self.get_total_cost())

    def get_summary(self) -> dict:
        """Get cost summary."""
        total_tokens = self.get_total_tokens()
        total_cost = self.get_total_cost()
        return {
            "files_reviewed": len(self.files),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "budget": self.budget,
            "remaining_budget": self.get_remaining_budget(),
            "over_budget": self.is_over_budget(),
            "avg_cost_per_file": round(
                total_cost / len(self.files), 4
            ) if self.files else 0,
        }

    def get_detailed_summary(self) -> str:
        """Get detailed cost breakdown as string."""
        lines = []
        lines.append("=" * 60)
        lines.append("  Cost Summary")
        lines.append("=" * 60)

        for fc in self.files:
            lines.append(f"\n  {fc.file_path}")
            lines.append(f"    Tokens: {fc.total_tokens:,} | Est. Cost: ${fc.estimated_cost:.4f}")
            for stage in fc.stages:
                lines.append(
                    f"      {stage.stage_name}: {stage.tokens_used:,} tokens | ${stage.estimated_cost:.4f}"
                )

        summary = self.get_summary()
        lines.append("\n" + "-" * 60)
        lines.append(f"  Total files: {summary['files_reviewed']}")
        lines.append(f"  Total tokens: {summary['total_tokens']:,}")
        lines.append(f"  Total cost: ${summary['total_cost_usd']:.4f}")
        if summary["budget"] is not None:
            lines.append(f"  Budget: ${summary['budget']:.2f}")
            lines.append(f"  Remaining: ${summary['remaining_budget']:.2f}")
        lines.append("=" * 60)

        return "\n".join(lines)

    def _estimate_cost(self, tokens: int) -> float:
        """Rough cost estimate (split 50/50 input/output)."""
        input_tokens = tokens * 0.5
        output_tokens = tokens * 0.5
        cost = (
            input_tokens / 1000 * self.pricing["input_per_1k"]
            + output_tokens / 1000 * self.pricing["output_per_1k"]
        )
        return cost
