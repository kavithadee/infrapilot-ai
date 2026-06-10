import json
import sys

def load_schema(file_path):
    with open(file_path) as f:
        return json.load(f)

def extract_field_names(schema):
    if isinstance(schema, dict) and "fields" in schema:
        return {field['name'] for field in schema['fields']}
    elif isinstance(schema, list):
        return {field['name'] for field in schema if 'name' in field}
    else:
        raise ValueError("Invalid schema format")

def main():
    emitted_schema_path = sys.argv[1]
    bq_schema_path = sys.argv[2]

    emitted_schema = load_schema(emitted_schema_path)
    bq_schema = load_schema(bq_schema_path)

    emitted_fields = extract_field_names(emitted_schema)
    bq_fields = extract_field_names(bq_schema)

    missing_fields = bq_fields - emitted_fields
    extra_fields = emitted_fields - bq_fields

    if missing_fields or extra_fields:
        print("Schema mismatch detected:")
        if missing_fields:
            print(f"Missing fields in emitted schema: {', '.join(missing_fields)}")
        if extra_fields:
            print(f"Extra fields in emitted schema: {', '.join(extra_fields)}")
        sys.exit(1)
    else:
        print("Schema compatible")
        sys.exit(0)

if __name__ == "__main__":
    main()
