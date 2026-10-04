#!/usr/bin/env python3
"""Gemini API（Veo）で、リールの背景に使う短い動画（イメージ映像）を作り clips/ に保存する。

使い方:
    export GEMINI_API_KEY=...            # Google AI Studio で発行したAPIキー
    python3 gen_broll.py scripts/broll_prompts.csv            # 全部作る
    python3 gen_broll.py scripts/broll_prompts.csv night_bed  # 名前を指定して1本だけ

モデルを変えるとき: export GEMINI_VIDEO_MODEL=veo-3.0-fast-generate-001 など
（使えるモデル名は Google AI Studio のドキュメントで確認してください）

必要なもの: Python 3.8以上（追加のライブラリは不要）
注意: Veo の動画生成は有料です。1本ごとに料金がかかります。
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
API = "https://generativelanguage.googleapis.com/v1beta"
MODEL = os.environ.get("GEMINI_VIDEO_MODEL", "veo-3.0-generate-001")

# 体験談に見える「人物の顔」は作らない（手元・部屋・雰囲気の映像だけにする）
NEGATIVE = "face, people talking to camera, text, logo, watermark, brand names"


def request(method, url, key, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-goog-api-key", key)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return res.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"APIエラー {e.code}: {e.read().decode(errors='replace')}")


def generate(name, prompt, key):
    out = os.path.join(BASE, "clips", f"{name}.mp4")
    if os.path.exists(out):
        print(f"スキップ: {out} はすでにあります（作り直す場合は削除してください）")
        return
    print(f"生成中: {name}（数分かかります）")
    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {"aspectRatio": "9:16", "negativePrompt": NEGATIVE},
    }
    op = json.loads(request("POST", f"{API}/models/{MODEL}:predictLongRunning", key, body))
    while not op.get("done"):
        time.sleep(10)
        op = json.loads(request("GET", f"{API}/{op['name']}", key))
    if "error" in op:
        sys.exit(f"生成に失敗しました: {op['error']}")
    samples = op["response"]["generateVideoResponse"].get("generatedSamples") or []
    if not samples:
        sys.exit(f"動画が返されませんでした（安全フィルタの可能性）: {json.dumps(op['response'], ensure_ascii=False)}")
    video = request("GET", samples[0]["video"]["uri"], key)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(video)
    print(f"  → {out}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("環境変数 GEMINI_API_KEY が設定されていません")
    only = set(sys.argv[2:])
    with open(sys.argv[1], encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if not only or r["name"] in only]
    if not rows:
        sys.exit("作成する動画がありません（name を確認してください）")
    for row in rows:
        generate(row["name"].strip(), row["prompt"].strip(), key)


if __name__ == "__main__":
    main()
