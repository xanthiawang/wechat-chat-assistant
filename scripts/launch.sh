#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "此 Beta 仅支持 Apple Silicon macOS。"; exit 1
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo "需要 Apple Command Line Tools。请运行 xcode-select --install，完成后重新打开安装器。"; exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "请先从 https://brew.sh 安装 Homebrew，再重新打开本安装器。"; exit 1
fi
if [[ ! -t 0 ]]; then echo "请在交互式终端打开安装器。"; exit 1; fi
echo "微信聊天助手 Beta · 依赖将由 Homebrew 安装（Python 3.14、Node 24、SQLCipher）。"
echo "这不会修改微信；聊天读取初始化会在向导中另行确认。"
read -r -p "继续安装依赖？输入 y：" consent
[[ "$consent" == y ]] || exit 0
brew install python@3.14 node@24 sqlcipher
export PATH="$(brew --prefix node@24)/bin:$(brew --prefix python@3.14)/bin:$PATH"
exec "$(brew --prefix python@3.14)/bin/python3.14" app/setup.py install
