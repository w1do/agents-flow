#!/usr/bin/env bash
# Подготовка песочницы агентов (mvp-06, design 16; sandbox-profile, design 3). Запуск, например:
#   bootstrap.sh --claude-version 2.1.292 --openspec-version 1.14.3 demo=https://gitlab.example/group/demo.git
#   bootstrap.sh ... --memory-ref <sha> --memory-repo w1do/memory-agent demo=https://gitlab.example/group/demo.git
#     (с памятью проекта: memory-agent из GitHub по полному sha коммита, D-51)
#
# Идемпотентен: повторный запуск не переустанавливает совпадающие версии и не клонирует заново.
# Секреты в файлы не пишутся. mcp.json содержит литеральные плейсхолдеры ${AGENTS_FLOW_URL} и
# ${AGENTS_FLOW_TOKEN}: Claude Code раскрывает их из env процесса. Токен GitLab уходит git только
# заголовком Authorization на префикс --gitlab-url (GIT_CONFIG_* в env одной команды), в файлы не
# пишется, git-askpass.sh не используется (D-52). EMBEDDING_API_KEY
# читается memory-agent из env этой команды; в .memory/.env и конфиг memory он не пишется.
# Все установки — через sudo -n: без sudo скрипт сообщает, что нужно поставить вручную.
set -euo pipefail
umask 077

# Ключи приходят в env процесса. Скрипт забирает их в переменные оболочки и снимает из env, чтобы
# postinst пакетов apt и lifecycle-скрипты npm их не видели. Значение получает только строка, где
# оно нужно: заголовок git для клонов и fetch (GIT_CONFIG_* одной команды) и memory init (EMBEDDING_API_KEY).
gitlab_token="${GITLAB_TOKEN:-}"
embedding_key="${EMBEDDING_API_KEY:-}"
unset GITLAB_TOKEN EMBEDDING_API_KEY

usage() {
  cat <<'USAGE'
Использование: bootstrap.sh --claude-version V --openspec-version V [--memory-ref SHA --memory-repo OWNER/NAME] <workspace_id>=<clone_url>...
  workspace_id — [A-Za-z0-9_-]{1,28}; clone_url — http(s)-адрес без учётных данных.
  Для git-операций нужен GITLAB_TOKEN в env; --gitlab-url — https-адрес GitLab, на его префикс уходит токен. Память: memory-agent ставится из GitHub по полному sha
  коммита (--memory-ref, 40 символов 0-9a-f) из репозитория --memory-repo; флаги задаются вместе.
  Ключ embeddings, если нужен, — в env EMBEDDING_API_KEY.
USAGE
}

SEMVER_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
# Базовый адрес GitLab: только https, без учётных данных, пробелов и query (D-52).
GITLAB_URL_RE='^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]+)*/?$'
PAIR_RE='^[A-Za-z0-9_-]{1,28}=https?://[^[:space:]@]+$'

claude_version=""
openspec_version=""
memory_ref=""
memory_repo=""
gitlab_url=""
repos=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude-version | --openspec-version | --memory-ref | --memory-repo | --gitlab-url)
      if [ "$#" -lt 2 ]; then
        echo "аргумент $1 без значения" >&2
        exit 2
      fi
      case "$1" in
        --claude-version) claude_version="$2" ;;
        --openspec-version) openspec_version="$2" ;;
        --memory-ref) memory_ref="$2" ;;
        --gitlab-url) gitlab_url="$2" ;;
        *) memory_repo="$2" ;;
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
# memory-agent ставится по полному sha коммита: тег и ветка изменяемы (D-51). Флаги — только вместе.
SHA_RE='^[0-9a-f]{40}$'
# Сегменты owner/name: начинаются и заканчиваются буквой или цифрой, внутри — . _ - (L1).
GH_REPO_RE='^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?/[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$'
if [ -n "$memory_ref" ] || [ -n "$memory_repo" ]; then
  if [ -z "$memory_ref" ] || [ -z "$memory_repo" ]; then
    echo "--memory-ref и --memory-repo задаются вместе" >&2
    exit 2
  fi
  if ! [[ "$memory_ref" =~ $SHA_RE ]]; then
    echo "--memory-ref — полный sha коммита (40 символов 0-9a-f)" >&2
    exit 2
  fi
  if ! [[ "$memory_repo" =~ $GH_REPO_RE ]]; then
    echo "--memory-repo в формате owner/name" >&2
    exit 2
  fi
