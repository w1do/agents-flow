import json
from pathlib import Path


SCHEMA_PATH = Path(__file__).parents[2] / "docs/api-schemas/identity.json"


def _resolve_ref(document, ref):
    file_name, pointer = ref.split("#", 1)
    assert file_name == "identity.json"
    value = document
    for part in pointer.strip("/").split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _assert_matches(value, schema, document):
    if "$ref" in schema:
        schema = _resolve_ref(document, schema["$ref"])
    if "anyOf" in schema:
        assert any(_matches(value, option, document) for option in schema["anyOf"])
        return
    expected = schema.get("type")
    if expected == "object":
        assert isinstance(value, dict)
        assert set(value) == set(schema["properties"])
        assert set(schema["required"]) == set(value)
        for key, item in value.items():
            _assert_matches(item, schema["properties"][key], document)
    elif expected == "array":
        assert isinstance(value, list)
        for item in value:
            _assert_matches(item, schema["items"], document)
    elif expected == "string":
        assert isinstance(value, str)
    elif expected == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)


def _matches(value, schema, document):
    try:
        _assert_matches(value, schema, document)
        return True
    except AssertionError:
        return False


async def test_project_responses_match_identity_schema(client, admin_headers, project):
    document = json.loads(SCHEMA_PATH.read_text())
    schema = document["$defs"]["ProjectResponse"]
    refs = []

    def collect_refs(value):
        if isinstance(value, dict):
            refs.extend([value["$ref"]] if "$ref" in value else [])
            for child in value.values():
                collect_refs(child)
        elif isinstance(value, list):
            for child in value:
                collect_refs(child)

    collect_refs(document)
    assert refs
    for ref in refs:
        assert _resolve_ref(document, ref)

    listing = await client.get("/api/v1/projects", headers=admin_headers)
    card = await client.get(f"/api/v1/projects/{project.id}", headers=admin_headers)
    assert listing.status_code == card.status_code == 200
    for item in listing.json() + [card.json()]:
        _assert_matches(item, schema, document)
