import sys
import json

if len(sys.argv) != 3:
    print("Usage: validate_bq_schema.py <emitted_schema_path> <bq_table_schema_path>")
    sys.exit(1)

emitted_schema_path = sys.argv[1]
bq_schema_path = sys.argv[2]

with open(emitted_schema_path) as f:
    emitted_content = f.read()

with open(bq_schema_path) as f:
    bq_content = f.read()

try:
    emitted_schema = json.loads(emitted_content)
    bq_schema = json.loads(bq_content)
except json.JSONDecodeError as e:
    print(f"Error parsing schema files: {e}")
    sys.exit(1)

emitted_field_names = {field['name'] for field in emitted_schema['fields']}
bq_field_names = {field['name'] for field in bq_schema['fields']}

missing_in_bq = emitted_field_names - bq_field_names
extra_in_bq = bq_field_names - emitted_field_names

if missing_in_bq or extra_in_bq:
    if missing_in_bq:
        print(f"Fields missing in BigQuery schema: {', '.join(missing_in_bq)}")
    if extra_in_bq:
        print(f"Extra fields in BigQuery schema not in emitted event: {', '.join(extra_in_bq)}")
    sys.exit(1)
else:
    print("Schema compatible")
    sys.exit(0)
