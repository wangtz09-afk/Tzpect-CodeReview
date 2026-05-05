"""Base Agent class with shared logic."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from utils.llm import LLMClient, LLMResponse
from config import get_settings


@dataclass
class AgentResult:
    """Result from an agent execution."""
    agent_name: str
    success: bool
    output: str
    metadata: dict = field(default_factory=dict)
    error: str = ""


class BaseAgent(ABC):
    """
    Base class for all agents in the pipeline.
    Each agent has its own LLM client, system prompt, and execution logic.
    """

    def __init__(self, agent_name: str, model: str):
        self.agent_name = agent_name
        self.settings = get_settings()
        self.llm = LLMClient(
            model=model,
            temperature=self.settings.get("temperature", 0.3),
            max_tokens=self.settings.get("max_tokens", 4096),
        )

    @abstractmethod
    def get_system_prompt(self, **kwargs) -> str:
        """Return the system prompt for this agent."""
        pass

    @abstractmethod
    def build_user_prompt(self, **kwargs) -> str:
        """Build the user prompt from input data."""
        pass

    def run(self, **kwargs) -> AgentResult:
        """Execute the agent's task."""
        try:
            system_prompt = self.get_system_prompt(**{k: v for k, v in kwargs.items() if k in ("review_context", "extra_context")})
            user_prompt = self.build_user_prompt(**kwargs)
            context = kwargs.get("context", "")

            # Truncate prompts if they exceed reasonable length
            max_prompt = 28000  # Leave room for system prompt and response
            if len(user_prompt) > max_prompt:
                user_prompt = self._truncate_prompt(user_prompt, max_prompt)

            response: LLMResponse = self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=context,
            )

            if not response.success:
                return AgentResult(
                    agent_name=self.agent_name,
                    success=False,
                    output="",
                    error=response.error,
                )

            return AgentResult(
                agent_name=self.agent_name,
                success=True,
                output=response.content,
                metadata={
                    "model": response.model,
                    "tokens_used": response.tokens_used,
                },
            )

        except Exception as e:
            return AgentResult(
                agent_name=self.agent_name,
                success=False,
                output="",
                error=str(e),
            )

    def _truncate_prompt(self, prompt: str, max_length: int) -> str:
        """Smart truncation: keep beginning and end, summarize middle."""
        if len(prompt) <= max_length:
            return prompt

        # Keep first 60% and last 40%
        keep_start = int(max_length * 0.6)
        keep_end = max_length - keep_start - 100
        truncated = (
            prompt[:keep_start]
            + f"\n\n... (truncated {len(prompt) - max_length} chars to fit context) ...\n\n"
            + prompt[-keep_end:]
        )
        return truncated