fi
if [ -n "$gitlab_url" ] && ! [[ "$gitlab_url" =~ $GITLAB_URL_RE ]]; then
  echo "--gitlab-url — https-адрес без учётных данных, пробелов и query" >&2
  exit 2
fi
if [ "${#repos[@]}" -gt 0 ] && [ -z "$gitlab_url" ]; then
  echo "нужен --gitlab-url: токен GitLab уходит только на префикс этого адреса" >&2
  exit 2
fi
# Нормализация: префикс с завершающим слэшем, как его сопоставляет git (http.<url>.*).
if [ -n "$gitlab_url" ]; then
  gitlab_url="${gitlab_url%/}/"
fi
for pair in "${repos[@]}"; do
  if ! [[ "$pair" =~ $PAIR_RE ]]; then
    echo "некорректная пара <workspace_id>=<clone_url>" >&2
    exit 2
  fi
done

# Защита от случайного запуска на машине разработчика (D-52, ревью): всё, что ниже, меняет систему
# (npm, apt, каталоги, клоны). Без HARNESS_SANDBOX_BOOTSTRAP=1 скрипт выходит до побочных эффектов;
# harness-server выставляет переменную в env своей команды.
if [ "${HARNESS_SANDBOX_BOOTSTRAP:-}" != "1" ]; then
  echo "bootstrap.sh выполняется только в песочнице харнесса (HARNESS_SANDBOX_BOOTSTRAP=1)" >&2
  exit 3
fi

HARNESS_DIR="${HOME:?HOME не задан}/.harness"

# Node 22.13 — минимум для memory-agent (D-47). Проверка без внешних утилит.
node_ok() {
  command -v node >/dev/null 2>&1 &&
    node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=13)?0:1)'
}

