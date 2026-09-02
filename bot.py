import os
import io
import re
import sqlite3
import uuid
import asyncio
import math
import time
import random
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

# ==================== الإعدادات ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "combos.db")

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

# قائمة الباسوردات الجديدة للتعديل
PASSWORD_REPLACEMENTS = [
    "Aa123456",
    "Aa123456@",
    "Aa123123",
    "Aa12341234",
    "Aa11223344",
    "Aa@123456"
]

app = Client(
    "combo_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp" if os.path.exists("/tmp") else "."
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
        CREATE TABLE IF NOT EXISTS user_tasks (
            user_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, task_name)
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

# ==================== سجل السحوبات + الإحالة ====================
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

# ==================== معالجة الكومبو (عدم التكرار) ====================
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

# ==================== دوال معالجة الملفات والنسخ المزدوج ====================
def process_duplicate_file(file_path: str, domain: str) -> tuple:
    """
    معالجة الملف وإنشاء نسختين:
    1- النسخة الأصلية: نفس المحتوى بدون تعديل
    2- النسخة المعدلة: نفس الإيميلات مع تغيير الباسوردات إلى القائمة المحددة
    """
    original_lines = []
    modified_lines = []
    
    # قراءة الملف
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']:
        try:
            with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        original_lines.append(line_str)
            break
        except Exception:
            continue
    
    if not original_lines:
        return None, None
    
    # إنشاء النسخة المعدلة
    for line in original_lines:
        parts = line.split(':')
        if len(parts) >= 2:
            # الإيميل هو الجزء الأول، الباسورد هو الجزء الأخير
            email = parts[0]
            # اختيار باسورد عشوائي من القائمة
            new_password = random.choice(PASSWORD_REPLACEMENTS)
            modified_lines.append(f"{email}:{new_password}")
        else:
            modified_lines.append(line)
    
    return original_lines, modified_lines

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

# ==================== سحب المالك (خاص بالمالك فقط - شامل وكامل) ====================
async def owner_full_withdrawal(client: Client, domain: str, limit_count: int, message: Message):
    """
    دالة خاصة بسحب المالك - شاملة 100% بدون استثناءات
    تقوم بجلب كافة الحسابات المتاحة للدومين المطلوب مع إنشاء نسختين
    """
    # جلب الكومبوهات من قاعدة البيانات
    results = await fetch_and_delete_combos(domain, limit_count)
    
    if not results:
        await message.reply(f"❌ لا توجد حسابات للدومين `{domain}`.")
        return
    
    # إنشاء ملفين: الأصلي والمعدل
    # النسخة الأصلية
    original_content = "\n".join(results)
    original_file = io.BytesIO(original_content.encode("utf-8"))
    original_file.name = f"{domain}_original_{len(results)}.txt"
    
    # النسخة المعدلة (تغيير الباسوردات)
    modified_lines = []
    for line in results:
        parts = line.split(':')
        if len(parts) >= 2:
            email = parts[0]
            new_password = random.choice(PASSWORD_REPLACEMENTS)
            modified_lines.append(f"{email}:{new_password}")
        else:
            modified_lines.append(line)
    
    modified_content = "\n".join(modified_lines)
    modified_file = io.BytesIO(modified_content.encode("utf-8"))
    modified_file.name = f"{domain}_modified_{len(results)}.txt"
    
    # إرسال الملفين
    await client.send_document(
        chat_id=message.chat.id,
        document=original_file,
        caption=f"📄 <b>النسخة الأصلية</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{len(results):,}</b> حساب\n✅ بدون أي تعديل على الإيميلات أو الباسوردات"
    )
    
    await client.send_document(
        chat_id=message.chat.id,
        document=modified_file,
        caption=f"🔄 <b>النسخة المعدلة</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{len(results):,}</b> حساب\n🔑 تم تغيير الباسوردات إلى القائمة المحددة"
    )
    
    # تسجيل العملية
    record_withdrawal(message.from_user.id, domain, len(results), 0)
    log_search_domain(domain)
    increment_operations()
    
    await message.reply(f"✅ تم سحب <b>{len(results):,}</b> حساب للدومين `{domain}` وإرسال نسختين (أصلية ومعدلة).")

@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id) and not await force_sub_guard(client, message):
        return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("📝 أرسل الدومين المطلوب:")

