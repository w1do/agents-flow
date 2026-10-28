# Deployment and local Compose stacks

| Compose file | Purpose |
|---|---|
| `../docker-compose.yml` | Dokploy application: `migrate`, `server`, `console` |
| `../deploy/db/docker-compose.yml` | PostgreSQL deployment stack |
| `../docker-compose.local.yml` | Local PostgreSQL and private application network |

## Secret files

Compose mounts secrets read-only under `/run/secrets`; secret values are not set in
container environment variables. File-backed Compose secrets use host file
permissions, so provision the directory as mode `0750` and each secret file as
mode `0440`, owned by a trusted deployment account and the group configured by
`SECRETS_GID`. The unprivileged app UID (10001) joins that group to read its
secrets. PostgreSQL runs as UID/GID 70 and joins the same group so it can read
`postgres_password` from the host bind-mounted secret. Set `SECRETS_GID` to the
actual owning GID of the secret files (the example uses 1000). For a different
GID, set the file group and keep it group-readable, for example:

```bash
sudo chgrp "$SECRETS_GID" .secrets/postgres_password
sudo chmod 0440 .secrets/postgres_password
```

This supplementary group grants read access to the mounted file without running
PostgreSQL as root or adding capabilities.

| File | Used by |
|---|---|
| `database_url` | migrate, server, console |
| `postgres_password` | PostgreSQL only |
| `jwt_secret` | server and console (the console imports shared database settings) |
| `admin_password` | server and console |
| `telegram_bot_token`, `telegram_webhook_secret` | server |
| `transcription_api_key`, `openai_api_key` | server |

The optional provider files can be empty when unused. Use a URL-safe PostgreSQL
password and put the matching credentials in `database_url`. For example, the
local URL is `postgresql+psycopg://agents_flow:<password>@db:5432/agents_flow`;
Dokploy uses `agents-flow-db` as the database host. Generate `jwt_secret` with at
least 32 random bytes and use an admin password of at least 12 characters (at most
72 UTF-8 bytes for bcrypt). Keep `.secrets/` mode `0750` and each file mode `0440`.
By default, `.secrets/` is resolved from the repository root; set `SECRETS_DIR` to
an absolute path if you keep files elsewhere. `.env` contains only non-secret
Compose settings; copy `.env.example` if needed.

## Local launch

After provisioning `.secrets/` as above, run from the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

The local override gives the application network internet egress while the database network has none.
The panel is at `http://localhost:8000`; health check is
`/healthz`. Stop and remove the local database volume with:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down -v
```

## Dokploy deployment

Create the external `dokploy-network` as part of Dokploy setup. Deploy the database
stack first, then the root application stack. The database Compose file creates
`agents-flow-database-private` with `internal: true`; the application joins it and
`dokploy-network`, while PostgreSQL joins only the private database network. The
database port is not published. The root application stack has no database service,
so it cannot start a second PostgreSQL instance.

When using the checked-out Compose files, start the DB stack from the repository
root with `docker compose --env-file .env -p agents-flow-db -f deploy/db/docker-compose.yml up -d`,
then deploy the root `docker-compose.yml` as the application stack. Configure the
same `agents-flow-database-private` network name in both stacks.

The `migrate` service receives only the `database_url` secret. The server receives
the database URL plus its runtime secrets. `TRUSTED_PROXY_IPS` is a JSON list of
proxy IPs/CIDRs; forwarded client addresses and `X-Forwarded-Proto` are used only
when the direct peer is inside that allowlist. Configure the proxy to replace or
append `X-Forwarded-For`.

Set non-secret settings in `.env` or Dokploy Environment. The app port binds to
loopback by default for a host reverse proxy; Dokploy can set
`SERVER_BIND_ADDRESS=0.0.0.0` when its proxy connects over the Docker network.
`POSTGRES_VOLUME_NAME` must remain stable across database deployments.

## Console

```bash
docker compose run --rm console --help
docker compose run --rm console create-admin
docker compose run --rm console create-project "Demo" --description "First project"
docker compose run --rm console create-category "SEO" --description "Search optimization"
docker compose run --rm console seed-skills
```

The console is in the `tools` profile and does not start with the server. It reads
`admin_password` from a secret file; if that file is empty, `create-admin` prompts
for a hidden password only in an interactive terminal. Existing admin passwords
are not changed. Commands do not create tables; run migrations first.

The PostgreSQL services run as the official Alpine image's `postgres` UID/GID (70)
with all Linux capabilities dropped. Their supplementary `SECRETS_GID` lets the
entrypoint read the host-mounted password file. The data directory is owned by
UID/GID 70, so the image entrypoint can initialize the volume and run without root.

For a host Python install from `server/`, use `pip install '.[dev]'` to include test dependencies;
the Docker runtime installs only project dependencies. `python -m app.console
--help` can run before database configuration.

## Runner worktree mount policy

The worktree must contain **no nested mount points**, including bind mounts on the
same filesystem. Mount deployment secrets outside the worktree. Run the runner
without privileges to create or change mounts, and keep `/proc/self/mountinfo`
readable in its mount namespace. The runner checks both `st_dev` and known nested
mount points; a matching path is rejected with `mount_crossing`. These checks do
not protect against a privileged process changing mounts concurrently.
