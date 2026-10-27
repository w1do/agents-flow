from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_access_token, decode_token


def test_access_token_has_expected_signature_and_claims(app):
    subject = str(uuid4())
    before = int(datetime.now(timezone.utc).timestamp())
    token = create_access_token(subject)
    claims = decode_token(token)
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert claims["sub"] == subject
    assert before <= claims["iat"] <= datetime.now(timezone.utc).timestamp()
    assert claims["exp"] - claims["iat"] == 43200


@pytest.mark.parametrize("case", ["missing_exp", "missing_iat", "missing_sub", "wrong_key",
                                 "wrong_algorithm", "unknown_user", "invalid_sub"])
async def test_admin_rejects_invalid_claims(client, admin_user, case):
    now = datetime.now(timezone.utc)
    claims = {"sub": str(admin_user.id), "iat": now, "exp": now + timedelta(hours=12)}
    secret = get_settings().jwt_secret.get_secret_value()
    algorithm = "HS256"
    if case.startswith("missing_"):
        del claims[case.removeprefix("missing_")]
    elif case == "wrong_key":
        secret = "x" * 32
    elif case == "wrong_algorithm":
        algorithm = "HS512"
        secret = secret.ljust(64, "x")
    elif case == "unknown_user":
        claims["sub"] = str(uuid4())
    else:
        claims["sub"] = "invalid uuid"
    token = jwt.encode(claims, secret, algorithm=algorithm)
    response = await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize("path,body", [
    ("/auth/login", {"email": "admin@example.test", "password": {"secret": "hidden-password"}}),
    ("/auth/login", {"password": "hidden-password"}),
    ("/harness/init", {"init_code": "hidden-init-code", "agent_name": "Agent"}),
    ("/harness/init", {"init_code": {"secret": "hidden-init-code"}, "project_id": str(uuid4()),
                       "agent_name": "Agent"}),
])
async def test_validation_errors_do_not_echo_secrets(client, path, body, caplog):
    response = await client.post(f"/api/v1{path}", json=body)
    assert response.status_code == 422
    assert "hidden-password" not in response.text + caplog.text
    assert "hidden-init-code" not in response.text + caplog.text
    assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
