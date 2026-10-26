"""Compose-стек харнесса: каждая ENV из Settings передаётся контейнерам (bug-class mvp-06c).

Без этой проверки переменная, добавленная в Settings, молча не доходит до migrate/server/worker:
сервис стартует с пустым значением или с настройкой по умолчанию.
"""

from pathlib import Path
from typing import Any

import yaml
from harness_server.settings import Settings

COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
# Переменные, которые Settings читает, но стек не передаёт: пусто. Добавлять сюда только с причиной.
NOT_PASSED: frozenset[str] = frozenset()


def _load_compose() -> dict[str, Any]:
    data = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _common_block() -> dict[str, Any]:
    # YAML-якорь разворачивается PyYAML при загрузке: x-harness-common содержит полный блок.
    block = _load_compose()["x-harness-common"]
    assert isinstance(block, dict)
    return block


def _settings_env_names() -> set[str]:
    # pydantic-settings без alias читает переменную по имени поля (регистр не важен).
    return {name.upper() for name in Settings.model_fields}


def test_every_settings_field_is_passed_to_containers() -> None:
    passed = set(_common_block()["environment"])

    missing = _settings_env_names() - passed - NOT_PASSED

    assert not missing, f"ENV из Settings не переданы в docker-compose.yml: {sorted(missing)}"


def test_no_unknown_env_in_common_block() -> None:
    # Опечатка в имени ENV в стеке молча не даёт значения: лишние имена тоже ловим.
    passed = set(_common_block()["environment"])

    unknown = passed - _settings_env_names()

    assert not unknown, f"ENV в docker-compose.yml, которых нет в Settings: {sorted(unknown)}"


def test_common_block_builds_image_locally() -> None:
    common = _common_block()

    assert common["build"] == {"context": ".", "dockerfile": "Dockerfile"}
    assert common["image"] == "${HARNESS_IMAGE:-agents-flow:local}"


def test_services_inherit_build_from_common_block() -> None:
    services = _load_compose()["services"]

    # Слияние якоря <<: *harness-common даёт migrate и server общий образ.
    for name in ("migrate", "server"):
        assert services[name]["build"] == _common_block()["build"]
        assert services[name]["image"] == _common_block()["image"]
