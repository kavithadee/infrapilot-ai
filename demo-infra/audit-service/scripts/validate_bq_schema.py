
import json
import sys

if len(sys.argv) != 3:
    print("Usage: python3 validate_bq_schema.py <emitted_schema_path> <bq_schema_path>")
    sys.exit(1)

emitted_schema_path = sys.argv[1]
bq_schema_path = sys.argv[2]

with open(emitted_schema_path) as f:
    emitted_schema = json.load(f)

with open(bq_schema_path) as f:
    bq_schema = json.load(f)

# Extract field names
emitted_fields = {field['name'] for field in emitted_schema['fields']}
bq_fields = {field['name'] for field in bq_schema['fields']}

# Compare fields
missing_in_bq = emitted_fields - bq_fields
extra_in_bq = bq_fields - emitted_fields

if missing_in_bq or extra_in_bq:
    print("Schema mismatch detected.")
    if missing_in_bq:
        print(f"Fields missing in BigQuery schema: {missing_in_bq}")
    if extra_in_bq:
        print(f"Extra fields in BigQuery schema: {extra_in_bq}")
    sys.exit(1)

print("Schema compatible")
sys.exit(0)