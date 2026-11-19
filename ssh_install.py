#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UNG220Z SSH 安装器。

只安装静态 dropbear，绑定 LAN 接口，禁用密码登录，仅允许公钥 + root。
"""
import functools
import http.server
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time

SSH_DIR = "/usr/data/ssh"
SSH_BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssh", "bin")
SSH_START = SSH_DIR + "/start_ssh.sh"
SSH_BOOT_DIR = "/usr/data/burntest"
SSH_BOOT_SCRIPT = SSH_BOOT_DIR + "/burntest.sh"
SSH_BOOT_FLAG = SSH_BOOT_DIR + "/burntestrun.txt"
SSH_HOST_KEY = SSH_DIR + "/dropbear_rsa_host_key"
SSH_AUTH_KEYS = SSH_DIR + "/authorized_keys"
SSH_MARKER = "UNG220Z_SSH_HOOK"
SSH_DEFAULT_PORT = 22


def build_start_ssh_script(port=SSH_DEFAULT_PORT, lan_if="br0"):
    """生成开机/手动启动脚本；只绑 LAN IP，禁用密码登录。"""
    return """#!/bin/sh
# %s
SSH_DIR=%s
PORT=%d
LAN_IF=%s
LOG=$SSH_DIR/ssh.log

mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR" 2>/dev/null

LAN_IP=""
i=0
while [ $i -lt 30 ]; do
    LAN_IP=$(ifconfig "$LAN_IF" 2>/dev/null | sed -n 's/.*inet addr:\\([0-9.]*\\) .*/\\1/p' | head -1)
    [ -z "$LAN_IP" ] && LAN_IP=$(ifconfig "$LAN_IF" 2>/dev/null | sed -n 's/.*inet \\([0-9.]*\\) .*/\\1/p' | head -1)
    [ -n "$LAN_IP" ] && break
    i=$((i + 1))
    sleep 1
done
[ -z "$LAN_IP" ] && LAN_IP=192.168.1.1

mkdir -p /root/.ssh
chmod 700 /root /root/.ssh 2>/dev/null
ln -sf "$SSH_DIR/authorized_keys" /root/.ssh/authorized_keys
chmod 600 "$SSH_DIR/authorized_keys" 2>/dev/null

# LAN 放行，其他接口丢弃；dropbear 同时只绑定 LAN IP
iptables -D INPUT -i "$LAN_IF" -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null
iptables -D INPUT ! -i "$LAN_IF" -p tcp --dport "$PORT" -j DROP 2>/dev/null
iptables -I INPUT 1 -i "$LAN_IF" -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null
iptables -I INPUT 2 ! -i "$LAN_IF" -p tcp --dport "$PORT" -j DROP 2>/dev/null

# 先停掉本工具的旧 dropbear；否则重复安装时 pidof 会误判并跳过启动
if [ -f /var/run/dropbear.pid ]; then
    kill "$(cat /var/run/dropbear.pid)" 2>/dev/null
    rm -f /var/run/dropbear.pid
fi
for p in $(pidof dropbear 2>/dev/null); do
    case "$(readlink /proc/$p/exe 2>/dev/null)" in
        "$SSH_DIR/dropbear"|"$SSH_DIR/dropbear (deleted)") kill -9 "$p" 2>/dev/null ;;
    esac
done
i=0
while pidof dropbear >/dev/null 2>&1 && [ $i -lt 10 ]; do
    sleep 0.5
    i=$((i + 1))
done

