"""Row shaping helpers used by the exporter."""


def expand_records(records):
    """Flatten records into sorted (key, text) pairs."""
    output = []
    for record in records:
        if isinstance(record, dict):
            for field_name in sorted(record):
                item = record[field_name]
                if item is None:
                    output.append((field_name, ""))
                else:
                    output.append((field_name, str(item)))
        else:
            output.append(("value", str(record)))
    output.sort()
    return output
