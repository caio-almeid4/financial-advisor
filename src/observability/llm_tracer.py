import time
from typing import Any

from src.observability.logger import get_logger


def log_event(stage: str, **data) -> None:
    """Structured log entry for a non-LLM pipeline stage."""
    get_logger().info("pipeline_event", extra={"stage": stage, **data})


def log_llm_call(
    *,
    stage: str,
    model: str,
    messages: list[dict],
    response: Any,
    latency_s: float,
    cot: str | None = None,
) -> None:
    """Structured log entry for a single OpenAI API call.

    Captures stage, model, token usage, latency, the full prompt, and
    optionally the model's chain-of-thought (reasoning field).
    """
    usage = getattr(response, "usage", None)

    # Derive a compact response preview depending on response type
    choice = response.choices[0] if response.choices else None
    if choice is None:
        response_preview = None
    elif hasattr(choice.message, "parsed") and choice.message.parsed is not None:
        # Structured output — serialise Pydantic model
        response_preview = choice.message.parsed.model_dump()
    else:
        # Plain text (writer stage)
        content = choice.message.content or ""
        response_preview = content[:500] + ("…" if len(content) > 500 else "")

    get_logger().info(
        "llm_call",
        extra={
            "stage": stage,
            "model": model,
            "latency_s": round(latency_s, 3),
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "cot": cot,
            "messages": messages,
            "response": response_preview,
        },
    )
