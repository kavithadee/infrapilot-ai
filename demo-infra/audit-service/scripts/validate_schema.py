import json
import sys

def load_schema(file_path):
    with open(file_path) as schema_file:
        return json.load(schema_file)

if __name__ == "__main__":
    schema_file_path = sys.argv[1]
    production_schema = {"fields": ["event_type", "timestamp", "user_id", "user_agent"]}  # Mocked production schema

    local_schema = load_schema(schema_file_path)

    production_fields = set(field for field in production_schema["fields"])
    local_fields = set(field for field in local_schema["fields"])

    if not local_fields.issubset(production_fields):
        missing_fields = local_fields - production_fields
        print(f"Schema Validation Failed: Missing fields in production schema: {missing_fields}")
        sys.exit(1)

    print("Schema Validation Passed")