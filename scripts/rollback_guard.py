"""Check application/schema compatibility without changing containers, data or grants."""

import argparse
import json


def compatible(schema, image_digest, release):
    return release.get("image_digest") == image_digest and schema in release.get(
        "supported_schema_heads", []
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schema", required=True)
    p.add_argument("--image-digest", required=True)
    p.add_argument("--release-record", required=True)
    args = p.parse_args()
    with open(args.release_record, encoding="utf-8") as stream:
        release = json.load(stream)
    if not compatible(args.schema, args.image_digest, release):
        raise SystemExit(
            "BLOCKED: no recorded image/schema compatibility; use roll-forward or tested restore"
        )
    print("Application rollback compatibility recorded. No runtime/data change performed.")