# apt всегда без вопросов: скрипт не должен ждать ввода в песочнице.
# Файлы, которые создаёт root (ключи и списки источников apt), тоже с umask 022: sudo берёт
# объединение umask пользователя и своего, и без этого ключ apt получается 0600 и apt его не читает.
root_umask() {
  (
    umask 022
    "$@"
  )
}
apt_update() {
  root_umask sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update -qq
}
apt_install() {
  root_umask sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
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
    root_umask sudo -n gpg --batch --yes --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" |
    root_umask sudo -n tee /etc/apt/sources.list.d/nodesource.list >/dev/null
  # npm из Ubuntu конфликтует с npm из пакета nodejs NodeSource.
  if dpkg -s npm >/dev/null 2>&1; then
    root_umask sudo -n env DEBIAN_FRONTEND=noninteractive apt-get remove -y npm
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
# umask 022 — только внутри подшелла: umask 077 скрипта через sudo дал бы файлам глобального
# префикса права 0600/0700 у root, и пользователь песочницы не запустил бы memory, claude, openspec.
npm_global() {
  # Кэш npm пользователя — только его; при создании 700, существующий каталог — тоже 700 (L2).
  [ -e "$HOME/.npm" ] || mkdir -m 700 "$HOME/.npm"
  if [ -O "$HOME/.npm" ]; then
    chmod 700 "$HOME/.npm"
  fi
  (
    umask 022
    local prefix lib
    prefix="$(npm config get prefix)"
    lib="$prefix/lib/node_modules"
    if { [ -d "$lib" ] && [ -w "$lib" ]; } || { [ ! -e "$lib" ] && [ -w "$prefix/lib" ]; }; then
      npm "$@"
    else
      sudo -n env PATH="$PATH" npm "$@"
    fi
  )
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

# memory-agent из GitHub по полному sha (D-51). Маркер хранит установленный spec: по нему повтор
# не переустанавливает, а новый sha в harness.yaml даёт новую установку. Маркер пишется только после
# успешной установки и проверки команды memory.
ensure_memory_agent() {
  local spec="github:${memory_repo}#${memory_ref}"
  local marker="$HARNESS_DIR/memory/installed-ref"
  if command -v memory >/dev/null 2>&1 && [ -f "$marker" ] && [ "$(cat "$marker")" = "$spec" ]; then
    echo "уже установлен: $spec"
    return 0
  fi
  mkdir -p "$HARNESS_DIR/memory"
  npm_global install -g "$spec"
  hash -r
  if ! command -v memory >/dev/null 2>&1; then
    echo "memory-agent установлен, но команды memory нет" >&2
    exit 1
  fi
  printf '%s\n' "$spec" >"$marker.tmp"
  mv "$marker.tmp" "$marker"
}

ensure_npm_package "@anthropic-ai/claude-code" "$claude_version"
ensure_npm_package "@fission-ai/openspec" "$openspec_version"

mkdir -p "$HARNESS_DIR/bin" "$HARNESS_DIR/tasks" "$HARNESS_DIR/worktrees" "$HOME/work"
# Пустые каталоги user-level для skills и агентов Claude (D-48): наполняет skills-library.
mkdir -p "$HOME/.claude/skills" "$HOME/.claude/agents"
chmod 700 "$HOME/.claude/skills" "$HOME/.claude/agents"

# Старый git-askpass.sh (до D-52) удаляется, если остался от прошлых запусков: токен в нём не нужен.
rm -f "$HARNESS_DIR/bin/git-askpass.sh"

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

# Заголовок git для клонов и fetch: не экспортируется, передаётся только env git-команд.
# Без токена заголовка нет: git ходит анонимно, это публичные репозитории (D-52).
git_auth_header=""
if [ -n "$gitlab_token" ]; then
  git_auth_header="Authorization: Basic $(printf '%s' "oauth2:$gitlab_token" | base64 -w0)"
fi
# Один вызов git для клона и fetch: заголовок — префиксная переменная той же команды, не argv.
run_git_auth() {
  if [ -n "$git_auth_header" ]; then
    # Редиректы выключены, чтобы заголовок не ушёл на другой хост.
    GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0="http.${gitlab_url}.extraHeader" \
      GIT_CONFIG_VALUE_0="$git_auth_header" GIT_CONFIG_KEY_1=http.followRedirects \
      GIT_CONFIG_VALUE_1=false GIT_TERMINAL_PROMPT=0 git "$@"
  else
    GIT_TERMINAL_PROMPT=0 git "$@"
  fi
}
for pair in "${repos[@]}"; do
  workspace_id="${pair%%=*}"
  url="${pair#*=}"
  dir="$HOME/work/$workspace_id"
  if [ ! -e "$dir" ]; then
    echo "клонирую $workspace_id"
    run_git_auth clone --quiet -- "$url" "$dir"
  else
    if [ ! -d "$dir/.git" ]; then
      echo "$dir существует и не является git-репозиторием" >&2
      exit 1
    fi
    echo "обновляю $workspace_id"
    git -C "$dir" remote set-url origin "$url"
    run_git_auth -C "$dir" fetch --quiet --prune origin
  fi
done

if [ -n "$memory_ref" ]; then
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
      root_umask sudo -n curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      sudo -n chmod a+r /etc/apt/keyrings/docker.asc
      # shellcheck source=/dev/null
      codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" |
        root_umask sudo -n tee /etc/apt/sources.list.d/docker.list >/dev/null
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

  ensure_memory_agent
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
