import json
import sys

def load_schema(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def get_field_names(schema):
    return {field['name'] for field in schema['fields']}

def main():
    if len(sys.argv) != 3:
        print('Usage: validate_bq_schema.py <emitted_schema_path> <bq_schema_path>')
        sys.exit(1)

    emitted_schema_path = sys.argv[1]
    bq_schema_path = sys.argv[2]

    emitted_schema = load_schema(emitted_schema_path)
    bq_schema = load_schema(bq_schema_path)

    emitted_fields = get_field_names(emitted_schema)
    bq_fields = get_field_names(bq_schema)

    missing_in_bq = emitted_fields - bq_fields
    extra_in_bq = bq_fields - emitted_fields

    if missing_in_bq or extra_in_bq:
        print('Schema mismatch detected:')
        if missing_in_bq:
            print(f'Missing in BigQuery: {missing_in_bq}')
        if extra_in_bq:
            print(f'Extra in BigQuery: {extra_in_bq}')
        sys.exit(1)

    print('Schema compatible')
    sys.exit(0)

if __name__ == '__main__':
    main()