# ==================== معالجة البحث والسحب ====================
@app.on_message(filters.text & ~filters.regex(r"^(🔍|📤|📊|🗑|✅|🚫|💣|📈|📢|⚙️|🔥|🎁|➕|💰|🔗|📺|💎|📋|👥|📂)"))
async def process_text_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    text_input = message.text.strip()
    state = user_action_state.get(user_id)

    if state == "awaiting_filter_keywords":
        user_filter_keywords[user_id] = [k.strip().lower() for k in re.split(r'[,|\n]', text_input) if k.strip()]
        user_action_state[user_id] = "awaiting_ulp_file"
        await message.reply("✅ أرسل ملف ULP الآن.")
        return

    if state == "awaiting_search_domain":
        user_action_state.pop(user_id, None)
        domain = text_input.lower()
        
        # التحقق من وجود الحسابات
        available = count_available_combos(domain)
        
        if available == 0:
            add_to_waitlist(user_id, domain)
            await message.reply("❌ لا توجد حسابات حالياً. تم إضافتك لقائمة الانتظار.")
            return

        # إذا كان المالك - سحب كامل وشامل
        if is_owner(user_id):
            await message.reply(f"👑 <b>سحب المالك</b>\n🌐 الدومين: `{domain}`\n📊 المتاح: <b>{available:,}</b> حساب\n⏳ جاري السحب الشامل...")
            await owner_full_withdrawal(client, domain, available, message)
            return
        
        # للمستخدمين العاديين - عرض أزرار الاختيار
        msg = await message.reply(f"🎯 متاح لـ `{domain}`: <b>{available:,}</b>\nاختر الكمية:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("100", callback_data=f"get_{domain}_100"),
             InlineKeyboardButton("500", callback_data=f"get_{domain}_500"),
             InlineKeyboardButton("1000", callback_data=f"get_{domain}_1000")],
            [InlineKeyboardButton("2500", callback_data=f"get_{domain}_2500"),
             InlineKeyboardButton("5000", callback_data=f"get_{domain}_5000"),
             InlineKeyboardButton("10000", callback_data=f"get_{domain}_10000")],
            [InlineKeyboardButton(f"📥 سحب الكل ({available:,})", callback_data=f"get_{domain}_all")]
        ]))
        return

    # معالجة الحالات الإدارية الإضافية لضمان عمل الأزرار بالكامل
    if is_owner(user_id):
        if state == "awaiting_delete_domain":
            user_action_state.pop(user_id, None)
            deleted_count = delete_by_domain(text_input)
            await message.reply(f"🗑 تم حذف <b>{deleted_count:,}</b> سطر للدومين `{text_input}`.")
            return
        elif state == "awaiting_send_pts":
            user_action_state.pop(user_id, None)
            try:
                parts = text_input.split()
                target_id = int(parts[0])
                pts_val = float(parts[1])
                add_user_points(target_id, pts_val)
                await message.reply(f"✅ تم إضافة {pts_val} نقطة للعضو `{target_id}`.")
            except Exception:
                await message.reply("❌ صيغة خاطئة. استخدم: `ID AMOUNT`")
            return
        elif state == "awaiting_ref_pts":
            user_action_state.pop(user_id, None)
            try:
                val = float(text_input)
                set_referral_points(val)
                await message.reply(f"✅ تم تحديث نقاط الإحالة إلى: {val}")
            except Exception:
                await message.reply("❌ قيمة غير صالحة.")
            return
        elif state == "awaiting_add_ad":
            user_action_state.pop(user_id, None)
            try:
                parts = text_input.split()
                ch_name = parts[0]
                reward_val = float(parts[1])
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO ad_channels (channel_id, points_reward) VALUES (?, ?)", (ch_name, reward_val))
                conn.commit()
                conn.close()
                await message.reply(f"✅ تم إضافة القناة الإعلانية `{ch_name}` بمكافأة `{reward_val}`.")
            except Exception:
                await message.reply("❌ صيغة خاطئة. استخدم: `@ChannelUsername 1`")
            return
        elif state == "awaiting_ban_user":
            user_action_state.pop(user_id, None)
            try:
                uid = int(text_input)
                update_user_block_status(uid, 1, "حظر إداري")
                await message.reply(f"🚫 تم حظر العضو `{uid}`.")
            except Exception:
                await message.reply("❌ آيدي غير صالح.")
            return
        elif state == "awaiting_unban_user":
            user_action_state.pop(user_id, None)
            try:
                uid = int(text_input)
                update_user_block_status(uid, 0, None)
                await message.reply(f"✅ تم فك حظر العضو `{uid}`.")
            except Exception:
                await message.reply("❌ آيدي غير صالح.")
            return
        elif state == "awaiting_gift_amount":
            user_action_state.pop(user_id, None)
            try:
                pts = float(text_input)
                code = str(uuid.uuid4())[:8]
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO gifts (code, points) VALUES (?, ?)", (code, pts))
                conn.commit()
                conn.close()
                bot_username = (await client.get_me()).username
                await message.reply(f"🎁 رابط الهدية:\nhttps://t.me/{bot_username}?start=gift_{code}")
            except Exception:
                await message.reply("❌ قيمة غير صالحة.")
            return

