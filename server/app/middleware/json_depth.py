"""Bound structural depth before the JSON decoder can exhaust its stack."""
from app.schemas.payload_limits import MAX_DEPTH


def excessive_depth(body):
    depth, quoted, escaped = 0, False, False
    for byte in body:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            # Allow the report envelope around the separately bounded payload.
            if depth > MAX_DEPTH + 4:
                return True
        elif byte in (93, 125):
            depth -= 1
    return False
