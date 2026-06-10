import sys
import json

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        emitted_schema = json.load(f)
    with open(sys.argv[2]) as f:
        bq_schema = json.load(f)

    emitted_fields = {f['name'] for f in emitted_schema['fields']}
    bq_fields = {f['name'] for f in bq_schema['fields']}

    missing_in_bq = emitted_fields - bq_fields
    extra_in_bq = bq_fields - emitted_fields

    if missing_in_bq or extra_in_bq:
        print("Missing fields in BigQuery schema:", missing_in_bq)
        print("Extra fields in BigQuery schema:", extra_in_bq)
        sys.exit(1)
    else:
        print("Schema compatible")
        sys.exit(0)