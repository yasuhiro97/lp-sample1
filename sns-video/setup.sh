#!/usr/bin/env bash
# 動画作成の準備ができているかを確認し、足りないものを案内（または自動で導入）します。
# 使い方:  bash sns-video/setup.sh     （リポジトリのどこから実行しても動きます）

set -u
cd "$(dirname "$0")" || exit 1

ok()   { printf '  ✅ %s\n' "$1"; }
ng()   { printf '  ❌ %s\n' "$1"; }
info() { printf '     %s\n' "$1"; }
FAILED=0

echo "1/4 Python を確認"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
  ok "$(python3 --version)"
else
  ng "Python 3.8 以上が見つかりません"
  info "Mac: ターミナルで  xcode-select --install  か  brew install python  を実行してください"
  FAILED=1
fi

echo "2/4 ffmpeg を確認"
if ! command -v ffmpeg >/dev/null 2>&1; then
  # Apple Silicon の Homebrew は PATH に入っていないことがある
  for p in /opt/homebrew/bin /usr/local/bin; do
    [ -x "$p/ffmpeg" ] && export PATH="$p:$PATH"
  done
fi
if command -v ffmpeg >/dev/null 2>&1; then
  ok "$(ffmpeg -version | head -1 | cut -c1-60)"
else
  ng "ffmpeg が入っていません"
  BREW="$(command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -1)"
  if [ -n "$BREW" ]; then
    echo "     Homebrew で ffmpeg を入れます（数分かかります）..."
    if "$BREW" install ffmpeg; then
      export PATH="$(dirname "$BREW"):$PATH"
      ok "ffmpeg を入れました"
    else
      ng "ffmpeg の導入に失敗しました。上のエラーを確認してください"
      FAILED=1
    fi
  else
    info "Homebrew がありません。https://brew.sh の手順で入れてから、もう一度実行してください"
    info "（Windows の場合: winget install ffmpeg）"
    FAILED=1
  fi
fi

echo "3/4 日本語テロップに必要なファイルを確認"
if [ -f fonts/MPLUSRounded1c-Bold.ttf ] && [ -f scripts/weekly.csv ] && [ -f make_video.py ]; then
  ok "フォントと台本があります"
else
  ng "ファイルが足りません（fonts/ や scripts/ ）。git pull で最新にしてください"
  info "作業ブランチの場合:  git fetch origin && git checkout claude/instagram-story-analysis-ybfrpp"
  FAILED=1
fi

echo "4/4 試しに動画を1本作る"
if [ "$FAILED" -eq 0 ]; then
  if python3 make_video.py scripts/weekly.csv w01 >/tmp/make_video_check.log 2>&1 && [ -s output/w01.mp4 ]; then
    ok "output/w01.mp4 ができました（15秒の縦動画）"
  else
    ng "動画の作成に失敗しました。次のエラーを教えてください:"
    tail -15 /tmp/make_video_check.log | sed 's/^/     /'
    FAILED=1
  fi
else
  info "上の❌を直してから、もう一度実行してください"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "準備できました。VS Code では「ターミナル → タスクの実行」から動画を作れます。"
  echo "（Veo の映像を作る場合だけ、GEMINI_API_KEY が必要です。キーはチャットに貼らず、ターミナルで設定してください）"
else
  echo "まだ準備できていない項目があります。"
  exit 1
fi
