#!/usr/bin/env bash
# Подготовка песочницы агентов (mvp-06, design 16; sandbox-profile, design 3). Запуск, например:
#   bootstrap.sh --claude-version 2.1.292 --openspec-version 1.14.3 demo=https://gitlab.example/group/demo.git
#   bootstrap.sh ... --memory-version 1.2.3 demo=https://gitlab.example/group/demo.git   # с памятью проекта
#
# Идемпотентен: повторный запуск не переустанавливает совпадающие версии и не клонирует заново.
# Секреты в файлы не пишутся. mcp.json содержит литеральные плейсхолдеры ${AGENTS_FLOW_URL} и
# ${AGENTS_FLOW_TOKEN}: Claude Code раскрывает их из env процесса. git-askpass.sh читает
# GITLAB_TOKEN из env при каждом запросе, значение в файле не появляется. EMBEDDING_API_KEY
# читается memory-agent из env этой команды; в .memory/.env и конфиг memory он не пишется.
# Все установки — через sudo -n: без sudo скрипт сообщает, что нужно поставить вручную.
set -euo pipefail
umask 077

# Ключи приходят в env процесса. Скрипт забирает их в переменные оболочки и снимает из env, чтобы
# postinst пакетов apt и lifecycle-скрипты npm их не видели. Значение получает только строка, где
# оно нужно: git-команда (askpass читает GITLAB_TOKEN из env git) и memory init (EMBEDDING_API_KEY).
gitlab_token="${GITLAB_TOKEN:-}"
embedding_key="${EMBEDDING_API_KEY:-}"
unset GITLAB_TOKEN EMBEDDING_API_KEY

usage() {
  cat <<'USAGE'
Использование: bootstrap.sh --claude-version V --openspec-version V [--memory-version V] <workspace_id>=<clone_url>...
  workspace_id — [A-Za-z0-9_-]{1,28}; clone_url — http(s)-адрес без учётных данных.
  Для git-операций нужен GITLAB_TOKEN в env. Для памяти (--memory-version) — project-memory точной
  версии; ключ embeddings, если нужен, — в env EMBEDDING_API_KEY.
USAGE
}

SEMVER_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
PAIR_RE='^[A-Za-z0-9_-]{1,28}=https?://[^[:space:]@]+$'

claude_version=""
openspec_version=""
memory_version=""
repos=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude-version | --openspec-version | --memory-version)
      if [ "$#" -lt 2 ]; then
        echo "аргумент $1 без значения" >&2
        exit 2
      fi
      case "$1" in
        --claude-version) claude_version="$2" ;;
        --openspec-version) openspec_version="$2" ;;
        *) memory_version="$2" ;;
      esac
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
if [ -n "$memory_version" ] && ! [[ "$memory_version" =~ $SEMVER_RE ]]; then
  echo "--memory-version в формате X.Y.Z" >&2
  exit 2
fi
for pair in "${repos[@]}"; do
  if ! [[ "$pair" =~ $PAIR_RE ]]; then
    echo "некорректная пара <workspace_id>=<clone_url>" >&2
    exit 2
  fi
done

HARNESS_DIR="${HOME:?HOME не задан}/.harness"

# Node 22.13 — минимум для memory-agent (D-47). Проверка без внешних утилит.
node_ok() {
  command -v node >/dev/null 2>&1 &&
    node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)'
}