# ==================== معالجة الكومبو (عدم التكرار) ====================
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

# ==================== معالجة الملفات والنسخ المزدوج (تابع) ====================
def process_duplicate_file(file_path: str, domain: str) -> tuple:
    """
    معالجة الملف وإنشاء نسختين:
    1- النسخة الأصلية: نفس المحتوى بدون تعديل
    2- النسخة المعدلة: نفس الإيميلات مع تغيير الباسوردات إلى القائمة المحددة
    """
    original_lines = []
    modified_lines = []
    
    # قراءة الملف
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']:
        try:
            with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        original_lines.append(line_str)
            break
        except Exception:
            continue
    
    if not original_lines:
        return None, None
    
    # إنشاء النسخة المعدلة
    for line in original_lines:
        parts = line.split(':')
        if len(parts) >= 2:
            email = parts[0]
            new_password = random.choice(PASSWORD_REPLACEMENTS)
            modified_lines.append(f"{email}:{new_password}")
        else:
            modified_lines.append(line)
    
    return original_lines, modified_lines

async def owner_full_withdrawal(client: Client, domain: str, limit_count: int, message: Message):
    """
    دالة خاصة بسحب المالك - شاملة 100% بدون استثناءات
    تقوم بجلب كافة الحسابات المتاحة للدومين المطلوب مع إنشاء نسختين
    """
    # جلب الكومبوهات من قاعدة البيانات
    results = await fetch_and_delete_combos(domain, limit_count)
    
    if not results:
        await message.reply(f"❌ لا توجد حسابات للدومين `{domain}`.")
        return
    
    # إنشاء ملفين: الأصلي والمعدل
    # النسخة الأصلية
    original_content = "\n".join(results)
    original_file = io.BytesIO(original_content.encode("utf-8"))
    original_file.name = f"{domain}_original_{len(results)}.txt"
    
    # النسخة المعدلة (تغيير الباسوردات)
    modified_lines = []
    for line in results:
        parts = line.split(':')
        if len(parts) >= 2:
            email = parts[0]
            new_password = random.choice(PASSWORD_REPLACEMENTS)
            modified_lines.append(f"{email}:{new_password}")
        else:
            modified_lines.append(line)
    
    modified_content = "\n".join(modified_lines)
    modified_file = io.BytesIO(modified_content.encode("utf-8"))
    modified_file.name = f"{domain}_modified_{len(results)}.txt"
    
    # إرسال الملفين
    await client.send_document(
        chat_id=message.chat.id,
        document=original_file,
        caption=f"📄 <b>النسخة الأصلية</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{len(results):,}</b> حساب\n✅ بدون أي تعديل على الإيميلات أو الباسوردات"
    )
    
    await client.send_document(
        chat_id=message.chat.id,
        document=modified_file,
        caption=f"🔄 <b>النسخة المعدلة</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{len(results):,}</b> حساب\n🔑 تم تغيير الباسوردات إلى القائمة المحددة"
    )
    
    # تسجيل العملية
    record_withdrawal(message.from_user.id, domain, len(results), 0)
    log_search_domain(domain)
    increment_operations()
    
    await message.reply(f"✅ تم سحب <b>{len(results):,}</b> حساب للدومين `{domain}` وإرسال نسختين (أصلية ومعدلة).")

