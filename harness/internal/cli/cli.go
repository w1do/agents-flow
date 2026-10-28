package cli

import (
	"context"
	"errors"
	"fmt"
	"io"

	"agentsflow/harness/internal/agent"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/gitrepo"
)

type Environment struct {
	Directory string
	Input     io.Reader
	Output    io.Writer
	Getenv    func(string) string
}

const usage = `Usage:
  harness init <project_id> --server-url <URL> [--agent-name <name>]
  harness run

Server URL can also be set with AGENTS_FLOW_SERVER_URL.
Init code is read from AGENTS_FLOW_INIT_TOKEN or stdin.
`

func Execute(ctx context.Context, args []string, env Environment) error {
	if len(args) == 0 {
		return errors.New("expected init or run; use harness -h for help")
	}
	switch args[0] {
	case "-h", "--help", "help":
		_, err := fmt.Fprint(env.Output, usage)
		return err
	case "init":
		return initialize(ctx, args[1:], env)
	case "run":
		if len(args) == 2 && (args[1] == "-h" || args[1] == "--help") {
			_, err := fmt.Fprintln(env.Output, "Usage: harness run")
			return err
		}
		if len(args) != 1 {
			return errors.New("run takes no arguments")
		}
		root, err := gitrepo.Root(ctx, env.Directory)
		if err != nil {
			return err
		}
		cfg, token, err := config.Load(root)
		if err != nil {
			return err
		}
		return agent.Run(ctx, cfg, token)
	default:
		return errors.New("unknown command; expected init or run")
	}
}
