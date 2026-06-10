"""
generated_code_validator.py — post-generation code quality gate.

Called after RemediationPolicy validation and before any MCP write call.
Raises CodeValidationError listing all failures so the caller can pass
the error list to a repair LLM call.

Checks (v1):
  1. Every .py file passes ast.parse() (syntax check).
  2. scripts/ files must not contain hardcoded mock schema patterns.
  3. scripts/ files must read schema data from files (sys.argv or open()).
  4. scripts/ files that iterate over fields must access them as dicts.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.remediation import FixSpec

from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CodeValidationError(ValueError):
    """Raised when generated code fails the quality gate."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        detail = "\n".join(f"  - {e}" for e in errors)
        super().__init__(
            f"Generated code validation failed ({len(errors)} error(s)):\n{detail}"
        )


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Patterns that indicate the script has hardcoded schema data rather than
# reading it from files.
_HARDCODED_SCHEMA_PATTERNS: tuple[str, ...] = (
    "production_schema =",
    "Mocked production schema",
    "mocked production schema",
)

# At least one of these must be present in a validation script to show it
# reads input from files (CLI args or direct file open).
_FILE_READ_INDICATORS: tuple[str, ...] = (
    "sys.argv",
    "open(",
    "Path(",
    "pathlib",
)

# Signals that the script iterates over schema fields.
_FIELD_ITERATION_SIGNALS: tuple[str, ...] = (
    "for field in",
    "for f in",
)

# If the script iterates over fields, it should access them as dicts
# (BigQuery schema: {"name": "...", "type": "..."}).
_DICT_ACCESS_INDICATORS: tuple[str, ...] = (
    '["name"]',
    "['name']",
    '.get("name")',
    ".get('name')",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_fix_spec_code(fix_spec: "FixSpec") -> None:
    """
    Validate all generated Python files in a FixSpec.

    Runs all checks and accumulates errors before raising so the caller
    gets the full error list for the repair prompt.
    Raises CodeValidationError if any check fails.
    Returns normally if all checks pass.
    """
    errors: list[str] = []

    for fix_file in fix_spec.files:
        path: str = fix_file.path
        content: str = fix_file.content

        if not path.endswith(".py"):
            continue  # only check Python files

        _check_syntax(path, content, errors)

        if "scripts/" in path:
            _check_no_hardcoded_schema(path, content, errors)
            _check_reads_from_files(path, content, errors)
            _check_field_dict_access(path, content, errors)

    if errors:
        logger.warning("code_validation_failed", error_count=len(errors))
        raise CodeValidationError(errors)

    logger.info("code_validation_passed", file_count=len(fix_spec.files))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_syntax(path: str, content: str, errors: list[str]) -> None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        errors.append(f"{path}: Python syntax error at line {e.lineno}: {e.msg}")


def _check_no_hardcoded_schema(path: str, content: str, errors: list[str]) -> None:
    for pattern in _HARDCODED_SCHEMA_PATTERNS:
        if pattern in content:
            errors.append(
                f"{path}: contains hardcoded schema pattern {pattern!r}. "
                "Schema data must be read from files, not inlined as Python literals."
            )
            return  # one error per file to avoid noise


def _check_reads_from_files(path: str, content: str, errors: list[str]) -> None:
    if not any(ind in content for ind in _FILE_READ_INDICATORS):
        errors.append(
            f"{path}: validation script does not read schema from files. "
            "Accept both schema file paths via sys.argv[1] and sys.argv[2], "
            "or open() them directly."
        )


def _check_field_dict_access(path: str, content: str, errors: list[str]) -> None:
    if not any(sig in content for sig in _FIELD_ITERATION_SIGNALS):
        return  # no field iteration — check not applicable

    if not any(ind in content for ind in _DICT_ACCESS_INDICATORS):
        errors.append(
            f"{path}: script iterates over schema fields but does not access them as "
            "dict objects. BigQuery schema fields are dicts: "
            '{"name": "...", "type": "..."}. '
            "Extract names with: {f[\"name\"] for f in schema[\"fields\"]}"
        )
