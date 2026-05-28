"""
report_builder.py — validate the agent's generate_report output as InvestigationReport.

Responsibility split:
  - report_builder: parse raw args, coerce LLM quirks, Pydantic-validate, raise on failure
  - investigator:   catch ReportValidationError, send formatted error back to OpenAI, retry once

This module never calls OpenAI — it only owns the validation + coercion logic.
"""

import json

from pydantic import ValidationError

from app.core.logging import get_logger
from app.schemas.report import InvestigationReport

logger = get_logger(__name__)


class ReportValidationError(Exception):
    """
    Raised when the agent's generate_report output cannot be validated as
    InvestigationReport. Carries structured Pydantic errors so the investigator
    can format a useful retry prompt.
    """

    def __init__(self, message: str, pydantic_errors: list | None = None) -> None:
        super().__init__(message)
        self.pydantic_errors: list = pydantic_errors or []


def build_report(raw_args: dict | str) -> InvestigationReport:
    """
    Parse and validate generate_report tool call args as InvestigationReport.

    Handles common LLM output quirks before Pydantic validation:
      - Double-encoded JSON: LLM sometimes returns the whole payload as a JSON string
        instead of a dict — we json.loads it first.
      - Wrong-case Literal fields: e.g. priority="Immediate" instead of "immediate".

    Raises:
        ReportValidationError: if the args cannot be coerced into a valid InvestigationReport.
    """
    # ------------------------------------------------------------------
    # 1. Handle double-encoded JSON
    # ------------------------------------------------------------------
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            raise ReportValidationError(
                f"generate_report args are not valid JSON: {e}"
            ) from e

    if not isinstance(raw_args, dict):
        raise ReportValidationError(
            f"generate_report args must be a dict, got {type(raw_args).__name__}"
        )

    # ------------------------------------------------------------------
    # 2. Normalize Literal fields (in-place, non-destructive for valid values)
    # ------------------------------------------------------------------
    _normalize_priority_case(raw_args)

    # ------------------------------------------------------------------
    # 3. Pydantic validation
    # ------------------------------------------------------------------
    try:
        report = InvestigationReport(**raw_args)
        logger.info(
            "report_validated",
            root_cause=report.likely_root_cause[:100],
            confidence=report.confidence_score,
            evidence_count=len(report.evidence),
            timeline_count=len(report.timeline),
            actions_count=len(report.recommended_actions),
        )
        return report
    except ValidationError as e:
        raise ReportValidationError(
            f"InvestigationReport validation failed with {e.error_count()} error(s)",
            pydantic_errors=e.errors(),
        ) from e


def format_validation_error_for_llm(error: ReportValidationError) -> str:
    """
    Render a ReportValidationError as a plain-text message to append to the
    conversation and send back to the LLM as a tool result.

    The investigator uses this string as the content of the generate_report
    tool result message so the model understands what to fix before retrying.

    Example output:
        The generate_report output failed validation. Fix the issues below and
        call generate_report again with a corrected payload:
          • recommended_actions → 0 → priority: Input should be 'immediate', 'short_term' or 'long_term'
          • confidence_score: Input should be less than or equal to 1
    """
    lines = [
        "The generate_report output failed validation. "
        "Fix the issues below and call generate_report again with a corrected payload:"
    ]
    for err in error.pydantic_errors:
        loc = " → ".join(str(part) for part in err["loc"])
        lines.append(f"  • {loc}: {err['msg']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_PRIORITIES = {"immediate", "short_term", "long_term"}


def _normalize_priority_case(raw_args: dict) -> None:
    """
    Normalise RecommendedAction.priority values in-place.

    Handles variants like "Immediate", "Short Term", "short-term" → the
    canonical Literal values the schema expects.
    """
    actions = raw_args.get("recommended_actions") or []
    for action in actions:
        if not isinstance(action, dict):
            continue
        priority = action.get("priority")
        if not isinstance(priority, str):
            continue
        normalized = priority.lower().replace(" ", "_").replace("-", "_")
        if normalized in _VALID_PRIORITIES:
            action["priority"] = normalized
