SERVER_EVENT_TYPES = frozenset({
    "publication-result", "claimed", "created", "status", "decision",
    "lease-claimed", "lease-expired", "lease-extended", "lease-renewed",
    "stalled", "merged", "paused", "trash", "error", "plan_decision",
    "result_decision", "lease_expired", "status_changed", "status-changed",
    "status-updated", "verification_missing",
})
SERVER_EVENT_PREFIXES = ("status-", "status_", "lease-", "lease_", "mcp_")


def is_reserved_event(event_type):
    return event_type in SERVER_EVENT_TYPES or event_type.startswith(SERVER_EVENT_PREFIXES)
