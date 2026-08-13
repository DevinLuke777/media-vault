#!/usr/bin/env python3
"""
media-vault 入库脚本
用法:
  python3 ingest.py --platform 抖音 --url <原链接> --path <本地相对路径>
  python3 ingest.py --scan   # 扫描媒体目录，按目录结构补录
自动从 URL 抓取元数据（作者/标题/内容/日期），失败可用 --title/--author 等覆盖。
"""
import argparse, json, os, re, sqlite3, sys, urllib.request, urllib.parse
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_library.db"))
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/vol1/1000/Downloads/拾光集")

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1"

def fetch(url, timeout=20, referer=None, extra_headers=None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")

def get_meta_xiaohongshu(url):
    """小红书：页面 JSON 抓 title/author/desc/time（发布秒级时间戳）"""
    html = fetch(url)
    # title：优先 note 数据里的（type=video 后的 title），避免匹配到其他 title
    t = re.search(r'"noteDetailMap":\{"[^"]+":\{"note":\{.*?"title":"([^"]+)"', html, re.S)
    if not t:
        t = re.search(r'"type":"(?:video|normal)","title":"([^"]+)"', html)
    title = t.group(1)[:100] if t else None
    a = re.search(r'"nickName":"([^"]+)"', html)
    author = a.group(1) if a else None
    av = re.search(r'"avatar":"([^"]+)"', html)
    avatar = av.group(1).replace("\\u002F", "/") if av else None
    d = re.search(r'"desc":"([^"]*)"', html)
    content = d.group(1)[:500] if d else None
    tm = re.search(r'"time":(\d{10})', html)
    post_time = None
    if tm:
        from datetime import datetime as _dt
        post_time = _dt.fromtimestamp(int(tm.group(1))).strftime("%Y-%m-%d %H:%M:%S")
    return {"title": title, "author_name": author, "author_avatar": avatar, "content": content, "post_time": post_time}

def get_meta_douyin(url):
    """抖音：走轻解析 API 拿 title/author"""
    try:
        enc = urllib.parse.quote(url, safe="")
        api = f"http://localhost:8086/video/share/url/parse?url={enc}"
        d = json.loads(fetch(api, timeout=30))
        data = d.get("data") or {}
        author = (data.get("author") or {}).get("name")
        avatar = (data.get("author") or {}).get("avatar")
        return {"title": data.get("title"), "author_name": author, "author_avatar": avatar}
    except Exception:
        return {}

def get_meta_weibo(url):
    """微博：m.weibo.cn API（含 created_at 发布秒级时间）"""
    m = re.search(r"weibo\.com/\d+/(\w+)", url)
    if not m:
        return {}
    try:
        api = f"https://m.weibo.cn/statuses/show?id={m.group(1)}"
        txt = fetch(api, timeout=20, referer="https://m.weibo.cn/",
                    extra_headers={"X-Requested-With": "XMLHttpRequest"})
        d = json.loads(txt)
        data = d.get("data") or {}
        user = data.get("user") or {}
        text = re.sub(r"<[^>]+>", "", data.get("text", ""))[:500]
        post_time = None
        ca = data.get("created_at")
        if ca:
            try:
                from datetime import datetime as _dt
                post_time = _dt.strptime(ca, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        return {"title": text[:50], "content": text,
                "author_name": user.get("screen_name"), "author_avatar": user.get("avatar_hd") or user.get("avatar_large"),
                "post_time": post_time}
    except Exception:
        return {}

def get_meta_tiktok(url):
    """TikTok：tikwm API（作者在 author 对象里，create_time 发布秒级）"""
    try:
        api = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url, safe='')}"
        d = json.loads(fetch(api, timeout=25))
        if d.get("code") == 0:
            data = d.get("data") or {}
            author = data.get("author") or {}
            post_time = None
            ct = data.get("create_time")
            if ct:
                from datetime import datetime as _dt
                post_time = _dt.fromtimestamp(int(ct)).strftime("%Y-%m-%d %H:%M:%S")
            return {"title": data.get("title") or data.get("content_desc"),
                    "author_name": author.get("nickname") or author.get("unique_id"),
                    "author_avatar": author.get("avatar") or data.get("origin_cover"),
                    "post_time": post_time}
    except Exception:
        pass
    return {}

