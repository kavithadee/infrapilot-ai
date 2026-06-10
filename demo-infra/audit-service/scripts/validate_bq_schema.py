
import json
import sys


def load_schema(filepath):
    with open(filepath) as f:
        return json.load(f)


def extract_field_names(schema):
    if 'fields' in schema:
        return {field['name'] for field in schema['fields']}
    else:
        return set(schema)


def main(emitted_schema_path, bq_schema_path):
    emitted_schema = load_schema(emitted_schema_path)
    bq_schema = load_schema(bq_schema_path)

    emitted_fields = extract_field_names(emitted_schema)
    bq_fields = extract_field_names(bq_schema)

    missing_in_bq = emitted_fields - bq_fields
    extra_in_bq = bq_fields - emitted_fields

    if missing_in_bq or extra_in_bq:
        if missing_in_bq:
            print(f"Missing in BigQuery: {missing_in_bq}")
        if extra_in_bq:
            print(f"Extra in BigQuery: {extra_in_bq}")
        sys.exit(1)
    else:
        print("Schema compatible")
        sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python validate_bq_schema.py <emitted_schema> <bq_schema>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
