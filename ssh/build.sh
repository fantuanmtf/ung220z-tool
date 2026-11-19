#!/usr/bin/env bash
# 重新构建 ssh/bin 下的静态 ARMv7 软浮点 dropbear。
#
# 目标设备（UNG220Z / ZTE zxic，Linux 4.1.25+）没有 VFP/NEON，
# 用户态是软浮点（ld-linux.so.3），所以必须用 arm-linux-musleabi
# 工具链，不能使用 arm-linux-musleabihf（硬浮点）产物。
set -euo pipefail

VERSION=2024.86
TARBALL=dropbear-${VERSION}.tar.bz2
URL=https://matt.ucc.asn.au/dropbear/releases/${TARBALL}
SHA256=e78936dffc395f2e0db099321d6be659190966b99712b55c530dd0a1822e0a5e

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILD=${BUILD_DIR:-$ROOT/ssh/.build}
PREFIX=${CROSS_PREFIX:-$HOME/.local/opt/arm-linux-musleabi-cross}
CC=$PREFIX/bin/arm-linux-musleabi-gcc
STRIP=$PREFIX/bin/arm-linux-musleabi-strip
READELF=$PREFIX/bin/arm-linux-musleabi-readelf
JOBS=${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}

for f in "$CC" "$STRIP" "$READELF"; do
    [ -x "$f" ] || {
        echo "缺少交叉工具链：$f" >&2
        echo "请先安装软浮点 musl 工具链，见 ssh/README.md" >&2
        exit 1
    }
done

mkdir -p "$BUILD"
cd "$BUILD"

if [ ! -f "$TARBALL" ]; then
    echo "下载 $URL"
    if command -v curl >/dev/null 2>&1; then
        curl -L --fail --retry 3 -o "$TARBALL" "$URL"
    else
        wget -O "$TARBALL" "$URL"
    fi
fi
echo "$SHA256  $TARBALL" | sha256sum -c -

rm -rf "dropbear-$VERSION"
tar xjf "$TARBALL"
cd "dropbear-$VERSION"

export PATH="$PREFIX/bin:$PATH"
CC="$CC" \
CFLAGS="-Os -march=armv7-a -mfloat-abi=soft -fno-pie" \
LDFLAGS="-static -no-pie" \
./configure \
    --host=arm-linux-musleabi \
    --enable-static \
    --disable-zlib \
    --disable-lastlog \
    --disable-utmp \
    --disable-utmpx \
    --disable-wtmp \
    --disable-wtmpx \
    --disable-pututline \
    --disable-pututxline \
    --disable-syslog \
    --disable-shadow \
    --enable-bundled-libtom

make -j"$JOBS" PROGRAMS="dropbear dropbearkey"

"$STRIP" dropbear dropbearkey
install -D -m 755 dropbear "$ROOT/ssh/bin/dropbear"
install -D -m 755 dropbearkey "$ROOT/ssh/bin/dropbearkey"
cp LICENSE "$ROOT/ssh/LICENSE"

cd "$ROOT/ssh"
sha256sum bin/dropbear bin/dropbearkey > SHA256SUMS

# 硬浮点产物会带 Tag_ABI_VFP_args；目标内核没有 VFP，必须拒绝。
if "$READELF" -A bin/dropbear | grep -q 'Tag_ABI_VFP_args'; then
    echo "错误：dropbear 是硬浮点产物，目标设备无法运行" >&2
    exit 1
fi

file bin/dropbear bin/dropbearkey
cat SHA256SUMS
echo "构建完成。"
