#!/usr/bin/env python3
"""
media-vault Web 展示应用 v4 — 全部重写
列表页：瀑布流卡片（缩略图 + 标题 + 作者/日期同一行）
详情页：标题 + 作者信息条 + 正文 + 视频播放 + 图片网格(lightbox)
"""
import os, re, sqlite3
from flask import Flask, render_template_string, request, abort, url_for, Response

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "media_library.db"))
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")

app = Flask(__name__)

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

_avatar_cache = {}

# ─── 列表页 ──────────────────────────────────────────
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache,no-store,must-revalidate">
<title>媒体宝库</title>
<style>
:root{--accent:#5b6ef5;--bg:#f0f0f5;--card:#fff;--text:#1a1a1a;--sub:#888;--border:#ececf0}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);-webkit-tap-highlight-color:transparent}

/* 顶栏 */
.topbar{position:sticky;top:0;z-index:100;background:var(--card);border-bottom:1px solid var(--border);padding:12px 16px}
.topbar h1{font-size:18px;font-weight:700;margin-bottom:10px}
.search-row{display:flex;gap:8px}
.search-row input{flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:20px;font-size:14px;outline:none;background:#f8f8fc}
.search-row input:focus{border-color:var(--accent)}
.filter-row{display:flex;gap:6px;margin-top:8px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.chip{padding:5px 14px;border-radius:20px;font-size:13px;white-space:nowrap;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--sub);transition:.15s}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.chip select{border:none;background:transparent;font-size:13px;outline:none}

/* 统计 */
.stat-bar{padding:8px 16px;font-size:12px;color:var(--sub)}

/* 瀑布流 */
.masonry{column-count:2;column-gap:10px;padding:0 10px 20px}
@media(min-width:600px){.masonry{column-count:3}}
@media(min-width:900px){.masonry{column-count:4}}

/* 卡片 */
.card{break-inside:avoid;margin-bottom:10px;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);display:block;text-decoration:none;color:inherit;transition:box-shadow .15s}
.card:active{box-shadow:0 0 0 2px var(--accent)}

/* 缩略图 */
.cover{position:relative;width:100%;overflow:hidden;background:#e8e8ee}
.cover img{width:100%;display:block;object-fit:cover}
.cover .empty{height:140px;display:flex;align-items:center;justify-content:center;font-size:36px;color:#ccc}
.cover .tag{position:absolute;top:6px;left:6px;background:rgba(0,0,0,.6);color:#fff;font-size:10px;padding:2px 8px;border-radius:12px}
.cover .play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:40px;height:40px;background:rgba(0,0,0,.5);border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:16px;pointer-events:none}

/* 信息行 */
.info{padding:8px 10px;display:flex;align-items:center;gap:4px}
.info .av{width:20px;height:20px;border-radius:50%;flex-shrink:0;background:#eee;object-fit:cover}
.info .av.hide{display:none}
.info .who{font-size:12px;color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;text-decoration:none}
.info .when{font-size:10px;color:var(--sub);flex-shrink:0}

.no-result{padding:80px 20px;text-align:center;color:var(--sub);font-size:15px}
</style>
</head>
<body>
<div class="topbar">
  <h1>媒体宝库</h1>
  <form class="search-row" method="get">
    <input type="text" name="q" placeholder="搜索标题/作者/内容…" value="{{ q }}">
  </form>
  <div class="filter-row">
    <span class="chip {% if not platform %}active{% endif %}" onclick="location.href='{{ url_no_plat }}'">全部</span>
    {% for p in platforms %}
    <span class="chip {% if platform==p %}active{% endif %}" onclick="location.href='/?platform={{ p|urlencode }}{% if q %}&q={{ q|urlencode }}{% endif %}{% if sort %}&sort={{ sort }}{% endif %}'">{{ '推特' if p == 'X' else p }}</span>
    {% endfor %}
    <span class="chip" style="border:none">
      <select onchange="location.href=this.value" style="color:var(--sub)">
        <option value="{{ url_created }}" {% if sort=='created' %}selected{% endif %}>最新采集</option>
        <option value="{{ url_posted }}" {% if sort=='posted' %}selected{% endif %}>最新发布</option>
      </select>
    </span>
  </div>
</div>

<div class="stat-bar">共 {{ total }} 条收藏{% if author %} · 作者: {{ author }}{% endif %}</div>

{% if not items %}
<div class="no-result">没有找到内容</div>
{% endif %}

<div class="masonry">
{% for it in items %}
<a class="card" href="/item/{{ it['id'] }}">
  <div class="cover">
    {% if it['cover'] %}
    <img src="{{ url_for('media', relpath=it['cover']) }}" loading="lazy">
    {% else %}
    <div class="empty">{{ '🎬' if it['is_video'] else '🖼️' }}</div>
    {% endif %}
    <span class="tag">{{ '推特' if it['platform'] == 'X' else it['platform'] }}</span>
    {% if it['is_video'] %}<span class="play">▶</span>{% endif %}
  </div>
  <div class="info">
    <img class="av" src="/avatar/{{ it['id'] }}" onerror="this.classList.add('hide')">
    <span class="who">{{ it['title'] or '无标题' }}</span>
    <span class="when">{{ it['created_at'][:10] if it['created_at'] else '' }}</span>
  </div>
</a>
{% endfor %}
</div>
</body>
</html>"""


# ─── 详情页 ──────────────────────────────────────────
DETAIL_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ it['title'] or '详情' }} - 媒体宝库</title>
<style>
:root{--accent:#5b6ef5;--bg:#f0f0f5;--card:#fff;--text:#1a1a1a;--sub:#888;--border:#ececf0}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text)}

.page{max-width:860px;margin:0 auto;padding:16px}
.back{font-size:14px;color:var(--accent);text-decoration:none;display:inline-block;margin-bottom:12px}

.card-box{background:var(--card);border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.06)}

/* 标题 */
.title{padding:16px 16px 0;font-size:18px;font-weight:700;line-height:1.4}

/* 作者信息条 — 纯 flex 行 */
.author-bar{padding:10px 16px;display:flex;align-items:center;gap:8px}
.author-bar .av{width:32px;height:32px;border-radius:50%;flex-shrink:0;background:#eee;object-fit:cover}
.author-bar .av.hide{display:none}
.author-bar .name{font-size:14px;color:var(--accent);text-decoration:none;font-weight:500}
.author-bar .plat{font-size:11px;color:var(--sub);background:#f0f0f5;padding:2px 8px;border-radius:12px}
.author-bar .time{font-size:12px;color:var(--sub);margin-left:auto;white-space:nowrap}

/* 正文 */
.content{padding:0 16px 12px;font-size:14px;line-height:1.6;color:#444;white-space:pre-wrap}

/* 媒体预览 */
.media-area{padding:0 16px 16px}
.media-area video{width:100%;border-radius:10px;background:#000;margin-bottom:10px}

.img-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px}
.img-grid a{display:block;aspect-ratio:1;overflow:hidden;border-radius:8px;background:#f0f0f4;cursor:pointer}
.img-grid a img{width:100%;height:100%;object-fit:cover}

.single-img{width:100%;border-radius:10px;cursor:pointer}

/* Lightbox */
.lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:9999;align-items:center;justify-content:center;flex-direction:column;padding:16px}
.lb.on{display:flex}
.lb img{max-width:92vw;max-height:78vh;border-radius:6px;object-fit:contain}
.lb .x{position:absolute;top:12px;right:20px;font-size:32px;color:#fff;cursor:pointer;line-height:1}
.lb .nav{position:absolute;top:50%;transform:translateY(-50%);font-size:36px;color:rgba(255,255,255,.6);cursor:pointer;padding:12px;user-select:none}
.lb .nav.l{left:8px}
.lb .nav.r{right:8px}
.lb .cnt{color:rgba(255,255,255,.5);font-size:13px;margin-top:8px}

/* 下载条 */
.dl{padding:0 16px 16px;display:flex;flex-wrap:wrap;gap:8px}
.dl a{font-size:12px;color:var(--accent);text-decoration:none;padding:6px 14px;border:1px solid var(--border);border-radius:8px}
.dl a.vid{color:#e74c3c;border-color:#fcc}

.orig{padding:0 16px 16px;font-size:12px;color:var(--sub);word-break:break-all}
.orig a{color:var(--accent);text-decoration:none}
</style>
</head>
<body>
<div class="page">
  <a class="back" href="/">← 返回</a>
  <div class="card-box">
    <div class="title">{{ it['title'] or '无标题' }}</div>
    <div class="author-bar">
      <img class="av" src="/avatar/{{ it['id'] }}" onerror="this.classList.add('hide')">
      <a class="name" href="/?author={{ it['author_name']|urlencode }}">{{ it['author_name'] or '未知作者' }}</a>
      <span class="plat">{{ '推特' if it['platform'] == 'X' else it['platform'] }}</span>
      <span class="time">{{ it['post_date'][:10] if it['post_date'] else '' }}</span>
    </div>
    {% if it['content'] %}<div class="content">{{ it['content'] }}</div>{% endif %}

    <div class="media-area">
      {% set ns = namespace(imgs=[], vids=[]) %}
      {% for f in files %}
        {% if f.lower().endswith(('.mp4','.mov','.mkv','.webm')) %}
          {% set ns.vids = ns.vids + [f] %}
        {% elif f.lower().endswith(('.jpg','.jpeg','.png','.webp','.gif')) %}
          {% set ns.imgs = ns.imgs + [f] %}
        {% endif %}
      {% endfor %}
      {% for f in ns.vids %}
      <video controls preload="metadata" src="{{ url_for('media', relpath=f) }}"></video>
      {% endfor %}
      {% if ns.imgs|length == 1 %}
      <img class="single-img" src="{{ url_for('media', relpath=ns.imgs[0]) }}" loading="lazy" onclick="openLb(0)">
      {% elif ns.imgs|length > 1 %}
      <div class="img-grid">
        {% for f in ns.imgs %}
        <a href="javascript:void(0)" onclick="openLb({{ loop.index0 }})"><img src="{{ url_for('media', relpath=f) }}" loading="lazy"></a>
        {% endfor %}
      </div>
      {% endif %}
    </div>

    <div class="dl">
      {% for f in files %}
      <a class="{{ 'vid' if f.lower().endswith(('.mp4','.mov','.mkv','.webm')) else '' }}" href="{{ url_for('media', relpath=f) }}" target="_blank">{{ f.split('/')[-1][-20:] }}</a>
      {% endfor %}
    </div>
    {% if it['original_url'] %}<div class="orig">🔗 <a href="{{ it['original_url'] }}" target="_blank">{{ it['original_url'] }}</a></div>{% endif %}
  </div>
</div>

{% if ns.imgs %}
<div class="lb" id="lb" onclick="closeLb(event)">
  <span class="x" onclick="closeLb(event)">&times;</span>
  <span class="nav l" onclick="lbStep(event,-1)">&#10094;</span>
  <img id="lbImg" src="">
  <span class="nav r" onclick="lbStep(event,1)">&#10095;</span>
  <div class="cnt" id="lbCnt"></div>
</div>
<script>
var imgs={{ ns.imgs|map('urlencode')|list|tojson }},idx=0,base="{{ url_for('media', relpath='') }}";
function openLb(i){idx=i;document.getElementById('lb').classList.add('on');show()}
function show(){document.getElementById('lbImg').src=base+imgs[idx];document.getElementById('lbCnt').textContent=(idx+1)+'/'+imgs.length}
function closeLb(e){if(e.target.tagName==='IMG'||e.target.classList.contains('nav'))return;document.getElementById('lb').classList.remove('on')}
function lbStep(e,d){e.stopPropagation();idx=(idx+d+imgs.length)%imgs.length;show()}
document.addEventListener('keydown',function(e){if(!document.getElementById('lb').classList.contains('on'))return;if(e.key==='Escape')document.getElementById('lb').classList.remove('on');if(e.key==='ArrowLeft')lbStep(e,-1);if(e.key==='ArrowRight')lbStep(e,1)});
</script>
{% endif %}
</body>
</html>"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]

def list_files(rel):
    if not rel:
        return []
    d = os.path.join(MEDIA_ROOT, rel)
    if not os.path.isdir(d):
        return []
    files = []
    for f in sorted(os.listdir(d), key=_natural_key):
        if f.startswith(".") or f == "_thumb.jpg":
            continue
        files.append(os.path.join(rel, f).replace("\\", "/"))
    return files

from urllib.parse import urlencode
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    plat = request.args.get("platform", "").strip()
    author = request.args.get("author", "").strip()
    sort = request.args.get("sort", "created")
    conn = db()
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR author_name LIKE ? OR content LIKE ?)")
        params += [f"%{q}%"] * 3
    if plat:
        where.append("platform = ?")
        params.append(plat)
    if author:
        where.append("author_name = ?")
        params.append(author)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    order = "created_at DESC, id DESC" if sort == "created" else "post_date DESC, id DESC"
    items = conn.execute(f"SELECT * FROM items {wsql} ORDER BY {order}", params).fetchall()
    platforms = [r["platform"] for r in conn.execute("SELECT DISTINCT platform FROM items ORDER BY platform")]
    conn.close()
    card_items = []
    for it in items:
        files = list_files(it["local_path"])
        cover = None
        is_video = False
        thumb = os.path.join(it["local_path"], "_thumb.jpg").replace("\\", "/")
        if os.path.isfile(os.path.join(MEDIA_ROOT, thumb)):
            cover = thumb
        for f in files:
            low = f.lower()
            if low.endswith(IMAGE_EXT) and cover is None:
                cover = f
            if low.endswith(VIDEO_EXT):
                is_video = True
        card_items.append({**dict(it), "cover": cover, "is_video": is_video})

    base_args = {}
    if q: base_args["q"] = q
    if sort: base_args["sort"] = sort
    url_no_plat = "/?" + urlencode(base_args)
    created_args = dict(base_args)
    created_args["sort"] = "created"
    posted_args = dict(base_args)
    posted_args["sort"] = "posted"
    if plat:
        created_args["platform"] = plat
        posted_args["platform"] = plat

    return render_template_string(INDEX_HTML,
        items=card_items, platforms=platforms, q=q, platform=plat,
        total=len(card_items), author=author, sort=sort,
        url_no_plat=url_no_plat,
        url_created="/?" + urlencode(created_args),
        url_posted="/?" + urlencode(posted_args))

@app.route("/item/<int:item_id>")
def detail(item_id):
    conn = db()
    it = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not it:
        abort(404)
    files = list_files(it["local_path"])
    return render_template_string(DETAIL_HTML, it=dict(it), files=files)
@app.route("/avatar/<int:item_id>")
def avatar(item_id):
    """作者头像代理：优先读本地预下载文件，其次服务端拉取外链，带内存缓存"""
    local_avatar = os.path.join(BASE, "avatars", f"{item_id}.jpg")
    if os.path.isfile(local_avatar):
        from flask import send_file
        return send_file(local_avatar)
    conn = db()
    it = conn.execute("SELECT author_avatar FROM items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not it or not it["author_avatar"]:
        abort(404)
    url = it["author_avatar"]
    cached = _avatar_cache.get(url)
    if cached:
        return Response(cached, content_type="image/jpeg")
    import urllib.request
    try:
        referer = "https://weibo.com/"
        if "xhscdn" in url:
            referer = "https://www.xiaohongshu.com/"
        elif "douyinpic" in url or "douyin" in url:
            referer = "https://www.douyin.com/"
        elif "twimg" in url:
            referer = "https://x.com/"
        elif "tiktokcdn" in url:
            referer = "https://www.tiktok.com/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1", "Referer": referer})
        data = urllib.request.urlopen(req, timeout=10).read()
        if len(data) > 500000:
            abort(404)
        _avatar_cache[url] = data
        return Response(data, content_type="image/jpeg")
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=10).read()
            if len(data) > 500000:
                abort(404)
            _avatar_cache[url] = data
            return Response(data, content_type="image/jpeg")
        except Exception:
            abort(404)

@app.route("/media/<path:relpath>")
def media(relpath):
    full = os.path.realpath(os.path.join(MEDIA_ROOT, relpath))
    root = os.path.realpath(MEDIA_ROOT)
    if not full.startswith(root):
        abort(403)
    if not os.path.isfile(full):
        abort(404)
    from flask import send_file
    return send_file(full)

def ensure_db():
    """启动时自动建库（容器首次挂载空目录时）"""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        title TEXT,
        content TEXT,
        author_name TEXT,
        author_avatar TEXT,
        post_date TEXT,
        original_url TEXT,
        local_path TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(original_url)
    )""")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    ensure_db()
    app.run(host="0.0.0.0", port=8090)