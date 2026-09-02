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

# ==================== الإعدادات الأساسية ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "combos.db")

bot_enabled_for_users = True
subscription_cache = {}
SUB_CACHE_SECONDS = 90

DAILY_REWARD_BASE = 0.5

# قائمة الباسوردات الجديدة المطلوبة للنسخة الثانية
CUSTOM_PASSWORDS_LIST = [
    "Aa123456",
    "Aa123456@",
    "Aa123123",
    "Aa12341234",
    "Aa11223344",
    "Aa@123456"
]

app = Client(
    "combo_bot_v2",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp" if os.path.exists("/tmp") else "."
)

# ==================== قاعدة البيانات والتحديثات الهيكلية ====================
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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    defaults = [
        ("total_operations", "0"),
        ("referral_points", "1.0"),
        ("log_channel", ""),
        ("forced_sub_enabled", "1"),
        ("daily_reward", "0.5"),
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

# ==================== دوال إدارة المستخدمين والنقاط ====================
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

def get_referral_points() -> float:
    return float(get_setting("referral_points", "1.0"))

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

# ==================== المستويات والإنجازات ====================
def calculate_level(points: float, total_withdrawals: int) -> str:
    if points >= 150 or total_withdrawals >= 75:
        return "ماسيني 💎"
    if points >= 80 or total_withdrawals >= 35:
        return "ذهبي 🥇"
    if points >= 25 or total_withdrawals >= 10:
        return "فضي 🥈"
    return "عادي 🥉"

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

# ==================== سجل العمليات والسحوبات ====================
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

# ==================== نظام التحقق من القنوات ====================
def get_forced_channels():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, title, invite_link FROM channels")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r["channel_id"], "title": r["title"] or "قناة", "link": r["invite_link"]} for r in rows]

def is_forced_sub_enabled() -> bool:
    return get_setting("forced_sub_enabled", "1") == "1"

async def is_user_in_channel(client: Client, user_id: int, channel_id: str) -> bool:
    try:
        chat_id = int(channel_id) if (str(channel_id).startswith("-") or str(channel_id).isdigit()) else channel_id
        member = await client.get_chat_member(chat_id, user_id)
        status = str(member.status).lower()
        if any(s in status for s in ("creator", "owner", "administrator", "member")):
            return True
        return False
    except Exception:
        return False

async def check_subscription(client: Client, user_id: int, force_refresh: bool = False) -> tuple:
    if is_owner(user_id) or not is_forced_sub_enabled():
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
        link = ch.get("link") or f"https://t.me/{ch['id']}"
        buttons.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=link)])
    buttons.append([InlineKeyboardButton(text="✅ تحقق من الاشتراك", callback_data="check_force_sub")])
    return InlineKeyboardMarkup(buttons)

async def send_force_sub_message(client: Client, chat_id: int, missing: list):
    text = "⛔️ <b>عذراً، يجب عليك الاشتراك في قنوات البوت للاستمرار:</b>"
    kb = build_subscription_keyboard(missing)
    await client.send_message(chat_id, text, reply_markup=kb)

# ==================== واجهات الاستخدام (Keyboards) ====================
def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("📊 الإحصائيات الشاملة")],
        [KeyboardButton("✅ تفعيل البوت"), KeyboardButton("🚫 إغلاق البوت")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين")],
        [KeyboardButton("💰 رصيدي ونقاطي"), KeyboardButton("📋 سجل العمليات")],
        [KeyboardButton("🔗 رابط الإحالة")]
    ], resize_keyboard=True)

# ==================== معالجة الكومبو والسحب (مع الحذف التلقائي) ====================
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

async def fetch_and_delete_combos(domain: str, limit_count: int, is_owner_user: bool = False) -> list:
    def _db_op():
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            query = f"%{domain.lower()}%"
            
            # إذا كان المالك وطلب الكل، نحدد جلب كل السطور المطابقة تماماً دون حدود
            if is_owner_user and limit_count == 0:
                cursor.execute("SELECT id, combo FROM combos WHERE LOWER(combo) LIKE ?", (query,))
            else:
                fetch_limit = int(limit_count * 2.5) + 1500
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
                if not is_owner_user and limit_count > 0 and len(results) >= limit_count:
                    break
                cleaned = extract_email_pass(r["combo"])
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    results.append(cleaned)
                    ids_to_delete.append(r["id"])

            # الحفاظ على نظام الحذف التلقائي بعد السحب تماماً كما طلبتم
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
                try: conn.rollback()
                except Exception: pass
            return []
        finally:
            if conn: conn.close()

    return await asyncio.to_thread(_db_op)

# ==================== المعالجات الأساسية للأحداث (Handlers) ====================
user_action_state = {}

@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)

    banned, reason = is_user_banned(user_id)
    if banned and not is_owner(user_id):
        await message.reply(f"🚫 تم حظرك من استخدام البوت.\nالسبب: {reason}")
        return

    if is_owner(user_id):
        await message.reply("أهلاً بك يا مطور البوت في لوحة التحكم الإدارية:", reply_markup=owner_keyboard())
        return

    if not bot_enabled_for_users:
        await message.reply("⚠️ عذراً، البوت في صيانة وتحديث حالياً.")
        return

    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return

    row = get_user_row(user_id)
    pts = get_user_points(user_id)
    text = f"مرحباً بك في بوت الكومبو 🚀\n\n💎 رصيدك الحالي: <b>{pts}</b> نقطة"
    await message.reply(text, reply_markup=user_keyboard())

