# /// script
# requires-python = ">=3.10"
# dependencies = ["novita_sandbox==2.1.1"]
# ///
"""Спайк mvp-01: проверка Novita Agent Sandbox и Claude Code внутри песочницы.

Назначение: подтвердить на живом API поведение, от которого зависит `mvp-06-sandbox-runtime`
(адаптер `SandboxProvider`): exec с кодом возврата и фоновым процессом, запись и чтение файлов,
пауза и возобновление с сохранением файла и процесса, продление таймаута, поведение после
истечения таймаута, установка pinned Claude Code и формат `stream-json` с usage.
Результаты переносятся в `docs/novita.md`. Решение D-16, риск A1 ТЗ.

Запуск (из корня репозитория):

    NOVITA_API_KEY=... uv run tools/spikes/novita_check.py
    NOVITA_API_KEY=... uv run tools/spikes/novita_check.py --only expire
    python3 tools/spikes/novita_check.py --help          # без ключа и без SDK
    python3 tools/spikes/novita_check.py --self-test     # офлайн, без ключа и без SDK

SDK импортируется лениво, уже после разбора аргументов и проверки ключа. Поэтому `--help`,
`--self-test` и сообщение об отсутствии ключа работают без установленного `novita_sandbox`.

ENV хоста:
    NOVITA_API_KEY            обязательна. Ключ читает и SDK; скрипт его никогда не печатает.
    NOVITA_DOMAIN             необязательна; домен SDK, по умолчанию us-phx-1.sandbox.novita.ai.
    CLAUDE_CODE_OAUTH_TOKEN   необязательна; токен подписки для шагов Claude Code.
                              Передаётся только в env конкретной команды песочницы, в файлы не пишется.
    HARNESS_PUBLIC_URL        необязательна; URL для проверки HTTPS из песочницы (шаг 2.3).
                              В вывод и отчёт попадает только scheme://host[:port].

Порядок: основная песочница (exec, пауза, продление, claude, HTTPS), затем её kill, и только потом
короткая песочница для истечения таймаута. Квота vCPU команды общая, поэтому две песочницы одновременно
могут не создаться.

Каждый шаг печатает одну строку-итог. Сбой шага печатается как `<шаг>: FAIL <причина>`, и скрипт
идёт дальше. Все созданные скриптом песочницы помечаются metadata `purpose=mvp-01-spike` и удаляются
в `finally` (в том числе при SIGTERM). Песочницы с той же metadata, которых не создавал этот запуск,
не убиваются: они печатаются как `cleanup: WARN orphan=...`. Код возврата 1, если был хотя бы один
FAIL; 2, если нет ключа.
"""

from __future__ import annotations

# Спайк намеренно ловит любой сбой SDK и сети на уровне шага: шаг печатает FAIL, и скрипт
# идёт дальше. Поэтому широкий except здесь правильный, а не ошибка.
# ruff: noqa: BLE001
import argparse
import json
import os
import re
import shlex
import signal
import sys
import time
from dataclasses import dataclass, field
from types import FrameType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    # SDK 2.1.1 не содержит py.typed. Игнорируется только ошибка импорта, и только для проверки
    # типов: во время работы импорт SDK идёт лениво через sdk().
    from novita_sandbox.core import Sandbox  # type: ignore[import-untyped]

ENV_API_KEY = "NOVITA_API_KEY"
ENV_CLAUDE_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ENV_PUBLIC_URL = "HARNESS_PUBLIC_URL"

DEFAULT_CLAUDE_VERSION = "2.1.292"
DEFAULT_URL = "https://example.com"
METADATA = {"purpose": "mvp-01-spike"}
ONLY_CHOICES = ("expire", "claude")

# Основная песочница живёт дольше шагов: пауза, npm install (до нескольких минут) и claude -p.
# Продление ставит 1200 с, а не 600 с из примера в задаче, иначе установка claude может не уложиться.
MAIN_TIMEOUT_S = 900
EXTEND_TO_S = 1200
PROBE_PATH = "/tmp/spike-probe.txt"
PROBE_TEXT = "novita-spike-probe"
PID_PATH = "/tmp/spike.pid"
CLAUDE_OUT = "/tmp/claude.jsonl"
CLAUDE_ERR = "/tmp/claude.err"
CLAUDE_EXIT = "/tmp/claude.exit"
CLAUDE_PROMPT = "Reply with the single word: pong"
CLAUDE_WAIT_S = 180
INPUT_USAGE_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
KEEP_EVENT_KEYS = (
    "type",
    "subtype",
    "model",
    "is_error",
    "num_turns",
    "total_cost_usd",
    "usage",
)
KEEP_MESSAGE_KEYS = ("id", "model", "usage", "stop_reason")
# Так claude сообщает, что не знает флаг или аргумент. Если он встречается рядом с max-turns,
# значит флаг не принят этой версией CLI.
UNKNOWN_ARG_MARKERS = ("unknown option", "unknown argument", "unrecognized")
# Шаблоны секретов, которые маскируются даже тогда, когда точного значения нет в ENV: токен
# подписки Claude (префикс sk-ant-) и ключи вида sk_... Точные значения маскируются отдельно.
SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk_[A-Za-z0-9]{20,}"),
)
NOT_FOUND_MARKERS = ("SandboxNotFoundException", "NotFoundException")


