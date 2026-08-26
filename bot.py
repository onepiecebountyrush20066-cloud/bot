import os
import io
import re
import sqlite3
import uuid
import asyncio
import math
import time
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

# كاش التحقق من الاشتراك (user_id -> timestamp آخر نجاح)
# كاش قصير فقط عشان ما يزعج المشترك، لكن الفحص يبقى صارم
subscription_cache = {}
SUB_CACHE_SECONDS = 90  # دقيقة ونص فقط

# إعدادات المكافآت والمستويات
FIRST_WITHDRAWAL_BONUS = 1.0
DAILY_REWARD_BASE = 0.5
ADVANCED_REFERRAL_REWARD = 0.5
BIG_WITHDRAWAL_THRESHOLD = 5000

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

    # جدول الكومبو
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS combos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            combo TEXT NOT NULL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_combo ON combos(combo)')

    # جدول المستخدمين (محسّن)
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

    # إضافة الأعمدة الجديدة لو الجدول قديم
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

    # جدول سجل السحوبات (مهم للإحالة المتقدمة + آخر العمليات + الإحصائيات)
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

    # جدول القنوات الإجبارية
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

    # قنوات الإعلانات
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

    # الهدايا
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            code TEXT PRIMARY KEY,
            points REAL NOT NULL,
            used_by INTEGER DEFAULT NULL
        )
    ''')

    # إحصائيات البحث
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_stats (
            domain TEXT PRIMARY KEY,
            search_count INTEGER DEFAULT 0
        )
    ''')

    # قائمة الانتظار الذكية
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waitlist (
            user_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            notified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, domain)
        )
    ''')

    # المهام
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tasks (
            user_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, task_name)
        )
    ''')

    # إعدادات البوت
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    defaults = [
        ("total_operations", "0"),
        ("referral_points", "1.0"),          # القديم القديم (للتوافق)
        ("advanced_referral_points", "0.5"), # الإحالة المتقدمة
        ("log_channel", ""),
        ("forced_sub_enabled", "1"),
        ("daily_reward", "0.5"),
        ("big_withdrawal_alert", "1"),
    ]
    for k, v in defaults:
        cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)', (k, v))

    # قناة افتراضية
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
    """يرجع (محظور؟, السبب)"""
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

def get_level_discount(level: str) -> float:
    """نسبة الخصم على النقاط المطلوبة"""
    if level == "ذهبي":
        return 0.20  # 20% خصم
    if level == "فضي":
        return 0.10  # 10% خصم
    return 0.0

def get_level_emoji(level: str) -> str:
    return {"ذهبي": "🥇", "فضي": "🥈", "عادي": "🥉"}.get(level, "🥉")

# ==================== سجل السحوبات + الإحالة المتقدمة ====================
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

def check_and_reward_advanced_referral(user_id: int, client: Client = None):
    """
    بعد كل سحب ناجح: لو العضو مدعو ووصل لـ 2 سحوبات ولم يُكافأ المُحيل بعد
    → نعطي المُحيل 0.5 نقطة
    """
    row = get_user_row(user_id)
    if not row:
        return
    referrer_id = row["referred_by"]
    if not referrer_id or row["referral_rewarded"] == 1:
        return

    count = get_user_withdrawals_count(user_id)
    if count >= 2:
        reward = get_advanced_referral_points()
        add_user_points(referrer_id, reward)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET referral_rewarded = 1 WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()

        if client:
            try:
                asyncio.create_task(
                    client.send_message(
                        referrer_id,
                        f"🎉 <b>مكافأة الإحالة المتقدمة!</b>\n\n"
                        f"المدعو الخاص بك أكمل <b>عمليتين سحب</b>.\n"
                        f"حصلت على <b>{reward}</b> نقطة."
                    )
                )
            except Exception:
                pass

def mark_first_withdrawal(user_id: int) -> bool:
    """يرجع True لو كانت أول سحبة (وأضفنا المكافأة)"""
    row = get_user_row(user_id)
    if not row or row["first_withdrawal_done"] == 1:
        return False
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET first_withdrawal_done = 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    add_user_points(user_id, FIRST_WITHDRAWAL_BONUS)
    return True

# ==================== المكافأة اليومية / الستريك ====================
def claim_daily_reward(user_id: int) -> tuple:
    """
    يرجع (نجاح؟, رسالة, النقاط المضافة)
    """
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
    # مكافأة إضافية بسيطة مع الستريك
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

def get_waitlist_for_domain(domain: str) -> list:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id FROM waitlist WHERE domain = ? AND notified = 0",
        (domain.lower(),)
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

def mark_waitlist_notified(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE waitlist SET notified = 1 WHERE domain = ?",
        (domain.lower(),)
    )
    conn.commit()
    conn.close()

# ==================== نظام الاشتراك الإجباري المحسّن ====================
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
    """
    تحقق صارم من عضوية القناة.
    - مشترك فقط لو الحالة member / administrator / creator
    - أي خطأ (ما عدا FloodWait مع إعادة محاولة) = غير مشترك
    """
    try:
        chat_id = int(channel_id) if (str(channel_id).startswith("-") or str(channel_id).isdigit()) else channel_id

        # محاولة أولى
        try:
            member = await client.get_chat_member(chat_id, user_id)
        except FloodWait as e:
            await asyncio.sleep(min(e.value, 8))
            member = await client.get_chat_member(chat_id, user_id)

        status = str(member.status).lower()

        # الحالات المقبولة فقط
        if any(s in status for s in (
            "creator", "owner", "administrator", "member",
            "chatmemberstatus.member",
            "chatmemberstatus.administrator",
            "chatmemberstatus.creator",
            "chatmemberstatus.owner"
        )):
            return True

        # Restricted: نقبل فقط لو is_member = True
        if "restricted" in status:
            return bool(getattr(member, "is_member", False))

        return False

    except (UserNotParticipant, ChannelPrivate, ChatAdminRequired, PeerIdInvalid):
        return False
    except FloodWait:
        # لو حصل FloodWait تاني بعد المحاولة → نعتبره غير مشترك (صارم)
        return False
    except Exception as e:
        print(f"[SUB CHECK STRICT ERROR] ch={channel_id} user={user_id} → {e}")
        # أي خطأ غير معروف = غير مشترك (حسب طلبك: صارم)
        return False

