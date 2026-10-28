"""One stdin request, one stage, one terminal event."""

import argparse
import sys

from .config import Config
from .errors import RunnerError
from .protocol import Events, Request


def main(argv=None, stdin=None, stdout=None):
    parser = argparse.ArgumentParser(description="Agents Flow JSON stdin / NDJSON stdout stage runner")
    parser.parse_args(argv)
    events = Events(sys.stdout if stdout is None else stdout)
    try:
        config = Config.from_env()
        request = Request.read(sys.stdin if stdin is None else stdin)
        events.checkpoint = request.data.get("checkpoint")
        if config.provider == "stub":
            from .stub import run
            run(request, events)
        else:
            from .deepagents import run
            run(request, events, config)
        return 0
    except Exception as error:
        message = str(error) if isinstance(error, RunnerError) else "Runner could not complete the stage"
        if not events.terminal:
            try:
                events.emit("failure", message=message, checkpoint=events.checkpoint)
            except RunnerError:
                # Harness already holds the input checkpoint if it cannot fit a new event.
                events.emit("failure", message=message)
        return 1
