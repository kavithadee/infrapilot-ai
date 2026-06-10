import subprocess
import pytest

@pytest.fixture
def make_schema_file(tmp_path):
    def _make(name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p
    return _make

def test_matching_schemas_pass(make_schema_file):
    emitted = make_schema_file("emitted.json", '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}')
    bq = make_schema_file("bq.json", '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}')
    result = subprocess.run(["python3", "demo-infra/audit-service/scripts/validate_bq_schema.py", str(emitted), str(bq)])
    assert result.returncode == 0

def test_mismatched_schemas_fails(make_schema_file):
    emitted = make_schema_file("emitted.json", '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}')
    bq = make_schema_file("bq.json", '{"fields": []}')
    result = subprocess.run(["python3", "demo-infra/audit-service/scripts/validate_bq_schema.py", str(emitted), str(bq)])
    assert result.returncode == 1