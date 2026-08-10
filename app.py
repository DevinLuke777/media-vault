#!/usr/bin/env python3
"""
media-vault Web 展示应用 v4 — 全部重写
列表页：瀑布流卡片（缩略图 + 标题 + 作者/日期同一行）
详情页：标题 + 作者信息条 + 正文 + 视频播放 + 图片网格(lightbox)
"""
import os, re, sqlite3
from flask import Flask, render_template_string, request, abort, url_for, Response, redirect

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
.masonry{display:flex;gap:10px;padding:0 10px 20px;align-items:flex-start}
.col{flex:1;min-width:0;display:flex;flex-direction:column;gap:10px}

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
  <h1>媒体宝库 <a href="/stats" style="font-size:13px;color:#eef;text-decoration:none;margin-left:8px;background:rgba(255,255,255,.2);padding:4px 10px;border-radius:20px">📊 统计</a> <a href="/?mode=manage" style="font-size:13px;color:#eef;text-decoration:none;margin-left:6px;background:rgba(255,255,255,.2);padding:4px 10px;border-radius:20px">🗑️ 管理</a></h1>
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

{% if mode == 'manage' %}
<form method="post" action="/delete-batch" id="batchForm" onsubmit="return confirm('确定删除选中的收藏？本地文件也会一并删除！')" style="width:100%;margin:0;padding:0">
{% endif %}
<div class="masonry" {% if mode == 'manage' %}style="padding-bottom:70px"{% endif %}>
{% for col in columns %}
<div class="col">
{% for it in col %}
{% if mode == 'manage' %}
<div style="position:relative;width:100%">
  <input type="checkbox" name="ids" value="{{ it['id'] }}" style="position:absolute;top:8px;right:8px;z-index:5;width:20px;height:20px;accent-color:#e74c3c">
{% endif %}
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
{% if mode == 'manage' %}
</div>
{% endif %}
{% endfor %}
</div>
{% endfor %}
{% if mode == 'manage' %}
<div style="position:fixed;bottom:0;left:0;right:0;background:var(--card);padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center;z-index:50;box-shadow:0 -2px 8px rgba(0,0,0,.08)">
  <label style="font-size:13px;color:var(--sub);display:flex;align-items:center;gap:4px"><input type="checkbox" id="selAll" style="width:16px;height:16px"> 全选</label>
  <button type="submit" style="background:#e74c3c;color:#fff;border:none;padding:8px 20px;border-radius:8px;font-size:13px;cursor:pointer">删除选中</button>
  <a href="/" style="font-size:13px;color:var(--sub);text-decoration:none">退出管理</a>
</div>
</form>
<script>document.getElementById('selAll').onchange=function(){document.querySelectorAll('input[name=ids]').forEach(function(c){c.checked=this.checked},this)}</script>
{% endif %}
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
      <span class="time" style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;line-height:1.3"><span>🕐 {{ it['post_date'][:19] if it['post_date'] else '' }}</span><span>📥 {{ it['created_at'][:19] if it['created_at'] else '' }}</span></span>
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

    {% if it['original_url'] %}<div class="orig">🔗 <a href="{{ it['original_url'] }}" target="_blank">{{ it['original_url'] }}</a></div>{% endif %}
    <div style="margin-top:20px;border-top:1px solid var(--border);padding-top:16px">
      <form method="post" action="/delete/{{ it['id'] }}" onsubmit="return confirm('确定删除这条收藏？本地文件也会一并删除！')">
        <button type="submit" style="background:#e74c3c;color:#fff;border:none;padding:10px 22px;border-radius:8px;font-size:14px;cursor:pointer">🗑️ 删除这条收藏</button>
      </form>
    </div>
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
    mode = request.args.get("mode", "")  # manage=批量管理模式
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
    platforms = [r["platform"] for r in conn.execute("SELECT platform, COUNT(*) c FROM items GROUP BY platform ORDER BY c DESC")]
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

    return render_template_string(INDEX_HTML,
        items=card_items, columns=[card_items[0::2], card_items[1::2]],
        platforms=platforms, q=q, platform=plat,
        total=len(card_items), author=author, sort=sort, mode=mode,
        url_no_plat=url_no_plat,
        url_created="/?" + urlencode(created_args),
        url_posted="/?" + urlencode(posted_args))

