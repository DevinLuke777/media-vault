# 🏛️ media-vault 媒体宝库

自托管**内容收藏库**：把社交平台（小红书/抖音/微博/TikTok/X）的图文视频下载后自动归档，网页浏览/播放/搜索，支持作者筛选与双时间排序。

```
用户发链接 → 下载（轻解析/备用通道）→ 媒体文件存 NAS + 元数据入库
→ 网页卡片流浏览 / 视频播放 / 图片灯箱 / 搜索筛选
```

## ✨ 功能

- 🎴 瀑布流卡片（缩略图 + 平台标签 + 作者 + 时间）
- 🔍 搜索（标题/作者/内容）、平台筛选、**作者点击筛选**
- 🕐 双时间（发布 + 采集）+ 排序切换
- 🎬 视频内联播放、图片网格 + **Lightbox 灯箱**
- 👤 作者头像本地代理（防外链打乱布局）
- 🖼️ 自动缩略图（视频抽帧/图片缩放）

## 📦 快速部署（Docker）

```bash
git clone https://github.com/<你的用户名>/media-vault.git
cd media-vault

# 1. 准备媒体目录（可选，先建空目录也行）
mkdir -p /path/to/your/media   # 之后按 平台/日期/标题 结构放内容

# 2. 改 docker-compose.yml 里的媒体路径
vim docker-compose.yml   # /path/to/your/media → 你的实际路径

# 3. 启动
docker compose up -d --build

# 4. 打开
# http://你的IP:8090
```

## 🔧 手动部署（不用 Docker）

```bash
pip install flask
python3 init_db.py          # 建库
MEDIA_ROOT=/path/to/media python3 app.py   # 启动 Web
```

## 📥 内容入库

媒体目录结构要求：`媒体根目录/平台/日期/标题/文件`（与轻解析下载目录一致）

```bash
# 方式1：扫描目录自动补录（只有平台/标题/日期，无作者）
python3 ingest.py --scan

# 方式2：指定原链接入库（自动抓作者/标题/发布时间/原链接）
python3 ingest.py --platform 小红书 --url "https://xhslink.cn/xxx" --path "小红书/2026-08-08/标题"

# 生成缩略图（新内容入库后跑）
python3 gen_thumbs.py
```

## 🧠 元数据采集

| 平台 | 元数据源 | 媒体下载 |
|------|---------|---------|
| 小红书 | 页面 JSON（title/nickName/avatar/time）| 视频=309 流无水印；图文=ci.xiaohongshu.com 无水印通道 |
| 抖音 | 轻解析 API（需自建轻解析服务）| 轻解析 |
| 微博 | m.weibo.cn API | original 原图 + live 图 |
| TikTok | tikwm API | tikwm |
| X/推特 | yt-dlp | yt-dlp |

> 采集脚本是通用参考实现，各平台反爬策略变化快，可能需要按当时情况调整。

## ⚠️ 踩坑记录

1. 小红书 259 流带水印 → 必须抓 `_309.mp4` 流
2. 小红书图文 CDN 图带水印 → 用 `ci.xiaohongshu.com/notes_pre_post/{id}` 通道
3. 图片条目必须生成 `_thumb.jpg`（否则卡片加载原图卡死）
4. 外链头像不能直接渲染（手机浏览器打碎布局）→ 走 `/avatar/<id>` 代理
5. 平台"X"标签显示为「推特」（避免误认关闭按钮）
6. Docker 内 `MEDIA_ROOT=/media`（挂载点），宿主机脚本用实际路径
7. `original_url` 不能存空串（UNIQUE 冲突）→ scan 用 `scan://路径` 占位

## 📁 项目结构

```
app.py           # Web 应用（列表/详情/搜索/头像代理/自动建库）
ingest.py        # 入库脚本（抓元数据 / 扫描目录）
gen_thumbs.py    # 缩略图生成
init_db.py       # 手动建库
Dockerfile       # 镜像（python:3.11-slim + flask）
docker-compose.yml
```

## 🔒 隐私说明

- 数据库、头像、媒体文件都在 `.gitignore` 中，**不会提交到仓库**
- 本仓库只含代码，不含任何收藏数据

## 📄 License

MIT
