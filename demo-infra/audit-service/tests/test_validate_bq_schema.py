import subprocess
import pytest

@pytest.fixture

def make_schema_file(tmp_path):
    def _make(name: str, content: str) -> str:
        p = tmp_path / name
        p.write_text(content)
        return str(p)
    return _make

def test_matching_schemas_pass(make_schema_file):
    emitted_schema = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    bq_schema = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    emitted_file = make_schema_file('emitted.json', emitted_schema)
    bq_file = make_schema_file('bq.json', bq_schema)

    result = subprocess.run(['python3', 'scripts/validate_bq_schema.py', emitted_file, bq_file])
    assert result.returncode == 0


def test_mismatched_schemas_fail(make_schema_file):
    emitted_schema = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    bq_schema = '{"fields": []}'
    emitted_file = make_schema_file('emitted.json', emitted_schema)
    bq_file = make_schema_file('bq.json', bq_schema)

    result = subprocess.run(['python3', 'scripts/validate_bq_schema.py', emitted_file, bq_file])
    assert result.returncode == 1
