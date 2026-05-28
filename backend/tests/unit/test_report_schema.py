"""
test_report_schema.py — unit tests for InvestigationReport Pydantic schema
and report_builder helpers.

Tests:
  - Valid full report passes validation
  - Missing required fields raise ReportValidationError
  - confidence_score out of [0,1] range is rejected
  - Priority normalisation (e.g. "Immediate" → "immediate") works
  - format_validation_error_for_llm produces a non-empty string
  - Double-encoded JSON (string inside string) is handled by build_report
"""

import json
import pytest

from app.agents.report_builder import (
    ReportValidationError,
    build_report,
    format_validation_error_for_llm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_report_dict() -> dict:
    return {
        "incident_summary": "lat-cron-job stopped writing to BigQuery.",
        "likely_root_cause": "Service account key path changed in v42 deploy.",
        "confidence_score": 0.9,
        "evidence": [
            {
                "tool": "get_recent_deploys",
                "finding": "Deploy v42 changed SERVICE_ACCOUNT_KEY_PATH.",
                "significance": "Config change coincides with incident start.",
            }
        ],
        "timeline": [
            {
                "timestamp": "2024-01-15T18:00:00+00:00",
                "event": "Deploy v42 pushed.",
                "source": "get_recent_deploys",
            }
        ],
        "recommended_actions": [
            {
                "action": "Revert SERVICE_ACCOUNT_KEY_PATH to /secrets/sa.json.",
                "priority": "immediate",
                "rationale": "Restores BigQuery auth immediately.",
            }
        ],
        "tools_used": ["get_recent_deploys", "get_service_logs", "get_bq_insert_errors"],
        "final_summary": "Deploy v42 broke BigQuery auth by changing the key path.",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_report_passes():
    report = build_report(_valid_report_dict())
    assert report.confidence_score == 0.9
    assert report.likely_root_cause.startswith("Service account")
    assert len(report.evidence) == 1
    assert len(report.recommended_actions) == 1


def test_valid_report_from_json_string():
    """build_report should accept a JSON-encoded string (double-encoded LLM output)."""
    raw = json.dumps(_valid_report_dict())
    report = build_report(raw)
    assert report.confidence_score == 0.9


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", [
    "incident_summary",
    "likely_root_cause",
    "confidence_score",
    "evidence",
    "timeline",
    "recommended_actions",
    "tools_used",
    "final_summary",
])
def test_missing_required_field_raises(missing_field):
    data = _valid_report_dict()
    del data[missing_field]
    with pytest.raises(ReportValidationError):
        build_report(data)


# ---------------------------------------------------------------------------
# confidence_score bounds
# ---------------------------------------------------------------------------

def test_confidence_score_above_1_rejected():
    data = _valid_report_dict()
    data["confidence_score"] = 1.1
    with pytest.raises(ReportValidationError):
        build_report(data)


def test_confidence_score_below_0_rejected():
    data = _valid_report_dict()
    data["confidence_score"] = -0.1
    with pytest.raises(ReportValidationError):
        build_report(data)


def test_confidence_score_boundary_values_accepted():
    for score in (0.0, 1.0, 0.5):
        data = _valid_report_dict()
        data["confidence_score"] = score
        report = build_report(data)
        assert report.confidence_score == score


# ---------------------------------------------------------------------------
# Priority normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_priority,expected", [
    ("immediate", "immediate"),
    ("Immediate", "immediate"),
    ("IMMEDIATE", "immediate"),
    ("short_term", "short_term"),
    ("Short Term", "short_term"),
    ("Short_Term", "short_term"),
    ("long_term", "long_term"),
    ("Long Term", "long_term"),
    ("Long_Term", "long_term"),
])
def test_priority_normalisation(raw_priority, expected):
    data = _valid_report_dict()
    data["recommended_actions"][0]["priority"] = raw_priority
    report = build_report(data)
    assert report.recommended_actions[0].priority == expected


def test_invalid_priority_raises():
    data = _valid_report_dict()
    data["recommended_actions"][0]["priority"] = "whenever"
    with pytest.raises(ReportValidationError):
        build_report(data)


# ---------------------------------------------------------------------------
# format_validation_error_for_llm
# ---------------------------------------------------------------------------

def test_format_validation_error_is_non_empty():
    data = _valid_report_dict()
    del data["likely_root_cause"]
    try:
        build_report(data)
    except ReportValidationError as e:
        msg = format_validation_error_for_llm(e)
        assert isinstance(msg, str)
        assert len(msg) > 20
        assert "likely_root_cause" in msg
