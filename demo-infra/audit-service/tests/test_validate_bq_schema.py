import pathlib
import subprocess
import pytest

_SCRIPT = str(pathlib.Path(__file__).parent.parent / "scripts" / "validate_bq_schema.py")

@pytest.fixture
def make_schema_file(tmp_path):
    def _make(name, content):
        p = tmp_path / name
        p.write_text(content)
        return p
    return _make

def test_matching_schemas_pass(make_schema_file):
    emitted_content = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    bq_content = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    emitted = make_schema_file("emitted.json", emitted_content)
    bq = make_schema_file("bq.json", bq_content)
    result = subprocess.run(["python3", _SCRIPT, str(emitted), str(bq)])
    assert result.returncode == 0

def test_mismatched_schemas_fail(make_schema_file):
    emitted_content = '{"fields": [{"name": "user_agent", "type": "STRING", "mode": "NULLABLE"}]}'
    bq_content = '{"fields": []}'
    emitted = make_schema_file("emitted.json", emitted_content)
    bq = make_schema_file("bq.json", bq_content)
    result = subprocess.run(["python3", _SCRIPT, str(emitted), str(bq)])
    assert result.returncode == 1
