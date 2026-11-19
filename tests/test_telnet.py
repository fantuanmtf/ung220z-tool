#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用假设备复现 UNG220Z / ZTE 固件的 Telnet 行为，验证登录与提权。

真实设备（本机实测）行为：
  - 提示符是 ``~ $``（csp 用户），不是 ``/ #``
  - Telnet 出厂口令 CMCCAdmin / aDm8H%MdA
  - ``su`` + aDm8H%MdA 才拿到 root 提示符 ``/ #``
"""
import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ung220z  # noqa: E402

TELNET_USER = "CMCCAdmin"
TELNET_PW = "aDm8H%MdA"


class FakeDevice(threading.Thread):
    """最小可用的 Telnet 假光猫（无 IAC 协商）。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.username = None
        self.state = "login_user"
        self.root = False
        self.pending_stale = False
        self._stop = threading.Event()

    def _prompt(self):
        return "/ # " if self.root else "~ $ "

    def run(self):
        conn, _ = self.srv.accept()
        f = conn.makefile("rwb", buffering=0)
        try:
            self._session(f)
        except (OSError, ValueError):
            pass
        finally:
            self._stop.set()
            try:
                f.close()
                conn.close()
            except Exception:
                pass

    def _session(self, f):
        f.write(b"\r\n\rLogin: ")
        while not self._stop.is_set():
            raw = f.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").strip("\r\n")

            if self.state == "login_user":
                self.username = line
                f.write(b"\r\nPassword: ")
                self.state = "login_pw"
            elif self.state == "login_pw":
                if (self.username, line) == (TELNET_USER, TELNET_PW):
                    f.write(b"\r\n~ $ ")
                    self.state = "shell"
                else:
                    f.write(b"\r\nLogin incorrect\r\n\rLogin: ")
                    self.state = "login_user"
            elif self.state == "su_pw":
                if line == TELNET_PW:
                    self.root = True
                    f.write(b"\r\n/ # ")
                    self.state = "shell"
                else:
                    f.write(b"\r\nsu: incorrect password\r\n~ $ ")
                    self.state = "shell"
            else:  # shell
                if line == "su":
                    f.write(b"\r\nPassword: ")
                    self.state = "su_pw"
                elif line == "echo __X__''END":
                    f.write(b"\r\n__X__END\r\n")
                    if self.pending_stale:
                        # 模拟上一轮 run() 在标记后遗留的输出
                        f.write(b"STALE\r\n")
                        self.pending_stale = False
                    f.write(self._prompt().encode())
                elif line == "bare":
                    # 某些状态下提示符会变成裸 "# "，并与命令回显拼在一起
                    f.write(b"\r\n# bare\r\nbare-output\r\n" + self._prompt().encode())
                elif line == "id":
                    uid = "uid=0(root) gid=0(root)" if self.root else "uid=108(csp) gid=110(csp)"
                    f.write(("\r\n%s\r\n" % uid).encode() + self._prompt().encode())
                elif line == "ls -l /x":
                    f.write("\r\n\x1b[1;32m/x\x1b[0m\r\n".encode() + self._prompt().encode())
                else:
                    f.write(b"\r\n" + self._prompt().encode())


class TelnetCompatTest(unittest.TestCase):
    def setUp(self):
        self.dev = FakeDevice()
        self.dev.start()
        self.tn = ung220z.Telnet("127.0.0.1", self.dev.port, timeout=3)

    def tearDown(self):
        self.tn.close()
        self.dev._stop.set()
        try:
            self.dev.srv.close()
        except Exception:
            pass

    def test_login_accepts_csp_prompt(self):
        """登录成功提示符是 '~ $'，不能只认 '/ #'。"""
        ok = self.tn.login([("CMCCAdmin", "wrong"), ("CMCCAdmin", TELNET_PW)])
        self.assertTrue(ok, "csp 提示符 '~ $' 应判定为登录成功")

    def test_escalate_to_root(self):
        self.assertTrue(self.tn.login([("CMCCAdmin", TELNET_PW)]))
        pw = self.tn.escalate_root([TELNET_PW])
        self.assertEqual(pw, TELNET_PW)
        self.assertIn("uid=0(root)", self.tn.run("id"))

    def test_run_strips_prompt_and_ansi(self):
        self.assertTrue(self.tn.login([("CMCCAdmin", TELNET_PW)]))
        self.tn.escalate_root([TELNET_PW])
        out = self.tn.run("ls -l /x")
        self.assertIn("/x", out)
        self.assertNotIn("\x1b[", out)
        self.assertNotIn("~ $", out)
        self.assertNotIn("/ #", out)

    def test_run_strips_bare_hash_prompt_echo(self):
        """root 提示符可能退化成裸 '# '，不能把 '# bare' 当成输出。"""
        self.assertTrue(self.tn.login([("CMCCAdmin", TELNET_PW)]))
        self.tn.escalate_root([TELNET_PW])
        out = self.tn.run("bare")
        self.assertEqual(out, "bare-output")

    def test_run_drains_stale_output(self):
        """上一条命令在标记后遗留的输出不能污染下一条命令。"""
        self.assertTrue(self.tn.login([("CMCCAdmin", TELNET_PW)]))
        self.tn.escalate_root([TELNET_PW])
        self.dev.pending_stale = True
        self.tn.run("id")
        time.sleep(0.2)
        out = self.tn.run("id")
        self.assertIn("uid=0(root)", out)
        self.assertNotIn("STALE", out)


if __name__ == "__main__":
    unittest.main()
