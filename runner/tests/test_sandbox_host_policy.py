import subprocess
import sys

import pytest


@pytest.mark.usefixtures("requires_bwrap")
def test_sandbox_starts_under_inherited_socket_denying_seccomp(tmp_path):
    # Reproduce reviewers' NETLINK_ROUTE failure without weakening socket rules.
    script = """import ctypes, io, os, sys
from types import SimpleNamespace
from runner.checks import run_checks
from runner.protocol import Events
from runner.sandbox import _seccomp_fd
from runner.workspace import Workspace

class Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('instructions', ctypes.c_void_p)]

fd = _seccomp_fd()
raw = os.read(fd, 65536)
os.close(fd)
buffer = ctypes.create_string_buffer(raw)
program = Program(len(raw) // 8, ctypes.cast(buffer, ctypes.c_void_p))
libc = ctypes.CDLL(None, use_errno=True)
assert libc.prctl(38, 1, 0, 0, 0) == 0
assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
workspace = Workspace(sys.argv[1])
request = SimpleNamespace(workspace=workspace, data={}, stage='testing',
    skills=[{'content': '```sh\\nprintf ok >proof\\n```'}])
try:
    assert run_checks(request, Events(io.StringIO()))['checks_passed']
finally:
    workspace.close()
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "proof").read_text() == "ok"
