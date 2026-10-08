#!/usr/bin/bash

set -eu

# チェック対象のディレクトリとマーカーファイル
MARKER_FILE="$HOME/.postCreateCommand-done"

if [ -f "$MARKER_FILE" ]; then
  # マーカーファイルがあれば終了
  exit 0
elif [ ! -w "$HOME" ]; then
  # ホームに書き込めない時は、異常終了
  echo "ホームディレクトリが書き込めません。"
  exit 1
fi

# 初期化スクリプトを実行

# dev mode only
mkdir -p /workspaces/.codex
if [ -e "$HOME/.codex" ] && [ ! -L "$HOME/.codex" ] ; then
  mv "$HOME/.codex" "$HOME/.codex.backup.$(date +%Y%m%d%H%M%S)"
fi
ln -s /workspaces/.codex ~/.codex

mkdir -p /workspaces/.claude
if [ -e "$HOME/.claude" ] && [ ! -L "$HOME/.claude" ] ; then
  mv "$HOME/.claude" "$HOME/.claude.backup.$(date +%Y%m%d%H%M%S)"
fi
ln -s /workspaces/.claude ~/.claude

# curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 初期化完了を示すマーカーファイルを作成
touch "$MARKER_FILE"