# ==================== معالجة الكومبو (عدم التكرار) ====================
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
        [KeyboardButton("📢 إضافة إعلان قناة"), KeyboardButton("🧾 قناة السجل (Audit Log)")],
        [KeyboardButton("💎 إحصائيات النقاط"), KeyboardButton("👥 الأكثر نشاطاً")],
        [KeyboardButton("🚫 حظر عضو"), KeyboardButton("✅ فك حظر عضو")],
        [KeyboardButton("💣 حذف كل البيانات"), KeyboardButton("📈 حالة البوت")]
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

# ==================== فرز ULP ====================
@app.on_message(filters.command("stop") & filters.user(OWNER_IDS))
async def stop_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = False
    await message.reply("🛑 تم إيقاف فرز ULP.")

@app.on_message(filters.command("on") & filters.user(OWNER_IDS))
async def on_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = True
    await message.reply("✅ تم تفعيل فرز ULP.")

@app.on_message(filters.regex("^📂 فرز ملفات ULP$") & filters.user(OWNER_IDS))
async def start_ulp_filter(client: Client, message: Message):
    global ulp_feature_enabled
    if not ulp_feature_enabled:
        await message.reply("⚠️ قسم فرز ULP متوقف. أرسل `/on` لتفعيله.")
        return
    user_id = message.from_user.id
    user_action_state[user_id] = "awaiting_filter_keywords"
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel_ulp_filter")]])
    await message.reply("🎯 أرسل الكلمات المفتاحية أو الدومينات للفرز:", reply_markup=cancel_kb)