# apt всегда без вопросов: скрипт не должен ждать ввода в песочнице.
apt_update() {
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update -qq
}
apt_install() {
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

# Node из репозитория NodeSource: ключ подписи скачивается и проверяется gpg, удалённый
# установочный скрипт не запускается.
ensure_node() {
  if node_ok; then
    echo "уже установлен: Node $(node -v)"
    return 0
  fi
  if ! sudo -n true 2>/dev/null; then
    echo "нужен Node ≥ 22.13: поставьте вручную или дайте sudo" >&2
    exit 1
  fi
  echo "ставлю Node 22 из репозитория NodeSource"
  apt_install ca-certificates curl gnupg
  sudo -n install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key |
    sudo -n gpg --batch --yes --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" |
    sudo -n tee /etc/apt/sources.list.d/nodesource.list >/dev/null
  # npm из Ubuntu конфликтует с npm из пакета nodejs NodeSource.
  if dpkg -s npm >/dev/null 2>&1; then
    sudo -n env DEBIAN_FRONTEND=noninteractive apt-get remove -y npm
  fi
  apt_update
  apt_install nodejs
  hash -r
  if ! node_ok; then
    echo "после установки нужен Node ≥ 22.13" >&2
    exit 1
  fi
}

ensure_node
command -v npm >/dev/null || { echo "нет npm в песочнице" >&2; exit 1; }
command -v git >/dev/null || { echo "нет git в песочнице" >&2; exit 1; }

# Глобальные пакеты ставятся в префикс npm. Если его lib/node_modules недоступен на запись
# (системный префикс), установка идёт через sudo -n; пользовательский префикс — без sudo.
npm_global() {
  local prefix lib
  prefix="$(npm config get prefix)"
  lib="$prefix/lib/node_modules"
  if { [ -d "$lib" ] && [ -w "$lib" ]; } || { [ ! -e "$lib" ] && [ -w "$prefix/lib" ]; }; then
    npm "$@"
  else
    sudo -n env PATH="$PATH" npm "$@"
  fi
}

# Ставит пакет, только если нужная версия ещё не установлена: повтор не переустанавливает.
ensure_npm_package() {
  local package="$1" version="$2"
  if npm list -g --depth=0 "$package" 2>/dev/null | grep -qF "${package}@${version}"; then
    echo "уже установлен: ${package}@${version}"
    return 0
  fi
  npm_global install -g "${package}@${version}"
}

ensure_npm_package "@anthropic-ai/claude-code" "$claude_version"
ensure_npm_package "@fission-ai/openspec" "$openspec_version"

mkdir -p "$HARNESS_DIR/bin" "$HARNESS_DIR/tasks" "$HARNESS_DIR/worktrees" "$HOME/work"
# Пустые каталоги user-level для skills и агентов Claude (D-48): наполняет skills-library.
mkdir -p "$HOME/.claude/skills" "$HOME/.claude/agents"
chmod 700 "$HOME/.claude/skills" "$HOME/.claude/agents"

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
    GITLAB_TOKEN="$gitlab_token" GIT_ASKPASS="$HARNESS_DIR/bin/git-askpass.sh" GIT_TERMINAL_PROMPT=0 \
      git clone --quiet -- "$url" "$dir"
  else
    if [ ! -d "$dir/.git" ]; then
      echo "$dir существует и не является git-репозиторием" >&2
      exit 1
    fi
    echo "обновляю $workspace_id"
    git -C "$dir" remote set-url origin "$url"
    GITLAB_TOKEN="$gitlab_token" GIT_ASKPASS="$HARNESS_DIR/bin/git-askpass.sh" GIT_TERMINAL_PROMPT=0 \
      git -C "$dir" fetch --quiet --prune origin
  fi
done

if [ -n "$memory_version" ]; then
  # setfacl нужен ensure-docker.sh при каждом запуске демона, поэтому пакет acl ставится отдельно
  # от установки Docker: при уже стоящем Docker иначе не будет setfacl (ревью, пункт 6).
  ensure_acl() {
    if command -v setfacl >/dev/null 2>&1; then
      return 0
    fi
    if ! sudo -n true 2>/dev/null; then
      echo "нужен пакет acl (setfacl): поставьте вручную или дайте sudo" >&2
      exit 1
    fi
    apt_update
    apt_install acl
  }
  # Docker Engine с Compose v2: нужен memory-agent (Qdrant и Typesense в контейнерах).
  ensure_docker() {
    if ! docker compose version >/dev/null 2>&1; then
      if ! sudo -n true 2>/dev/null; then
        echo "нужен Docker Compose v2: поставьте вручную или дайте sudo" >&2
        exit 1
      fi
      echo "ставлю Docker Engine из репозитория Docker"
      apt_update
      apt_install ca-certificates curl
      sudo -n install -m 0755 -d /etc/apt/keyrings
      sudo -n curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      sudo -n chmod a+r /etc/apt/keyrings/docker.asc
      # shellcheck source=/dev/null
      codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" |
        sudo -n tee /etc/apt/sources.list.d/docker.list >/dev/null
      apt_update
      apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    # Скрипт запуска демона: после паузы песочницы Novita демон остановлен, а при активации
    # его надо поднять снова (design 3, 12). Запускается при активации, поэтому лежит в ~/.harness/bin.
    cat > "$HARNESS_DIR/bin/ensure-docker.sh" <<'ENSURE'
#!/usr/bin/env bash
# Поднимает Docker Engine, если он остановлен. Идемпотентен: работающий демон не трогает.
set -euo pipefail
if docker info >/dev/null 2>&1; then
  exit 0
fi
if ! sudo -n true 2>/dev/null; then
  echo "нужен sudo для запуска Docker" >&2
  exit 1
fi
if [ -d /run/systemd/system ]; then
  sudo -n systemctl start docker
else
  sudo -n sh -c 'nohup dockerd >/var/log/dockerd.log 2>&1 &'
fi
for _ in $(seq 1 30); do
  [ -S /var/run/docker.sock ] && break
  sleep 1
done
# Доступ пользователю к сокету без перелогина в группу docker.
sudo -n setfacl -m "u:$(id -un):rw" /var/run/docker.sock
docker info >/dev/null
ENSURE
    chmod 700 "$HARNESS_DIR/bin/ensure-docker.sh"
    bash "$HARNESS_DIR/bin/ensure-docker.sh"
  }
  ensure_acl
  ensure_docker

  ensure_npm_package project-memory "$memory_version"
  memory service up

  mkdir -p "$HARNESS_DIR/memory"
  for pair in "${repos[@]}"; do
    workspace_id="${pair%%=*}"
    dir="$HOME/work/$workspace_id"
    # Индекс памяти — локальный каталог клона; в git он не попадает.
    exclude="$dir/.git/info/exclude"
    mkdir -p "$(dirname "$exclude")"
    grep -qxF '.memory/' "$exclude" 2>/dev/null || echo '.memory/' >>"$exclude"
    # Первый запуск индексирует проект; повторный не переиндексирует неизменённые файлы.
    if [ -n "$embedding_key" ]; then
      EMBEDDING_API_KEY="$embedding_key" memory init --path "$dir"
    else
      memory init --path "$dir"
    fi
    touch "$HARNESS_DIR/memory/$workspace_id.ready"
    echo "память готова: $workspace_id"
  done
fi

echo "bootstrap завершён"