def sdk() -> Any:
    """Ленивый импорт SDK. Вызывается только тогда, когда реально нужен вызов песочницы, то есть
    после разбора аргументов и проверки ключа. Так `--help` и `--self-test` работают без SDK."""
    # SDK без py.typed: ошибка импорта для mypy игнорируется здесь, вызовы типизируются как Any.
    from novita_sandbox import core  # type: ignore[import-untyped]

    return core


@dataclass
class Run:
    """Результат команды переднего плана. Ненулевой код возврата здесь не исключение."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass
class Ctx:
    """Состояние запуска: шаблон, маскируемые секреты, созданные id и накопленные строки отчёта."""

    template: str | None
    secrets: tuple[str, ...]
    created: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    failures: int = 0


def say(ctx: Ctx, line: str) -> None:
    """Печатает строку-итог и сохраняет её для --report."""
    print(line, flush=True)
    ctx.lines.append(line)


def fail(ctx: Ctx, label: str, reason: str) -> None:
    """Печатает `<шаг>: FAIL <причина>` и считает сбой."""
    ctx.failures += 1
    say(ctx, f"{label}: FAIL {reason}")


def redact(text: str, secrets: tuple[str, ...]) -> str:
    """Маскирует точные значения секретов и шаблоны (sk-ant-, sk_...) на *** и схлопывает текст
    в одну строку. Маскировка идёт ДО любой обрезки: иначе секрет, попавший на границу среза,
    вывелся бы частично. Пустые значения пропускаются, иначе replace вставит *** между всеми символами."""
    flat = " ".join(text.split())
    for secret in secrets:
        if secret:
            flat = flat.replace(secret, "***")
    for pattern in SECRET_PATTERNS:
        flat = pattern.sub("***", flat)
    return flat


def short_error(exc: BaseException, secrets: tuple[str, ...]) -> str:
    """Однострочное описание исключения с маскировкой."""
    return f"{type(exc).__name__}: {redact(str(exc), secrets)[:200]}"


def safe_url(url: str) -> str:
    """Только scheme://host[:port]. Без userinfo, пути и query: в них могут быть токены.
    Для curl используется полный URL, а в вывод и отчёт попадает безопасная форма."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "invalid-url"
    return f"{parts.scheme or '?'}://{parts.hostname or '?'}{port}"


def create_reason(exc: BaseException, secrets: tuple[str, ...]) -> str:
    """Короткая причина сбоя create. 429 от Novita в этом спайке означает лимит vCPU команды,
    поэтому печатаем только её. Полный текст SDK уходит в --report, а в консоль не выводится."""
    text = str(exc)
    if type(exc).__name__ == "RateLimitException" or "429" in text:
        return "vCPU limit (429)" if "vcpu" in text.lower() else "rate limit (429)"
    return short_error(exc, secrets)


def is_not_found(exc: BaseException) -> bool:
    """Песочница не найдена: по имени класса SDK или по тексту сообщения."""
    return type(exc).__name__ in NOT_FOUND_MARKERS or "not found" in str(exc).lower()


def run_cmd(
    sbx: Sandbox, cmd: str, timeout: float = 60, envs: dict[str, str] | None = None
) -> Run:
    """Команда переднего плана. SDK бросает CommandExitException при ненулевом коде, здесь он
    превращается в обычный результат, чтобы шаг сравнивал код возврата явно."""
    core = sdk()
    try:
        res = sbx.commands.run(cmd, timeout=timeout, envs=envs)
    except core.CommandExitException as exc:
        return Run(int(exc.exit_code), str(exc.stdout), str(exc.stderr))
    return Run(int(res.exit_code), str(res.stdout), str(res.stderr))


def create_sandbox(ctx: Ctx, timeout: int) -> Sandbox:
    """Создаёт песочницу с меткой purpose и сразу запоминает id, чтобы cleanup её нашёл даже
    если следующий шаг упадёт."""
    sbx = sdk().Sandbox.create(
        template=ctx.template, timeout=timeout, metadata=METADATA
    )
    ctx.created.append(str(sbx.sandbox_id))
    return sbx


