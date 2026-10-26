"""Итог «Три задачи» без секретов и лишнего текста."""

from harness_server.services.plan_notify import planning_summary


def test_three_tasks() -> None:
    assert planning_summary(["Экспорт CSV", "Тесты экспорта", "Документация"]) == (
        "спецификация готова, задач: 3\n• Экспорт CSV\n• Тесты экспорта\n• Документация"
    )


def test_summary_redacts_before_shortening() -> None:
    secret = "opaque-long-secret-value-" * 3
    result = planning_summary([secret + " документация"], [secret])
    assert secret not in result
    assert "opaque" not in result and "[REDACTED]" in result
