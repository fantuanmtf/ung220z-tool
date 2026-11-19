#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSH 安装器里可单测的纯逻辑。"""
import os
import shutil
import stat
import tempfile
import unittest

import ung220z as u


class StartScriptTest(unittest.TestCase):
    def test_script_binds_lan_ip_and_uses_key_only(self):
        s = u.build_start_ssh_script(port=2222)
        self.assertIn("PORT=2222", s)
        self.assertIn('-p "$LAN_IP:$PORT"', s)
        self.assertIn(" -s ", s)
        self.assertNotIn(" -g ", s)
        self.assertIn("dropbear_rsa_host_key", s)
        self.assertIn("$SSH_DIR/authorized_keys", s)
        self.assertIn("ln -sf", s)
        self.assertIn("chmod 700 /root", s)
        self.assertIn("iptables", s)
        # 重复安装时先杀掉本工具的旧 dropbear，避免 pidof 误判后跳过启动
        self.assertIn("kill -9", s)
        self.assertIn("readlink /proc/$p/exe", s)
        self.assertNotIn("if ! pidof dropbear", s)

    def test_script_uses_requested_interface_and_port(self):
        s = u.build_start_ssh_script(port=2200, lan_if="br-lan")
        self.assertIn("LAN_IF=br-lan", s)
        self.assertIn("PORT=2200", s)
        self.assertIn('-p "$LAN_IP:$PORT"', s)

    def test_boot_hook_calls_starter(self):
        s = u.build_boot_hook_script()
        self.assertIn("UNG220Z_SSH_HOOK", s)
        self.assertIn("/usr/data/ssh/start_ssh.sh", s)


@unittest.skipUnless(shutil.which("ssh-keygen"), "需要 ssh-keygen")
class KeypairTest(unittest.TestCase):
    def test_generates_then_reuses_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "id_rsa")
            priv, pub = u.ensure_ssh_keypair(path)
            self.assertEqual(priv, path)
            self.assertTrue(pub.startswith("ssh-rsa "), pub[:32])
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            before = os.stat(path).st_mtime_ns
            priv2, pub2 = u.ensure_ssh_keypair(path)
            self.assertEqual(priv2, path)
            self.assertEqual(pub2, pub)
            self.assertEqual(os.stat(path).st_mtime_ns, before)


class SshCommandTest(unittest.TestCase):
    def test_default_port_uses_no_pty(self):
        self.assertEqual(
            u.ssh_command("/tmp/key", "192.168.1.1"),
            "ssh -T -i /tmp/key root@192.168.1.1",
        )

    def test_custom_port_uses_no_pty(self):
        self.assertEqual(
            u.ssh_command("/tmp/key", "192.168.1.1", 2222),
            "ssh -T -i /tmp/key -p 2222 root@192.168.1.1",
        )


if __name__ == "__main__":
    unittest.main()
