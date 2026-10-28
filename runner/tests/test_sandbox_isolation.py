import ctypes
import errno
import os

import pytest

from runner.sandbox import sandbox_args
from runner.sandbox_paths import private_directory
from test_checks import execute


def test_mount_fd_is_consumed_and_ipc_namespace_is_required(tmp_path):
    with private_directory() as fd:
        args, fds = sandbox_args(tmp_path, fd)
        try:
            assert args[args.index("--bind-fd") + 1] == str(fds[0])
            assert "--unshare-ipc" in args
            # Socket-denying seccomp must work even where NETLINK_ROUTE is denied.
            assert "--unshare-net" not in args
        finally:
            for inherited in fds:
                os.close(inherited)


@pytest.mark.usefixtures("requires_bwrap")
def test_command_inherits_no_host_descriptors_or_openat_escape(tmp_path):
    marker = tmp_path.parent / ".env.host-fd-proof"
    marker.write_text("host-only-control")
    unrelated = os.open(marker, os.O_RDONLY)
    try:
        command = """import os, stat
leaked = []
for name in os.listdir('/proc/self/fd'):
    fd = int(name)
    if fd < 3:
        continue
    try:
        info = os.fstat(fd)
    except OSError:
        continue
    leaked.append(fd)
    if stat.S_ISDIR(info.st_mode):
        parent = os.open('..', os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
        os.close(parent)
assert not leaked, leaked
"""
        _, events = execute(tmp_path, "python3", command)
        assert events[0]["exit_code"] == 0
        assert marker.read_text() == "host-only-control"
    finally:
        os.close(unrelated)
        marker.unlink()


@pytest.mark.usefixtures("requires_bwrap")
def test_command_cannot_attach_same_uid_host_sysv_shared_memory(tmp_path):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.shmat.restype = ctypes.c_void_p
    libc.shmdt.argtypes = [ctypes.c_void_p]
    shmid = libc.shmget(0, 4096, 0o1000 | 0o600)
    assert shmid >= 0
    address = libc.shmat(shmid, None, 0)
    assert address != ctypes.c_void_p(-1).value
    try:
        ctypes.memmove(address, b"host-shared-memory-control\0", 27)
        command = ("import ctypes\nlibc = ctypes.CDLL(None, use_errno=True)\n"
                   "libc.shmat.restype = ctypes.c_void_p\n"
                   f"address = libc.shmat({shmid}, None, 0)\n"
                   "assert address == ctypes.c_void_p(-1).value\n")
        _, events = execute(tmp_path, "python3", command)
        assert events[0]["exit_code"] == 0
        assert ctypes.string_at(address) == b"host-shared-memory-control"
    finally:
        libc.shmdt(address)
        libc.shmctl(shmid, 0, None)


@pytest.mark.usefixtures("requires_bwrap")
def test_all_socket_families_socketpair_and_io_uring_are_denied(tmp_path):
    command = f"""import ctypes, errno, socket
for family in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX, socket.AF_NETLINK):
    try:
        socket.socket(family, socket.SOCK_DGRAM)
    except OSError as exc:
        assert exc.errno == {errno.EPERM}
    else:
        raise AssertionError('socket allowed')
try:
    socket.socketpair()
except OSError as exc:
    assert exc.errno == errno.EPERM
else:
    raise AssertionError('socketpair allowed')
libc = ctypes.CDLL(None, use_errno=True)
assert libc.syscall(425, 1, 0) == -1
assert ctypes.get_errno() == errno.EPERM
"""
    _, events = execute(tmp_path, "python3", command)
    assert events[0]["exit_code"] == 0
