import sqlite3
import datetime

DB_NAME = 'users.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        username TEXT,
        join_date TEXT,
        invite_link TEXT,
        photo_url TEXT,
        label TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        sender TEXT,
        message TEXT,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

def add_user(user_id, full_name, username, join_date, invite_link=None, photo_url=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, full_name, username, join_date, invite_link, photo_url) VALUES (?, ?, ?, ?, ?, ?)', (user_id, full_name, username, join_date, invite_link, photo_url))
    c.execute('UPDATE users SET invite_link = ?, photo_url = ? WHERE user_id = ?', (invite_link, photo_url, user_id))
    conn.commit()
    conn.close()

def get_total_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total = c.fetchone()[0]
    conn.close()
    return total

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id, full_name, username, join_date, invite_link, photo_url FROM users')
    users = c.fetchall()
    conn.close()
    return users

def save_message(user_id, sender, message, timestamp=None):
    if timestamp is None:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)', (user_id, sender, message, timestamp))
    conn.commit()
    conn.close()

def get_messages_for_user(user_id, limit=100):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT sender, message, timestamp FROM messages WHERE user_id = ? ORDER BY id ASC LIMIT ?', (user_id, limit))
    messages = c.fetchall()
    conn.close()
    return messages 