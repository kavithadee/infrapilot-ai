import sys
import json

def load_schema(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def validate_schemas(emitted_schema_path, bq_schema_path):
    emitted_schema = load_schema(emitted_schema_path)
    bq_schema = load_schema(bq_schema_path)

    emitted_fields = {f['name'] for f in emitted_schema['fields']}
    bq_fields = {f['name'] for f in bq_schema['fields']}

    missing_in_bq = emitted_fields - bq_fields
    extra_in_bq = bq_fields - emitted_fields

    if missing_in_bq or extra_in_bq:
        if missing_in_bq:
            print(f'Missing in BigQuery schema: {missing_in_bq}')
        if extra_in_bq:
            print(f'Extra in BigQuery schema: {extra_in_bq}')
        sys.exit(1)

    print('Schema compatible')
    sys.exit(0)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: python3 validate_bq_schema.py <emitted_schema_path> <bq_schema_path>')
        sys.exit(1)
    validate_schemas(sys.argv[1], sys.argv[2])