def create_or_fail(ctx: Ctx, label: str, timeout: int) -> Sandbox | None:
    """create_sandbox, но сбой печатается как `<label>: FAIL <причина>`, а не роняет скрипт."""
    try:
        return create_sandbox(ctx, timeout)
    except Exception as exc:
        ctx.details.setdefault("create_errors", []).append(
            short_error(exc, ctx.secrets)
        )
        fail(ctx, label, create_reason(exc, ctx.secrets))
        return None


def list_sandboxes(states: tuple[str, ...] | None) -> dict[str, str]:
    """Песочницы с нашей metadata из Sandbox.list: sandbox_id -> состояние. Фильтр по metadata
    исключает чужие песочницы. Пагинация по образцу SDK."""
    core = sdk()
    state_filter = None if states is None else [core.SandboxState(s) for s in states]
    query = core.SandboxQuery(metadata=dict(METADATA), state=state_filter)
    paginator = core.Sandbox.list(query=query)
    found: dict[str, str] = {}
    while paginator.has_next:
        for item in paginator.next_items():
            found[str(item.sandbox_id)] = str(getattr(item.state, "value", item.state))
    return found


def process_alive(sbx: Sandbox) -> bool:
    """Жив ли фоновый процесс из PID-файла. Проверка через `kill -0`, а не через ps/pgrep,
    потому что в шаблоне их может не быть."""
    run = run_cmd(
        sbx, f'kill -0 "$(cat {PID_PATH})" 2>/dev/null && echo ALIVE || echo DEAD'
    )
    return "ALIVE" in run.stdout


def safe_read(sbx: Sandbox, path: str) -> str | None:
    """Чтение файла, при ошибке None: для проверки «файл потерян» ошибка тоже результат."""
    try:
        return str(sbx.files.read(path))
    except Exception:
        return None


def stderr_mark(text: str) -> str:
    return "OK" if "err" in text else "MISSING"


def step_exec(ctx: Ctx, sbx: Sandbox) -> None:
    """1.2: echo, код возврата и stdout."""
    try:
        run = run_cmd(sbx, "echo hello")
    except Exception as exc:
        fail(ctx, "exec", short_error(exc, ctx.secrets))
        return
    if run.exit_code == 0 and run.stdout.strip() == "hello":
        say(ctx, "exec: OK")
    else:
        fail(
            ctx, "exec", f"exit_code={run.exit_code} stdout={run.stdout.strip()[:80]!r}"
        )


def step_exec_nonzero(ctx: Ctx, sbx: Sandbox) -> None:
    """1.2: фиксируем, как SDK ведёт себя при ненулевом коде. Исключение здесь не сбой шага,
    это и есть наблюдаемое поведение, поэтому счётчик не растёт."""
    core = sdk()
    try:
        run = sbx.commands.run("sh -c 'echo err >&2; exit 3'", timeout=60)
    except core.CommandExitException as exc:
        say(
            ctx,
            "exec nonzero: raises CommandExitException "
            f"exit_code={exc.exit_code} stderr={stderr_mark(str(exc.stderr))}",
        )
        return
    except Exception as exc:
        say(ctx, f"exec nonzero: raises {short_error(exc, ctx.secrets)}")
        return
    say(
        ctx,
        f"exec nonzero: exit_code={run.exit_code} stderr={stderr_mark(str(run.stderr))}",
    )


def step_pause_resume(ctx: Ctx, sbx: Sandbox) -> Sandbox:
    """1.3: файл и фоновый процесс переживают pause -> connect. Возвращает handle, которым
    пользоваться дальше. При ошибке pause возвращает исходный handle."""
    label = "pause/resume"
    try:
        sbx.files.write(PROBE_PATH, PROBE_TEXT)
        # Обычный run, а не background: нужен pid-файл. Вывод перенаправлен, иначе run ждёт
        # закрытия stdout/stderr дочернего процесса и зависает.
        start = run_cmd(sbx, f"nohup sleep 600 >/dev/null 2>&1 & echo $! > {PID_PATH}")
        if start.exit_code != 0:
            raise RuntimeError(f"start background exit_code={start.exit_code}")
        alive_before = process_alive(sbx)
        sandbox_id = str(sbx.sandbox_id)
        t0 = time.monotonic()
        sbx.pause()
        pause_s = time.monotonic() - t0
        t1 = time.monotonic()
        resumed = sdk().Sandbox.connect(sandbox_id, timeout=MAIN_TIMEOUT_S)
        resume_s = time.monotonic() - t1
    except Exception as exc:
        fail(ctx, label, short_error(exc, ctx.secrets))
        return sbx

    content = safe_read(resumed, PROBE_PATH)
    files_ok = content == PROBE_TEXT
    try:
        alive_after = process_alive(resumed)
    except Exception:
        alive_after = False
    note = "" if alive_before else " note=process_not_running_before_pause"
    say(
        ctx,
        f"{label}: files={'OK' if files_ok else 'LOST'} "
        f"process={'OK' if alive_after else 'LOST'} "
        f"pause_s={pause_s:.1f} resume_s={resume_s:.1f}{note}",
    )
    ctx.details["pause"] = {
        "alive_before": alive_before,
        "files_read_back": content is not None,
        "files_match": files_ok,
        "process_alive_after": alive_after,
        "pause_s": round(pause_s, 2),
        "resume_s": round(resume_s, 2),
    }
    return resumed


