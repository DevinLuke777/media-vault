#!/usr/bin/env python3
# 内容收藏库 - 建库脚本
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_library.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
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
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_platform ON items(platform)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_date ON items(post_date)")
    conn.commit()
    conn.close()
    print(f"✅ 数据库已就绪: {DB_PATH}")

if __name__ == "__main__":
    init_db()