async def check_subscription(client: Client, user_id: int, force_refresh: bool = False) -> tuple:
    """
    فحص كامل وصارم:
    - لو مش مشترك في أي قناة إجبارية → ممنوع يستخدم البوت
    - لو مشترك في الكل → يسمح له
    - كاش قصير فقط للمشتركين الناجحين (ما يخفي عدم الاشتراك)
    """
    if is_owner(user_id):
        return True, []

    if not is_forced_sub_enabled():
        return True, []

    # كاش نجاح فقط (قصير)
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
        # فشل → نمسح الكاش فوراً
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

# ==================== Audit Log + إشعار السحب الكبير ====================
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

# ==================== معالجة الكومبو ====================
def count_available_combos(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    query = f"%{domain.lower()}%"
    cursor.execute("SELECT COUNT(*) as c FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    count = cursor.fetchone()["c"]
    conn.close()
    return count

def extract_email_pass(line: str) -> str:
    """
    محاولة استخراج جزء مفيد من السطر.
    لو السطر صيغة ULP معقدة نفضل الإبقاء على أكبر جزء مفيد.
    """
    line = line.strip()
    if not line:
        return line
    parts = line.split(':')
    if len(parts) >= 3:
        # صيغة شائعة: domain:user:pass أو url:email:pass
        # نرجع آخر جزئين غالباً (user:pass أو email:pass)
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
            fetch_limit = int(limit_count * 1.8) + 500
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

    # فحص الحظر
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
    else:
        # لو كان محظور سابقاً من البوت نفسه نفكه؟ لا، نتركه
        pass

    # معالجة روابط الهدية والإحالة
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
            # الإحالة المتقدمة: نسجل referred_by فقط، والنقاط بعد عمليتين سحب
            if referrer_id != user_id and not is_existing_user:
                cursor.execute(
                    "UPDATE users SET referred_by = ? WHERE user_id = ?",
                    (referrer_id, user_id)
                )
                conn.commit()
                # ما نعطيش نقاط فوراً (نظام متقدم)
                try:
                    await client.send_message(
                        referrer_id,
                        f"👤 انضم عضو جديد عبر رابطك!\n"
                        f"هتحصل على <b>{get_advanced_referral_points()}</b> نقطة "
                        f"بعد ما يعمل <b>عمليتين سحب</b>."
                    )
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

    # تحقق الاشتراك (مع الكاش)
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

    # نفرض refresh عشان نتأكد
    is_ok, missing = await check_subscription(client, user_id, force_refresh=True)

    if is_ok:
        await callback.answer("✅ تم التحقق بنجاح! أهلاً بك", show_alert=False)
        clear_sub_cache()  # اختياري
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
            await callback.message.reply(text, reply_markup=user_keyboard())

        await client.send_message(
            user_id,
            "🏠 القائمة الرئيسية جاهزة:",
            reply_markup=user_keyboard() if not is_owner(user_id) else owner_keyboard()
        )
    else:
        await callback.answer(
            "❌ لم تشترك في كل القنوات بعد!\nتأكد من الاشتراك ثم اضغط مرة أخرى.",
            show_alert=True
        )
        await send_force_sub_message(client, user_id, missing, edit_message=callback.message)

# ==================== حماية الأوامر ====================
async def force_sub_guard(client: Client, message: Message) -> bool:
    user_id = message.from_user.id
    if is_owner(user_id):
        return True

    banned, reason = is_user_banned(user_id)
    if banned:
        await message.reply(f"🚫 أنت محظور من استخدام البوت.\nالسبب: {reason}")
        return False

    if not bot_enabled_for_users:
        await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
        return False

    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return False

    return True

# ==================== تحكم المالك بفرز ULP ====================
@app.on_message(filters.command("stop") & filters.user(OWNER_IDS))
async def stop_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = False
    await message.reply("🛑 تم إيقاف قسم فرز ملفات ULP بنجاح.")

@app.on_message(filters.command("on") & filters.user(OWNER_IDS))
async def on_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = True
    await message.reply("✅ تم تفعيل قسم فرز ملفات ULP بنجاح.")

# ==================== قسم فرز ملفات ULP ====================
@app.on_message(filters.regex("^📂 فرز ملفات ULP$") & filters.user(OWNER_IDS))
async def start_ulp_filter(client: Client, message: Message):
    global ulp_feature_enabled
    if not ulp_feature_enabled:
        await message.reply("⚠️ قسم فرز ملفات ULP متوقف حالياً. أرسل `/on` لتفعيله.")
        return

    user_id = message.from_user.id
    user_action_state[user_id] = "awaiting_filter_keywords"

    cancel_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_ulp_filter")]
    ])

    await message.reply(
        "🎯 <b>قسم فرز ملفات ULP المستهدفة</b>\n\n"
        "أرسل الكلمات المفتاحية أو اسم الدومين/الخدمة.\n"
        "مثال: `ludo, netflix, expressvpn`",
        reply_markup=cancel_kb
    )

