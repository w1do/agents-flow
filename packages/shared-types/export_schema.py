"""Export project schemas from the canonical Pydantic models without server changes."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "src"))

from harness_shared.projects import (
    ProjectInput,
    ProjectRead,
    ProjectUpdate,
)
from pydantic.json_schema import models_json_schema

_, schema = models_json_schema(
    [(model, "validation") for model in (ProjectInput, ProjectUpdate, ProjectRead)]
)
print(json.dumps(schema, ensure_ascii=False))
