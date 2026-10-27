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
    index = 0
    while index < len(pending):
        if pending[index] == 13:
            if index + 1 == len(pending):
                return None
            first_end = index + (2 if pending[index + 1] == 10 else 1)
        elif pending[index] == 10:
            first_end = index + 1
        else:
            index += 1
            continue

        if first_end == len(pending):
            return None
        if pending[first_end] == 13:
            if first_end + 1 == len(pending):
                return None
            end = first_end + (2 if pending[first_end + 1] == 10 else 1)
        elif pending[first_end] == 10:
            end = first_end + 1
        else:
            index = first_end
            continue

        event = bytes(pending[:end])
        del pending[:end]
        return event
    return None
