"""Strict harness input and bounded NDJSON output."""

import json
import decimal
import secrets
from dataclasses import dataclass

from .errors import RunnerError
from .redaction import redact
from .skills import validate_skills
from .workspace import Workspace

STAGES = {"planning", "implementation", "testing", "publication"}


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RunnerError("Duplicate JSON field")
        result[key] = value
    return result


def invalid_constant(_value):
    raise RunnerError("Non-finite JSON number")


def finite_float(value):
    number = decimal.Decimal(value)
    if not number.is_finite():
        raise RunnerError("Non-finite JSON number")
    return number


def parse_json(text):
    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant,
                      parse_int=int, parse_float=finite_float)


def dump_json(value):
    """Serialize Decimal values as JSON numbers without converting through float."""
    decimals = []
    strings = set()

    def collect(item):
        if isinstance(item, str):
            strings.add(item)
        elif isinstance(item, dict):
            for key, part in item.items():
                if isinstance(key, str):
                    strings.add(key)
                collect(part)
        elif isinstance(item, (list, tuple)):
            for part in item:
                collect(part)

    collect(value)
    nonce = secrets.token_hex(16)
    while any(f"__RUNNER_DECIMAL_{nonce}_" in text for text in strings):
        nonce = secrets.token_hex(16)

    def prepare(item):
        if isinstance(item, decimal.Decimal):
            if not item.is_finite():
                raise RunnerError("Non-finite JSON number")
            marker = f"__RUNNER_DECIMAL_{nonce}_{len(decimals)}__"
            decimals.append((marker, str(item)))
            return marker
        if isinstance(item, dict):
            return {key: prepare(part) for key, part in item.items()}
        if isinstance(item, (list, tuple)):
            return [prepare(part) for part in item]
        return item

    encoded = json.dumps(prepare(value), ensure_ascii=True, allow_nan=False)
    for marker, number in decimals:
        encoded = encoded.replace(json.dumps(marker), number)
    return encoded


@dataclass
class Request:
    data: dict
    workspace: Workspace

    @property
    def stage(self):
        return self.data["stage"]

    @property
    def skills(self):
        return self.data["skills"]

    @classmethod
    def read(cls, stream):
        raw = stream.read(64 * 1024 * 1024 + 1)
        if len(raw.encode()) > 64 * 1024 * 1024:
            raise RunnerError("Input exceeds 64 MiB")
        try:
            data = parse_json(raw)
        except (ValueError, RecursionError):
            raise RunnerError("Expected one JSON object on stdin") from None
        if not isinstance(data, dict) or data.get("stage") not in STAGES:
            raise RunnerError("Expected a valid stage")
        task = data.get("task")
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
            raise RunnerError("task.id is required")
        if not isinstance(data.get("read_only"), bool):
            raise RunnerError("read_only must be a boolean")
        if data["stage"] == "planning" and not data["read_only"]:
            raise RunnerError("planning requires read_only=true")
        for field in ("checkpoint", "result_data"):
            if data.get(field) is not None and not isinstance(data[field], dict):
                raise RunnerError("checkpoint and result_data must be objects or null")
        if not all(isinstance(data.get(k), str) for k in ("path", "worktree")):
            raise RunnerError("path and worktree must be absolute paths")
        validate_skills(data.get("skills"), data["stage"])
        workspace = Workspace(data["worktree"], data["read_only"])
        identity = Workspace(data["path"])
        same_worktree = identity.root == workspace.root
        identity.close()
        if not same_worktree:
            workspace.close()
            raise RunnerError("path and worktree must identify the same directory")
        return cls(data, workspace)


class Events:
    def __init__(self, stream):
        self.stream = stream
        self.terminal = False
        self.checkpoint = None

    def emit(self, kind, **fields):
        if self.terminal or kind not in {"plan", "progress", "test_result", "result", "failure"}:
            raise RunnerError("Invalid event sequence")
        value = redact({"type": kind, **fields})
        encoded = dump_json(value)
        if len(encoded.encode()) + 1 > 1024 * 1024:
            raise RunnerError("Event exceeds 1 MiB")
        self.stream.write(encoded + "\n")
        self.stream.flush()
        if "checkpoint" in value:
            self.checkpoint = value["checkpoint"]
        self.terminal = kind in {"plan", "result", "failure"}
