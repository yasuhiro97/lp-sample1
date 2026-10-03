#!/usr/bin/env python3
"""台本CSVからリール用の縦長動画（1080x1920, MP4）を作る。

使い方:
    python3 make_video.py scripts/reel_b_genre.csv          # CSV内の全動画を作る
    python3 make_video.py scripts/reel_b_genre.csv b02      # 指定したIDだけ作る

必要なもの: Python 3.8以上（追加のライブラリは不要）、ffmpeg
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))

# ---- 全体の設定 ----------------------------------------------------------
W, H = 1080, 1920
FPS = 30
FONT = os.path.join(BASE, "fonts", "MPLUSRounded1c-Bold.ttf")
PR_LABEL = "PR"                 # 全シーンの左上に常に表示する
TEXT_COLOR = "0x4A3A5C"         # テロップの文字色（濃い紫）
BOX_COLOR = "white@0.92"        # テロップの背景
FRAME_COLOR = "white"           # frameレイアウトの枠の色
MAX_TEXT_W = 900                # テロップの最大幅（これを超えると文字を自動で小さくする）

# Instagramのボタンやキャプションに隠れない範囲（上15%・下25%を避ける）
SAFE_TOP = int(H * 0.15)
SAFE_BOTTOM = int(H * 0.75)

# frameレイアウト: スマホ画面の録画を中央に小さく置く
FRAME_W, FRAME_H = 560, 996
FRAME_X = (W - FRAME_W) // 2
FRAME_Y = 600
FRAME_BORDER = 10

# mockレイアウト: 録画を使わずに「配信画面のイメージ」を描く
MOCK_SCREEN = "0x2B2238"        # 画面の背景
MOCK_STAGE = "#B89BE0"          # 配信エリアの色（CSVの accent 列で変更可）
MOCK_NOTE = "※画面はイメージです"


def hex_color(value, default):
    value = (value or "").strip() or default
    return "0x" + value.lstrip("#")


def text_width(line, size):
    """文字幅の概算（全角1文字=1em、半角=0.6em）。"""
    return sum(size * (0.6 if ord(ch) < 0x2E80 else 1.0) for ch in line)


def fit_size(line, size, max_w=MAX_TEXT_W):
    """1行が max_w に収まるよう文字サイズを小さくする。"""
    width = text_width(line, 1)
    return int(min(size, max_w / width)) if width else size


def write_text(workdir, name, text):
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def mock_draws(scene, workdir, index):
    """録画の代わりに、配信画面のイメージ（タイトル・LIVE・流れるコメント）を描く。

    CSVの mock 列: 「タイトル|コメント1|コメント2|...」
    """
    parts = [p.strip() for p in (scene.get("mock") or "").split("|") if p.strip()]
    title, comments = (parts[0], parts[1:]) if parts else ("", [])
    stage = hex_color(scene.get("accent"), MOCK_STAGE)
    x0, y0 = FRAME_X, FRAME_Y
    pad = 30
    draws = [
        # 配信エリア
        f"drawbox=x={x0 + pad}:y={y0 + 110}:w={FRAME_W - pad * 2}:h=420:color={stage}@0.9:t=fill",
        # LIVE表示
        drawtext(write_text(workdir, f"s{index}_live.txt", "LIVE"), 30,
                 x0 + pad, y0 + 44, "white", "0xE5487A"),
    ]
    if title:
        tf = write_text(workdir, f"s{index}_title.txt", title)
        draws.append(drawtext(tf, fit_size(title, 64, FRAME_W - 120), "(w-text_w)/2",
                              f"{y0 + 290}+8*sin(2*PI*t)", "white", None))
    # コメントが0.6秒ごとに1つずつ表示される
    for i, comment in enumerate(comments[:4]):
        tf = write_text(workdir, f"s{index}_c{i}.txt", comment)
        start = 0.3 + 0.6 * i
        draws.append(drawtext(
            tf, fit_size(comment, 32, FRAME_W - 120), x0 + pad + 10, y0 + 590 + i * 84,
            "white", "white@0.18", f"if(lt(t,{start}),0,min(1,(t-{start})/0.25))",
        ))
    note = write_text(workdir, f"s{index}_mocknote.txt", MOCK_NOTE)
    draws.append(drawtext(note, 24, f"{x0 + FRAME_W - pad}-text_w", y0 + FRAME_H - 50,
                          "white@0.7", None))
    return draws


def ff_escape(path):
    """フィルタ内で使うファイルパスのエスケープ。"""
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def drawtext(textfile, size, x, y, color, box, alpha=None):
    opts = [
        f"fontfile='{ff_escape(FONT)}'",
        f"textfile='{ff_escape(textfile)}'",
        f"fontsize={size}",
        f"fontcolor={color}",
        f"x='{x}'",
        f"y='{y}'",
    ]
    if box:
        opts += ["box=1", f"boxcolor={box}", f"boxborderw={max(12, size // 3)}"]
    if alpha:
        opts.append(f"alpha='{alpha}'")
    return "drawtext=" + ":".join(opts)


def build_scene(scene, workdir, index):
    """1シーン分の動画を作り、そのファイルパスを返す。"""
    dur = float(scene["duration"])
    layout = (scene.get("layout") or "full").strip()
    clip = (scene.get("clip") or "").strip()
    clip_path = os.path.join(BASE, clip) if clip else ""
    has_clip = layout != "mock" and bool(clip_path) and os.path.exists(clip_path)
    bg = hex_color(scene.get("bg"), "#F9D9E7")
    lines = [l for l in scene["text"].replace("\\n", "\n").split("\n") if l.strip()]
    size = int(scene.get("size") or 72)
    pos = (scene.get("pos") or "center").strip()

    inputs = ["-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H}:r={FPS}:d={dur}"]
    if has_clip:
        inputs += ["-stream_loop", "-1", "-t", str(dur), "-i", clip_path]

    chain = []
    if layout == "mock":
        chain.append(
            f"[0:v]drawbox=x={FRAME_X - FRAME_BORDER}:y={FRAME_Y - FRAME_BORDER}"
            f":w={FRAME_W + FRAME_BORDER * 2}:h={FRAME_H + FRAME_BORDER * 2}"
            f":color={FRAME_COLOR}:t=fill,"
            f"drawbox=x={FRAME_X}:y={FRAME_Y}:w={FRAME_W}:h={FRAME_H}"
            f":color={MOCK_SCREEN}:t=fill[base]"
        )
    elif layout == "frame":
        chain.append(
            f"[0:v]drawbox=x={FRAME_X - FRAME_BORDER}:y={FRAME_Y - FRAME_BORDER}"
            f":w={FRAME_W + FRAME_BORDER * 2}:h={FRAME_H + FRAME_BORDER * 2}"
            f":color={FRAME_COLOR}:t=fill[bg]"
        )
        if has_clip:
            chain.append(
                f"[1:v]scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
                f"crop={FRAME_W}:{FRAME_H},setsar=1,fps={FPS}[clip]"
            )
            chain.append(f"[bg][clip]overlay={FRAME_X}:{FRAME_Y}:shortest=1[base]")
        else:
            chain.append(
                f"[bg]drawbox=x={FRAME_X}:y={FRAME_Y}:w={FRAME_W}:h={FRAME_H}"
                f":color=0xD9D2E3:t=fill[base]"
            )
    elif has_clip:
        chain.append(
            f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS}[base]"
        )
    else:
        chain.append("[0:v]null[base]")

    draws = mock_draws(scene, workdir, index) if layout == "mock" else []

    # 素材が未配置のときは、どこに何を入れるかを表示する
    if clip and not has_clip:
        note = os.path.join(workdir, f"s{index}_note.txt")
        with open(note, "w", encoding="utf-8") as f:
            f.write(f"ここに {clip} を入れる")
        cy = FRAME_Y + FRAME_H // 2 if layout == "frame" else H // 2 + 300
        draws.append(drawtext(note, 30, "(w-text_w)/2", cy, "0x7A6E8A", None))

    # テロップ（1行ずつ中央ぞろえ。2シーン目以降は0.3秒で下からふわっと出す。
    # 1シーン目はフックなので、最初のフレームからはっきり見せる）
    animate = index > 1
    sizes = [fit_size(line, size) for line in lines]
    heights = [int(s * 1.6) for s in sizes]
    if pos == "top":
        top = SAFE_TOP + 150
    else:
        top = (SAFE_TOP + SAFE_BOTTOM) // 2 - sum(heights) // 2
    for i, (line, line_size) in enumerate(zip(lines, sizes)):
        tf = os.path.join(workdir, f"s{index}_l{i}.txt")
        with open(tf, "w", encoding="utf-8") as f:
            f.write(line)
        y = top + sum(heights[:i])
        if animate:
            y = f"{y}+(1-min(1,t/0.3))*40"
        draws.append(drawtext(tf, line_size, "(w-text_w)/2", y, TEXT_COLOR, BOX_COLOR,
                              "min(1,t/0.3)" if animate else None))

    # PR表記（左上・全シーン）
    pr = os.path.join(workdir, "pr.txt")
    with open(pr, "w", encoding="utf-8") as f:
        f.write(PR_LABEL)
    draws.append(drawtext(pr, 40, 64, SAFE_TOP + 16, "white", "0x4A3A5C@0.75"))

    chain.append("[base]" + ",".join(draws) + f",format=yuv420p[v]")

    out = os.path.join(workdir, f"scene_{index:02d}.mp4")
    cmd = (
        ["ffmpeg", "-y", "-loglevel", "error"]
        + inputs
        + ["-f", "lavfi", "-t", str(dur), "-i", "anullsrc=r=44100:cl=stereo"]
        + ["-filter_complex", ";".join(chain)]
        + ["-map", "[v]", "-map", f"{2 if has_clip else 1}:a"]
        + ["-t", str(dur), "-r", str(FPS)]
        + ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
        + ["-c:a", "aac", "-b:a", "128k", out]
    )
    subprocess.run(cmd, check=True)
    return out


def build_video(video_id, scenes, outdir):
    scenes = sorted(scenes, key=lambda s: int(s["scene"]))
    with tempfile.TemporaryDirectory() as workdir:
        parts = [build_scene(s, workdir, i) for i, s in enumerate(scenes, 1)]
        listfile = os.path.join(workdir, "list.txt")
        with open(listfile, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        out = os.path.join(outdir, f"{video_id}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", listfile, "-c", "copy", "-movflags", "+faststart", out],
            check=True,
        )
    # カバー画像（1シーン目の終わり付近）
    cover = os.path.join(outdir, f"{video_id}_cover.jpg")
    first = float(scenes[0]["duration"])
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(max(0.0, first - 0.5)),
         "-i", out, "-frames:v", "1", "-q:v", "2", cover],
        check=True,
    )
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg が見つかりません。先にインストールしてください（Mac: brew install ffmpeg）")

    csv_path = sys.argv[1]
    only = set(sys.argv[2:])
    videos = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            vid = row["video_id"].strip()
            if vid and (not only or vid in only):
                videos.setdefault(vid, []).append(row)
    if not videos:
        sys.exit("作成する動画がありません（video_id を確認してください）")

    outdir = os.path.join(BASE, "output")
    os.makedirs(outdir, exist_ok=True)
    for vid, scenes in videos.items():
        total = sum(float(s["duration"]) for s in scenes)
        print(f"作成中: {vid}（{len(scenes)}シーン・{total:g}秒）")
        print(f"  → {build_video(vid, scenes, outdir)}")


if __name__ == "__main__":
    main()
