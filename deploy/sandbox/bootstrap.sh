#!/usr/bin/env bash
# Подготовка песочницы агентов (mvp-06, design 16). Запуск, например:
#   bootstrap.sh --claude-version 2.1.292 --openspec-version 1.14.3 demo=https://gitlab.example/group/demo.git
#
# Идемпотентен: повторный запуск не переустанавливает совпадающие версии и не клонирует заново.
# Секреты в файлы не пишутся. mcp.json содержит литеральные плейсхолдеры ${AGENTS_FLOW_URL} и
# ${AGENTS_FLOW_TOKEN}: Claude Code раскрывает их из env процесса. git-askpass.sh читает
# GITLAB_TOKEN из env при каждом запросе, значение в файле не появляется.
set -euo pipefail
umask 077

usage() {
  cat <<'USAGE'
Использование: bootstrap.sh --claude-version V --openspec-version V <workspace_id>=<clone_url>...
  workspace_id — [A-Za-z0-9_-]{1,28}; clone_url — http(s)-адрес без учётных данных.
  Для git-операций нужен GITLAB_TOKEN в env.
USAGE
}

SEMVER_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
PAIR_RE='^[A-Za-z0-9_-]{1,28}=https?://[^[:space:]@]+$'

claude_version=""
openspec_version=""
repos=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude-version | --openspec-version)
      if [ "$#" -lt 2 ]; then
        echo "аргумент $1 без значения" >&2
        exit 2
      fi
      if [ "$1" = "--claude-version" ]; then claude_version="$2"; else openspec_version="$2"; fi
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --*)
      echo "неизвестный аргумент: $1" >&2
      exit 2
      ;;
    *)
      repos+=("$1")
      shift
      ;;
  esac
done

if ! [[ "$claude_version" =~ $SEMVER_RE && "$openspec_version" =~ $SEMVER_RE ]]; then
  echo "нужны --claude-version и --openspec-version в формате X.Y.Z" >&2
  exit 2
fi
for pair in "${repos[@]}"; do
  if ! [[ "$pair" =~ $PAIR_RE ]]; then
    echo "некорректная пара <workspace_id>=<clone_url>" >&2
    exit 2
  fi
done

HARNESS_DIR="${HOME:?HOME не задан}/.harness"
command -v npm >/dev/null || { echo "нет npm в песочнице" >&2; exit 1; }
command -v git >/dev/null || { echo "нет git в песочнице" >&2; exit 1; }

# Ставит пакет, только если нужная версия ещё не установлена: повтор не переустанавливает.
ensure_npm_package() {
  local package="$1" version="$2"
  if npm list -g --depth=0 "$package" 2>/dev/null | grep -qF "${package}@${version}"; then
    echo "уже установлен: ${package}@${version}"
    return 0
  fi
  npm install -g "${package}@${version}"
}

ensure_npm_package "@anthropic-ai/claude-code" "$claude_version"
ensure_npm_package "@fission-ai/openspec" "$openspec_version"

mkdir -p "$HARNESS_DIR/bin" "$HARNESS_DIR/tasks" "$HARNESS_DIR/worktrees" "$HOME/work"

# Значения не записываются: токен берётся из GITLAB_TOKEN в момент запроса git.
# Квотированный heredoc не раскрывает переменные, поэтому текст скрипта пишется как есть.
cat > "$HARNESS_DIR/bin/git-askpass.sh" <<'ASKPASS'
#!/usr/bin/env bash
# Ответ на запрос git: логин фиксирован, пароль — токен из окружения процесса.
case "$1" in
  Username*) printf '%s\n' oauth2 ;;
  Password*) printf '%s\n' "${GITLAB_TOKEN:?GITLAB_TOKEN не задан}" ;;
esac
ASKPASS
chmod 700 "$HARNESS_DIR/bin/git-askpass.sh"

# Плейсхолдеры остаются литеральными: Claude Code подставляет их из env при запуске агента.
cat > "$HARNESS_DIR/mcp.json" <<'MCP'
{
  "mcpServers": {
    "agents-flow": {
      "type": "http",
      "url": "${AGENTS_FLOW_URL}",
      "headers": {
        "Authorization": "Bearer ${AGENTS_FLOW_TOKEN}"
      }
    }
  }
}
MCP
chmod 600 "$HARNESS_DIR/mcp.json"

for pair in "${repos[@]}"; do
  workspace_id="${pair%%=*}"
  url="${pair#*=}"
  dir="$HOME/work/$workspace_id"
  if [ ! -e "$dir" ]; then
    echo "клонирую $workspace_id"
    GIT_ASKPASS="$HARNESS_DIR/bin/git-askpass.sh" GIT_TERMINAL_PROMPT=0 \
      git clone --quiet -- "$url" "$dir"
  else
    if [ ! -d "$dir/.git" ]; then
      echo "$dir существует и не является git-репозиторием" >&2
      exit 1
    fi
    echo "обновляю $workspace_id"
    git -C "$dir" remote set-url origin "$url"
    GIT_ASKPASS="$HARNESS_DIR/bin/git-askpass.sh" GIT_TERMINAL_PROMPT=0 \
      git -C "$dir" fetch --quiet --prune origin
  fi
done

echo "bootstrap завершён"
