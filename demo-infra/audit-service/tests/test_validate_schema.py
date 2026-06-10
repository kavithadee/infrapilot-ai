import subprocess
import pytest

VALID_SCHEMA = "{"fields": ["event_type", "timestamp", "user_id"]}"
INVALID_SCHEMA = "{"fields": ["event_type", "timestamp", "user_id", "location"]}"

@pytest.fixture
def write_schema_file(tmp_path, content):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(content)
    return schema_path


def test_valid_schema_passes(write_schema_file):
    schema_path = write_schema_file(VALID_SCHEMA)
    result = subprocess.run([
        "python3",
        "demo-infra/audit-service/scripts/validate_schema.py",
        str(schema_path)
    ])
    assert result.returncode == 0


def test_invalid_schema_fails(write_schema_file):
    schema_path = write_schema_file(INVALID_SCHEMA)
    result = subprocess.run([
        "python3",
        "demo-infra/audit-service/scripts/validate_schema.py",
        str(schema_path)
    ])
    assert result.returncode != 0