"$SSH_DIR/dropbear" -r "$SSH_DIR/dropbear_rsa_host_key" -p "$LAN_IP:$PORT" -s -P /var/run/dropbear.pid >>"$LOG" 2>&1
""" % (SSH_MARKER, SSH_DIR, int(port), lan_if)


def build_boot_hook_script():
    """生成 /usr/data/burntest/burntest.sh 的内容。"""
    return "#!/bin/sh\n# %s\n%s\n" % (SSH_MARKER, SSH_START)


def _public_key(path):
    try:
        r = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", path],
                           capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise RuntimeError("找不到 ssh-keygen；请先安装 OpenSSH 客户端")
    if r.returncode != 0:
        raise RuntimeError("读取 SSH 公钥失败（私钥可能有口令）：%s"
                           % (r.stderr.strip() or r.stdout.strip()))
    pub = r.stdout.strip()
    if not pub.startswith(("ssh-rsa ", "ssh-ed25519 ", "ecdsa-sha2-")):
        raise RuntimeError("无法识别 SSH 公钥格式：%s" % pub[:40])
    return pub


def ensure_ssh_keypair(path):
    """确保 path 处有可用的无口令私钥；返回 (私钥路径, 公钥文本)。"""
    path = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700)
    if os.path.exists(path):
        os.chmod(path, 0o600)
        return path, _public_key(path)
    try:
        r = subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "3072", "-N", "",
                            "-f", path, "-C", "ung220z@%s" % socket.gethostname()],
                           capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError("找不到 ssh-keygen；请先安装 OpenSSH 客户端")
    if r.returncode != 0:
        raise RuntimeError("ssh-keygen 失败：%s"
                           % (r.stderr.strip() or r.stdout.strip()))
    os.chmod(path, 0o600)
    return path, _public_key(path)


def detect_host_ip(target_ip):
    """探测本机到 target_ip 的出口 LAN IP。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_ip, 80))
        return s.getsockname()[0]
    except OSError as e:
        raise RuntimeError("无法确定本机 LAN IP：%s" % e)
    finally:
        s.close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def _serve(directory, host_ip):
    handler = functools.partial(_QuietHandler, directory=directory)
    srv = http.server.ThreadingHTTPServer((host_ip, 0), handler)
    th = threading.Thread(target=srv.serve_forever, name="ung220z-http", daemon=True)
    th.start()
    return srv, th


def _stop_server(srv, th):
    try:
        srv.shutdown()
    except Exception:
        pass
    try:
        srv.server_close()
    except Exception:
        pass
    th.join(timeout=2)


def _write(path, data, mode):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    os.chmod(path, mode)


