"""
remediation_classifier.py — deterministic classification of selected recommendations.

No LLM call. Pure keyword matching on the selected_recommendation text.

v1 classification rules (evaluated in order):
  1. Blocked keywords → UnsupportedRemediationType (rollback, secret, migration, etc.)
  2. Schema validation keywords → "schema_validation"
  3. Anything else → UnsupportedRemediationType (unrecognised)

Only "schema_validation" is actionable in v1. ci_guardrail and test_coverage are
named here for future expansion but not yet reachable via the keyword rules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class UnsupportedRemediationType(ValueError):
    """
    Raised when the selected_recommendation maps to a blocked type, or cannot
    be mapped to any recognised v1 remediation type.

    Treated as HTTP 422 Unprocessable Entity at the API layer.
    """


# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

# Checked first — any match raises immediately, no further evaluation.
_BLOCKED_KEYWORDS: frozenset[str] = frozenset(
    {
        "rollback",
        "revert",
        "secret",
        "credential",
        "kubectl",
        "helm",
        "migration",
        "migrate",
        "alter table",
        "drop table",
        "bq update",
        "bq mk",
        "production mutation",
        "rotate",
    }
)

# Checked after the blocklist — first match returns "schema_validation".
_SCHEMA_VALIDATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "schema",
        "validation",
        "validate",
        "compatibility",
        "compatible",
        "pre-deploy",
        "predeploy",
        "pre_deploy",
        "mismatch",
    }
)

# ---------------------------------------------------------------------------
# v1 allowed types (for reference / future gating)
# ---------------------------------------------------------------------------

V1_ALLOWED_TYPES: frozenset[str] = frozenset({"schema_validation"})


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_remediation_type(selected_recommendation: str) -> str:
    """
    Classify a selected_recommendation string into a remediation type.

    Returns the remediation type (e.g. "schema_validation") on success.
    Raises UnsupportedRemediationType if the recommendation is blocked or
    cannot be matched to a known type.

    Evaluation order:
      1. Blocklist  — any blocked keyword → raise immediately.
      2. Schema validation keywords → return "schema_validation".
      3. Fallback   → raise (unrecognised recommendation).
    """
    text = selected_recommendation.lower()

    # Step 1: blocklist — checked first, blocklist always wins
    for keyword in _BLOCKED_KEYWORDS:
        if keyword in text:
            raise UnsupportedRemediationType(
                f"Recommendation contains a blocked keyword: '{keyword}'. "
                f"InfraPilot does not automate rollbacks, migrations, secret "
                f"rotation, or direct infrastructure mutations. "
                f"Please implement this change manually."
            )

    # Step 2: schema validation
    for keyword in _SCHEMA_VALIDATION_KEYWORDS:
        if keyword in text:
            return "schema_validation"

    # Step 3: unrecognised
    raise UnsupportedRemediationType(
        f"Could not classify recommendation as a supported remediation type. "
        f"Supported types in v1: {sorted(V1_ALLOWED_TYPES)}. "
        f"Received: '{selected_recommendation[:200]}'"
    )
