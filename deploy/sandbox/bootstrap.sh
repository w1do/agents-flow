#!/usr/bin/env bash
# Подготовка песочницы агентов (mvp-06, design 16; sandbox-profile, design 3). Запуск, например:
#   bootstrap.sh --phase setup --claude-version 2.1.292 --openspec-version 1.14.3
#   bootstrap.sh --phase memory --claude-version 2.1.292 --openspec-version 1.14.3 --memory-ref <sha> --memory-repo w1do/memory-agent demo=https://gitlab.example/group/demo.git
#     (фаза memory: индексация клонов памятью проекта, memory-agent из GitHub по полному sha коммита, D-51)
#
# Идемпотентен: повторный запуск не переустанавливает совпадающие версии и не клонирует заново.
# Скрипт не клонирует репозитории и не получает их ключей: клоны и fetch делает harness-server отдельными
# git-командами (D-62). Фаза setup (установки) запускается без ключей в env; фаза memory получает только
# EMBEDDING_API_KEY, который memory-agent читает из env этой команды; в .memory/.env и конфиг memory он не пишется.
# Секреты в файлы не пишутся. mcp.json содержит литеральные плейсхолдеры ${AGENTS_FLOW_URL} и
# ${AGENTS_FLOW_TOKEN}: Claude Code раскрывает их из env процесса.
# Все установки — через sudo -n: без sudo скрипт сообщает, что нужно поставить вручную.
set -euo pipefail
umask 077

# Ключ embeddings приходит в env только фазе memory. Скрипт забирает его в переменную оболочки и снимает
# из env вместе с любыми переменными, похожими на ключи git; их имена (не значения) проверяются ниже:
# фаза setup запускается без ключей, чтобы postinst apt и lifecycle npm их не видели (D-62).
embedding_key="${EMBEDDING_API_KEY:-}"
secret_env_names=""
while IFS= read -r name; do
  case "$name" in
    GIT_AUTH_HEADER_* | GIT_CONFIG_* | GITLAB_TOKEN | EMBEDDING_API_KEY)
      secret_env_names="$secret_env_names $name"
      unset "$name"
      ;;
  esac
done < <(compgen -e)

usage() {
  cat <<'USAGE'
Использование: bootstrap.sh --phase setup|memory --claude-version V --openspec-version V [--memory-ref SHA --memory-repo OWNER/NAME] <workspace_id>=<clone_url>...
  --phase setup — установки, каталоги и memory-agent; в env не должно быть ключей.
  --phase memory — только индексация клонов (нужны --memory-ref и --memory-repo); ключ embeddings — в env EMBEDDING_API_KEY.
  workspace_id — [A-Za-z0-9_-]{1,28}; clone_url — https-адрес без учётных данных. Клоны и fetch делает harness-server (D-62).
  Память: memory-agent ставится из GitHub по полному sha коммита (--memory-ref, 40 символов 0-9a-f) из репозитория
  --memory-repo; флаги задаются вместе.
USAGE
}

SEMVER_RE='^[0-9]+\.[0-9]+\.[0-9]+$'
# Пара: адрес клона только https, без учётных данных, пробелов, query и fragment (D-60).
PAIR_RE='^[A-Za-z0-9_-]{1,28}=https://[^[:space:]@?#]+$'

phase=""
claude_version=""
openspec_version=""
memory_ref=""
memory_repo=""
repos=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude-version | --openspec-version | --memory-ref | --memory-repo | --phase)
      if [ "$#" -lt 2 ]; then
        echo "аргумент $1 без значения" >&2
        exit 2
      fi
      case "$1" in
        --claude-version) claude_version="$2" ;;
        --openspec-version) openspec_version="$2" ;;
        --memory-ref) memory_ref="$2" ;;
        --phase) phase="$2" ;;
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
for pair in "${repos[@]}"; do
  if ! [[ "$pair" =~ $PAIR_RE ]]; then
    echo "некорректная пара <workspace_id>=<clone_url>" >&2
    exit 2
  fi
done
case "$phase" in
  setup | memory) ;;
  *)
    echo "нужен --phase setup или --phase memory" >&2
    exit 2
    ;;
esac
if [ "$phase" = "memory" ] && [ -z "$memory_ref" ]; then
  echo "фаза memory требует --memory-ref и --memory-repo" >&2
  exit 2
