"""Refresh all config scopes before executing any repository operation."""
SETTINGS = (
    "core.attributesFile=/dev/null", "core.excludesFile=/dev/null", "status.showUntrackedFiles=all",
    "core.autocrlf=false", "core.safecrlf=false", "core.fsmonitor=false", "core.hooksPath=/dev/null",
    "commit.gpgSign=false", "core.abbrev=40", "log.showSignature=false", "gpg.program=/bin/false",
    "gpg.ssh.program=/bin/false", "diff.external=", "submodule.recurse=false",
    "diff.ignoreSubmodules=all", "core.sshCommand=/bin/false", "core.pager=cat",
    "credential.helper=", "core.askPass=/bin/false",
    "protocol.allow=never", "protocol.ssh.allow=never", "protocol.git.allow=never",
    "protocol.http.allow=never", "protocol.https.allow=never", "protocol.ftp.allow=never",
    "protocol.ftps.allow=never", "protocol.file.allow=never", "protocol.ext.allow=never",
    "protocol.sftp.allow=never", "protocol.rsync.allow=never",
)


def entries(raw):
    # With --null --show-origin Git emits origin NUL key LF value NUL.
    fields = raw.decode("utf-8").split("\0")
    return [(field.partition("\n")[0], field.partition("\n")[2] if "\n" in field else "true")
            for field in fields[1::2] if field]


def safety_options(process):
    args = ("--list", "--show-origin", "--includes", "--null")
    config = entries(process._invoke("config", *args, discovery=True).stdout)
    if any(key.lower() == "extensions.worktreeconfig" and value.lower() in {"true", "yes", "on", "1"}
           for key, value in config):
        config += entries(process._invoke("config", "--worktree", *args, discovery=True).stdout)
    settings = set()
    for key, *_ in config:
        lower = key.lower()
        # include.path only contributes discovered keys, never a safety override.
        if lower.startswith("filter."):
            driver = key.rsplit(".", 1)[0]
            settings.update(driver + "." + setting for setting in
                            ("clean=cat", "smudge=cat", "process=", "required=false"))
        if lower.startswith("diff.") and lower.endswith((".command", ".textconv")):
            settings.add(key + "=")
    return [arg for setting in sorted(settings) for arg in ("-c", setting)]