@app.on_callback_query(filters.regex("^cancel_ulp_filter$"))
async def cancel_ulp_filter_cb(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    user_action_state.pop(user_id, None)
    user_filter_keywords.pop(user_id, None)
    await callback.answer("تم الإلغاء.")
    await callback.message.edit_text("❌ تم إلغاء الفرز.")

@app.on_message(filters.document)
async def process_ulp_document_filter(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        return

    if user_action_state.get(user_id) == "awaiting_ulp_upload":
        await handle_large_document(client, message)
        return

    global ulp_feature_enabled
    if not ulp_feature_enabled:
        return

    keywords = user_filter_keywords.get(user_id)
    if not keywords:
        return

    saved_ulp_path = None
    output_filename = None
    try:
        file_name = message.document.file_name or "data.ulp"
        msg = await message.reply("⏳ جاري تنزيل الملف والفرز...")
        saved_ulp_path = await client.download_media(message)

        filtered_lines = []
        seen = set()
        keywords_lower = [k.lower().strip() for k in keywords if k.strip()]

        def strict_match(line: str, keys: list) -> bool:
            line_l = line.lower().strip()
            if not line_l:
                return False
            for key in keys:
                if key in line_l:
                    return True
            return False

        for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']:
            try:
                with open(saved_ulp_path, 'r', encoding=enc, errors='ignore') as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str and strict_match(line_str, keywords_lower):
                            if line_str not in seen:
                                seen.add(line_str)
                                filtered_lines.append(line_str)
                break
            except Exception:
                continue

        if not filtered_lines:
            await msg.edit_text("❌ لم يتم العثور على نتائج مطابقة.")
        else:
            output_filename = f"Filtered_{file_name}"
            with open(output_filename, "w", encoding="utf-8") as out_f:
                out_f.write("\n".join(filtered_lines))

            await client.send_document(
                chat_id=message.chat.id,
                document=output_filename,
                caption=f"✅ تم الفرز بنجاح!\nالنتائج: <b>{len(filtered_lines):,}</b> سطر"
            )
            await msg.delete()
    except Exception as e:
        await message.reply(f"❌ خطأ: {e}")
    finally:
        if saved_ulp_path and os.path.exists(saved_ulp_path):
            os.remove(saved_ulp_path)
        if output_filename and os.path.exists(output_filename):
            os.remove(output_filename)
        user_filter_keywords.pop(user_id, None)
        user_action_state.pop(user_id, None)

# ==================== أوامر الأعضاء ====================
@app.on_message(filters.regex("^💰 رصيدي ونقاطي$"))
async def check_balance(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    row = get_user_row(message.from_user.id)
    await message.reply(f"💎 رصيدك: <b>{row['points']}</b> نقطة\nمستواك: {get_level_emoji(row['level'])} {row['level']}")

@app.on_message(filters.regex("^📋 آخر العمليات$"))
async def last_operations(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    ops = get_last_operations(message.from_user.id, 5)
    if not ops:
        await message.reply("📋 لا توجد عمليات سحب سابقة.")
        return
    text = "📋 <b>آخر العمليات:</b>\n\n"
    for i, op in enumerate(ops, 1):
        text += f"{i}. <code>{op['domain']}</code> ({op['amount']:,} حساب)\n"
    await message.reply(text)

@app.on_message(filters.regex("^🎁 المكافأة اليومية$"))
async def daily_reward_handler(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    _, msg, _ = claim_daily_reward(message.from_user.id)
    await message.reply(msg)

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    await message.reply(f"🔗 <b>رابط الإحالة:</b>\n<code>{link}</code>")

@app.on_message(filters.regex("^📺 قنوات الإعلانات$"))
async def show_ad_channels(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, points_reward FROM ad_channels")
    ads = cursor.fetchall()
    conn.close()
    if not ads:
        await message.reply("📺 لا توجد قنوات إعلانية.")
        return
    txt = "📺 <b>القنوات الإعلانية:</b>\n\n"
    btns = []
    for ch, pts in ads:
        ch_link = f"https://t.me/{ch.replace('@', '')}" if str(ch).startswith("@") else ch
        txt += f"• {ch} (+{pts} نقطة)\n"
        btns.append([InlineKeyboardButton(f"انضمام (+{pts})", url=ch_link)])
    await message.reply(txt, reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.regex("^📊 إحصائياتي$"))
async def personal_stats(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    row = get_user_row(message.from_user.id)
    await message.reply(f"📊 إجمالي سحوباتك: <b>{row['total_withdrawals']}</b> عملية")

# ==================== الأزرار الإدارية الكاملة ====================
@app.on_message(filters.regex("^🗑 حذف حسب دومين$") & filters.user(OWNER_IDS))
async def ask_delete_domain(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_delete_domain"
    await message.reply("🗑 أرسل الدومين الذي تريد حذف كافة حساباته من قاعدة البيانات:")

@app.on_message(filters.regex("^🔥 الأكثر والأقل طلباً$") & filters.user(OWNER_IDS))
async def show_popular_domains(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, search_count FROM search_stats ORDER BY search_count DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await message.reply("📊 لا توجد إحصائيات بحث مسجلة حتى الآن.")
        return
    text = "🔥 <b>الأكثر طلباً وبحثاً:</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. <code>{r['domain']}</code> (عدد العمليات: {r['search_count']})\n"
    await message.reply(text)

@app.on_message(filters.regex("^➕ إرسال نقاط ID$") & filters.user(OWNER_IDS))
async def ask_send_pts(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_send_pts"
    await message.reply("➕ أرسل الآيدي والمبلغ بهذه الصيغة:\n`ID AMOUNT`\nمثال: `123456789 10`")

@app.on_message(filters.regex("^⚙️ نقاط الإحالة$") & filters.user(OWNER_IDS))
async def ask_ref_pts(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ref_pts"
    await message.reply(f"⚙️ نقاط الإحالة الحالية: <b>{get_referral_points()}</b>\nأرسل القيمة الجديدة للرصيد:")

@app.on_message(filters.regex("^📢 إضافة إعلان قناة$") & filters.user(OWNER_IDS))
async def ask_add_ad(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_add_ad"
    await message.reply("📢 أرسل يوزر القناة ومكافأة النقاط هكذا:\n`@ChannelUsername 1`")

@app.on_message(filters.regex("^💎 إحصائيات النقاط$") & filters.user(OWNER_IDS))
async def top_points_users(client: Client, message: Message):
    rows = get_top_points_users(15)
    if not rows:
        await message.reply("💎 لا توجد بيانات مسجلة.")
        return
    text = "💎 <b>أكثر المستخدمين امتلاكاً للنقاط:</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. <code>{r['user_id']}</code> - <b>{r['points']}</b> نقطة ({r['level']})\n"
    await message.reply(text)

@app.on_message(filters.regex("^👥 الأكثر نشاطاً$") & filters.user(OWNER_IDS))
async def most_active_users(client: Client, message: Message):
    rows = get_most_active_users(10)
    if not rows:
        await message.reply("👥 لا توجد عمليات سحب مسجلة.")
        return
    text = "👥 <b>الأكثر نشاطاً في السحب:</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. <code>{r['user_id']}</code> - <b>{r['total_withdrawals']}</b> عملية سحب\n"
    await message.reply(text)

@app.on_message(filters.regex("^🚫 حظر عضو$") & filters.user(OWNER_IDS))
async def ask_ban_user(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ban_user"
    await message.reply("🚫 أرسل آيدي العضو المراد حظره:")

@app.on_message(filters.regex("^✅ فك حظر عضو$") & filters.user(OWNER_IDS))
async def ask_unban_user(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_unban_user"
    await message.reply("✅ أرسل آيدي العضو لفك حظره:")

@app.on_message(filters.regex("^💣 حذف كل البيانات$") & filters.user(OWNER_IDS))
async def confirm_delete_all(client: Client, message: Message):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ نعم، احذف الكل نهائياً", callback_data="confirm_wipe_db")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_wipe_db")]
    ])
    await message.reply("💣 هل أنت متأكد من حذف جميع الكومبوهات وقاعدة البيانات؟", reply_markup=kb)

@app.on_callback_query(filters.regex("^confirm_wipe_db$") & filters.user(OWNER_IDS))
async def wipe_db_cb(client: Client, callback: CallbackQuery):
    delete_all_combos()
    await callback.answer("تم حذف كافة الكومبوهات بنجاح.", show_alert=True)
    await callback.message.edit_text("💣 تم تفريغ قاعدة بيانات الكومبوهات بالكامل.")

@app.on_callback_query(filters.regex("^cancel_wipe_db$"))
async def cancel_wipe_cb(client: Client, callback: CallbackQuery):
    await callback.answer("تم الإلغاء.")
    await callback.message.edit_text("❌ تم إلغاء عملية الحذف.")

@app.on_message(filters.regex("^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def bot_status_details(client: Client, message: Message):
    total, _, users_c, blocked_c, active_c = get_stats()
    text = (
        f"📈 <b>تقرير حالة البوت الشامل:</b>\n\n"
        f"• إجمالي الكومبوهات: <b>{total:,}</b>\n"
        f"• إجمالي الأعضاء: <b>{users_c:,}</b>\n"
        f"• الأعضاء النشطون: <b>{active_c:,}</b>\n"
        f"• الأعضاء المحظورون: <b>{blocked_c:,}</b>\n"
        f"• إجمالي عمليات السحب: <b>{get_total_operations():,}</b>\n"
        f"• حالة البوت للأعضاء: {'✅ يعمل' if bot_enabled_for_users else '🚫 متوقف'}"
    )
    await message.reply(text)

@app.on_message(filters.regex("^📈 عدد العمليات$") & filters.user(OWNER_IDS))
async def total_operations_count(client: Client, message: Message):
    await message.reply(f"📈 إجمالي العمليات الناجحة في البوت: <b>{get_total_operations():,}</b> عملية")

# ==================== الإدارة ====================
@app.on_message(filters.regex("^🧾 قناة السجل \(Audit Log\)$") & filters.user(OWNER_IDS))
async def audit_log_settings(client: Client, message: Message):
    await message.reply(f"🧾 قناة السجل الحالية: <code>{get_log_channel() or 'غير محددة'}</code>\nلتغييرها:\n`/set_log_channel -100xxx`")

@app.on_message(filters.command("set_log_channel") & filters.user(OWNER_IDS))
async def set_log_channel_cmd(client: Client, message: Message):
    if len(message.command) > 1:
        set_log_channel(message.command[1])
        await message.reply("✅ تم الحفظ.")

@app.on_message(filters.regex("^🎁 إنشاء رابط هدية$") & filters.user(OWNER_IDS))
async def make_gift_process(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_gift_amount"
    await message.reply("🎁 أرسل عدد النقاط لرابط الهدية (مثال: 5):")

@app.on_message(filters.command("send_pts") & filters.user(OWNER_IDS))
async def process_send_pts(client: Client, message: Message):
    if len(message.command) >= 3:
        add_user_points(int(message.command[1]), float(message.command[2]))
        await message.reply("✅ تم إضافة النقاط.")

@app.on_message(filters.command("ban") & filters.user(OWNER_IDS))
async def ban_user_cmd(client: Client, message: Message):
    if len(message.command) >= 2:
        update_user_block_status(int(message.command[1]), 1, "مخالفة")
        await message.reply("🚫 تم الحظر.")

@app.on_message(filters.command("unban") & filters.user(OWNER_IDS))
async def unban_user_cmd(client: Client, message: Message):
    if len(message.command) >= 2:
        update_user_block_status(int(message.command[1]), 0, None)
        await message.reply("✅ تم فك الحظر.")

@app.on_message(filters.regex("^⚙️ إعدادات الاشتراك$") & filters.user(OWNER_IDS))
async def channel_settings(client: Client, message: Message):
    await message.reply("⚙️ لإضافة قناة:\n`/add_channel -100xxx الاسم رابط`\nللحذف:\n`/del_channel -100xxx`")

@app.on_message(filters.command("add_channel") & filters.user(OWNER_IDS))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) >= 2:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO channels (channel_id, title) VALUES (?, ?)", (message.command[1], "قناة"))
        conn.commit()
        conn.close()
        clear_sub_cache()
        await message.reply("✅ تم إضافة القناة.")

@app.on_message(filters.command("del_channel") & filters.user(OWNER_IDS))
async def del_channel_cmd(client: Client, message: Message):
    if len(message.command) >= 2:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE channel_id = ?", (message.command[1],))
        conn.commit()
        conn.close()
        clear_sub_cache()
        await message.reply("🗑 تم الحذف.")

@app.on_message(filters.command("bc") & filters.user(OWNER_IDS))
async def start_broadcast(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply("رد على الرسالة.")
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    users = cursor.fetchall()
    conn.close()
    for row in users:
        try:
            await message.reply_to_message.copy(row["user_id"])
            await asyncio.sleep(0.03)
        except Exception:
            pass
    await message.reply("✅ تمت الإذاعة.")

@app.on_message(filters.regex("^✅ تفعيل البوت$") & filters.user(OWNER_IDS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = True
    await message.reply("✅ البوت مفعل.")

@app.on_message(filters.regex("^🚫 إغلاق البوت$") & filters.user(OWNER_IDS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = False
    await message.reply("🚫 البوت مغلق.")

@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, _, users_c, blocked_c, _ = get_stats()
    await message.reply(f"📊 إحصائيات:\n• الكومبو: {total:,}\n• الأعضاء: {users_c:,}\n• المحظورين: {blocked_c}")

@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def ask_file(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ulp_upload"
    await message.reply("📤 أرسل الملفات الآن للإضافة.")

async def handle_large_document(client: Client, message: Message):
    temp_path = None
    try:
        msg = await message.reply("⏳ جاري الرفع المعالجة...")
        temp_path = await message.download()
        added = await asyncio.to_thread(add_combos_from_file, temp_path)
        await msg.edit_text(f"✅ تمت الإضافة بنجاح: <b>{added:,}</b>")
    except Exception as e:
        await message.reply(f"❌ خطأ: {e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

# ==================== البحث والاستخراج ====================
@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id) and not await force_sub_guard(client, message):
        return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("📝 أرسل الدومين المطلوب:")

@app.on_callback_query(filters.regex("^get_"))
async def callback_get_combos(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # إذا كان المالك - لا نسمح له بالدخول إلى هذه الدالة (يستخدم نظام السحب الشامل الخاص)
    if is_owner(user_id):
        await callback.answer("👑 استخدم زر البحث العادي للسحب الشامل.", show_alert=True)
        return
    
    is_ok, _ = await check_subscription(client, user_id)
    if not is_ok:
        await callback.answer("❌ اشترك في القنوات أولاً!", show_alert=True)
        return

    parts = callback.data.split("_")
    domain = parts[1]
    amount_str = parts[2]

    available = count_available_combos(domain)
    if amount_str == "all":
        amount = available
    else:
        amount = int(amount_str)

    if amount <= 0:
        await callback.answer("❌ عذراً، نفدت الحسابات.", show_alert=True)
        return

    required_points = round((amount / 1000.0), 2)
    if required_points < 0.1 and amount > 0:
        required_points = 0.1

    user_pts = get_user_points(user_id)
    if user_pts < required_points:
        if amount_str == "all":
            max_possible = int(user_pts * 1000)
            if max_possible > 0:
                amount = min(available, max_possible)
                required_points = round((amount / 1000.0), 2)
            else:
                await callback.answer("❌ رصيدك غير كافي!", show_alert=True)
                return
        else:
            await callback.answer("❌ رصيدك غير كافي!", show_alert=True)
            return

    await callback.answer("⏳ جاري الاستخراج...", show_alert=False)
    await callback.message.edit_text(f"⏳ جاري سحب <b>{amount:,}</b> فريد لـ `{domain}`...")

    results = await fetch_and_delete_combos(domain, amount)

    if not results:
        await callback.message.edit_text("❌ عذراً، نفدت الحسابات.")
        return

    actual_amount = len(results)
    spent = round((actual_amount / 1000.0), 2)

    deduct_user_points(user_id, spent)
    record_withdrawal(user_id, domain, actual_amount, spent)
    log_search_domain(domain)
    increment_operations()

    file_obj = io.BytesIO("\n".join(results).encode("utf-8"))
    file_obj.name = f"{domain}_{actual_amount}_combos.txt"

    await client.send_document(
        chat_id=user_id,
        document=file_obj,
        caption=f"✅ <b>تم استخراج الحسابات بنجاح (بدون تكرار)!</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{actual_amount:,}</b>"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass

if __name__ == "__main__":
    print("🤖 Bot is running with all buttons active & ULP cleanup feature...")
    print("👑 Owner full withdrawal with duplicate files (original + modified passwords) enabled.")
    app.run()