def step_timeout_extend(ctx: Ctx, sbx: Sandbox) -> None:
    """1.4: продление основной песочницы, сравнение end_at до и после."""
    label = "timeout extend"
    try:
        before = sbx.get_info().end_at
        sbx.set_timeout(EXTEND_TO_S)
        after = sbx.get_info().end_at
    except Exception as exc:
        fail(ctx, label, short_error(exc, ctx.secrets))
        return
    verdict = "EXTENDED" if after > before else "NOT_EXTENDED"
    say(
        ctx,
        f"{label}: OK {verdict} end_at={before} -> {after} requested={EXTEND_TO_S}s",
    )
    ctx.details["extend"] = {"end_at_before": str(before), "end_at_after": str(after)}


def kill_main(ctx: Ctx, sbx: Sandbox) -> None:
    """Убивает основную песочницу до шага истечения таймаута. Квота vCPU команды общая, и короткая
    песочница иначе не создастся. Повторный kill в cleanup безвреден."""
    try:
        killed = sdk().Sandbox.kill(str(sbx.sandbox_id))
    except Exception as exc:
        fail(ctx, "main sandbox", f"kill {short_error(exc, ctx.secrets)}")
        return
    say(ctx, f"main sandbox: kill={'OK' if killed else 'NOT_FOUND'}")


def step_timeout_expire(ctx: Ctx, short_timeout: int) -> None:
    """1.4: короткая отдельная песочница. Ждём истечения и смотрим, жива ли она, по exec и по
    Sandbox.list. `killed` ставится только если connect вернул «не найдено» и при этом list
    либо ответил, что песочницы нет (absent), либо упал (list=error, это отмечается явно)."""
    label = "timeout expire"
    short = create_or_fail(ctx, label, short_timeout)
    if short is None:
        return
    short_id = str(short.sandbox_id)
    wait_s = short_timeout + 15
    time.sleep(wait_s)

    listed: str | None = None
    list_error = False
    list_detail = ""
    try:
        listed = list_sandboxes(None).get(short_id)
    except Exception as exc:
        list_error = True
        list_detail = short_error(exc, ctx.secrets)
    if list_error:
        list_text = f"error({list_detail})"
    else:
        list_text = listed if listed is not None else "absent"

    exec_ok = False
    try:
        run = run_cmd(short, "echo alive", timeout=20)
        exec_ok = run.exit_code == 0 and run.stdout.strip() == "alive"
        exec_text = "OK" if exec_ok else f"exit_code={run.exit_code}"
    except Exception as exc:
        exec_text = short_error(exc, ctx.secrets)

    connect_text = ""
    connect_not_found = False
    if not exec_ok:
        try:
            sdk().Sandbox.connect(short_id)
            connect_text = " connect=OK"
        except Exception as exc:
            connect_not_found = is_not_found(exc)
            connect_text = f" connect={short_error(exc, ctx.secrets)}"

    if exec_ok:
        behavior = "alive"
    elif listed == "paused":
        behavior = "paused"
    elif connect_not_found and not list_error and listed is None:
        behavior = "killed"
    elif connect_not_found and list_error:
        behavior = "killed list=error"
    else:
        behavior = "unknown"
    say(
        ctx,
        f"{label}: {behavior} exec={exec_text} list_state={list_text} "
        f"short_timeout={short_timeout}s waited={wait_s}s{connect_text}",
    )
    ctx.details["expire"] = {
        "behavior": behavior,
        "exec_ok": exec_ok,
        "list_state": list_text,
        "connect_not_found": connect_not_found,
    }


