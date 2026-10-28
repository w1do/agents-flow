package gitrepo

import (
	"context"
	"os"
	"os/exec"
)

// command drops inherited Git overrides and disables host execution paths.
func command(ctx context.Context, dir string, options []string, args ...string) *exec.Cmd {
	return configuredCommand(ctx, dir, options, false, false, args...)
}

func configuredCommand(ctx context.Context, dir string, options []string, discover, localClone bool, args ...string) *exec.Cmd {
	argv := append([]string{"-C", dir}, options...)
	for _, setting := range []string{
		"core.hooksPath=/dev/null", "core.fsmonitor=false", "core.attributesFile=/dev/null",
		"core.excludesFile=/dev/null", "status.showUntrackedFiles=all",
		"log.showSignature=false", "commit.gpgSign=false", "core.autocrlf=false",
		"core.safecrlf=false", "gpg.program=/bin/false", "gpg.ssh.program=/bin/false",
		"diff.external=", "submodule.recurse=false", "core.sshCommand=/bin/false",
		"core.pager=cat", "credential.helper=", "core.askPass=/bin/false",
		"protocol.allow=never", "protocol.ssh.allow=never", "protocol.git.allow=never",
		"protocol.http.allow=never", "protocol.https.allow=never", "protocol.ftp.allow=never",
		"protocol.ftps.allow=never", "protocol.file.allow=never", "protocol.ext.allow=never",
		"protocol.sftp.allow=never", "protocol.rsync.allow=never",
	} {
		argv = append(argv, "-c", setting)
	}
	if localClone {
		argv = append(argv, "-c", "protocol.file.allow=always")
	}
	cmd := exec.CommandContext(ctx, "git", append(argv, args...)...)
	names := []string{"PATH", "LANG", "TZ"}
	if discover {
		names = append(names, "HOME", "XDG_CONFIG_HOME")
	}
	for _, name := range names {
		if value, ok := os.LookupEnv(name); ok {
			cmd.Env = append(cmd.Env, name+"="+value)
		}
	}
	if !discover {
		cmd.Env = append(cmd.Env,
			"GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_SYSTEM=/dev/null")
	}
	cmd.Env = append(cmd.Env,
		"GIT_NO_LAZY_FETCH=1", "GIT_TERMINAL_PROMPT=0", "GIT_ASKPASS=/bin/true",
		"GIT_PAGER=cat", "GIT_LITERAL_PATHSPECS=1",
	)
	// A whitelist overrides individual protocol opt-ins, including custom helpers.
	allowedProtocols := ""
	if localClone {
		allowedProtocols = "file"
	}
	cmd.Env = append(cmd.Env, "GIT_ALLOW_PROTOCOL="+allowedProtocols)
	return cmd
}
