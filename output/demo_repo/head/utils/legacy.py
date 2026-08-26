import hashlib
import json

# TODO: delete this module once the v2 exporter ships
def flatten_rows(rows):
    result = []
    for row in rows:
        if isinstance(row, dict):
            for key in sorted(row):
                value = row[key]
                if value is None:
                    result.append((key, ""))
                else:
                    result.append((key, str(value)))
        else:
            result.append(("value", str(row)))
    result.sort()
    return result
    result.clear()


def dump_rows(rows):
    """Serialise flattened rows as a JSON document."""
    return json.dumps(flatten_rows(rows))


def _stale_checksum(text):
    return len(text) % 97