def step_claude_install(ctx: Ctx, sbx: Sandbox, claude_version: str) -> bool:
    """2.1: node, pinned claude, флаги из --help. Возвращает True, если claude установлен."""
    label = "claude"
    node = run_cmd(sbx, "node -v")
    npm = run_cmd(sbx, "npm -v")
    if node.exit_code != 0 or npm.exit_code != 0:
        fail(ctx, label, "no node in template")
        return False
    install = run_cmd(
        sbx, f"npm install -g @anthropic-ai/claude-code@{claude_version}", timeout=600
    )
    if install.exit_code != 0:
        fail(ctx, label, f"npm install exit_code={install.exit_code}")
        return False
    version_run = run_cmd(sbx, "claude --version")
    help_run = run_cmd(sbx, "claude --help")
    if version_run.exit_code != 0:
        fail(ctx, label, f"claude --version exit_code={version_run.exit_code}")
        return False
    version_words = version_run.stdout.split()
    version = version_words[0] if version_words else "unknown"
    help_text = help_run.stdout + help_run.stderr

    def flag(name: str) -> str:
        return "yes" if name in help_text else "no"

    # --max-turns в 2.1.292 не виден в --help, хотя описан в CLI reference. Поэтому окончательное
    # подтверждение даёт шаг 2.2 (max_turns_accepted), а здесь значение помечается как скрытое.
    max_turns = "yes" if "--max-turns" in help_text else "no(hidden in --help)"
    say(
        ctx,
        f"{label}: version={version} max-turns={max_turns} "
        f"bare={flag('--bare')} output-format={flag('--output-format')}",
    )
    ctx.details["claude"] = {
        "version": version,
        "max_turns_in_help": "--max-turns" in help_text,
        "bare": "--bare" in help_text,
        "output_format": "--output-format" in help_text,
    }
    return True


def _int(value: object) -> int:
    """Токены из JSON; нечисловое значение считаем нулём, а не падаем."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def sanitize_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Оставляет только поля usage и метаданные. Текст ответа, cwd и инструменты не сохраняем,
    потому что в них может попасть вывод команд или секреты."""
    out: dict[str, Any] = {k: ev[k] for k in KEEP_EVENT_KEYS if k in ev}
    msg = ev.get("message")
    if isinstance(msg, dict):
        out["message"] = {k: msg[k] for k in KEEP_MESSAGE_KEYS if k in msg}
    return out


def analyze_stream(lines: list[str]) -> dict[str, Any]:
    """Сверка usage по stream-json. Assistant-события одного message.id повторяются, и
    output_tokens в них может быть плейсхолдером. Поэтому берём последнее вхождение каждого
    id и сравниваем входные токены с usage из события result."""
    events = 0
    parse_errors = 0
    last_usage: dict[str, dict[str, Any]] = {}
    result_usage: dict[str, Any] | None = None
    result_subtype: str | None = None
    samples: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            ev: Any = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if not isinstance(ev, dict):
            parse_errors += 1
            continue
        events += 1
        etype = str(ev.get("type"))
        if etype not in seen_types and len(samples) < 5:
            seen_types.add(etype)
            samples.append(sanitize_event(ev))
        if etype == "assistant":
            msg = ev.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("id"), str):
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    last_usage[str(msg["id"])] = usage
        elif etype == "result":
            usage = ev.get("usage")
            if isinstance(usage, dict):
                result_usage = usage
            subtype = ev.get("subtype")
            result_subtype = str(subtype) if subtype is not None else None

    input_sum = sum(
        sum(_int(u.get(k)) for k in INPUT_USAGE_KEYS) for u in last_usage.values()
    )
    output_sum = sum(_int(u.get("output_tokens")) for u in last_usage.values())
    result: dict[str, Any] = {
        "events": events,
        "parse_errors": parse_errors,
        "messages": len(last_usage),
        "result": result_usage is not None,
        "result_subtype": result_subtype,
        "input_sum": input_sum,
        "output_sum": output_sum,
        "samples": samples,
    }
    if result_usage is not None:
        result["result_input"] = sum(
            _int(result_usage.get(k)) for k in INPUT_USAGE_KEYS
        )
        result["output_result"] = _int(result_usage.get("output_tokens"))
        result["reconcile"] = (
            "OK" if input_sum == result["result_input"] else "MISMATCH"
        )
    else:
        result["reconcile"] = "NO_RESULT"
    return result


def max_turns_verdict(
    exit_code: str, has_result: bool, subtype: str | None, err_lower: str
) -> str:
    """`yes`, только если claude завершился с кодом 0, есть событие result и его subtype не начинается
    с error (например error_max_turns: флаг принят, но лимит не соблюдён). `no`, если в stderr
    unknown option/argument рядом с max-turns. Иначе `unknown`."""
    ok = exit_code == "0" and has_result and not str(subtype or "").startswith("error")
    if ok:
        return "yes"
    if "max-turns" in err_lower and any(m in err_lower for m in UNKNOWN_ARG_MARKERS):
        return "no"
    return "unknown"