fi
# Только имена: в фазе setup ключей нет совсем, в фазе memory допустим только EMBEDDING_API_KEY (D-62).
for name in $secret_env_names; do
  if [ "$phase" = "setup" ] || [ "$name" != "EMBEDDING_API_KEY" ]; then
    echo "фаза $phase запускается без $name в env (D-62)" >&2
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

# Индексация клонов памятью (D-47). Фаза memory идёт после клонов сервера и ничего не ставит (D-62).
index_memory_clones() {
  if ! command -v memory >/dev/null 2>&1; then
    echo "memory-agent не установлен: сначала bootstrap.sh --phase setup" >&2
    exit 1
  fi
  mkdir -p "$HARNESS_DIR/memory"
  local pair workspace_id dir exclude
  for pair in "${repos[@]}"; do
    workspace_id="${pair%%=*}"
    dir="$HOME/work/$workspace_id"
    if [ ! -d "$dir/.git" ]; then
      echo "нет клона $workspace_id: память не индексируется" >&2
      exit 1
    fi
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
}
if [ "$phase" = "memory" ]; then
  index_memory_clones
  exit 0
fi

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
  # Образ песочницы может прийти с пустыми списками apt: без update установка не находит пакеты.
  apt_update
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
# Кэш npm пользователя — только его; при создании 700, существующий каталог — тоже 700 (L2).
ensure_npm_home() {
  [ -e "$HOME/.npm" ] || mkdir -m 700 "$HOME/.npm"
  if [ -O "$HOME/.npm" ]; then
    chmod 700 "$HOME/.npm"
  fi
}

npm_global() {
  ensure_npm_home
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
  local base="$HOME/.harness/memory-agent"
  local dir="$base/$memory_ref"
  local bin="$dir/dist/cli/index.js"
  # Пропуск, только если маркер совпадает и memory ведёт на сборку этого коммита (ревью).
  if [ -f "$marker" ] && [ "$(cat "$marker")" = "$spec" ] && [ -x "$bin" ] \
    && [ "$(readlink -f /usr/local/bin/memory 2>/dev/null)" = "$(readlink -f "$bin")" ]; then
    echo "уже установлен: $spec"
    return 0
  fi
  # Симлинк в /usr/local/bin требует sudo; без него установка бессмысленна (Docker тоже нужен sudo).
  if ! sudo -n true 2>/dev/null; then
    echo "нужен sudo для установки memory-agent" >&2
    exit 1
  fi
  # Установка от пользователя песочницы (D-51, уточнено после live): npm-зависимость из GitHub
  # собирается prepare от root и падает (tsc: not found), поэтому клон по sha, npm ci по lockfile,
  # сборка и подрезка devDependencies идут здесь. Публичный репозиторий: клон анонимный, без заголовка.
  ensure_npm_home
  mkdir -p "$base" "$HARNESS_DIR/memory"
  if [ ! -d "$dir/.git" ]; then
    rm -rf -- "$dir"
    GIT_TERMINAL_PROMPT=0 git clone -q "https://github.com/${memory_repo}.git" "$dir"
  fi
  if ! git -C "$dir" cat-file -e "${memory_ref}^{commit}" 2>/dev/null; then
    GIT_TERMINAL_PROMPT=0 git -C "$dir" fetch -q origin
  fi
  git -C "$dir" -c advice.detachedHead=false checkout -q "$memory_ref"
  (
    cd "$dir" && npm ci --no-audit --no-fund && npm run build && npm prune --omit=dev --no-audit --no-fund
  )
  if [ ! -f "$bin" ]; then
    echo "memory-agent: после сборки нет $bin" >&2
    exit 1
  fi
  # tsc не выставляет бит исполнения; shebang сборки — #!/usr/bin/env node.
  chmod u+x "$bin"
  sudo -n ln -sfn "$bin" /usr/local/bin/memory
  hash -r
  if [ "$(readlink -f /usr/local/bin/memory)" != "$(readlink -f "$bin")" ]; then
    echo "memory-agent: /usr/local/bin/memory не ведёт на сборку $memory_ref" >&2
    exit 1
  fi
  printf '%s\n' "$spec" >"$marker.tmp"
  mv "$marker.tmp" "$marker"
  # Прежние сборки других коммитов удаляются только после успешного переключения (ревью).
  local old name
  for old in "$base"/*; do
    [ -d "$old" ] || continue
    name="${old##*/}"
    if [[ "$name" =~ ^[0-9a-f]{40}$ ]] && [ "$name" != "$memory_ref" ]; then
      rm -rf -- "$old"
    fi
  done
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
fi

echo "bootstrap завершён"
