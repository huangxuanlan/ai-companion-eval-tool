#!/bin/bash
set -e

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  exec python3 launcher.py
fi

if command -v python >/dev/null 2>&1; then
  exec python launcher.py
fi

echo "未找到 Python 3，请先安装 Python 3.11+。"
exit 1