def step_stream_json(ctx: Ctx, sbx: Sandbox, token: str) -> None:
    """2.2: короткий claude -p в фоне. Токен идёт только в envs команды. Вывод пишется
    в файлы песочницы, поэтому сама команда не ждёт stdout."""
    label = "stream-json"
    # `< /dev/null`: claude -p не должен ждать stdin. Код возврата пишем в файл, чтобы поллинг
    # не зависел от того, держит ли фоновый handle процесс.
    script = (
        f"claude -p {shlex.quote(CLAUDE_PROMPT)} --output-format stream-json --verbose "
        f"--max-turns 1 < /dev/null > {CLAUDE_OUT} 2> {CLAUDE_ERR}; echo $? > {CLAUDE_EXIT}"
    )
    try:
        sbx.commands.run(
            script, background=True, envs={ENV_CLAUDE_TOKEN: token}, timeout=0
        )
        deadline = time.monotonic() + CLAUDE_WAIT_S
        done = False
        while time.monotonic() < deadline:
            if run_cmd(sbx, f"test -s {CLAUDE_EXIT}", timeout=20).exit_code == 0:
                done = True
                break
            time.sleep(5)
        if not done:
            fail(ctx, label, f"claude -p did not finish within {CLAUDE_WAIT_S}s")
            return
        exit_code = run_cmd(sbx, f"cat {CLAUDE_EXIT}").stdout.strip()
        raw = str(sbx.files.read(CLAUDE_OUT))
        err_text = str(sbx.files.read(CLAUDE_ERR))
    except Exception as exc:
        fail(ctx, label, short_error(exc, ctx.secrets))
        return

    analysis = analyze_stream(raw.splitlines())
    max_turns_accepted = max_turns_verdict(
        exit_code,
        bool(analysis["result"]),
        analysis["result_subtype"],
        err_text.lower(),
    )
    analysis["claude_exit"] = exit_code
    analysis["stderr_bytes"] = len(err_text)
    # Маскировка до обрезки: иначе секрет на границе 300 символов попал бы в отчёт частично.
    analysis["stderr_head"] = redact(err_text, ctx.secrets)[:300]
    analysis["max_turns_accepted"] = max_turns_accepted
    ctx.details["stream"] = analysis
    say(
        ctx,
        f"{label}: events={analysis['events']} messages={analysis['messages']} "
        f"result={'yes' if analysis['result'] else 'no'} "
        f"result_subtype={analysis['result_subtype'] or 'none'} "
        f"reconcile={analysis['reconcile']} "
        f"input_sum={analysis['input_sum']} "
        f"result_input={analysis.get('result_input', 'n/a')} "
        f"output_result={analysis.get('output_result', 'n/a')} "
        f"output_sum={analysis['output_sum']} "
        f"max_turns_accepted={max_turns_accepted} exit={exit_code}",
    )


def step_verbose_probe(ctx: Ctx, sbx: Sandbox, token: str) -> None:
    """2.2 (доп.): проба stream-json без --verbose. Нужна, чтобы зафиксировать требование."""
    label = "stream-json no-verbose"
    try:
        run = run_cmd(
            sbx,
            f"claude -p {shlex.quote(CLAUDE_PROMPT)} --output-format stream-json "
            "--max-turns 1 < /dev/null",
            timeout=180,
            envs={ENV_CLAUDE_TOKEN: token},
        )
    except Exception as exc:
        fail(ctx, label, short_error(exc, ctx.secrets))
        return
    mentions = "verbose" in run.stderr.lower()
    say(
        ctx,
        f"{label}: {'FAILS' if run.exit_code != 0 else 'OK'} exit_code={run.exit_code} "
        f"stderr_mentions_verbose={'yes' if mentions else 'no'}",
    )


def step_https(ctx: Ctx, sbx: Sandbox) -> None:
    """2.3: HTTPS из песочницы. Проверяем именно изнутри песочницы (допущение A2).
    Curl получает полный URL, а вывод и отчёт содержат только scheme://host[:port]."""
    url = os.environ.get(ENV_PUBLIC_URL) or DEFAULT_URL
    shown = safe_url(url)
    try:
        run = run_cmd(
            sbx,
            f"curl -sS -o /dev/null -w '%{{http_code}}' --max-time 30 {shlex.quote(url)}",
            timeout=60,
        )
    except Exception as exc:
        fail(ctx, "https", f"url={shown} {short_error(exc, ctx.secrets)}")
        return
    if run.exit_code == 0:
        say(ctx, f"https: url={shown} code={run.stdout.strip()}")
    else:
        # Полный URL в stderr curl заменяем на безопасную форму, затем маскируем секреты.
        stderr = redact(run.stderr.replace(url, shown), ctx.secrets)[:120]
        fail(ctx, "https", f"url={shown} code=ERR exit={run.exit_code} stderr={stderr}")


