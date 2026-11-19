# ung220z-tool

针对 **UNG220Z（九联 / Unionman 中国移动光猫）** 的一键凭据提取工具。

> ⚠️ 仅用于**你自己的设备**，用于找回自己忘记的管理密码、迁移宽带配置或安全自查。
> 未经授权对他人设备使用属于违法行为，作者不承担任何责任。

## 背景

这类光猫的 Web 管理页基于 `.gch` CGI 框架，登录口令由 TR-069 定期轮换，普通用户拿到的密码往往几天就失效。本工具走 Telnet 通道，直接读取设备配置库，拿到**当下有效**的全部凭据。

在 ZTE 系固件上，`telnet.gch` 还接受一组**出厂默认 Telnet 账号**，它与 Web 密码相互独立；工具会先尝试这组默认账号，再回退到你输入的 Web 账号。

## 工作流程

```
用户输入账号密码
   ↓
telnet.gch 开启 Telnet（优先尝试出厂 CMCCAdmin / aDm8H%MdA）
   ↓
Telnet 登录（csp，提示符 ~ $）→ su 提权到 root shell（/ #）
   ↓
sidbg 1 DB decry /userconfig/cfg/db_user_cfg.xml 解密配置
   ↓
提取 Web 账号 / Telnet 口令 / PPPoE / WiFi 密钥 / root 口令
   ↓
安装 SSH（默认，仅密钥、仅内网、开机自启）并校验登录
   ↓
打印凭据表 + 落盘日志
```

## 用法

```bash
python3 ung220z.py
```

会依次询问：

```
※ 用户名和密码通常印在光猫【背面贴纸】上（S/N 标签）
  形如「用户名：user   密码：xxxxxxxx」，把光猫翻过来就能看到

① 光猫地址 [192.168.1.1]:
② 用户名 [user]:
③ 密码（输入时不显示）
   密码:
```

也可以全部走命令行：

