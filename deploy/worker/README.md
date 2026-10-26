# Host worker

The worker is a systemd **user** service running on the host, not in the application Compose stack. Artifact review and local verification do not mean the unit has been installed, enabled, started, or that a database has been deployed.

## Requirements and configuration

Run it as the same non-root account (and same `HOME`) used for `agent init`. Install the server package and `harness-server` executable for that account, in a trusted executable path. The unit includes `%h/.local/bin`, `/usr/local/bin`, `/usr/bin`, and `/bin`; use a unit override for another trusted install path. No checkout path is assumed.

Create `%h/.config/agents-flow` with mode `0700` and `worker.env` with mode `0600`; keep both outside the repository. Set required worker values (placeholders only):

```dotenv
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/DBNAME
HARNESS_CONFIG=/absolute/host/path/to/harness.yaml
HARNESS_SECRET_KEY=<secret>
TELEGRAM_BOT_TOKEN=<secret>
TELEGRAM_CHAT_ID=<chat-id>
TELEGRAM_WEBHOOK_SECRET=<secret>
HARNESS_PUBLIC_URL=https://harness.example.invalid
```

`HARNESS_CONFIG` is an absolute host path readable by this user, not a container path such as `/app/...`. Keep the server’s `DATABASE_URL` on its Compose network; the host worker uses loopback `127.0.0.1:5432`. `HARNESS_PUBLIC_URL` is the externally reachable HTTPS server URL. Add applicable optional settings as needed. Never commit real values or this env file.

## Manual systemd user lifecycle

Copy this unit to `%h/.config/systemd/user/agents-flow-worker.service`, then run `systemctl --user daemon-reload`. The operator may manage it with `systemctl --user start|status|restart|stop|enable|disable agents-flow-worker.service`; logs: `journalctl --user -u agents-flow-worker.service`. Enable lingering through the system administrator only if it must run without an interactive login.

`KillMode=process` deliberately leaves detached agent tasks running when the worker stops or restarts. Stopping the unit is **not** task cancellation. Cancel via the project’s verified task-cancellation/operator interface or task-specific runbook; do not kill arbitrary processes. No service lifecycle or database deployment is performed by documenting this artifact.
