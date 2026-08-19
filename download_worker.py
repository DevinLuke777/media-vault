#!/usr/bin/env python3
"""
拾光集 · 后台自动入库队列 worker（2026-08-18）
从 拾光集/_queue.json 读取 pending 链接，自动:
  抖音    -> 轻解析(8086, cookie已配) 解析下载 -> 归档 -> ingest
  小红书视频 -> 短链展开 -> 挖 258 无水印流 -> 下载 -> 归档 -> ingest
  小红书图文 -> XHS-Downloader + cookie 下无水印原图 -> 归档 -> ingest
               (token 过期则降级 sns-webpic 带水印渲染图并标记 degraded)
用法: python3 download_worker.py --drain    # 处理一次队列里所有 pending
用系统/Hermes cron 每 2 分钟调用一次; stdout 为空=静默(成功不打扰)。
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.parse, shutil, glob
from datetime import datetime

MEDIA = os.environ.get("MEDIA_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "拾光集"))
QUEUE = os.environ.get("QUEUE_FILE", os.path.join(MEDIA, "_queue.json"))
LOCK = os.path.join(MEDIA, "_queue.lock")
VALT = os.environ.get("MEDIA_VAULT_DIR", "/vol1/1000/Docker/media-vault")  # ingest.py 所在(运行实例)
INGEST = os.path.join(VALT, "ingest.py")
PY = os.environ.get("PYTHON_BIN", os.environ.get("PYTHON", "python3"))
XHS_VENV = os.environ.get("XHS_VENV", "python3")    # XHS-Downloader 的 venv python

UA_I = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
UA_D = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


# ── 队列读写 ──────────────────────────────────────────
def load_queue():
    if not os.path.isfile(QUEUE):
        return []
    try:
        with open(QUEUE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save_queue(q):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)
    os.replace(tmp, QUEUE)


def fetch(url, timeout=20, referer=None):
    headers = {"User-Agent": UA_I}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read()


def clean_title(t):
    t = (t or "").strip()
    while t and not re.match(r"[\u4e00-\u9fffA-Za-z0-9]", t[0]):
        t = t[1:]
    return t


def today():
    return time.strftime("%Y-%m-%d")


def gen_thumb(d, title, is_video):
    """生成 _thumb.jpg"""
    try:
        src = os.path.join(d, f"{title}.mp4") if is_video else os.path.join(d, f"{title}_1.png")
        if not os.path.isfile(src):
            # 图片多命名时兜底
            cands = sorted(glob.glob(os.path.join(d, "*.png")) + glob.glob(os.path.join(d, f"{title}_1.jpg")))
            if not cands:
                return
            src = cands[0]
        cmd = ["ffmpeg", "-y"] + (["-ss", "0.5"] if is_video else []) + \
            ["-i", src, "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", os.path.join(d, "_thumb.jpg")]
        subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception:
        pass


# ── 抖音 ──────────────────────────────────────────────
def download_douyin(url):
    """轻解析解析+下载，返回 (relative_path, title, platform)。
    ⚠️ 用时间戳精确匹配自己那条的落盘目录，避免并发时抓到别的 untitled 串号"""
    # 展开短链
    real = url
    m = re.search(r"v\.douyin\.com/([A-Za-z0-9_-]+)/", url)
    if not m and re.search(r"douyin\.com", url):
        mm = re.search(r"/(video|note)/(\d+)", url)
        if mm:
            real = f"https://www.iesdouyin.com/share/{mm.group(1)}/{mm.group(2)}/"
    if "iesdouyin" not in real:
        short = re.search(r"https://v\.douyin\.com/[A-Za-z0-9_-]+/?", url)
        if short:
            try:
                real = urllib.request.urlopen(urllib.request.Request(short.group(0), headers={"User-Agent": UA_I}), timeout=15).geturl()
            except Exception:
                real = url
    # 调轻解析
    enc = urllib.parse.quote(real, safe="")
    api = f"http://localhost:8086/video/share/url/parse?url={enc}"
    d = json.loads(fetch(api, timeout=40).decode("utf-8", "ignore"))
    if d.get("code") != 200:
        raise RuntimeError(f"轻解析失败: {d.get('msg','?')}")
    data = d.get("data") or {}
    author = (data.get("author") or {}).get("name") or "未知作者"
    title = clean_title(data.get("title")) or author
    base = os.path.join(MEDIA, "抖音", today())
    # 记录请求前的已存在顶层目录(快照)，之后只认"新出现的"落盘目录
    os.makedirs(base, exist_ok=True)
    pre_names = set(os.listdir(base))
    # 调轻解析下载(触发 auto_save 落盘)
    # 等落盘: 只匹配 base 下"新出现"的目录(不在 pre_names 快照里)
    found = None
    waited = 0
    while waited < 90:
        now_names = set(os.listdir(base))
        new = now_names - pre_names
        for name in new:
            p = os.path.join(base, name)
            if os.path.isdir(p):
                files = [f for f in os.listdir(p)]
                media_files = [f for f in files if f.lower().endswith((".mp4", ".jpg", ".jpeg", ".png", ".mov"))]
                if media_files:
                    found = p
                    break
        if found:
            break
        time.sleep(5)
        waited += 5
    if not found:
        # 兜底：没等到的用 untitled/（但要确认不是旧的）
        for name in os.listdir(base):
            p = os.path.join(base, name)
            if os.path.isdir(p) and name == "untitled" and p not in [os.path.join(base, x) for x in pre_names]:
                files = [f for f in os.listdir(p)]
                if any(f.lower().endswith((".mp4", ".mov")) for f in files):
                    found = p
                    break
    if not found:
        raise RuntimeError("等待抖音落盘超时")
    # 归档: 统一到 抖音/日期/标题/标题.mp4
    target = os.path.join(base, title)
    os.makedirs(target, exist_ok=True)
    # 移动文件并重命名视频为 标题.mp4
    for f in list(os.listdir(found)):
        if f.startswith("."):
            continue
        src = os.path.join(found, f)
        if f.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            # 视频统一命名 标题.mp4（并发时旧目录可能残留同名，覆盖处理）
            dst = os.path.join(target, f"{title}.mp4")
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(src, dst)
        elif f.lower().endswith((".jpg", ".jpeg", ".png")):
            # 图文图片保持原名或按序号
            nm = re.match(r"image_0*(\d+)\.(jpg|jpeg|png)", f.lower())
            if nm:
                dst = os.path.join(target, f"{title}_{nm.group(1)}.{nm.group(2)}")
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)
            else:
                shutil.move(src, os.path.join(target, f))
        elif f.endswith(".mp3"):
            os.remove(src)  # 图文音频不需要
        else:
            shutil.move(src, os.path.join(target, f))
    # 清掉空的源目录
    if os.path.isdir(found) and os.listdir(found) == []:
        try:
            os.rmdir(found)
        except Exception:
            pass
    rel = os.path.join("抖音", today(), title)
    d = os.path.join(MEDIA, rel)
    # 判断图文：目录里有图片且无视频
    is_图文 = any(f.lower().endswith((".jpg", ".jpeg", ".png")) for f in os.listdir(d)) and \
             not any(f.lower().endswith((".mp4", ".mov", ".webm")) for f in os.listdir(d))
    gen_thumb(d, title, is_video=not is_图文)
    return rel, title, "抖音", author


# ── 小红书 ─────────────────────────────────────────────
def xhs_expand(url):
    """展开 xhslink 短链，返回 (real_url, note_id, xsec_token, type)"""
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA_I}), timeout=15)
    real = r.geturl()
    m = re.search(r"/discovery/item/([a-f0-9]{24})", real)
    if not m:
        raise RuntimeError("小红书短链展开失败")
    nid = m.group(1)
    # token 在展开后的 real URL 里(xhslink短链本身不含)，其次才可能从原url带
    tok = re.search(r"xsec_token=([A-Za-z0-9_\-]+)=", real)
    if not tok:
        tok = re.search(r"xsec_token=([A-Za-z0-9_\-]+)=", url or "")
    tok = tok.group(1) if tok else None
    # type 从 real URL 的 type=video / type=normal
    typ = "normal"
    tm = re.search(r"type=(\w+)", real)
    if tm:
        typ = tm.group(1)
    return real, nid, tok, typ


def xhs_get_page(real_url, nid, tok):
    """抓页面。实测(2026-08-18): 带 cookie 反而触发反爬返回 ~10KB JS 壳，
    不带 cookie + token + 桌面UA 成功(861KB 含 masterUrl)。token 失效时返回空壳→抛错"""
    url = f"https://www.xiaohongshu.com/discovery/item/{nid}"
    if tok:
        url += f"?xsec_source=app_share&xsec_token={tok}="
    # 只试桌面 UA + token(不带cookie)，与手动 curl 成功方式一致
    for ua in (UA_D, UA_I):
        try:
            headers = {"User-Agent": ua, "Referer": "https://www.xiaohongshu.com/"}
            req = urllib.request.Request(url, headers=headers)
            html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
            if len(html) > 10000 and ("masterUrl" in html or "imageList" in html or ("nickname" in html and '"title"' in html)):
                return html, nid
        except Exception:
            pass
    raise RuntimeError("小红书页面抓取失败(可能是 xsec_token 过期,需在App重新分享该链接)")


def xhs_download_video(html, nid, title, author):
    """挖 258/309 流下载视频"""
    m = re.search(r'"masterUrl":"([^"]+)"', html)
    if not m:
        raise RuntimeError("无 masterUrl")
    vurl = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
    data = fetch(vurl, timeout=120, referer="https://www.xiaohongshu.com/")
    d = os.path.join(MEDIA, "小红书", today(), title)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{title}.mp4"), "wb") as f:
        f.write(data)
    gen_thumb(d, title, is_video=True)
    return os.path.join("小红书", today(), title)


def xhs_download_images(html, nid, title, author, real_url):
    """图文: 优先 XHS-Downloader 无水印原图; 失败降级 sns-webpic 直抓"""
    d = os.path.join(MEDIA, "小红书", today(), title)
    os.makedirs(d, exist_ok=True)
    # 尝试 XHS-Downloader(无水印原图)
    cookie_file = os.environ.get("XHS_COOKIE_FILE", "/vol1/@appdata/trim.hermes/workspace/xhs_cookie.txt")
    if os.path.isfile(cookie_file) and os.path.isfile(XHS_VENV):
        tok = re.search(r"xsec_token=([A-Za-z0-9_\-]+)=", real_url or "")
        url = f"https://www.xiaohongshu.com/discovery/item/{nid}"
        if tok:
            url += f"?xsec_source=app_share&xsec_token={tok.group(1)}="
        cookie = open(cookie_file, encoding="utf-8").read().strip()
        work = f"/tmp/xhs_worker_{nid}"
        shutil.rmtree(work, ignore_errors=True)
        try:
            xhs_dir = os.environ.get("XHS_DIR", "/vol1/@appdata/trim.hermes/workspace/xhs-downloader")
            subprocess.run(
                [XHS_VENV, os.path.join(xhs_dir, "main.py"),
                 "--url", url, "--cookie", cookie, "--work_path", work,
                 "--image_format", "PNG", "--download_record", "false"],
                capture_output=True, timeout=150)
            pngs = glob.glob(os.path.join(work, "Download", "**", "*.png"), recursive=True) + \
                   glob.glob(os.path.join(work, "Download", "*.png"), recursive=True)
            if pngs:
                pngs.sort()
                for i, p in enumerate(pngs, 1):
                    shutil.copy(p, os.path.join(d, f"{title}_{i}.png"))
                gen_thumb(d, title, is_video=False)
                return os.path.join("小红书", today(), title)
        except Exception:
            pass
    # 降级: sns-webpic 直抓(带水印)
    urls = re.findall(r'https?://sns-webpic[^"\\s\\]|\\"\\'']+', html)
    urls = [u for u in urls if "h5_1080" in u or "!nd_prv" in u or "!nd_dft" in u]
    seen, picked = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            picked.append(u.replace("\\u002F", "/"))
    if not picked:
        # 裸 http URL
        picked = re.findall(r'https?://sns-webpic-qc\.xhscdn\.com[^"\\s\\]+?h5_1080[^"\\s]*', html)
        picked = [u.replace("\\u002F", "/") for u in picked]
        seen, dedup = set(), []
        for u in picked:
            if u not in seen:
                seen.add(u)
                dedup.append(u)
        picked = dedup
    ok = 0
    for i, u in enumerate(picked[:20], 1):
        try:
            data = fetch(u, timeout=60, referer="https://www.xiaohongshu.com/")
            open(os.path.join(d, f"{title}_{i}.jpg"), "wb").write(data)
            ok += 1
        except Exception:
            pass
    if ok == 0:
        raise RuntimeError("小红书图文下载失败(无水印+水印都拿不到)")
    gen_thumb(d, title, is_video=False)
    return os.path.join("小红书", today(), title)


def download_xiaohongshu(url):
    real, nid, tok, typ = xhs_expand(url)
    html, _ = xhs_get_page(real, nid, tok)
    # 提取标题：优先 <title>（权威「笔记标题 - 小红书」），再 note JSON，最后 fallback
    mt = re.search(r'<title>([^<]*?)</title>', html)
    title = None
    if mt:
        t = mt.group(1).replace(" - 小红书", "").strip()
        if t and t != "小红书":
            title = t
    if not title:
        mn = re.search(r'"title":"([^"]*)"', html)
        if mn and mn.group(1) and "想了解" not in mn.group(1):
            title = mn.group(1)
    title = clean_title(title or "小红书笔记")
    author = "小红书用户"
    ma = re.search(r'"nickname":"([^"]*)"', html)
    if ma:
        author = ma.group(1)
    if typ == "video" or ('"masterUrl"' in html and '"imageList"' not in html):
        rel = xhs_download_video(html, nid, title, author)
        return rel, title, "小红书"
    else:
        rel = xhs_download_images(html, nid, title, author, real)
        return rel, title, "小红书"


# ── 主流程 ─────────────────────────────────────────────
def ingest(rel, title, url, platform, author=None):
    r = subprocess.run([PY, INGEST, "--platform", platform, "--url", url,
                        "--path", rel, "--title", title,
                        *(["--author", author] if author and author != "未知作者" else [])],
                       capture_output=True, timeout=60)
    out = (r.stdout or b"").decode("utf-8", "ignore")
    # 去重拦截或被跳过：下载的文件不会入库 → 清掉已下载目录防残留
    if "已收藏过" in out or "跳过" in out:
        d = os.path.join(MEDIA, rel)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        return False
    return True


def process_one(item):
    url = item["url"].strip()
    if not url.startswith("http"):
        item["status"] = "failed"
        item["message"] = "无效链接"
        return
    try:
        author = None
        if "douyin" in url or "iesdouyin" in url:
            rel, title, plat, author = download_douyin(url)
        elif "xhslink" in url or "xiaohongshu" in url:
            rel, title, plat = download_xiaohongshu(url)
        else:
            item["status"] = "failed"
            item["message"] = "不支持的平台(仅支持抖音/小红书)"
            return
        ingest(rel, title, item.get("original_url") or url, plat, author=author or None)
        item["status"] = "done"
        item["title"] = title
        item["path"] = rel
        item["message"] = "完成"
    except Exception as e:
        item["status"] = "failed"
        item["message"] = str(e)[:150]


def drain():
    q = load_queue()
    if not q:
        return
    # 清理：done(成功已入库)清掉；failed 保留1天(超时自动清)；pending/processing保留
    now_ts = time.time()
    kept = []
    for it in q:
        st = it.get("status")
        if st == "done":
            continue  # 成功直接删
        if st == "failed":
            # 超过1天自动清（86400s），保留原因供短期查看
            try:
                ct = datetime.strptime(it.get("created_at", ""), "%Y-%m-%d %H:%M:%S")
                if now_ts - ct.timestamp() > 86400:
                    continue
            except Exception:
                pass  # created_at 无法解析则保留
        kept.append(it)
    if len(kept) != len(q):
        q = kept
        save_queue(q)
    if not q:
        return
    changed = False
    for item in q:
        if item.get("status") not in ("pending", "processing"):
            continue
        item["status"] = "processing"
        changed = True
    if changed:
        save_queue(q)
    # 处理一个, 立即保存, 避免长阻塞
    for item in q:
        if item.get("status") == "processing":
            process_one(item)
            # 成功的立即从队列移除(已入库)；失败的保留(原因让用户看)
            if item.get("status") == "done":
                q = [it for it in q if it.get("id") != item.get("id")]
            save_queue(q)
            break  # 每次调用只处理一个，防超时; 下个周期处理下一个


def main():
    # cron no_agent 直接跑脚本(不带参数) → 默认执行 drain; --drain 仅是显式同效
    # 简单锁防并发
    if os.path.isfile(LOCK):
        try:
            age = time.time() - os.path.getmtime(LOCK)
            if age < 90:
                return  # 上次还在跑(超90s才允许重入)
        except Exception:
            pass
    open(LOCK, "w").close()
    try:
        drain()
    finally:
        try:
            os.remove(LOCK)
        except Exception:
            pass


if __name__ == "__main__":
    main()