```bash
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码'
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码' --no-browser

# 只取凭据，不安装 SSH
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码' --no-ssh

# 使用已有密钥 / 改 SSH 端口
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码' \
  --ssh-key ~/.ssh/id_rsa --ssh-port 2222

# 卸载本工具安装的 SSH
python3 ung220z.py -i 192.168.1.1 -u user -p '你的密码' --ssh-uninstall
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `-i, --ip` | 光猫地址，默认 `192.168.1.1` |
| `-u, --user` | 登录用户名，默认 `user` |
| `-p, --password` | 登录密码，不填则交互输入 |
| `--telnet-user` | Telnet 用户名，默认 `CMCCAdmin` |
| `--telnet-password` | Telnet 口令；不填会自动尝试出厂口令与 Web 口令 |
| `--no-browser` | 不调用浏览器，纯 HTTP 请求 |
| `--unlock` | Web 被会话锁占住时重启 httpd 解锁 |
| `--no-release` | 不尝试释放残留 Web 会话 |
| `--no-ssh` | 不安装 SSH，只提取凭据 |
| `--ssh-port` | SSH 端口，默认 `22` |
| `--ssh-key` | 使用已有 SSH 私钥；默认自动生成 RSA 3072 |
| `--ssh-uninstall` | 卸载本工具安装的 SSH 后退出 |
| `--host-ip` | 上传二进制时宿主机 IP，默认自动探测 |
| `--ssh-lan-if` | SSH 绑定的 LAN 接口，默认 `br0` |

## 输出示例

```
[22:15:00] INFO   会话开始  目标=192.168.1.1  账户=user
[22:15:00] HTTP   telnet.gch → TelnetSet Success!（CMCCAdmin）
[22:15:00] PROBE  nc -zv 192.168.1.1 23 → succeeded
[22:15:01] AUTH   Telnet CMCCAdmin / ****** → 登录成功（csp）
[22:15:01] AUTH   su → root 成功（口令 ******）
[22:15:02] SHELL  sidbg 1 DB decry /userconfig/cfg/db_user_cfg.xml → /tmp/debug-decry-cfg
[22:15:03] DATA   DevAuthInfo  CMCCAdmin  / ******  Level=1
[22:15:04] CRACK  root 口令已由 su 验证：******
[22:15:06] SSH    上传地址 192.168.1.2，目标 192.168.1.1:22
[22:15:09] SSH    验证成功：root@192.168.1.1 可用密钥登录
```

最后输出凭据汇总表，并写入 `ung220z_<时间戳>.log`。如果 SSH 安装成功，汇总表里会多一行：

```
SSH (仅密钥)           ssh -T -i /home/you/.ssh/ung220z_192.168.1.1_rsa root@192.168.1.1
```

## SSH（默认安装）

工具默认在提取完凭据后安装一个**只允许密钥登录**的 SSH 服务：

- 服务端：仓库自带的静态 ARMv7 软浮点 `dropbear` / `dropbearkey`（见 `ssh/bin/`），上传到设备 `/usr/data/ssh/`。
- 认证：`dropbear -s` 关闭所有密码登录，只接受公钥；**允许 root 用户登录**。
- 网络：只绑定 `br0` 的 LAN IP:22；iptables 只放行 `br0` 的 22 端口，其他接口的 22 端口丢弃。WAN 侧不监听。
- 开机自启：`/usr/data/ssh/start_ssh.sh` 负责重建 `/root/.ssh/authorized_keys`、补 iptables、启动 dropbear；由 `/usr/data/burntest/burntest.sh` 调用，`/usr/data/burntest/burntestrun.txt` 作为开机 flag。
- 密钥：默认在宿主机生成 RSA 3072 密钥对，私钥在 `~/.ssh/ung220z_<ip>_rsa`（0600），设备上只放公钥。也可以 `--ssh-key` 指定已有私钥。
- 卸载：`--ssh-uninstall` 会停 dropbear、删 iptables 规则、删本工具安装的文件；只有确认 boot hook 带本工具标记时才会删 hook。

连接：

```bash
ssh -T -i ~/.ssh/ung220z_192.168.1.1_rsa root@192.168.1.1
# 改过端口：
ssh -T -i ~/.ssh/ung220z_192.168.1.1_rsa -p 2222 root@192.168.1.1
```

> **PTY 兼容性**：该固件的 devpts/PTY 路径不完整，直接 `ssh ...`（申请 PTY）会报
> `PTY allocation request failed` / `shell request failed`。请使用上面的 `ssh -T`
> （不申请 PTY）：单条命令、管道 shell 和 `scp` 都可用；`tty` 会显示 `not a tty`。
> 需要完整交互式终端时，用 Telnet（`CMCCAdmin` → `su`）。`ssh -T` 登录时可能看到
> 一行无害的 `ln: /lib/libjli.so: File exists`。

第一次连接会提示未知主机密钥。确认地址无误后接受即可；也可以先用
`ssh-keyscan -p 22 192.168.1.1` 查看指纹，再用
`-o StrictHostKeyChecking=accept-new` 首次连接。不要为了方便长期关闭主机密钥校验。

注意事项：

- **私钥不要丢**。私钥只存在你的电脑上；丢了就在电脑上删掉对应密钥，重跑工具生成新密钥（或 `--ssh-key` 指定新密钥），安装器会覆盖设备上的公钥。
- 这是 root 级远程入口。请保护私钥、只在可信 LAN 使用；不要把 22 端口映射到公网。
- `/usr/data` 是 jffs2 持久分区，但**固件升级/恢复出厂可能清空它**；升级后重跑工具即可重新安装。
- 如果设备上已有非本工具创建的 `/usr/data/burntest/burntest.sh`，安装器会拒绝覆盖，避免破坏原有的 burn-in 测试。此时用 `--no-ssh`，或手动把 `/usr/data/ssh/start_ssh.sh` 加进你的启动脚本。
- 本工具默认安装 SSH；如果你不需要，加 `--no-ssh`。

手动卸载（在 root shell 里）：

```sh
[ -f /var/run/dropbear.pid ] && kill "$(cat /var/run/dropbear.pid)"
rm -rf /usr/data/ssh
rm -f /root/.ssh/authorized_keys
rm -f /usr/data/burntest/burntest.sh /usr/data/burntest/burntestrun.txt
iptables -D INPUT -i br0 -p tcp --dport 22 -j ACCEPT 2>/dev/null
iptables -D INPUT ! -i br0 -p tcp --dport 22 -j DROP 2>/dev/null
```

## Telnet 规则（ZTE 系固件）

| 环节 | 说明 |
|---|---|
| 开 Telnet | `GET /usr=<user>&psw=<pass>&cmd=1&telnet.gch`。`cmd=1` 开端口，`cmd=0` 关端口。成功返回 `TelnetSet Success!`。 |
| 默认后门 | 对 `usr=CMCCAdmin`（或设备配置里的管理员用户名），`psw=aDm8H%MdA` 会被接受，**不要求**它等于当前 Web 管理员密码。这是固件行为，不是本工具绕过。 |
| 副作用 | `telnet.gch` 只设置 `TS_Enable=cmd`、`Wan_Enable=0`、`Lan_Enable=1`、`TPage_Mode=1`；它**不会**修改 `TS_UName` / `TS_UPwd`，也不会把 Web 密码同步成 Telnet 密码。 |
| Telnet 账号 | 与 Web 账号独立。国内移动/ZTE 系出厂为 `CMCCAdmin` / `aDm8H%MdA`，登录后是 `csp` 用户，提示符 `~ $`。 |
| 提权 | `su` 再输入 root 口令（同出厂 `aDm8H%MdA`）得到 `/ #`；工具会依次尝试出厂口令、你输入的 Web 口令、`admin`、`root`。 |
| 配置解密 | `sidbg 1 DB decry /userconfig/cfg/db_user_cfg.xml` 无口令即可解密，输出 `/tmp/debug-decry-cfg`。 |
| root 口令 | `/etc/shadow` 中为 SHA-256 crypt；如果 `su` 已验证过，工具直接采用验证结果，否则用常见出厂口令比对。 |

如果 Telnet 口令被轮换，工具会用 `--telnet-user` / `--telnet-password` 指定；默认先试
`CMCCAdmin` / `aDm8H%MdA`，再试你输入的 Web 账号。

## 依赖

- Python 3.8+，标准库即可，无需 pip 安装
- 设备已开启 Telnet（脚本会自动通过 `telnet.gch` 尝试开启）
- 安装 SSH 时需要宿主机有 OpenSSH 的 `ssh-keygen`；校验登录时还需要 `ssh` 客户端
- 破解 `/etc/shadow` 时需要 `openssl`（没有时只是少一个比对来源）
- 只有重新编译 `ssh/bin/` 才需要交叉工具链，普通用户不需要

## 重新构建 SSH 二进制

`ssh/bin/` 已经提交了可直接用的二进制。需要重新编译时：

```sh
./ssh/build.sh
```

目标设备没有 VFP/NEON，必须使用 **arm-linux-musleabi（软浮点）** 工具链，
不能用 `arm-linux-musleabihf`。详细说明、源码校验和与许可证见
[`ssh/README.md`](ssh/README.md)。校验已提交的二进制：

```sh
cd ssh && sha256sum -c SHA256SUMS
```

## 免责声明

本项目仅用于教育与自有设备维护。使用者应确保对目标设备拥有合法管理权限。
默认安装的 SSH 是 root 级入口，请自行评估风险并妥善保管私钥。
