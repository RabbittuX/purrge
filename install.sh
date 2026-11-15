#!/bin/bash
# Purrge 安装脚本：
#   curl -fsSL https://raw.githubusercontent.com/RabbittuX/purrge/master/install.sh | bash
#   或者 git clone 后运行：bash install.sh
# 可选参数：--engine claude|codex|workbuddy|deepseek|pi  --threshold 15  --yes
set -e
[ "$(uname)" = "Darwin" ] || { echo "Purrge 目前只支持 macOS"; exit 1; }

py_ok() { [ -n "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; }
PY="$(command -v python3 || true)"
[ -n "$PURRGE_FORCE_NO_PY" ] && PY=""               # CI 自检用：模拟没有 Python
if ! py_ok "$PY"; then                               # 没有可用的 Python 3.8+：用苹果官方的命令行开发者工具安装
  # 不用 Homebrew：在 Homebrew 不再提供预编译包的 macOS 上会从源码编译，还会顺带升级/替换其他软件
  echo "没有检测到 Python 3.8 以上。即将弹出苹果的「命令行开发者工具」安装窗口，请点「安装」。"
  echo "装好后会自动继续，不用重新运行这条命令（一般需要 5～15 分钟）。"
  xcode-select --install 2>/dev/null || true
  PY=/usr/bin/python3
  for _ in $(seq 1 360); do                           # 最多等 60 分钟
    xcode-select -p >/dev/null 2>&1 && py_ok "$PY" && break
    sleep 10
  done
  if ! py_ok "$PY"; then
    echo "还没有检测到 Python。命令行工具装好后，重新运行这条安装命令即可。"
    exit 1
  fi
  echo "✓ Python 已就绪：$("$PY" --version 2>&1)"
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ ! -f "$SRC/runtime/lib/dg.py" ]; then          # 通过 curl 运行：下载最新代码
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "正在下载 Purrge…"
  curl -fsSL https://codeload.github.com/RabbittuX/purrge/tar.gz/refs/heads/master | tar -xz -C "$TMP"
  SRC="$(echo "$TMP"/purrge-*)"
fi

if [ -n "$PURRGE_SH_CHECK_ONLY" ]; then "$PY" "$SRC/runtime/lib/dg.py" version; exit $?; fi   # CI 自检用
if [ -e /dev/tty ] && { : < /dev/tty; } 2>/dev/null; then
  "$PY" "$SRC/runtime/lib/dg.py" install "$@" < /dev/tty
else
  "$PY" "$SRC/runtime/lib/dg.py" install "$@"
fi
