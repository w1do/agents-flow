"""SSE framing and event-level payload sanitization."""


def sanitize_sse_event(event, sanitize_json):
    lines = event.splitlines(keepends=True)
    data_lines = []
    payloads = []
    for index, line in enumerate(lines):
        content = line.rstrip(b"\r\n")
        if not content.startswith(b"data:"):
            continue
        payload = content[5:]
        if payload.startswith(b" "):
            payload = payload[1:]
        data_lines.append(index)
        payloads.append(payload)
    if not data_lines:
        return event

    original = b"\n".join(payloads)
    cleaned = sanitize_json(original)
    if cleaned == original:
        return event

    first = data_lines[0]
    result = []
    for index, line in enumerate(lines):
        if index == first:
            content = line.rstrip(b"\r\n")
            ending = line[len(content):]
            result.append(b"data: " + cleaned + ending)
        elif index not in data_lines:
            result.append(line)
    return b"".join(result)


def next_sse_event(pending):
    separators = (b"\r\n\r\n", b"\n\n")
    matches = [(pending.find(separator), separator) for separator in separators]
    matches = [(index, separator) for index, separator in matches if index >= 0]
    if not matches:
        return None
    index, separator = min(matches, key=lambda match: match[0])
    end = index + len(separator)
    event = bytes(pending[:end])
    del pending[:end]
    return event
