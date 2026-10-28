"""Combine isolated checks with host Git facts and publication outcomes."""

from .git_commit import commit
from .git_facts import GitError, GitFacts
from .git_process import CommitIntegrityError
from .errors import RunnerError
from .checks import run_checks
from .redaction import safe_path


def finish_checks(request, events):
    data = dict(request.data.get("result_data") or {})
    publication = request.stage == "publication"
    for field in ("verification", "claims", "changed_paths", "base_sha", "code", "no_changes", "degradations"):
        data.pop(field, None)
    data.update(commit_sha=None, commit_subject=None)
    data.update(checks_run=0, checks_passed=False)
    facts = None
    try:
        facts = GitFacts(request)
        data.update(base_sha=facts.base, changed_paths=facts.changed_paths())
        data.update(run_checks(request, events))
        data["changed_paths"] = facts.changed_paths()
        success = data["checks_passed"] and (not publication or data["checks_run"] > 0)
        if publication and success:
            data.update(commit(request, facts))
            if facts.finalization.snapshot is not None:
                success = facts.finalization.snapshot.success
        else:
            data["verification"] = facts.verification()
    except GitError as error:
        data["code"] = str(error)
        data["changed_paths"] = [safe_path(path) for path in data.get("changed_paths", [])]
        if facts is not None:
            try:
                data["verification"] = facts.verification()
            except GitError:
                pass
            data = facts.finalization.result(data, facts)
        if not publication or isinstance(error, CommitIntegrityError):
            events.emit("failure", message=str(error), result_data=data, checkpoint=events.checkpoint)
            raise
        success = False
    except RunnerError as error:
        data["changed_paths"] = [safe_path(path) for path in data.get("changed_paths", [])]
        if facts is not None:
            data["verification"] = facts.verification()
        events.emit("failure", message=str(error), result_data=data, checkpoint=events.checkpoint)
        raise
    data["changed_paths"] = [safe_path(path) for path in data.get("changed_paths", [])]
    if publication:
        events.emit("result", success=success,
                    message="Publication commands passed" if success else data.get("code", "Publication did not succeed"),
                    result_data=data)
    elif not success:
        events.emit("failure", message="Skill verification failed", result_data=data, checkpoint=events.checkpoint)
        raise RunnerError("Skill verification failed")
    else:
        summary = "Checks passed" if data["checks_run"] else "No check commands supplied"
        events.emit("result", result_summary=summary, result_data=data)