def get_meta_x(url):
    """X/Twitter：yt-dlp --dump-json 元数据"""
    import subprocess
    try:
        r = subprocess.run(["yt-dlp", "--dump-json", "--no-warnings", url],
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PATH": os.environ.get("PATH", "")})
        d = json.loads(r.stdout)
        title = (d.get("title") or "").split(" - ", 1)[-1]
        return {"title": title[:100], "author_name": d.get("uploader"),
                "author_avatar": d.get("thumbnail"), "content": None}
    except Exception:
        return {}

META_FUNCS = {
    "小红书": get_meta_xiaohongshu,
    "抖音": get_meta_douyin,
    "微博": get_meta_weibo,
    "TikTok": get_meta_tiktok,
    "X": get_meta_x,
    "Twitter": get_meta_x,
}

def bark_notify(row):
    """新收藏通知（Bark）：BARK_URL 环境变量为空则不推送"""
    url = os.environ.get("BARK_URL", "")
    if not url:
        return
    title = f"📥 新收藏 [{row['platform']}]"
    body = row["title"] or "无标题"
    if row.get("author_name"):
        body += f"\n👤 {row['author_name']}"
    if row.get("post_date"):
        body += f"\n🕐 {row['post_date']}"
    try:
        u = f"{url.rstrip('/')}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
        urllib.request.urlopen(urllib.request.Request(u), timeout=8).read()
    except Exception:
        pass

def ingest(platform, url, local_path, title=None, author=None, avatar=None, content=None, post_date=None, force=False):
    meta = {}
    fn = META_FUNCS.get(platform)
    if fn:
        try:
            meta = fn(url) or {}
        except Exception:
            meta = {}
    row = {
        "platform": platform,
        "title": title or meta.get("title"),
        "content": content or meta.get("content"),
        "author_name": author or meta.get("author_name"),
        "author_avatar": avatar or meta.get("author_avatar"),
        "post_date": post_date or meta.get("post_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "original_url": url,
        "local_path": local_path,
    }
    # 标题兜底：用本地目录名（下载时已按标题命名）
    if not row["title"] and local_path:
        row["title"] = os.path.basename(local_path.rstrip("/"))[:100]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        # 去重保护：original_url 已存在 → 提示并跳过（除非 --force）
        if url and not force:
            dup = cur.execute("SELECT id, title, created_at FROM items WHERE original_url=?",
                              (url,)).fetchone()
            if dup:
                print(f"⚠️ 已收藏过 (id={dup[0]})「{dup[1] or '无标题'}」（采集于 {dup[2]}），跳过。用 --force 强制更新")
                conn.close()
                return
        cur.execute("""INSERT OR REPLACE INTO items
            (platform, title, content, author_name, author_avatar, post_date, original_url, local_path)
            VALUES (:platform,:title,:content,:author_name,:author_avatar,:post_date,:original_url,:local_path)""", row)
        conn.commit()
        print(f"✅ 入库: [{platform}] {row['title'] or '无标题'} 作者:{row['author_name'] or '?'}")
        conn.close()
        bark_notify(row)  # 新收藏通知
        return
    except Exception as e:
        print(f"❌ 入库失败: {e}")
    finally:
        conn.close()

def scan_and_ingest():
    """扫描媒体目录：平台/日期/标题/文件 → 入库"""
    if not os.path.isdir(MEDIA_ROOT):
        print(f"媒体目录不存在: {MEDIA_ROOT}")
        return
    for platform in os.listdir(MEDIA_ROOT):
        pdir = os.path.join(MEDIA_ROOT, platform)
        if not os.path.isdir(pdir) or platform.startswith("."):
            continue
        for date_dir in os.listdir(pdir):
            ddir = os.path.join(pdir, date_dir)
            if not os.path.isdir(ddir):
                continue
            for item_dir in os.listdir(ddir):
                idir = os.path.join(ddir, item_dir)
                if not os.path.isdir(idir):
                    continue
                files = [f for f in os.listdir(idir) if not f.startswith(".")]
                if not files:
                    continue
                rel = f"{platform}/{date_dir}/{item_dir}"
                conn = sqlite3.connect(DB_PATH)
                exists = conn.execute("SELECT 1 FROM items WHERE local_path=?", (rel,)).fetchone()
                conn.close()
                if exists:
                    continue
                conn = sqlite3.connect(DB_PATH)
                conn.execute("""INSERT OR IGNORE INTO items
                    (platform, title, author_name, post_date, local_path, original_url)
                    VALUES (?,?,?,?,?, ?)""", (platform, item_dir, None, date_dir, rel, f"scan://{rel}"))
                conn.commit()
                conn.close()
                print(f"  ✅ 入库: [{platform}] {item_dir}")
    print("扫描完成")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform")
    ap.add_argument("--url")
    ap.add_argument("--path")
    ap.add_argument("--title")
    ap.add_argument("--author")
    ap.add_argument("--avatar")
    ap.add_argument("--content")
    ap.add_argument("--date")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--force", action="store_true", help="重复链接时强制覆盖更新")
    args = ap.parse_args()
    if args.scan:
        scan_and_ingest()
    elif args.platform and args.url:
        ingest(args.platform, args.url, args.path, args.title, args.author, args.avatar, args.content, args.date, args.force)
    else:
        print("用法: python3 ingest.py --platform 抖音 --url <链接> --path <相对路径> [--title ...]")
        print("      python3 ingest.py --scan")
        print("      python3 ingest.py --platform 小红书 --url <链接> --path <路径> --force   # 强制更新重复项")