@app.on_callback_query(filters.regex("^cancel_ulp_filter$"))
async def cancel_ulp_filter_cb(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    user_action_state.pop(user_id, None)
    user_filter_keywords.pop(user_id, None)
    await callback.answer("تم إلغاء عملية الفرز.", show_alert=False)
    await callback.message.edit_text("❌ تم إلغاء عملية فرز ULP.")

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
        await message.reply(
            "⚠️ <b>يرجى تحديد الكلمات المراد فرزها أولاً!</b>\n"
            "اضغط على زر <b>📂 فرز ملفات ULP</b> أولاً."
        )
        return

    saved_ulp_path = None
    output_filename = None

    try:
        file_name = message.document.file_name or "data.ulp"
        msg = await message.reply(f"⏳ جاري تنزيل ملف الـ ULP: <b>{file_name}</b>...")

        saved_ulp_path = await client.download_media(message)
        await msg.edit_text("🔍 تم تنزيل الملف.. جاري قراءة البيانات والتصفية...")

        filtered_lines = []
        seen = set()
        keywords_lower = [k.lower().strip() for k in keywords if k.strip()]

        def strict_match(line: str, keys: list) -> bool:
            """
            تطابق صارم لكن عملي:
            - يقبل السطر لو الكلمة المفتاحية موجودة بوضوح (دومين / رابط / خدمة)
            - يشتغل مع معظم صيغ الـ ULP الحقيقية
            - يرفض التطابق العشوائي الضعيف للكلمات القصيرة جداً
            """
            line_l = line.lower().strip()
            if not line_l:
                return False

            for key in keys:
                if not key:
                    continue
                key = key.lower().strip()

                # 1) تطابق مباشر واضح (الأهم والأكثر استخداماً في ملفات ULP)
                if key in line_l:
                    # كلمات قصيرة جداً (3 حروف أو أقل) تحتاج نمط أقوى عشان ما تجيبش نتايج غلط
                    if len(key) <= 3:
                        strong = [
                            f".{key}.", f".{key}/", f"/{key}.", f"/{key}/",
                            f"@{key}.", f"://{key}", f".{key}:", f" {key} ",
                            f"/{key} ", f" {key}/", f"{key}.com", f"{key}.net"
                        ]
                        if any(p in line_l for p in strong):
                            return True
                        continue

                    # كلمات متوسطة أو طويلة (ludo, expressvpn, bandainamcoid.com ...) → نقبلها مباشرة
                    return True

            return False

        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16', 'utf-8']
        file_read_ok = False
        total_lines_checked = 0

        for enc in encodings:
            try:
                with open(saved_ulp_path, 'r', encoding=enc, errors='ignore') as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str or len(line_str) < 3:
                            continue
                        total_lines_checked += 1
                        if strict_match(line_str, keywords_lower):
                            # نحافظ على السطر الأصلي كامل (صيغة ULP / Log كما هي)
                            if line_str not in seen:
                                seen.add(line_str)
                                filtered_lines.append(line_str)
                file_read_ok = True
                break
            except Exception:
                continue

        if not file_read_ok:
            await msg.edit_text("❌ فشل قراءة الملف. تأكد أنه ملف نصي (txt / log / ulp).")
            return

        if not filtered_lines:
            await msg.edit_text(
                f"❌ لم يتم العثور على نتائج تطابق الكلمات المحددة!\n\n"
                f"تم فحص حوالي <b>{total_lines_checked:,}</b> سطر.\n"
                f"الكلمات: <code>{', '.join(keywords_lower)}</code>\n\n"
                f"تأكد أن الملف يحتوي على هذه الكلمات."
            )
        else:
            await msg.edit_text("📤 جاري تجهيز وإرسال ملف النتائج...")

            safe_base = re.sub(r'[^\w\-_\.]', '_', os.path.splitext(file_name)[0])[:40]
            output_filename = f"Filtered_{safe_base}.txt"
            with open(output_filename, "w", encoding="utf-8") as out_f:
                out_f.write("\n".join(filtered_lines))

            kw_text = ", ".join([f"`{k}`" for k in keywords])

            await client.send_document(
                chat_id=message.chat.id,
                document=output_filename,
                caption=(
                    f"✅ <b>تم اكتمال عملية الفرز بنجاح!</b>\n\n"
                    f"📄 الملف الأصلي: <code>{file_name}</code>\n"
                    f"🎯 عدد الأسطر المفروزة: <b>{len(filtered_lines):,}</b>\n"
                    f"🔍 الكلمات: {kw_text}\n"
                    f"📦 الصيغة: ULP / Log كاملة (السطر كما هو)"
                )
            )
            await msg.delete()

    except Exception as e:
        await message.reply(f"❌ حدث خطأ أثناء الفرز:\n<code>{str(e)}</code>")

    finally:
        if saved_ulp_path and os.path.exists(saved_ulp_path):
            try:
                os.remove(saved_ulp_path)
            except Exception:
                pass
        if output_filename and os.path.exists(output_filename):
            try:
                os.remove(output_filename)
            except Exception:
                pass
        user_filter_keywords.pop(user_id, None)
        user_action_state.pop(user_id, None)

# ==================== أوامر الأعضاء ====================
@app.on_message(filters.regex("^💰 رصيدي ونقاطي$"))
async def check_balance(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    user_id = message.from_user.id
    row = get_user_row(user_id)
    pts = float(row["points"])
    level = row["level"]
    emoji = get_level_emoji(level)
    streak = int(row["streak_count"] or 0)
    total_w = int(row["total_withdrawals"] or 0)

    text = (
        f"💎 <b>رصيدك الحالي:</b> {pts} نقطة\n"
        f"{emoji} <b>المستوى:</b> {level}\n"
        f"🔥 <b>الستريك:</b> {streak} يوم\n"
        f"📤 <b>إجمالي السحوبات:</b> {total_w}"
    )
    await message.reply(text)

@app.on_message(filters.regex("^📋 آخر العمليات$"))
async def last_operations(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    user_id = message.from_user.id
    ops = get_last_operations(user_id, 5)
    if not ops:
        await message.reply("📋 لا توجد عمليات سحب سابقة.")
        return

    text = "📋 <b>آخر 5 عمليات سحب:</b>\n\n"
    for i, op in enumerate(ops, 1):
        dt = op["created_at"][:16].replace("T", " ") if op["created_at"] else "-"
        text += (
            f"{i}. <code>{op['domain']}</code>\n"
            f"   الكمية: <b>{op['amount']:,}</b> | النقاط: {op['points_spent']}\n"
            f"   التاريخ: {dt}\n\n"
        )
    await message.reply(text)

@app.on_message(filters.regex("^🎁 المكافأة اليومية$"))
async def daily_reward_handler(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    success, msg, pts = claim_daily_reward(message.from_user.id)
    await message.reply(msg)

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    bot_username = (await client.get_me()).username
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start={user_id}"
    adv_pts = get_advanced_referral_points()
    await message.reply(
        f"🔗 <b>رابط الإحالة الخاص بك:</b>\n<code>{link}</code>\n\n"
        f"شاركه مع أصدقائك.\n"
        f"هتحصل على <b>{adv_pts}</b> نقطة بعد ما المدعو يعمل <b>عمليتين سحب</b>."
    )

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
        await message.reply("📺 لا توجد قنوات إعلانية متاحة حالياً.")
        return

    txt = "📺 <b>اشترك في القنوات التالية للحصول على نقاط:</b>\n\n"
    btns = []
    for ch, pts in ads:
        ch_link = f"https://t.me/{ch.replace('@', '')}" if str(ch).startswith("@") else ch
        txt += f"• {ch} (المكافأة: <b>{pts}</b> نقطة)\n"
        btns.append([InlineKeyboardButton(f"الانضمام (+{pts})", url=ch_link)])

    await message.reply(txt, reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.regex("^📊 إحصائياتي$"))
async def personal_stats(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    user_id = message.from_user.id
    row = get_user_row(user_id)
    ops = get_last_operations(user_id, 100)

    total_accounts = sum(op["amount"] for op in ops)
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    week_accounts = sum(op["amount"] for op in ops if op["created_at"] and op["created_at"] >= week_ago)

    text = (
        f"📊 <b>إحصائياتك الشخصية</b>\n\n"
        f"💎 النقاط: <b>{row['points']}</b>\n"
        f"{get_level_emoji(row['level'])} المستوى: <b>{row['level']}</b>\n"
        f"📤 إجمالي السحوبات: <b>{row['total_withdrawals']}</b>\n"
        f"📦 إجمالي الحسابات المسحوبة: <b>{total_accounts:,}</b>\n"
        f"📅 هذا الأسبوع: <b>{week_accounts:,}</b> حساب\n"
        f"🔥 الستريك: <b>{row['streak_count']}</b> يوم"
    )
    await message.reply(text)

# ==================== أوامر الإدارة ====================
@app.on_message(filters.regex("^🧾 قناة السجل \(Audit Log\)$") & filters.user(OWNER_IDS))
async def audit_log_settings(client: Client, message: Message):
    curr_log = get_log_channel()
    log_info = f"<code>{curr_log}</code>" if curr_log else "غير محددة"
    await message.reply(
        f"🧾 <b>قناة السجل الحالية:</b> {log_info}\n\n"
        "لتحديد أو تغيير القناة:\n"
        "`/set_log_channel -100xxxxxxxxxx`"
    )

@app.on_message(filters.command("set_log_channel") & filters.user(OWNER_IDS))
async def set_log_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ مثال:\n`/set_log_channel -1001234567890`")
        return
    ch_id = message.command[1].strip()
    set_log_channel(ch_id)
    await message.reply(f"✅ تم ضبط قناة السجل إلى: <code>{ch_id}</code>")

@app.on_message(filters.regex("^⚙️ نقاط الإحالة$") & filters.user(OWNER_IDS))
async def ref_pts_settings(client: Client, message: Message):
    adv = get_advanced_referral_points()
    await message.reply(
        f"⚙️ <b>نقاط الإحالة المتقدمة الحالية:</b> <b>{adv}</b>\n\n"
        f"(تُعطى بعد ما المدعو يعمل عمليتين سحب)\n\n"
        "للتغيير:\n`/set_adv_ref 0.5`"
    )

@app.on_message(filters.command("set_adv_ref") & filters.user(OWNER_IDS))
async def set_adv_ref_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ مثال: `/set_adv_ref 0.5`")
        return
    try:
        pts = float(message.command[1])
        set_setting("advanced_referral_points", str(pts))
        await message.reply(f"✅ تم تغيير مكافأة الإحالة المتقدمة إلى <b>{pts}</b>")
    except ValueError:
        await message.reply("❌ أدخل رقم صحيح.")

@app.on_message(filters.regex("^📢 إضافة إعلان قناة$") & filters.user(OWNER_IDS))
async def add_ad_info(client: Client, message: Message):
    await message.reply("📝 استخدم:\n`/add_ad @channel 2`")

@app.on_message(filters.command("add_ad") & filters.user(OWNER_IDS))
async def add_ad_cmd(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ استخدم:\n`/add_ad @channel_username POINTS`")
        return
    ch = message.command[1]
    pts = float(message.command[2])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO ad_channels (channel_id, points_reward) VALUES (?, ?)",
        (ch, pts)
    )
    conn.commit()
    conn.close()
    await message.reply(f"✅ تم إضافة القناة <code>{ch}</code> بمكافأة <b>{pts}</b>")

@app.on_message(filters.regex("^🎁 إنشاء رابط هدية$") & filters.user(OWNER_IDS))
async def create_gift_cmd(client: Client, message: Message):
    await message.reply("📝 أرسل:\n`/make_gift 5`")

@app.on_message(filters.command("make_gift") & filters.user(OWNER_IDS))
async def make_gift_process(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ `/make_gift 5`")
        return
    pts = float(message.command[1])
    code = str(uuid.uuid4())[:8]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gifts (code, points) VALUES (?, ?)", (code, pts))
    conn.commit()
    conn.close()
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start=gift_{code}"
    await message.reply(f"✅ رابط الهدية بقيمة <b>{pts}</b>:\n\n{link}")

@app.on_message(filters.regex("^➕ إرسال نقاط ID$") & filters.user(OWNER_IDS))
async def send_points_id_cmd(client: Client, message: Message):
    await message.reply("📝 استخدم:\n`/send_pts USER_ID POINTS`")

@app.on_message(filters.command("send_pts") & filters.user(OWNER_IDS))
async def process_send_pts(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ `/send_pts USER_ID POINTS`")
        return
    target_id = int(message.command[1])
    pts = float(message.command[2])
    add_user_points(target_id, pts)
    await message.reply(f"✅ تم إضافة <b>{pts}</b> نقطة لـ <code>{target_id}</code>")

# ==================== حظر ورفع حظر ====================
@app.on_message(filters.regex("^🚫 حظر عضو$") & filters.user(OWNER_IDS))
async def ban_ask(client: Client, message: Message):
    await message.reply(
        "📝 لحظر عضو أرسل:\n"
        "`/ban USER_ID السبب هنا`\n\n"
        "مثال:\n`/ban 123456789 سبام`"
    )

@app.on_message(filters.command("ban") & filters.user(OWNER_IDS))
async def ban_user_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ `/ban USER_ID السبب`")
        return
    try:
        target = int(message.command[1])
    except ValueError:
        await message.reply("❌ الآيدي يجب أن يكون رقم.")
        return
    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "محظور من الإدارة"
    if target in OWNER_IDS:
        await message.reply("❌ لا يمكن حظر المالك.")
        return
    update_user_block_status(target, 1, reason)
    clear_sub_cache(target)
    await message.reply(f"🚫 تم حظر <code>{target}</code>\nالسبب: {reason}")
    try:
        await client.send_message(target, f"🚫 تم حظرك من البوت.\nالسبب: {reason}")
    except Exception:
        pass

@app.on_message(filters.regex("^✅ فك حظر عضو$") & filters.user(OWNER_IDS))
async def unban_ask(client: Client, message: Message):
    await message.reply("📝 لفك الحظر أرسل:\n`/unban USER_ID`")

@app.on_message(filters.command("unban") & filters.user(OWNER_IDS))
async def unban_user_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ `/unban USER_ID`")
        return
    try:
        target = int(message.command[1])
    except ValueError:
        await message.reply("❌ الآيدي يجب أن يكون رقم.")
        return
    update_user_block_status(target, 0, None)
    await message.reply(f"✅ تم فك حظر <code>{target}</code>")
    try:
        await client.send_message(target, "✅ تم فك الحظر عنك. يمكنك استخدام البوت الآن.")
    except Exception:
        pass

# ==================== إعدادات الاشتراك ====================
@app.on_message(filters.regex("^⚙️ إعدادات الاشتراك$") & filters.user(OWNER_IDS))
async def channel_settings(client: Client, message: Message):
    channels = get_forced_channels()
    enabled = is_forced_sub_enabled()
    status = "✅ مفعل" if enabled else "❌ معطل"

    txt = f"🔗 <b>إعدادات الاشتراك الإجباري</b>\n\n• الحالة: <b>{status}</b>\n\n"
    txt += "📢 <b>القنوات الحالية:</b>\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            link_info = f"\n   🔗 {ch['link']}" if ch.get('link') else ""
            txt += f"{i}. <b>{ch['title']}</b>\n   ID: <code>{ch['id']}</code>{link_info}\n\n"
    else:
        txt += "لا توجد قنوات حالياً.\n\n"

    txt += (
        "➕ إضافة:\n`/add_channel -1001234567890 عنوان https://t.me/+xxxx`\n\n"
        "🗑 حذف:\n`/del_channel -1001234567890`\n\n"
        "🔄 تفعيل/تعطيل:\n`/toggle_force_sub`\n\n"
        "🧹 مسح كاش الاشتراك:\n`/clear_sub_cache`"
    )
    await message.reply(txt)

@app.on_message(filters.command("toggle_force_sub") & filters.user(OWNER_IDS))
async def toggle_force_sub_cmd(client: Client, message: Message):
    current = is_forced_sub_enabled()
    new_value = "0" if current else "1"
    set_setting("forced_sub_enabled", new_value)
    clear_sub_cache()
    status = "مفعل ✅" if new_value == "1" else "معطل ❌"
    await message.reply(f"✅ حالة الاشتراك الإجباري: <b>{status}</b>")

@app.on_message(filters.command("clear_sub_cache") & filters.user(OWNER_IDS))
async def clear_cache_cmd(client: Client, message: Message):
    clear_sub_cache()
    await message.reply("✅ تم مسح كاش التحقق من الاشتراك.")

@app.on_message(filters.command("add_channel") & filters.user(OWNER_IDS))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ أدخل بيانات القناة.")
        return
    ch_id = message.command[1]
    title = "قناة"
    invite_link = None

    if len(message.command) >= 3:
        if message.command[-1].startswith("http") or message.command[-1].startswith("t.me"):
            invite_link = message.command[-1]
            if not invite_link.startswith("http"):
                invite_link = "https://" + invite_link
            title = " ".join(message.command[2:-1]) if len(message.command) > 3 else "قناة"
        else:
            title = " ".join(message.command[2:])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
        (ch_id.strip(), title, invite_link)
    )
    conn.commit()
    conn.close()
    clear_sub_cache()
    await message.reply(f"✅ تم إضافة القناة:\n• <b>{title}</b>\n• <code>{ch_id}</code>")

@app.on_message(filters.command("del_channel") & filters.user(OWNER_IDS))
async def del_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ أدخل آيدي أو يوزر القناة.")
        return
    ch = message.command[1].strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    clear_sub_cache()
    if deleted:
        await message.reply(f"🗑 تم حذف <code>{ch}</code>")
    else:
        await message.reply(f"⚠️ لم يتم العثور على <code>{ch}</code>")

@app.on_message(filters.regex("^📢 إذاعة للأعضاء$") & filters.user(OWNER_IDS))
async def broadcast_ask(client: Client, message: Message):
    await message.reply("📝 رد على الرسالة المراد إذاعتها واكتب `/bc`")

@app.on_message(filters.command("bc") & filters.user(OWNER_IDS))
async def start_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply("❌ يجب الرد على الرسالة بـ `/bc`")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    users = cursor.fetchall()
    conn.close()

    await message.reply(f"🚀 جاري الإذاعة لـ <b>{len(users)}</b> عضو...")
    success, failed = 0, 0

    for row in users:
        uid = row["user_id"]
        try:
            await target_msg.copy(uid)
            success += 1
            await asyncio.sleep(0.04)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await target_msg.copy(uid)
                success += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated):
            update_user_block_status(uid, 1, "حظر البوت")
            failed += 1
        except Exception:
            failed += 1

    await message.reply(f"✅ اكتملت الإذاعة!\n🟢 نجاح: {success}\n🔴 فشل: {failed}")

@app.on_message(filters.regex("^📈 عدد العمليات$") & filters.user(OWNER_IDS))
async def ops_count(client: Client, message: Message):
    await message.reply(f"📊 إجمالي عمليات الاستخراج: <b>{get_total_operations():,}</b>")

@app.on_message(filters.regex("^🔥 الأكثر والأقل طلباً$") & filters.user(OWNER_IDS))
async def top_and_least_searched(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, search_count FROM search_stats ORDER BY search_count DESC LIMIT 10")
    top_searches = cursor.fetchall()
    cursor.execute("SELECT domain, search_count FROM search_stats ORDER BY search_count ASC LIMIT 10")
    least_searches = cursor.fetchall()
    conn.close()

    txt = "🔥 <b>أكثر المواقع طلباً:</b>\n"
    for d, c in top_searches:
        txt += f"• <code>{d}</code> → {c} مرة\n"
    txt += "\n❄️ <b>أقل المواقع طلباً:</b>\n"
    for d, c in least_searches:
        txt += f"• <code>{d}</code> → {c} مرة\n"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 حذف الكومبو للمواقع الضعيفة", callback_data="clean_unused_domains")]
    ])
    await message.reply(txt, reply_markup=buttons)

@app.on_callback_query(filters.regex("^clean_unused_domains$"))
async def clean_unused(client: Client, callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    await callback.answer()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain FROM search_stats WHERE search_count <= 1")
    rows = cursor.fetchall()
    deleted_total = sum(delete_by_domain(dom["domain"]) for dom in rows)
    conn.close()
    await callback.message.edit_text(f"✅ تم حذف <b>{deleted_total:,}</b> كومبو للمواقع الضعيفة.")

@app.on_message(filters.regex("^✅ تفعيل البوت$") & filters.user(OWNER_IDS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = True
    await message.reply("✅ تم تفعيل البوت للأعضاء.")

@app.on_message(filters.regex("^🚫 إغلاق البوت$") & filters.user(OWNER_IDS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = False
    await message.reply("🚫 تم إغلاق البوت عن الأعضاء.")

@app.on_message(filters.regex("^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def bot_status(client: Client, message: Message):
    status = "🟢 مفعل" if bot_enabled_for_users else "🔴 مغلق"
    ulp_st = "🟢 مفعل" if ulp_feature_enabled else "🔴 متوقف"
    force_st = "🟢 مفعل" if is_forced_sub_enabled() else "🔴 معطل"
    cache_size = len(subscription_cache)
    await message.reply(
        f"<b>حالة البوت:</b>\n\n"
        f"• البوت العام: {status}\n"
        f"• فرز ULP: {ulp_st}\n"
        f"• الاشتراك الإجباري: {force_st}\n"
        f"• حجم كاش الاشتراك: {cache_size}"
    )

@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, top_domains, total_users, blocked_users, active_users = get_stats()
    text = f"""📊 <b>إحصائيات البوت الكاملة</b>

👥 <b>الأعضاء:</b>
• إجمالي المسجلين: <b>{total_users:,}</b>
• النشطين: <b>{active_users:,}</b>
• المحظورين: <b>{blocked_users:,}</b>

📦 <b>الكومبو:</b>
• الإجمالي: <b>{total:,}</b>

🔥 <b>أكثر الدومينات توفراً:</b>
"""
    if top_domains:
        for i, (domain, count) in enumerate(top_domains, 1):
            text += f"{i}. <code>{domain}</code> → {count:,}\n"
    else:
        text += "لا توجد بيانات.\n"
    await message.reply(text)

@app.on_message(filters.regex("^💎 إحصائيات النقاط$") & filters.user(OWNER_IDS))
async def points_stats(client: Client, message: Message):
    top_users = get_top_points_users(20)
    if not top_users:
        await message.reply("📊 لا يوجد أعضاء لديهم نقاط.")
        return
    text = "💎 <b>أكثر الأعضاء نقاطاً:</b>\n\n"
    for i, row in enumerate(top_users, 1):
        emoji = get_level_emoji(row["level"])
        text += f"{i}. <code>{row['user_id']}</code> → <b>{row['points']}</b> {emoji}\n"
    await message.reply(text)

@app.on_message(filters.regex("^👥 الأكثر نشاطاً$") & filters.user(OWNER_IDS))
async def most_active(client: Client, message: Message):
    rows = get_most_active_users(15)
    if not rows:
        await message.reply("لا توجد بيانات نشاط.")
        return
    text = "👥 <b>أكثر الأعضاء نشاطاً (حسب السحوبات):</b>\n\n"
    for i, row in enumerate(rows, 1):
        emoji = get_level_emoji(row["level"])
        text += (
            f"{i}. <code>{row['user_id']}</code> → "
            f"{row['total_withdrawals']} سحب | {row['points']} نقطة {emoji}\n"
        )
    await message.reply(text)

@app.on_message(filters.regex("^💣 حذف كل البيانات$") & filters.user(OWNER_IDS))
async def confirm_delete_all(client: Client, message: Message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم احذف الكل", callback_data="confirm_delete_all"),
         InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")]
    ])
    await message.reply("⚠️ هل أنت متأكد من حذف <b>كل</b> الكومبوهات؟", reply_markup=buttons)

@app.on_callback_query(filters.regex("^confirm_delete_all$"))
async def delete_all_confirmed(client: Client, callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        return
    await callback.answer()
    delete_all_combos()
    await callback.message.edit_text("✅ تم حذف كل البيانات بنجاح.")

@app.on_callback_query(filters.regex("^cancel_delete$"))
async def cancel_delete(client: Client, callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء عملية الحذف.")

@app.on_message(filters.regex("^🗑 حذف حسب دومين$") & filters.user(OWNER_IDS))
async def ask_domain_delete(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_domain_delete"
    await message.reply("📝 أرسل اسم الدومين الذي تريد حذفه بالكامل:")

# ==================== رفع ملفات ====================
@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def ask_file(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ulp_upload"
    await message.reply(
        "📤 <b>وضع رفع ملفات الكومبو مفعّل</b>\n\n"
        "أرسل ملفاً واحداً أو أكثر وسيتم إضافتها للقاعدة."
    )

async def handle_large_document(client: Client, message: Message):
    try:
        file_name = message.document.file_name or "unknown.txt"
        file_size = message.document.file_size or 0
        msg = await message.reply(
            f"⏳ جاري تحميل: <b>{file_name}</b> ({file_size / 1024 / 1024:.2f} MB)..."
        )

        safe_name = re.sub(r'[^\w\-_\.]', '_', file_name)
        temp_path = await message.download(file_name=f"temp_{message.id}_{safe_name}")

        await msg.edit_text("⏳ جاري معالجة وإضافة الكومبوهات...")
        added = await asyncio.to_thread(add_combos_from_file, temp_path)

        try:
            os.remove(temp_path)
        except Exception:
            pass

        await msg.edit_text(
            f"✅ تم رفع الملف بنجاح!\n\n"
            f"الملف: <b>{file_name}</b>\n"
            f"تمت إضافة: <b>{added:,}</b> كومبو"
        )

        # إشعار قائمة الانتظار لو في دومينات معينة (اختياري - يمكن توسيعه)
    except Exception as e:
        await message.reply(f"❌ خطأ أثناء الرفع:\n<code>{str(e)}</code>")

# ==================== البحث والسحب ====================
@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        if not await force_sub_guard(client, message):
            return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("📝 أرسل اسم الموقع أو اللعبة الذي تريد البحث عنه:")

@app.on_message(
    filters.text
    & ~filters.regex(
        r"^(🔍|📤|📊|🗑|✅|🚫|💣|📈|📢|⚙️|🔥|🎁|➕|💰|🔗|📺|💎|📋|👥|📂)"
    )
)
async def process_text_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    text_input = message.text.strip()

    if user_action_state.get(user_id) == "awaiting_filter_keywords":
        if not is_owner(user_id):
            user_action_state.pop(user_id, None)
            return
        global ulp_feature_enabled
        if not ulp_feature_enabled:
            user_action_state.pop(user_id, None)
            await message.reply("⚠️ قسم فرز ULP متوقف.")
            return

        raw_keys = [k.strip().lower() for k in re.split(r'[,|\n]', text_input) if k.strip()]
        if not raw_keys:
            await message.reply("❌ أدخل كلمات صحيحة.")
            return

        user_filter_keywords[user_id] = raw_keys
        user_action_state[user_id] = "awaiting_ulp_file"
        kw_str = ", ".join([f"`{k}`" for k in raw_keys])
        await message.reply(
            f"✅ تم تسجيل الكلمات: {kw_str}\n\n"
            f"📂 أرسل الآن ملف الـ ULP."
        )
        return

    if user_action_state.get(user_id) == "awaiting_domain_delete":
        user_action_state.pop(user_id, None)
        if not is_owner(user_id):
            return
        msg = await message.reply(f"🗑 جاري حذف كومبوهات: `{text_input}`...")
        deleted_count = delete_by_domain(text_input)
        await msg.edit_text(f"✅ تم حذف <b>{deleted_count:,}</b> كومبو للدومين `{text_input}`")
        return

    if user_action_state.get(user_id) == "awaiting_search_domain":
        user_action_state.pop(user_id, None)
        domain = text_input.lower()

        if not is_owner(user_id):
            if not await force_sub_guard(client, message):
                return

        msg = await message.reply(f"🔍 جاري البحث عن: <code>{domain}</code>...")
        available = count_available_combos(domain)

        if available == 0:
            # قائمة انتظار
            add_to_waitlist(user_id, domain)
            await msg.edit_text(
                f"❌ لا توجد حسابات متوفرة حالياً لـ <code>{domain}</code>.\n\n"
                f"✅ تم إضافتك لقائمة الانتظار.\n"
                f"هنتبلغك لما يتوفر."
            )
            return

        # اقتراحات بسيطة لو العدد قليل
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("100", callback_data=f"get_{domain}_100"),
                InlineKeyboardButton("500", callback_data=f"get_{domain}_500"),
                InlineKeyboardButton("1000", callback_data=f"get_{domain}_1000")
            ],
            [
                InlineKeyboardButton("2500", callback_data=f"get_{domain}_2500"),
                InlineKeyboardButton("5000", callback_data=f"get_{domain}_5000"),
                InlineKeyboardButton("10000", callback_data=f"get_{domain}_10000")
            ],
            [InlineKeyboardButton("❌ إغلاق", callback_data="close_search")]
        ])

        await msg.edit_text(
            f"🎯 <b>نتائج البحث:</b> <code>{domain}</code>\n\n"
            f"📊 المتاح: <b>{available:,}</b> حساب\n\n"
            f"اختر الكمية:",
            reply_markup=markup
        )
        return

@app.on_callback_query(filters.regex("^get_"))
async def callback_get_combos(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id

    if not is_owner(user_id):
        banned, reason = is_user_banned(user_id)
        if banned:
            await callback.answer(f"محظور: {reason}", show_alert=True)
            return
        is_ok, missing = await check_subscription(client, user_id)
        if not is_ok:
            await callback.answer("❌ يجب الاشتراك في القنوات أولاً!", show_alert=True)
            return

    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer("خطأ في البيانات.", show_alert=True)
        return

    domain = parts[1]
    amount = int(parts[2])

    # حساب النقاط مع الخصم حسب المستوى
    points_per_1k = 1.0
    required_points = math.ceil((amount / 1000.0) * points_per_1k * 10) / 10.0
    if required_points < 0.1:
        required_points = 0.1

    # خصم تلقائي حسب الكمية
    if amount >= 10000:
        required_points *= 0.85
    elif amount >= 5000:
        required_points *= 0.90
    elif amount >= 2500:
        required_points *= 0.95

    row = get_user_row(user_id)
    level = row["level"] if row else "عادي"
    discount = get_level_discount(level)
    required_points = round(required_points * (1 - discount), 2)
    if required_points < 0.1:
        required_points = 0.1

    user_pts = get_user_points(user_id)

    if not is_owner(user_id) and user_pts < required_points:
        await callback.answer(
            f"❌ رصيدك غير كافي!\nتحتاج {required_points} ولديك {user_pts}",
            show_alert=True
        )
        return

    await callback.answer("⏳ جاري استخراج الحسابات...", show_alert=False)
    await callback.message.edit_text(
        f"⏳ جاري سحب <b>{amount:,}</b> حساب لـ `{domain}`..."
    )

    results = await fetch_and_delete_combos(domain, amount)

    if not results:
        await callback.message.edit_text(
            f"❌ نفدت الحسابات أو حدث خطأ لـ `{domain}`."
        )
        return

    actual_amount = len(results)
    spent = 0 if is_owner(user_id) else required_points

    if not is_owner(user_id):
        deduct_user_points(user_id, spent)

    # تسجيل العملية
    record_withdrawal(user_id, domain, actual_amount, spent)
    log_search_domain(domain)
    increment_operations()

    # مكافأة أول سحب
    first_bonus = False
    if not is_owner(user_id):
        first_bonus = mark_first_withdrawal(user_id)

    # الإحالة المتقدمة
    if not is_owner(user_id):
        check_and_reward_advanced_referral(user_id, client)

    await send_audit_log(client, callback.from_user, domain, actual_amount, spent)
    await notify_big_withdrawal(client, callback.from_user, domain, actual_amount)

    file_obj = io.BytesIO("\n".join(results).encode("utf-8"))
    file_name = f"{domain}_{actual_amount}_combos.txt"
    file_obj.name = file_name

    caption = (
        f"✅ <b>تم الاستخراج بنجاح!</b>\n\n"
        f"🌐 الدومين: <code>{domain}</code>\n"
        f"📊 العدد: <b>{actual_amount:,}</b>\n"
    )
    if not is_owner(user_id):
        caption += f"💳 النقاط المستهلكة: <b>{spent}</b>\n"
        caption += f"💎 رصيدك المتبقي: <b>{get_user_points(user_id)}</b>\n"
        if discount > 0:
            caption += f"🏷 خصم المستوى ({level}): {int(discount*100)}%\n"
        if first_bonus:
            caption += f"\n🎁 <b>مكافأة أول سحب:</b> +{FIRST_WITHDRAWAL_BONUS} نقطة!"

    await client.send_document(
        chat_id=user_id,
        document=file_obj,
        caption=caption
    )
    try:
        await callback.message.delete()
    except Exception:
        pass

@app.on_callback_query(filters.regex("^close_search$"))
async def close_search_cb(client: Client, callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass

# ==================== التشغيل ====================
if __name__ == "__main__":
    print("🤖 Bot is starting with full features...")
    app.run()
