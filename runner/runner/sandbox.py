"""Bubblewrap mounts and syscall restrictions for untrusted skill commands."""

import os
import platform
import struct

SYSTEM_FILES = ("passwd", "group", "nsswitch.conf", "hosts", "resolv.conf", "ld.so.cache")
SYSTEM_DIRS = ("/usr", "/lib", "/lib64", "/bin", "/sbin")


def _seccomp_fd():
    calls = {"x86_64": (41, 53, 425), "aarch64": (198, 199, 425),
             "i386": (359, 360, 102, 425)}
    # socket, socketpair, io_uring_setup; socketcall is covered on 32-bit x86.
    nodes = {"x86_64": ((133, 1), (259, 2)), "aarch64": ((33, 2),),
             "i386": ((14, 1), (297, 2))}
    machine = platform.machine()
    denied = calls.get(machine)
    if denied is None:
        raise OSError("unsupported seccomp architecture")
    audit_arch = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7,
                  "i386": 0x40000003}[machine]
    instructions = [struct.pack("HBBI", 0x20, 0, 0, 4),
                    struct.pack("HBBI", 0x15, 1, 0, audit_arch),
                    struct.pack("HBBI", 0x06, 0, 0, 0x80000000),
                    struct.pack("HBBI", 0x20, 0, 0, 0)]
    if machine == "x86_64":
        instructions.extend((struct.pack("HBBI", 0x45, 0, 1, 0x40000000),
                             struct.pack("HBBI", 0x06, 0, 0, 0x00050001)))
    # Emit one compare/deny pair per blocked syscall, then allow everything else.
    for nr in denied:
        instructions.extend((struct.pack("HBBI", 0x15, 0, 1, nr),
                             struct.pack("HBBI", 0x06, 0, 0, 0x00050001)))
    # Permit private FIFOs, which the artifact collector rejects. Device nodes
    # remain denied. A blanket EPERM would hide a FIFO attempt from collection.
    for nr, mode_arg in nodes[machine]:
        instructions.extend((struct.pack("HBBI", 0x15, 0, 5, nr),
                             struct.pack("HBBI", 0x20, 0, 0, 16 + 8 * mode_arg),
                             struct.pack("HBBI", 0x54, 0, 0, 0o170000),
                             struct.pack("HBBI", 0x15, 1, 0, 0o010000),
                             struct.pack("HBBI", 0x06, 0, 0, 0x00050001),
                             struct.pack("HBBI", 0x06, 0, 0, 0x7FFF0000)))
    instructions.append(struct.pack("HBBI", 0x06, 0, 0, 0x7FFF0000))
    fd = os.memfd_create("runner-seccomp", 0)
    os.write(fd, b"".join(instructions))
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def sandbox_args(worktree, projected_fd):
    fd = os.dup(projected_fd)
    try:
        filter_fd = _seccomp_fd()
    except OSError:
        os.close(fd)
        raise
    args = []
    for path in SYSTEM_DIRS:
        if os.path.exists(path):
            args.extend(("--ro-bind", path, path))
    args.extend(("--dir", "/etc", "--dir", "/etc/ssl", "--dir", "/etc/ca-certificates"))
    for name in SYSTEM_FILES:
        path = f"/etc/{name}"
        if os.path.exists(path):
            args.extend(("--ro-bind-try", path, path))
    for path in ("/etc/ssl/certs", "/etc/ca-certificates"):
        if os.path.exists(path):
            args.extend(("--ro-bind-try", path, path))
    args.extend(("--chmod", "0555", "/etc"))
    args.extend(("--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                 "--tmpfs", "/home", "--dir", "/home/runner", "--tmpfs", "/run",
                 "--bind-fd", str(fd), str(worktree)))
    # bwrap consumes/closes --bind-fd, unlike a /proc/self/fd pathname bind.
    # All sockets are denied by seccomp; avoid bwrap's NETLINK_ROUTE setup,
    # which fails under hosts that already prohibit socket creation.
    args.extend(("--seccomp", str(filter_fd), "--unshare-ipc", "--unshare-pid",
                 "--new-session", "--die-with-parent", "--cap-drop", "ALL"))
    return args, (fd, filter_fd)
