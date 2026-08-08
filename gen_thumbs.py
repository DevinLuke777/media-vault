#!/usr/bin/env python3
# 为视频条目生成封面缩略图（ffmpeg 抽帧，存为条目目录 _thumb.jpg）
import os, sqlite3, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "media_library.db")
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/vol1/1000/Downloads/媒体宝库")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

def gen_thumb(src_path, thumb_path, is_image=False):
    """生成缩略图：视频抽帧 / 图片直接缩放"""
    try:
        cmd = ["ffmpeg", "-y"]
        if not is_image:
            cmd += ["-ss", "0.5"]
        cmd += ["-i", src_path, "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", thumb_path]
        subprocess.run(cmd, capture_output=True, timeout=60)
        return os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 3000
    except Exception:
        return False

def main():
    conn = sqlite3.connect(DB_PATH)
    items = conn.execute("SELECT id, local_path FROM items").fetchall()
    made, skipped = 0, 0
    for item_id, rel in items:
        if not rel:
            continue
        d = os.path.join(MEDIA_ROOT, rel)
        if not os.path.isdir(d):
            continue
        # 已有缩略图则跳过
        thumb = os.path.join(d, "_thumb.jpg")
        if os.path.exists(thumb):
            skipped += 1
            continue
        video = None
        img = None
        for f in os.listdir(d):
            low = f.lower()
            if video is None and low.endswith(VIDEO_EXT):
                video = os.path.join(d, f)
            if img is None and low.endswith(IMAGE_EXT):
                img = os.path.join(d, f)
        if video:
            ok = gen_thumb(video, thumb)
        elif img:
            # 图片条目：用第一张图直接缩放（不走抽帧）
            ok = gen_thumb(img, thumb, is_image=True)
        else:
            continue
        if ok:
            print(f"✅ item {item_id}: {os.path.basename(thumb)}")
            made += 1
        else:
            print(f"❌ item {item_id}: 缩略图生成失败")
    print(f"\n完成: 生成 {made} 个缩略图, 跳过 {skipped} 个已有")
    conn.close()

if __name__ == "__main__":
    main()