def _verify_from_host(priv, ip, port, log):
    if not shutil.which("ssh"):
        log("SSH", "宿主机没有 ssh 客户端，跳过登录验证")
        return False
    cmd = ["ssh", "-F", "/dev/null", "-i", priv, "-p", str(port),
           "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
           "-o", "ConnectTimeout=5", "root@%s" % ip, "id"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception as e:
        log("WARN", "SSH 登录验证异常：%s" % e)
        return False
    if r.returncode == 0 and "uid=0(root)" in r.stdout:
        log("SSH", "验证成功：root@%s 可用密钥登录" % ip)
        return True
    log("WARN", "SSH 登录验证失败：%s" % (r.stderr.strip() or r.stdout.strip()))
    return False


def install_ssh(tn, ip, port=SSH_DEFAULT_PORT, key_path=None, host_ip=None,
                lan_if="br0", log=print):
    """在已提权的 telnet 会话里安装并启动 dropbear；返回结果 dict。"""
    key_path = key_path or os.path.expanduser("~/.ssh/ung220z_%s_rsa" % ip)
    result = {"ok": False, "key": os.path.abspath(os.path.expanduser(key_path)),
              "port": port, "ip": ip}
    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise RuntimeError("SSH 端口无效：%s" % port)
        if "uid=0(root)" not in tn.run("id", timeout=10):
            raise RuntimeError("需要 root shell 才能安装 SSH")
        host_ip = host_ip or detect_host_ip(ip)
        log("SSH", "上传地址 %s，目标 %s:%d" % (host_ip, ip, port))
        priv, pub = ensure_ssh_keypair(key_path)
        result["key"] = priv
        log("SSH", "用户密钥 %s" % priv)

        missing = [n for n in ("dropbear", "dropbearkey")
                   if not os.path.isfile(os.path.join(SSH_BIN_DIR, n))]
        if missing:
            raise RuntimeError("缺少 %s；请先运行 ssh/build.sh" % ", ".join(missing))

        existing_boot = tn.run("cat %s 2>/dev/null" % SSH_BOOT_SCRIPT)
        if existing_boot.strip() and SSH_MARKER not in existing_boot:
            raise RuntimeError("已有 %s，拒绝覆盖；请先备份/移走" % SSH_BOOT_SCRIPT)
        if not existing_boot.strip():
            flag = tn.run("test -e %s && echo yes" % SSH_BOOT_FLAG)
            if "yes" in flag:
                raise RuntimeError("检测到 burn-in flag %s，拒绝覆盖" % SSH_BOOT_FLAG)

        existing_auth = tn.run("ls -l /root/.ssh/authorized_keys 2>/dev/null")
        if existing_auth.strip() and ("-> %s" % SSH_AUTH_KEYS) not in existing_auth:
            raise RuntimeError("已有 /root/.ssh/authorized_keys，拒绝覆盖")

        tmp = tempfile.mkdtemp(prefix="ung220z-ssh-")
        srv = th = None
        try:
            for name in ("dropbear", "dropbearkey"):
                shutil.copy2(os.path.join(SSH_BIN_DIR, name), os.path.join(tmp, name))
                os.chmod(os.path.join(tmp, name), 0o755)
            _write(os.path.join(tmp, "authorized_keys"), pub + "\n", 0o600)
            _write(os.path.join(tmp, "start_ssh.sh"),
                   build_start_ssh_script(port, lan_if), 0o755)
            _write(os.path.join(tmp, "burntest.sh"), build_boot_hook_script(), 0o755)
            srv, th = _serve(tmp, host_ip)
            base = "http://%s:%d" % (host_ip, srv.server_address[1])
            log("SSH", "临时 HTTP 服务 %s" % base)

            tn.run("mkdir -p %s %s" % (SSH_DIR, SSH_BOOT_DIR))
            # dropbear 可能正在运行，直接覆盖会报 ETXTBSY；先写 .new 再 mv。
            for name in ("dropbear", "dropbearkey"):
                dest = SSH_DIR + "/" + name
                tmp_dest = dest + ".new"
                out = tn.run("wget -O %s %s/%s && echo __DL_OK__" % (tmp_dest, base, name),
                             timeout=60)
                if "__DL_OK__" not in out:
                    raise RuntimeError("下载 %s 失败：%s" % (name, out[-200:]))
                tn.run("chmod 755 %s && mv -f %s %s" % (tmp_dest, tmp_dest, dest))
            for name in ("authorized_keys", "start_ssh.sh", "burntest.sh"):
                dest = SSH_DIR + "/" + name
                out = tn.run("wget -O %s %s/%s && echo __DL_OK__" % (dest, base, name),
                             timeout=60)
                if "__DL_OK__" not in out:
                    raise RuntimeError("下载 %s 失败：%s" % (name, out[-200:]))

            tn.run("chmod 755 %s/dropbear %s/dropbearkey %s/start_ssh.sh"
                   % (SSH_DIR, SSH_DIR, SSH_DIR))
            tn.run("chmod 600 %s/authorized_keys" % SSH_DIR)
            tn.run("chmod 700 %s" % SSH_DIR)

            if "yes" not in tn.run("test -s %s && echo yes" % SSH_HOST_KEY):
                log("SSH", "生成 dropbear RSA 主机密钥")
                tn.run("%s/dropbearkey -t rsa -s 2048 -f %s"
                       % (SSH_DIR, SSH_HOST_KEY), timeout=90)
                tn.run("chmod 600 %s" % SSH_HOST_KEY)
            if "yes" not in tn.run("test -s %s && echo yes" % SSH_HOST_KEY):
                raise RuntimeError("dropbear 主机密钥生成失败")

            out = tn.run("cp %s/burntest.sh %s && echo __CP_OK__"
                         % (SSH_DIR, SSH_BOOT_SCRIPT))
            if "__CP_OK__" not in out:
                raise RuntimeError("写入开机钩子失败：%s" % out[-200:])
            tn.run("chmod 755 %s" % SSH_BOOT_SCRIPT)
            tn.run("touch %s" % SSH_BOOT_FLAG)

            tn.run("if [ -f /var/run/dropbear.pid ]; then "
                   "kill $(cat /var/run/dropbear.pid) 2>/dev/null; "
                   "rm -f /var/run/dropbear.pid; fi")
            time.sleep(1)
            # dropbear 收到 TERM 后可能等子连接退出；直接 KILL 本工具的旧进程，
            # 否则 start_ssh.sh 里的 pidof 会误判“已在运行”而跳过启动。
            tn.run("for p in $(pidof dropbear 2>/dev/null); do "
                   "case \"$(readlink /proc/$p/exe 2>/dev/null)\" in "
                   "%s/dropbear*) kill -9 $p 2>/dev/null;; esac; done" % SSH_DIR)
            for _ in range(20):
                if not tn.run("pidof dropbear").strip():
                    break
                time.sleep(0.5)
            start_out = tn.run("sh %s" % SSH_START, timeout=60)
            pids = listen = ""
            deadline = time.time() + 8
            while time.time() < deadline:
                pids = tn.run("pidof dropbear")
                listen = tn.run("netstat -lntp | grep ':%d '" % port)
                if pids.strip() and ("%s:%d" % (ip, port)) in listen:
                    break
                time.sleep(0.5)
            if not pids.strip() or ("%s:%d" % (ip, port)) not in listen:
                raise RuntimeError("dropbear 未监听 %s:%d（pid=%s，listen=%s，start=%s）"
                                   % (ip, port, pids.strip(), listen.strip()[-200:],
                                      start_out.strip()[-200:]))

            result.update({"ok": True, "verified": _verify_from_host(priv, ip, port, log),
                           "command": ssh_command(priv, ip, port)})
            return result
        finally:
            if srv:
                _stop_server(srv, th)
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        log("WARN", "SSH 安装失败：%s" % e)
        result["error"] = str(e)
        return result


def uninstall_ssh(tn, port=SSH_DEFAULT_PORT, lan_if="br0", log=print):
    """停止并删除 dropbear、开机钩子和 iptables 规则。"""
    try:
        port = int(port)
        if "uid=0(root)" not in tn.run("id", timeout=10):
            raise RuntimeError("需要 root shell 才能卸载 SSH")
        tn.run("if [ -f /var/run/dropbear.pid ]; then "
               "kill $(cat /var/run/dropbear.pid) 2>/dev/null; "
               "rm -f /var/run/dropbear.pid; fi")
        tn.run("for p in $(pidof dropbear 2>/dev/null); do "
               "x=$(readlink /proc/$p/exe 2>/dev/null); "
               "case \"$x\" in %s/dropbear|\"%s/dropbear (deleted)\") kill -9 $p;; esac; "
               "done" % (SSH_DIR, SSH_DIR))
        tn.run("iptables -D INPUT -i %s -p tcp --dport %d -j ACCEPT 2>/dev/null"
               % (lan_if, port))
        tn.run("iptables -D INPUT ! -i %s -p tcp --dport %d -j DROP 2>/dev/null"
               % (lan_if, port))
        tn.run("if [ \"$(readlink /root/.ssh/authorized_keys 2>/dev/null)\" = \"%s\" ]; "
               "then rm -f /root/.ssh/authorized_keys; fi" % SSH_AUTH_KEYS)
        tn.run("if grep -q %s %s 2>/dev/null; then rm -f %s; rm -f %s; fi"
               % (SSH_MARKER, SSH_BOOT_SCRIPT, SSH_BOOT_SCRIPT, SSH_BOOT_FLAG))
        rc = tn.run("grep -q %s %s 2>/dev/null || grep -q %s %s 2>/dev/null; echo RC=$?"
                    % (SSH_MARKER, SSH_BOOT_SCRIPT, SSH_MARKER, SSH_START))
        if "RC=0" in rc:
            tn.run("rm -rf %s" % SSH_DIR)
        else:
            log("WARN", "未找到本工具标记，保留 %s（请确认后手动删除）" % SSH_DIR)
        tn.run("rmdir /root/.ssh 2>/dev/null")
        log("SSH", "已卸载 SSH 服务、开机自启和 iptables 规则")
        return True
    except Exception as e:
        log("WARN", "SSH 卸载失败：%s" % e)
        return False


def ssh_command(priv, ip, port=SSH_DEFAULT_PORT):
    # 该固件的 devpts/PTY 路径不兼容，-T 走无 PTY 通道；
    # 单条命令、管道 shell 和 scp 都可用，完整交互式终端请用 Telnet。
    if int(port) == 22:
        return "ssh -T -i %s root@%s" % (shlex.quote(priv), ip)
    return "ssh -T -i %s -p %d root@%s" % (shlex.quote(priv), int(port), ip)