@app.on_callback_query(filters.regex("^check_force_sub$"))
async def check_force_sub_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_ok, missing = await check_subscription(client, user_id, force_refresh=True)
    if is_ok:
        await callback.answer("✅ تم التحقق من اشتراكك بنجاح!")
        await client.send_message(user_id, "🏠 القائمة الرئيسية:", reply_markup=user_keyboard())
    else:
        await callback.answer("❌ لم تقم بالاشتراك في كافة القنوات المطلوبة!", show_alert=True)

@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("📝 أرسل الآن الدومين المراد البحث عنه (مثال: `ludo` أو `gmail.com`):")

@app.on_message(filters.text & ~filters.regex(r"^(🔍|📊|✅|🚫|💰|📋|🔗)"))
async def process_text_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    text_input = message.text.strip()
    state = user_action_state.get(user_id)

    if state == "awaiting_search_domain":
        user_action_state.pop(user_id, None)
        domain = text_input.lower()
        msg = await message.reply(f"🔍 جاري البحث عن الدومين `{domain}`...")
        available = count_available_combos(domain)

        if available == 0:
            await msg.edit_text("❌ عذراً، لا توجد حسابات متاحة لهذا الدومين حالياً.")
            return

        markup_buttons = [
            [InlineKeyboardButton("100", callback_data=f"get_{domain}_100"),
             InlineKeyboardButton("500", callback_data=f"get_{domain}_500"),
             InlineKeyboardButton("1000", callback_data=f"get_{domain}_1000")],
            [InlineKeyboardButton("2500", callback_data=f"get_{domain}_2500"),
             InlineKeyboardButton("5000", callback_data=f"get_{domain}_5000"),
             InlineKeyboardButton("10000", callback_data=f"get_{domain}_10000")]
        ]
        
        # خيار سحب الكل متاح للجميع، ولكن للمالك يتم جلب كل العدد الحقيقي الضخم بدون قيود
        markup_buttons.append([InlineKeyboardButton(f"📥 سحب الكل ({available:,})", callback_data=f"get_{domain}_all")])

        markup = InlineKeyboardMarkup(markup_buttons)
        await msg.edit_text(f"🎯 المتاح للدومين `{domain}`: <b>{available:,}</b> حساب\nاختر كمية السحب المطلوبة:", reply_markup=markup)

@app.on_callback_query(filters.regex("^get_"))
async def callback_get_combos(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    domain = parts[1]
    amount_str = parts[2]

    available = count_available_combos(domain)
    
    # تصحيح سحب الكل للمالك ليسحب كل شيء بدون استثناء
    if amount_str == "all":
        amount = available if is_owner(user_id) else min(available, 15000)
    else:
        amount = int(amount_str)

    if amount <= 0:
        await callback.answer("❌ عذراً، الكمية غير متاحـة.", show_alert=True)
        return

    required_points = 0 if is_owner(user_id) else round((amount / 1000.0), 2)
    user_pts = get_user_points(user_id)

    if not is_owner(user_id) and user_pts < required_points:
        await callback.answer("❌ رصيدك غير كافي لإتمام هذه العملية!", show_alert=True)
        return

    await callback.answer("⏳ جاري استخراج الحسابات ومعالجتها...", show_alert=False)
    await callback.message.edit_text(f"⏳ جاري سحب ومعالجة <b>{amount:,}</b> من حسابات `{domain}`...")

    # جلب الحسابات الأصلية (مع الحذف التلقائي من القاعدة)
    results = await fetch_and_delete_combos(domain, 0 if (is_owner(user_id) and amount_str == "all") else amount, is_owner_user=is_owner(user_id))
    if not results:
        await callback.message.edit_text("❌ عذراً، نفدت الحسابات المطلوبة.")
        return

    actual_amount = len(results)
    spent = 0 if is_owner(user_id) else round((actual_amount / 1000.0), 2)

    if not is_owner(user_id):
        deduct_user_points(user_id, spent)

    record_withdrawal(user_id, domain, actual_amount, spent)
    log_search_domain(domain)
    increment_operations()

    # 1. الملف الأول: النسخة الأصلية
    original_file_obj = io.BytesIO("\n".join(results).encode("utf-8"))
    original_file_obj.name = f"{domain}_original_{actual_amount}.txt"

    # 2. الملف الثاني: النسخة المعدلة بالباسوردات الجديدة المحددة
    modified_results = []
    for line in results:
        if ":" in line:
            email_part = line.split(":")[0]
            new_pass = random.choice(CUSTOM_PASSWORDS_LIST)
            modified_results.append(f"{email_part}:{new_pass}")
        else:
            modified_results.append(line)

    modified_file_obj = io.BytesIO("\n".join(modified_results).encode("utf-8"))
    modified_file_obj.name = f"{domain}_secured_passwords_{actual_amount}.txt"

    # إرسال الملفين معاً للمستخدم
    await client.send_document(
        chat_id=user_id,
        document=original_file_obj,
        caption=f"📁 <b>الملف الأصلي:</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{actual_amount:,}</b>"
    )

    await client.send_document(
        chat_id=user_id,
        document=modified_file_obj,
        caption=f"🔐 <b>الملف المُعدل (بالباسوردات الجديدة الثابتة):</b>\n🌐 الدومين: `{domain}`\n📊 العدد: <b>{actual_amount:,}</b>"
    )

    try: 
        await callback.message.delete()
    except Exception: 
        pass

if __name__ == "__main__":
    print("🚀 Bot v2 updated successfully with custom passwords file generation and unrestricted owner fetch!")
    app.run()
