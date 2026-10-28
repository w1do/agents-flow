package cli

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"agentsflow/harness/internal/bootstrap"
)

func initialize(ctx context.Context, args []string, env Environment) error {
	flags := flag.NewFlagSet("init", flag.ContinueOnError)
	flags.SetOutput(env.Output)
	server := flags.String("server-url", env.Getenv("AGENTS_FLOW_SERVER_URL"), "server HTTP(S) URL")
	allowInsecure := flags.Bool("allow-insecure", false, "allow HTTP to non-loopback server (unsafe)")
	name, _ := os.Hostname()
	if name == "" {
		name = "harness"
	}
	agentName := flags.String("agent-name", name, "agent display name")
	// Accept both init <id> --flags and init --flags <id>.
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		args = append(append([]string{}, args[1:]...), args[0])
	}
	if err := flags.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return errors.New("invalid init options; use harness init -h")
	}
	if flags.NArg() != 1 {
		return errors.New("init requires exactly one project_id")
	}
	if *server == "" {
		return errors.New("set --server-url or AGENTS_FLOW_SERVER_URL")
	}
	err := bootstrap.InitWithInsecure(ctx, bootstrap.Options{
		Directory: env.Directory, ServerURL: *server, ProjectID: flags.Arg(0), AgentName: *agentName,
		ReadCode: func() (string, error) {
			if value := env.Getenv("AGENTS_FLOW_INIT_TOKEN"); value != "" {
				return value, nil
			}
			if _, err := fmt.Fprint(env.Output, "Init code: "); err != nil {
				return "", err
			}
			value, err := bufio.NewReader(env.Input).ReadString('\n')
			if errors.Is(err, io.EOF) && value != "" {
				err = nil
			}
			return value, err
		},
	}, *allowInsecure)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(env.Output, "Initialized workflow/.")
	return err
}
