"""Dummy shell for the emulated RTTY terminal.

The controller's Tools → Terminal opens a remote shell on the device. A real
device runs a BusyBox/ash shell; this emulator provides a minimal fake shell
that recognises a handful of common diagnostic commands and echoes a prompt
for anything else, so the operator gets a believable terminal experience in
the controller UI without a real OS shell.

The shell is purely in-memory and per-session: each terminal session (``sid``)
gets its own ``DummyShell`` instance with an independent working directory and
command history. Output is returned as bytes so the caller can send it back
over the RTTY TERMDATA channel.
"""
from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass, field


@dataclass
class DummyShell:
    """A minimal fake POSIX-ish shell for one terminal session."""

    device_name: str = ""
    device_type: str = ""
    cwd: str = "/"
    history: list[str] = field(default_factory=list)
    # Buffer for the current input line (keystrokes accumulate until Enter).
    _line_buf: str = field(default="", repr=False)

    # -- prompt ----------------------------------------------------------
    def prompt(self) -> bytes:
        """Return the prompt string as bytes (sent after each command)."""
        # Switch-style prompt (the controller sends PS1="\w#" for switches).
        return f"{self.cwd}# ".encode("utf-8")

    # -- main entry: feed keystrokes, get output -------------------------
    def feed(self, keystroke: bytes) -> bytes:
        """Feed raw keystroke bytes from the operator; return shell output.

        This mimics a line-buffered terminal: printable characters accumulate
        in ``_line_buf``; ``\\r`` (Enter) executes the line and produces the
        command output + the next prompt. ``\\b`` (Ctrl-H / backspace) removes
        the last char. Other control characters are ignored.
        """
        out = b""
        for byte in keystroke:
            ch = bytes([byte])
            if byte == 0x0D:  # \r — Enter
                out += b"\r\n"
                out += self._execute_line(self._line_buf)
                self._line_buf = ""
                out += self.prompt()
            elif byte == 0x08 or byte == 0x7F:  # backspace / DEL
                if self._line_buf:
                    self._line_buf = self._line_buf[:-1]
                    out += b"\b \b"  # erase char on terminal
            elif byte == 0x03:  # Ctrl-C
                out += b"^C\r\n"
                self._line_buf = ""
                out += self.prompt()
            elif byte == 0x04:  # Ctrl-D
                out += b"\r\nlogout\r\n"
            elif 0x20 <= byte < 0x7F:  # printable ASCII
                self._line_buf += ch.decode("ascii")
                out += ch  # echo
            # else: ignore other control bytes
        return out

    # -- command execution ----------------------------------------------
    def _execute_line(self, line: str) -> bytes:
        line = line.strip()
        if not line:
            return b""
        self.history.append(line)
        parts = line.split()
        cmd = parts[0]
        args = parts[1:]
        try:
            handler = getattr(self, f"_cmd_{cmd.replace('-', '_')}", None)
            if handler is not None:
                return handler(args)
            return self._cmd_unknown(cmd, args)
        except Exception as exc:  # noqa: BLE001
            return f"{cmd}: {exc}\r\n".encode("utf-8")

    # -- built-in commands ----------------------------------------------
    def _cmd_unknown(self, cmd: str, args: list[str]) -> bytes:
        return (
            f"-sh: {cmd}: not found\r\n".encode("utf-8")
        )

    def _cmd_help(self, args: list[str]) -> bytes:
        msg = (
            "Device emulator dummy shell — available commands:\r\n"
            "  help, ls, pwd, cd, cat, echo, uname, uptime, df, free,\r\n"
            "  ip, ifconfig, ps, date, whoami, id, env, history, clear, exit\r\n"
        )
        return msg.encode("utf-8")

    def _cmd_ls(self, args: list[str]) -> bytes:
        path = args[0] if args else self.cwd
        # Fake a minimal filesystem
        entries = {
            "/": ["bin", "dev", "etc", "proc", "tmp", "usr", "var", "home", "lib"],
            "/etc": ["hostname", "hosts", "passwd", "shadow", "version"],
            "/proc": ["cpuinfo", "meminfo", "version", "uptime"],
            "/tmp": [],
            "/var": ["log", "run"],
            "/var/log": ["messages", "syslog", "dmesg"],
        }
        listing = entries.get(path.rstrip("/") or "/", [])
        if not listing and (path.rstrip("/") or "/") not in entries:
            return f"ls: {path}: No such file or directory\r\n".encode("utf-8")
        return ("  ".join(listing) + "\r\n").encode("utf-8") if listing else b""

    def _cmd_pwd(self, args: list[str]) -> bytes:
        return (self.cwd + "\r\n").encode("utf-8")

    def _cmd_cd(self, args: list[str]) -> bytes:
        target = args[0] if args else "/"
        if target.startswith("/"):
            new = target
        else:
            new = os.path.normpath(os.path.join(self.cwd, target))
        # Only allow the fake dirs
        valid = {"/", "/etc", "/proc", "/tmp", "/var", "/var/log", "/usr", "/home"}
        if new.rstrip("/") in valid or new == "/":
            self.cwd = new.rstrip("/") or "/"
            return b""
        return f"-sh: cd: {target}: No such file or directory\r\n".encode("utf-8")

    def _cmd_cat(self, args: list[str]) -> bytes:
        if not args:
            return b""
        path = args[0]
        files = {
            "/etc/hostname": f"{self.device_name}\n",
            "/etc/version": f"Device emulator {self.device_type} v1.0.0\n",
            "/proc/cpuinfo": (
                "processor\t: 0\nmodel name\t: MIPS interAptiv\n"
                "BogoMIPS\t: 580.00\n"
            ),
            "/proc/meminfo": (
                "MemTotal:         262144 kB\n"
                "MemFree:          131072 kB\n"
            ),
            "/proc/uptime": f"{time.time():.2f} 580.00\n",
        }
        content = files.get(path)
        if content is None:
            return f"cat: {path}: No such file or directory\r\n".encode("utf-8")
        return content.replace("\n", "\r\n").encode("utf-8")

    def _cmd_echo(self, args: list[str]) -> bytes:
        return (" ".join(args) + "\r\n").encode("utf-8")

    def _cmd_uname(self, args: list[str]) -> bytes:
        if "-a" in args:
            return (
                f"Linux {self.device_name} 4.19.95 #1 SMP "
                f"{platform.machine()} GNU/Linux\r\n"
            ).encode("utf-8")
        return b"Linux\r\n"

    def _cmd_uptime(self, args: list[str]) -> bytes:
        secs = int(time.time())
        return (
            f"  {time.strftime('%H:%M:%S')} up {secs // 3600}h, "
            f"load average: 0.08, 0.04, 0.01\r\n"
        ).encode("utf-8")

    def _cmd_df(self, args: list[str]) -> bytes:
        return (
            "Filesystem           1K-blocks      Used Available Use% Mounted on\r\n"
            "/dev/root                16384      4096     12288  25% /\r\n"
            "tmpfs                    65536         0     65536   0% /tmp\r\n"
        ).encode("utf-8")

    def _cmd_free(self, args: list[str]) -> bytes:
        return (
            "              total       used       free     shared    buffers\r\n"
            "Mem:         262144      131072     131072          0      16384\r\n"
            "Swap:             0          0          0\r\n"
        ).encode("utf-8")

    def _cmd_ip(self, args: list[str]) -> bytes:
        if args and args[0] == "addr":
            return (
                "1: lo: <LOOPBACK,UP> mtu 65536\r\n"
                "    inet 127.0.0.1/8 scope host lo\r\n"
                "2: eth0: <BROADCAST,MULTICAST,UP> mtu 1500\r\n"
                "    inet 192.168.1.1/24 brd 192.168.1.255 scope global eth0\r\n"
            ).encode("utf-8")
        if args and args[0] == "route":
            return (
                "default via 192.168.1.254 dev eth0\r\n"
                "192.168.1.0/24 dev eth0  proto kernel\r\n"
            ).encode("utf-8")
        return b"Usage: ip [addr|route]\r\n"

    def _cmd_ifconfig(self, args: list[str]) -> bytes:
        return (
            "eth0      Link encap:Ethernet  HWaddr AA:BB:CC:DD:EE:FF\r\n"
            "          inet addr:192.168.1.1  Bcast:192.168.1.255  Mask:255.255.255.0\r\n"
            "          UP BROADCAST RUNNING MULTICAST  MTU:1500\r\n\r\n"
            "lo        Link encap:Local Loopback\r\n"
            "          inet addr:127.0.0.1  Mask:255.0.0.0\r\n"
            "          UP LOOPBACK RUNNING  MTU:65536\r\n"
        ).encode("utf-8")

    def _cmd_ps(self, args: list[str]) -> bytes:
        return (
            "  PID USER       VSZ STAT COMMAND\r\n"
            "    1 root      1500 S    /sbin/init\r\n"
            "   42 root      2800 S    /usr/sbin/rtty\r\n"
            "  100 root      1200 R    ps\r\n"
        ).encode("utf-8")

    def _cmd_date(self, args: list[str]) -> bytes:
        return (time.strftime("%a %b %d %H:%M:%S UTC %Y\r\n")).encode("utf-8")

    def _cmd_whoami(self, args: list[str]) -> bytes:
        return b"root\r\n"

    def _cmd_id(self, args: list[str]) -> bytes:
        return b"uid=0(root) gid=0(root) groups=0(root)\r\n"

    def _cmd_env(self, args: list[str]) -> bytes:
        return (
            f"USER=root\r\n"
            f"HOME=/root\r\n"
            f"PS1=\\w# \r\n"
            f"PATH=/usr/bin:/bin:/usr/sbin:/sbin\r\n"
            f"DEVICE={self.device_name}\r\n"
        ).encode("utf-8")

    def _cmd_history(self, args: list[str]) -> bytes:
        out = b""
        for i, cmd in enumerate(self.history, 1):
            out += f"  {i:3d}  {cmd}\r\n".encode("utf-8")
        return out

    def _cmd_clear(self, args: list[str]) -> bytes:
        return b"\x1b[2J\x1b[H"

    def _cmd_exit(self, args: list[str]) -> bytes:
        return b"logout\r\n"

    def _cmd_reboot(self, args: list[str]) -> bytes:
        return b"Rebooting...\r\n"

    def _cmd_version(self, args: list[str]) -> bytes:
        return (
            f"Device emulator dummy shell v1.0.0\r\n"
            f"device={self.device_name} type={self.device_type}\r\n"
        ).encode("utf-8")