"""Offline smoke: real subprocesses, a temporary Git repository and task worktree."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def smoke():
    with tempfile.TemporaryDirectory(prefix="agents-flow-smoke-") as temporary:
        root = Path(temporary)
        project, worktree = root / "project", root / "task-worktree"
        project.mkdir()
        env = {"PATH": os.defpath, "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1",
               "AGENT_PROVIDER": "stub"}

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], env=env, text=True,
                                  capture_output=True, check=True).stdout.strip()

        git("init", "--quiet")
        git("-c", "user.name=Runner smoke", "-c", "user.email=runner@example.invalid",
            "commit", "--quiet", "--allow-empty", "-m", "Temporary smoke fixture")
        original = git("rev-parse", "HEAD")
        git("worktree", "add", "--quiet", "-b", "task/smoke", str(worktree))
        request = {
            "task": {"id": "smoke", "title": "Offline smoke"},
            "path": str(worktree), "worktree": str(worktree), "branch": "task/smoke",
            "checkpoint": None, "skills": [],
        }
        for stage in ("planning", "implementation", "testing"):
            request.update(stage=stage, read_only=stage == "planning")
            if stage == "testing":
                request["skills"] = [{"category": "testing", "filename": "testing--smoke.md",
                                      "content": "```sh\ntest -s runner-stub.txt\n```"}]
            outcome = subprocess.run([sys.executable, "-m", "runner"], cwd=worktree,
                                     input=json.dumps(request), text=True, capture_output=True, env=env)
            print(outcome.stdout, end="", flush=True)
            if outcome.returncode != 0:
                raise SystemExit(outcome.returncode)
            events = [json.loads(line) for line in outcome.stdout.splitlines()]
            terminal = events[-1]
            assert terminal["type"] == ("plan" if stage == "planning" else "result")
            for event in events:
                if "checkpoint" in event:
                    request["checkpoint"] = event["checkpoint"]
            if stage == "planning":
                request["plan_text"] = terminal["plan_text"]
                assert not (worktree / "runner-stub.txt").exists()
            else:
                request["result_data"] = terminal["result_data"]
        assert (worktree / "runner-stub.txt").read_text() == "Agents Flow stub implementation.\n"
        assert not (project / "runner-stub.txt").exists()
        assert git("rev-parse", "HEAD") == original
        assert git("status", "--porcelain") == ""


if __name__ == "__main__":
    smoke()