def cleanup(ctx: Ctx) -> None:
    """1.5: kill только песочниц, созданных этим запуском (ctx.created), затем проверка Sandbox.list
    с фильтром purpose=mvp-01-spike. Оставшиеся созданные — FAIL. Песочницы с нашей metadata,
    которых этот запуск не создавал, только печатаются как orphan, не убиваются."""
    for sid in ctx.created:
        try:
            sdk().Sandbox.kill(sid)
        except Exception as exc:
            say(ctx, f"cleanup: kill {sid} error {short_error(exc, ctx.secrets)}")
    try:
        alive = list_sandboxes(("running", "paused"))
    except Exception as exc:
        fail(ctx, "cleanup", f"remaining=unknown ({short_error(exc, ctx.secrets)})")
        return
    remaining = [sid for sid in ctx.created if sid in alive]
    orphans = sorted(sid for sid in alive if sid not in ctx.created)
    if remaining:
        fail(ctx, "cleanup", f"remaining={','.join(remaining)}")
    else:
        say(ctx, "cleanup: OK remaining=0")
    if orphans:
        say(ctx, f"cleanup: WARN orphan={','.join(orphans)}")


def run_steps(ctx: Ctx, args: argparse.Namespace, token: str | None) -> None:
    """Порядок: основная песочница (exec, пауза, продление, claude, HTTPS), её kill, затем короткая
    песочница для истечения таймаута. Выбор шагов задаёт --only; без него выполняются все шаги.
    Всё, что создано, убирает cleanup в finally."""
    only = set(args.only or [])
    full = not only
    run_main = full or "claude" in only
    run_expire = (full or "expire" in only) and not args.skip_timeout

    sbx: Sandbox | None = None
    if run_main:
        sbx = create_or_fail(ctx, "exec", MAIN_TIMEOUT_S)
    if sbx is not None:
        step_exec(ctx, sbx)
        if full:
            step_exec_nonzero(ctx, sbx)
            sbx = step_pause_resume(ctx, sbx)
            if args.skip_timeout:
                say(ctx, "timeout extend: SKIPPED (--skip-timeout)")
            else:
                step_timeout_extend(ctx, sbx)
    elif full:
        say(ctx, "exec nonzero: SKIPPED (no main sandbox)")
        say(ctx, "pause/resume: SKIPPED (no main sandbox)")
        say(ctx, "timeout extend: SKIPPED (no main sandbox)")

    if run_main:
        if args.skip_claude:
            say(ctx, "claude: SKIPPED (--skip-claude)")
            say(ctx, "stream-json: SKIPPED (--skip-claude)")
        elif sbx is None:
            say(ctx, "claude: SKIPPED (no main sandbox)")
            say(ctx, "stream-json: SKIPPED (no main sandbox)")
        else:
            installed = False
            try:
                installed = step_claude_install(ctx, sbx, args.claude_version)
            except Exception as exc:
                fail(ctx, "claude", short_error(exc, ctx.secrets))
            if token is None:
                say(ctx, "stream-json: SKIPPED (no CLAUDE_CODE_OAUTH_TOKEN)")
            elif not installed:
                say(ctx, "stream-json: SKIPPED (claude not installed)")
            else:
                step_stream_json(ctx, sbx, token)
                step_verbose_probe(ctx, sbx, token)

    if sbx is not None:
        if full:
            step_https(ctx, sbx)
        kill_main(ctx, sbx)
    elif full:
        say(ctx, "https: SKIPPED (no main sandbox)")

    if run_expire:
        step_timeout_expire(ctx, args.short_timeout)
    elif full and args.skip_timeout:
        say(ctx, "timeout expire: SKIPPED (--skip-timeout)")


def write_report(ctx: Ctx, path: str) -> None:
    """Сырые результаты в JSON. Файл создаётся с правами 0600 и без следования symlink.
    Токены и ключ сюда не попадают: строки уже прошли маскировку, примеры stream-json очищены
    от текста ответа, а URL сведён к scheme://host."""
    payload = {
        "lines": ctx.lines,
        "created": ctx.created,
        "details": ctx.details,
    }
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)  # права существующего файла тоже приводятся к 0600
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    except OSError as exc:
        fail(ctx, "report", short_error(exc, ctx.secrets))
        return
    say(ctx, f"report: written {path}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Спайк mvp-01: проверка Novita Agent Sandbox и Claude Code."
    )
    parser.add_argument(
        "--claude-version",
        default=DEFAULT_CLAUDE_VERSION,
        help="версия @anthropic-ai/claude-code (по умолчанию %(default)s)",
    )
    parser.add_argument(
        "--report",
        metavar="PATH",
        default=None,
        help="сохранить результаты в JSON, права 0600 (по умолчанию не пишется)",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=ONLY_CHOICES,
        default=None,
        help="запустить только указанный набор шагов, флаг можно повторять: "
        "expire — только короткая песочница; claude — основная песочница, claude 2.1 и 2.2. "
        "По умолчанию выполняются все шаги",
    )
    parser.add_argument(
        "--skip-claude",
        action="store_true",
        help="пропустить шаги Claude Code (2.1 и 2.2)",
    )
    parser.add_argument(
        "--skip-timeout",
        action="store_true",
        help="пропустить шаги продления и истечения таймаута (1.4)",
    )
    parser.add_argument(
        "--short-timeout",
        type=int,
        default=30,
        metavar="SEC",
        help="таймаут короткой песочницы в секундах (по умолчанию %(default)s)",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="шаблон песочницы (по умолчанию шаблон SDK)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="офлайн-проверки маскировки, разбора stream-json и логики флагов; без ключа и SDK",
    )
    args = parser.parse_args(argv)
    if args.short_timeout <= 0:
        parser.error("--short-timeout должен быть больше 0")
    return args


