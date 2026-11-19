# SSH 服务端二进制

`bin/dropbear` 与 `bin/dropbearkey` 是给 UNG220Z（ZTE zxic，Linux 4.1.25+，
ARMv7-A Cortex-A9）用的静态、软浮点 dropbear 2024.86。

## 为什么必须是软浮点

目标设备内核配置为 `# CONFIG_VFP is not set`，CPU 特性里也没有 `vfp`/`neon`，
用户态动态加载器是软浮点的 `/lib/ld-linux.so.3`。硬浮点
（`arm-linux-musleabihf`）产物里的 VFP 指令会直接触发 SIGILL，所以这里使用
`arm-linux-musleabi` 工具链，并显式加 `-mfloat-abi=soft`。

`ssh/bin/dropbear` 可用 `readelf -A` 检查：不应出现 `Tag_ABI_VFP_args`。

## 二进制来源

- 上游：dropbear 2024.86
- 源码：<https://matt.ucc.asn.au/dropbear/releases/dropbear-2024.86.tar.bz2>
- 源码 SHA256：`e78936dffc395f2e0db099321d6be659190966b99712b55c530dd0a1822e0a5e`
- 二进制 SHA256：见 `SHA256SUMS`
- 许可证：见 `LICENSE`（dropbear 上游许可证）

## 重新构建

安装软浮点 musl 交叉工具链（不要用 `musleabihf`）：

```sh
curl -LO https://musl.cc/arm-linux-musleabi-cross.tgz
tar xzf arm-linux-musleabi-cross.tgz -C "$HOME/.local/opt"
```

然后在本仓库根目录执行：

```sh
./ssh/build.sh
```

脚本会下载并校验 dropbear 源码、静态编译、strip、更新 `ssh/bin/` 和
`ssh/SHA256SUMS`，并检查产物没有 VFP ABI 标记。可以用 `CROSS_PREFIX`
指定工具链前缀，用 `BUILD_DIR` 指定构建目录，用 `JOBS` 指定并行数。

## 校验已提交的二进制

```sh
cd ssh && sha256sum -c SHA256SUMS
```

`ssh/bin/` 里的二进制已经提交，普通用户不需要自己编译。
