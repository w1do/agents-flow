"""Находки сканирования не раскрывают секреты ни в значениях, ни в repr."""

import pytest
from harness_server.security.redaction import SecretFinding, scan_diff


@pytest.mark.parametrize(
    "token",
    [
        "123456:" + "A" * 35,
        "glpat-" + "a" * 24,
        "ghp_" + "a" * 40,
        "github_pat_" + "a" * 24,
        "sk-ant-" + "a" * 24,
        "aft_" + "a" * 40,
        "Bearer " + "a" * 24,
        "Basic b2F1dGgyOmdscGF0LWFiY2RlZmdoaWprbG1ub3BxcnN0",
        "https://user:password@gitlab.com/repo",
    ],
)
def test_scan_reports_patterns_without_values(token: str) -> None:
    findings = scan_diff(f"diff --git a/file b/file\n+key={token}\n")
    assert findings == [SecretFinding(2, "token_pattern")]
    assert token not in repr(findings)


@pytest.mark.parametrize("value", ["custom-secret-value", "tiny", 'a"b$()'])
def test_scan_reports_exact_values_including_short_values(value: str) -> None:
    assert scan_diff(f"+key={value}", iter([value])) == [SecretFinding(1, "exact_value")]


def test_scan_clean_diff_and_empty_values() -> None:
    assert scan_diff("+создать спецификацию", [""]) == []


def test_scan_includes_deleted_lines() -> None:
    assert scan_diff("-secret=custom-value", ["custom-value"])


def test_scan_detects_multiline_exact_values() -> None:
    assert scan_diff("header\n+first\n+second", ["first\n+second"]) == [
        SecretFinding(2, "exact_value")
    ]