def run_self_test() -> int:
    """Офлайн-проверки без сети, без ключа и без SDK. Печатает `self-test: OK` или по одной строке
    `self-test: FAIL <что>` на каждую провалившуюся проверку."""
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        if not ok:
            failures.append(name)
            print(f"self-test: FAIL {name}", flush=True)

    secret = "SEC" + "x" * 37  # 40 символов, будет на границе среза
    text = "a" * 295 + secret + "b" * 10
    masked = redact(text, (secret,))
    check(
        "redact: секрет на границе 290-310 символов маскируется целиком",
        secret not in masked,
    )
    check(
        "redact: префикс секрета не остаётся в первых 300 символах",
        "SECx" not in masked[:300],
    )
    check(
        "redact: шаблон sk-ant- маскируется без точного значения",
        "sk-ant-" not in redact("token sk-ant-oat01-AbC_def-123 end", ()),
    )
    check(
        "redact: шаблон sk_ маскируется",
        "sk_A1" not in redact("key sk_" + "A1" * 12 + " end", ()),
    )
    check(
        "redact: пустые секреты не портят текст",
        redact("abc def", ("", "")) == "abc def",
    )

    dup_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "usage": {"input_tokens": 10, "output_tokens": 7},
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m2",
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "usage": {"input_tokens": 15, "output_tokens": 9},
            }
        ),
    ]
    stream = analyze_stream(dup_lines)
    check(
        "analyze_stream: дедупликация по message.id, messages=2",
        stream["messages"] == 2,
    )
    check("analyze_stream: input_sum=15 без двойного счёта", stream["input_sum"] == 15)
    check("analyze_stream: reconcile=OK", stream["reconcile"] == "OK")
    check(
        "analyze_stream: output_sum берёт последнее вхождение (7+2)",
        stream["output_sum"] == 9,
    )
    check(
        "analyze_stream: result_subtype=success", stream["result_subtype"] == "success"
    )

    check(
        "max_turns: exit 0, result success -> yes",
        max_turns_verdict("0", True, "success", "") == "yes",
    )
    check(
        "max_turns: exit 1 при наличии result -> не yes",
        max_turns_verdict("1", True, "success", "") != "yes",
    )
    check(
        "max_turns: error_max_turns -> не yes",
        max_turns_verdict("0", True, "error_max_turns", "") != "yes",
    )
    check(
        "max_turns: unknown option рядом с max-turns -> no",
        max_turns_verdict("1", False, None, "error: unknown option '--max-turns'")
        == "no",
    )

    check(
        "safe_url: без userinfo, пути и query",
        safe_url("https://user:pw@example.com:8443/p?q=s")
        == "https://example.com:8443",
    )
    check(
        "safe_url: без порта",
        safe_url("https://example.com/a?b=c") == "https://example.com",
    )

    if failures:
        return 1
    print("self-test: OK", flush=True)
    return 0


def _on_sigterm(signum: int, frame: FrameType | None) -> None:
    """SIGTERM превращаем в SystemExit: тогда finally отрабатывает и cleanup убирает песочницы."""
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()
    api_key = os.environ.get(ENV_API_KEY, "")
    if not api_key:
        print(
            f"Ошибка: переменная окружения {ENV_API_KEY} не задана. "
            "Ключ берётся только из ENV, файлы с ключом скрипт не читает.",
            file=sys.stderr,
        )
        return 2
    signal.signal(signal.SIGTERM, _on_sigterm)
    token = os.environ.get(ENV_CLAUDE_TOKEN) or None
    secrets = tuple(s for s in (api_key, token or "") if s)
    ctx = Ctx(template=args.template, secrets=secrets)
    try:
        run_steps(ctx, args, token)
    finally:
        cleanup(ctx)
        if args.report:
            write_report(ctx, args.report)
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