@app.route("/stats")
def stats():
    """统计面板：平台分布 / 作者Top / 收藏趋势"""
    conn = db()
    platforms = conn.execute("SELECT platform, COUNT(*) c FROM items GROUP BY platform ORDER BY c DESC").fetchall()
    authors = conn.execute("SELECT author_name, COUNT(*) c FROM items WHERE author_name IS NOT NULL AND author_name != '' GROUP BY author_name ORDER BY c DESC LIMIT 10").fetchall()
    trend = conn.execute("SELECT substr(created_at,1,10) d, COUNT(*) c FROM items GROUP BY d ORDER BY d DESC LIMIT 14").fetchall()
    trend = list(reversed(trend))  # 旧→新
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    max_p = max((r["c"] for r in platforms), default=1)
    max_a = max((r["c"] for r in authors), default=1)
    return render_template_string(STATS_HTML, platforms=platforms, authors=authors,
                                  trend=trend, total=total, max_p=max_p, max_a=max_a)

STATS_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>统计 - 媒体宝库</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6fa;color:#222;padding:20px;max-width:760px;margin:0 auto}
h1{font-size:20px;margin-bottom:20px}
.back{display:inline-block;margin-bottom:16px;color:#667eea;text-decoration:none;font-size:14px}
.card{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card h2{font-size:15px;margin-bottom:14px;color:#444}
.row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.row .label{width:90px;font-size:13px;color:#666;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{height:22px;background:linear-gradient(90deg,#667eea,#764ba2);border-radius:4px;min-width:2px;transition:width .4s}
.row .num{font-size:12px;color:#999;flex-shrink:0}
.total{font-size:14px;color:#888;margin-bottom:16px}
.trend-grid{display:flex;align-items:flex-end;gap:4px;height:120px;padding-top:10px}
.trend-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end}
.trend-bar{width:70%;background:linear-gradient(180deg,#667eea,#764ba2);border-radius:3px 3px 0 0;min-height:2px}
.trend-date{font-size:10px;color:#aaa;writing-mode:vertical-rl;transform:rotate(180deg);max-height:34px;overflow:hidden}
</style>
</head>
<body>
<a class="back" href="/">← 返回列表</a>
<h1>📊 媒体宝库统计</h1>
<div class="total">共 {{ total }} 条收藏</div>

<div class="card">
  <h2>🌐 平台分布</h2>
  {% for p in platforms %}
  <div class="row">
    <span class="label">{{ p['platform'] }}</span>
    <div class="bar" style="width:{{ (p['c'] / max_p * 100)|int }}%"></div>
    <span class="num">{{ p['c'] }}</span>
  </div>
  {% endfor %}
</div>

<div class="card">
  <h2>👤 作者 Top 10</h2>
  {% for a in authors %}
  <div class="row">
    <span class="label"><a href="/?author={{ a['author_name']|urlencode }}" style="color:#667eea;text-decoration:none">{{ a['author_name'] }}</a></span>
    <div class="bar" style="width:{{ (a['c'] / max_a * 100)|int }}%"></div>
    <span class="num">{{ a['c'] }}</span>
  </div>
  {% endfor %}
</div>

<div class="card">
  <h2>📈 收藏趋势（近 {{ trend|length }} 天）</h2>
  {% if trend %}
  <div class="trend-grid">
    {% for t in trend %}
    <div class="trend-col" title="{{ t['d'] }}: {{ t['c'] }} 条">
      <div class="trend-bar" style="height:{{ (t['c'] / trend|map(attribute='c')|max * 100)|int }}%"></div>
      <span class="trend-date">{{ t['d'][5:] }}</span>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div style="color:#999;font-size:13px">暂无数据</div>
  {% endif %}
</div>
</body>
</html>"""

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

@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    """删除单条收藏：数据库记录 + 媒体目录文件"""
    conn = db()
    it = conn.execute("SELECT local_path FROM items WHERE id=?", (item_id,)).fetchone()
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    if it and it["local_path"]:
        import shutil
        d = os.path.join(MEDIA_ROOT, it["local_path"])
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return redirect(url_for("index"))

@app.route("/delete-batch", methods=["POST"])
def delete_batch():
    """批量删除：勾选的 ids 一起删（记录 + 文件）"""
    ids = request.form.getlist("ids")
    import shutil
    conn = db()
    for i in ids:
        it = conn.execute("SELECT local_path FROM items WHERE id=?", (i,)).fetchone()
        if it:
            conn.execute("DELETE FROM items WHERE id=?", (i,))
            if it["local_path"]:
                d = os.path.join(MEDIA_ROOT, it["local_path"])
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

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