import os
import re
import sqlite3
import uuid
import asyncio
import math
from collections import Counter
from pyrogram import Client, filters
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
)
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated

# ==================== الإعدادات ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]

# مسار قاعدة البيانات (يعمل على Railway + محلي)
DB_PATH = os.getenv("DB_PATH", "/data/combos.db")
if not os.path.exists(os.path.dirname(DB_PATH)) and os.path.dirname(DB_PATH):
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    except Exception:
        DB_PATH = "combos.db"

bot_enabled_for_users = True
user_action_state = {}

app = Client(
    "combo_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp" if os.path.exists("/tmp") else "."
)

# ==================== قاعدة البيانات ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('PRAGMA journal_mode = WAL;')
    cursor.execute('PRAGMA synchronous = OFF;')
    cursor.execute('PRAGMA cache_size = -64000;')
    cursor.execute('PRAGMA temp_store = MEMORY;')
    
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
            is_blocked INTEGER DEFAULT 0
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
    except Exception:
        pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY
        )
    ''')
    
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
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    # الإعدادات الافتراضية للأسعار
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("total_operations", "0")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("referral_points", "1.0")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("price_per_1k", "1.0")')      # سعر كل 1000 كومبو
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("price_under_1k", "0.5")')  # سعر أقل من 1000
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode = WAL;')
    conn.execute('PRAGMA synchronous = OFF;')
    return conn

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def get_setting(key: str, default: str = "0") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_price_per_1k() -> float:
    return float(get_setting("price_per_1k", "1.0"))

def get_price_under_1k() -> float:
    return float(get_setting("price_under_1k", "0.5"))

def calculate_price(amount: int, is_owner_user: bool = False) -> float:
    if is_owner_user:
        return 0.0
    if amount < 1000:
        return get_price_under_1k()
    # كل 1000 = price_per_1k
    return math.ceil(amount / 1000) * get_price_per_1k()

# ==================== النقاط ====================
def get_user_points(user_id: int) -> float:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, points) VALUES (?, 0)", (user_id,))
        conn.commit()
        conn.close()
        return 0.0
    conn.close()
    return float(row[0])

def add_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, points) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET points = points + ?", (user_id, points, points))
    conn.commit()
    conn.close()

def deduct_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()

def update_user_block_status(user_id: int, status: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def increment_operations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_operations'")
    conn.commit()
    conn.close()

def get_total_operations() -> int:
    return int(get_setting("total_operations", "0"))

def get_referral_points() -> float:
    return float(get_setting("referral_points", "1.0"))

def set_referral_points(points: float):
    set_setting("referral_points", str(points))

def log_search_domain(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO search_stats (domain, search_count) VALUES (?, 1) ON CONFLICT(domain) DO UPDATE SET search_count = search_count + 1", (domain.lower(),))
    conn.commit()
    conn.close()

# ==================== الاشتراكات ====================
async def check_subscription(client: Client, user_id: int) -> bool:
    if is_owner(user_id):
        return True
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    for (ch,) in channels:
        try:
            chat_id = int(ch) if (ch.startswith("-") or ch.isdigit()) else ch
            member = await client.get_chat_member(chat_id, user_id)
            if member.status in ["kicked", "left"]:
                return False
        except Exception:
            return False
    return True

@app.on_chat_member_updated()
async def on_ad_member_update(client: Client, update: ChatMemberUpdated):
    user_id = update.from_user.id if update.from_user else None
    if not user_id:
        return
        
    chat_identifier = str(update.chat.id)
    chat_username = f"@{update.chat.username}" if update.chat.username else None
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT channel_id, points_reward FROM ad_channels WHERE channel_id = ? OR channel_id = ?", (chat_identifier, chat_username))
    row = cursor.fetchone()
    
    if row:
        target_ch, reward_pts = row[0], float(row[1])
        if (not update.old_chat_member or update.old_chat_member.status in ["left", "kicked"]) and update.new_chat_member.status in ["member", "administrator"]:
            cursor.execute("SELECT 1 FROM ad_rewards WHERE user_id = ? AND channel_id = ?", (user_id, target_ch))
            if not cursor.fetchone():
                add_user_points(user_id, reward_pts)
                cursor.execute("INSERT INTO ad_rewards (user_id, channel_id) VALUES (?, ?)", (user_id, target_ch))
                conn.commit()
                try:
                    await client.send_message(user_id, f"🎉 تم إضافة **{reward_pts}** نقطة لاشتراكك في القناة الإعلانية!")
                except Exception:
                    pass
        elif update.old_chat_member and update.old_chat_member.status in ["member", "administrator"] and update.new_chat_member.status in ["left", "kicked"]:
            cursor.execute("SELECT 1 FROM ad_rewards WHERE user_id = ? AND channel_id = ?", (user_id, target_ch))
            if cursor.fetchone():
                deduct_user_points(user_id, reward_pts)
                cursor.execute("DELETE FROM ad_rewards WHERE user_id = ? AND channel_id = ?", (user_id, target_ch))
                conn.commit()
                try:
                    await client.send_message(user_id, f"⚠️ تم خصم **{reward_pts}** نقطة من رصيدك لمغادرتك القناة الإعلانية.")
                except Exception:
                    pass
    conn.close()

# ==================== دوال الكومبو ====================
def count_available_combos(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    query = f"%{domain.lower()}%"
    cursor.execute("SELECT COUNT(*) FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def extract_email_pass(line: str) -> str:
    parts = line.strip().split(':')
    if len(parts) >= 2:
        return f"{parts[-2]}:{parts[-1]}"
    return line.strip()

async def fetch_and_delete_combos(domain: str, limit_count: int) -> list:
    def _db_op():
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            query = f"%{domain.lower()}%"
            
            cursor.execute(
                "SELECT id, combo FROM combos WHERE LOWER(combo) LIKE ? LIMIT ?",
                (query, limit_count)
            )
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            ids_to_delete = [r[0] for r in rows]
            results = []
            seen = set()
            
            for r in rows:
                cleaned = extract_email_pass(r[1])
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    results.append(cleaned)
            
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
    cursor.execute("SELECT COUNT(*) FROM combos")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked_users = cursor.fetchone()[0]

    active_users = total_users - blocked_users

    cursor.execute("SELECT combo FROM combos LIMIT 40000")
    rows = cursor.fetchall()
    conn.close()

    domains = []
    domain_regex = re.compile(r'@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
    for r in rows:
        domains.extend([m.lower() for m in domain_regex.findall(r[0])])

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
    cursor.execute("SELECT COUNT(*) FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    count = cursor.fetchone()[0]
    cursor.execute("DELETE FROM combos WHERE LOWER(combo) LIKE ?", (query,))
    conn.commit()
    cursor.execute("VACUUM")
    conn.commit()
    conn.close()
    return count

# ==================== لوحات التحكم ====================
def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("📤 رفع ملف ULP")],
        [KeyboardButton("📊 الإحصائيات"), KeyboardButton("🗑 حذف حسب دومين")],
        [KeyboardButton("✅ تفعيل البوت"), KeyboardButton("🚫 إغلاق البوت")],
        [KeyboardButton("📢 إذاعة للأعضاء"), KeyboardButton("⚙️ إعدادات الاشتراك")],
        [KeyboardButton("📈 عدد العمليات"), KeyboardButton("🔥 الأكثر والأقل طلباً")],
        [KeyboardButton("🎁 إنشاء رابط هدية"), KeyboardButton("➕ إرسال نقاط ID")],
        [KeyboardButton("⚙️ نقاط الإحالة"), KeyboardButton("💰 تحكم بالأسعار")],
        [KeyboardButton("📢 إضافة إعلان قناة"), KeyboardButton("💣 حذف كل البيانات")],
        [KeyboardButton("📈 حالة البوت")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("💰 رصيدي ونقاطي")],
        [KeyboardButton("🔗 رابط الإحالة"), KeyboardButton("📺 قنوات الإعلانات")]
    ], resize_keyboard=True)

# ==================== الأوامر ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "عضو"
    username = f"@{message.from_user.username}" if message.from_user.username else "بدون يوزر"
    
    user_action_state.pop(user_id, None)
    args = message.command
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    is_existing_user = cursor.fetchone() is not None
    
    if not is_existing_user:
        cursor.execute("INSERT INTO users (user_id, points, is_blocked) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
        
        notify_text = (
            f"👤 **عضو جديد دخل البوت!** 🔥\n\n"
            f"• الاسم: **{first_name}**\n"
            f"• اليوزر: {username}\n"
            f"• الآيدي: <code>{user_id}</code>"
        )
        for owner in OWNER_IDS:
            try:
                await client.send_message(owner, notify_text)
            except Exception:
                pass
    else:
        update_user_block_status(user_id, 0)

    if len(args) > 1:
        ref_payload = args[1]
        
        if ref_payload.startswith("gift_"):
            code = ref_payload.replace("gift_", "")
            cursor.execute("SELECT points, used_by FROM gifts WHERE code = ?", (code,))
            gift = cursor.fetchone()
            if gift:
                if gift[1] is not None:
                    await message.reply("⚠️ تم استخدام رابط الهدية هذا سابقاً!")
                else:
                    pts = float(gift[0])
                    cursor.execute("UPDATE gifts SET used_by = ? WHERE code = ?", (user_id, code))
                    conn.commit()
                    add_user_points(user_id, pts)
                    await message.reply(f"🎁 مبروك! حصلت على <b>{pts}</b> نقطة من رابط الهدية.")
            else:
                await message.reply("❌ كود الهدية غير صالحة أو غير موجودة.")
            
        elif ref_payload.isdigit():
            referrer_id = int(ref_payload)
            if referrer_id != user_id and not is_existing_user:
                cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                conn.commit()
                ref_pts = get_referral_points()
                add_user_points(referrer_id, ref_pts)
                try:
                    await client.send_message(referrer_id, f"🎉 انضم عضو جديد عبر رابطك! حصلت على <b>{ref_pts}</b> نقطة.")
                except Exception:
                    pass

    conn.close()

    text = f"""اهلا بك في <b>بوت استخراج الكومبو والـ ULP</b> 🔥

رصيدك الحالي: <b>{get_user_points(user_id)}</b> نقطة 💎

قناة التحديثات: https://t.me/+91X31VNWIU1iNDM8
المطور: @D3_1D"""

    if is_owner(user_id):
        await message.reply(text, reply_markup=owner_keyboard())
    else:
        if not bot_enabled_for_users:
            await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
            return
        if not await check_subscription(client, user_id):
            await message.reply("⚠️ يجب عليك الاشتراك في قنوات البوت أولاً لاستخدام الخدمة!")
            return
        await message.reply(text, reply_markup=user_keyboard())

@app.on_message(filters.regex("^💰 رصيدي ونقاطي$"))
async def check_balance(client: Client, message: Message):
    user_action_state.pop(message.from_user.id, None)
    pts = get_user_points(message.from_user.id)
    await message.reply(f"💎 رصيدك الحالي هو: <b>{pts}</b> نقطة.")

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    user_action_state.pop(message.from_user.id, None)
    bot_username = (await client.get_me()).username
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start={user_id}"
    ref_pts = get_referral_points()
    await message.reply(
        f"🔗 <b>رابط الإحالة الخاص بك:</b>\n<code>{link}</code>\n\n"
        f"شاركه مع أصدقائك للحصول على <b>{ref_pts} نقطة</b> عند انضمام أي عضو جديد عبر رابطك!"
    )

@app.on_message(filters.regex("^📺 قنوات الإعلانات$"))
async def show_ad_channels(client: Client, message: Message):
    user_action_state.pop(message.from_user.id, None)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, points_reward FROM ad_channels")
    ads = cursor.fetchall()
    conn.close()
    
    if not ads:
        await message.reply("📺 لا توجد قنوات إعلانية متاحة حالياً لكسب النقاط.")
        return
        
    txt = "📺 <b>اشترك في القنوات التالية للحصول على نقاط:</b>\n\n"
    btns = []
    for ch, pts in ads:
        ch_link = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        txt += f"• القناة: {ch} (المكافأة: <b>{pts}</b> نقطة)\n"
        btns.append([InlineKeyboardButton(f"الانضمام إلى {ch} (+{pts} نقطة)", url=ch_link)])
        
    await message.reply(txt, reply_markup=InlineKeyboardMarkup(btns))

# ==================== أوامر المالك ====================
@app.on_message(filters.regex("^💰 تحكم بالأسعار$") & filters.user(OWNER_IDS))
async def price_control(client: Client, message: Message):
    price_1k = get_price_per_1k()
    price_under = get_price_under_1k()
    ref_pts = get_referral_points()
    
    text = f"""⚙️ <b>لوحة تحكم الأسعار</b>

• سعر كل <b>1000</b> كومبو: <b>{price_1k}</b> نقطة
• سعر أقل من 1000 كومبو: <b>{price_under}</b> نقطة
• نقاط الإحالة: <b>{ref_pts}</b> نقطة

لتغيير الأسعار استخدم الأوامر التالية:

<code>/set_price_1k 1.0</code>
<code>/set_price_under 0.5</code>
<code>/set_ref_points 1.0</code>"""
    await message.reply(text)

@app.on_message(filters.command("set_price_1k") & filters.user(OWNER_IDS))
async def set_price_1k_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ مثال: <code>/set_price_1k 1.0</code>")
        return
    try:
        val = float(message.command[1])
        set_setting("price_per_1k", str(val))
        await message.reply(f"✅ تم تغيير سعر الـ 1000 كومبو إلى <b>{val}</b> نقطة.")
    except ValueError:
        await message.reply("❌ أدخل رقم صحيح.")

@app.on_message(filters.command("set_price_under") & filters.user(OWNER_IDS))
async def set_price_under_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ مثال: <code>/set_price_under 0.5</code>")
        return
    try:
        val = float(message.command[1])
        set_setting("price_under_1k", str(val))
        await message.reply(f"✅ تم تغيير سعر أقل من 1000 إلى <b>{val}</b> نقطة.")
    except ValueError:
        await message.reply("❌ أدخل رقم صحيح.")

@app.on_message(filters.regex("^⚙️ نقاط الإحالة$") & filters.user(OWNER_IDS))
async def ref_pts_settings(client: Client, message: Message):
    current_pts = get_referral_points()
    await message.reply(
        f"⚙️ <b>نقاط الإحالة الحالية:</b> <b>{current_pts}</b> نقطة.\n\n"
        "لتغيير القيمة أرسل:\n<code>/set_ref_points 2</code>"
    )

@app.on_message(filters.command("set_ref_points") & filters.user(OWNER_IDS))
async def set_ref_pts_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ مثال: <code>/set_ref_points 1.5</code>")
        return
    try:
        pts = float(message.command[1])
        set_referral_points(pts)
        await message.reply(f"✅ تم تغيير مكافأة الإحالة إلى <b>{pts}</b> نقطة.")
    except ValueError:
        await message.reply("❌ أدخل رقم صحيح.")

@app.on_message(filters.regex("^📢 إضافة إعلان قناة$") & filters.user(OWNER_IDS))
async def add_ad_info(client: Client, message: Message):
    await message.reply("📝 استخدم الأمر:\n<code>/add_ad @channel 2</code>")

@app.on_message(filters.command("add_ad") & filters.user(OWNER_IDS))
async def add_ad_cmd(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ الصيغة: <code>/add_ad @channel_username POINTS</code>")
        return
    ch = message.command[1]
    pts = float(message.command[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO ad_channels (channel_id, points_reward) VALUES (?, ?)", (ch, pts))
    conn.commit()
    conn.close()
    
    await message.reply(f"✅ تم إضافة القناة <code>{ch}</code> بمكافأة <b>{pts}</b> نقطة.")

@app.on_message(filters.regex("^🎁 إنشاء رابط هدية$") & filters.user(OWNER_IDS))
async def create_gift_cmd(client: Client, message: Message):
    await message.reply("📝 أرسل:\n<code>/make_gift 5</code>")

@app.on_message(filters.command("make_gift") & filters.user(OWNER_IDS))
async def make_gift_process(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ الاستخدام: <code>/make_gift 5</code>")
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
    await message.reply(f"✅ تم إنشاء رابط الهدية بقيمة <b>{pts}</b> نقطة:\n\n{link}")

@app.on_message(filters.regex("^➕ إرسال نقاط ID$") & filters.user(OWNER_IDS))
async def send_points_id_cmd(client: Client, message: Message):
    await message.reply("📝 استخدم:\n<code>/send_pts USER_ID POINTS</code>")

@app.on_message(filters.command("send_pts") & filters.user(OWNER_IDS))
async def process_send_pts(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ الصيغة: <code>/send_pts USER_ID POINTS</code>")
        return
    target_id = int(message.command[1])
    pts = float(message.command[2])
    add_user_points(target_id, pts)
    await message.reply(f"✅ تم إضافة <b>{pts}</b> نقطة للمستخدم <code>{target_id}</code>.")

@app.on_message(filters.regex("^⚙️ إعدادات الاشتراك$") & filters.user(OWNER_IDS))
async def channel_settings(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM channels")
    rows = cursor.fetchall()
    conn.close()
    
    txt = "⚙️ <b>قنوات الاشتراك الإجباري:</b>\n\n"
    if rows:
        for (ch,) in rows:
            txt += f"• <code>{ch}</code>\n"
    else:
        txt += "لا توجد قنوات حالياً.\n"
        
    txt += "\n➕ إضافة: <code>/add_channel @username</code>\n"
    txt += "🗑 حذف: <code>/del_channel @username</code>"
    await message.reply(txt)

@app.on_message(filters.command("add_channel") & filters.user(OWNER_IDS))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ اكتب أيدي أو يوزر القناة!")
        return
    ch = message.command[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels (channel_id) VALUES (?)", (ch,))
    conn.commit()
    conn.close()
    await message.reply(f"✅ تم إضافة القناة <code>{ch}</code>.")

@app.on_message(filters.command("del_channel") & filters.user(OWNER_IDS))
async def del_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ اكتب أيدي أو يوزر القناة!")
        return
    ch = message.command[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch,))
    conn.commit()
    conn.close()
    await message.reply(f"🗑 تم حذف القناة <code>{ch}</code>.")

@app.on_message(filters.regex("^📢 إذاعة للأعضاء$") & filters.user(OWNER_IDS))
async def broadcast_ask(client: Client, message: Message):
    await message.reply("📝 رد على الرسالة اللي تريد تذيعها واكتب <code>/bc</code>")

@app.on_message(filters.command("bc") & filters.user(OWNER_IDS))
async def start_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply("❌ لازم ترد على الرسالة بـ <code>/bc</code>")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    await message.reply(f"🚀 جاري الإذاعة لـ <b>{len(users)}</b> عضو...")
    success, failed = 0, 0
    
    for (uid,) in users:
        try:
            await target_msg.copy(uid)
            update_user_block_status(uid, 0)
            success += 1
            await asyncio.sleep(0.04)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await target_msg.copy(uid)
            update_user_block_status(uid, 0)
            success += 1
        except (UserIsBlocked, InputUserDeactivated):
            update_user_block_status(uid, 1)
            failed += 1
        except Exception:
            failed += 1
            
    await message.reply(f"✅ اكتملت الإذاعة!\n🟢 النجاح: {success}\n🔴 الفشل: {failed}")

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
    
    deleted_total = 0
    for (dom,) in rows:
        deleted_total += delete_by_domain(dom)
        
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
    status = "🟢 مفعل للأعضاء" if bot_enabled_for_users else "🔴 مغلق عن الأعضاء"
    await message.reply(f"حالة البوت حالياً:\n\n<b>{status}</b>")

@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, top_domains, total_users, blocked_users, active_users = get_stats()
    text = f"""📊 <b>إحصائيات البوت</b>

👥 <b>الأعضاء:</b>
• المسجلين: <b>{total_users:,}</b>
• النشطين: <b>{active_users:,}</b>
• المحظورين: <b>{blocked_users:,}</b>

📦 <b>الكومبو:</b>
• الإجمالي: <b>{total:,}</b>

🔥 <b>أكثر الدومينات:</b>
"""
    if top_domains:
        for i, (domain, count) in enumerate(top_domains, 1):
            text += f"{i}. <code>{domain}</code> → {count:,}\n"
    else:
        text += "لا توجد بيانات.\n"
    await message.reply(text)

@app.on_message(filters.regex("^💣 حذف كل البيانات$") & filters.user(OWNER_IDS))
async def confirm_delete_all(client: Client, message: Message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم احذف الكل", callback_data="confirm_delete_all"),
         InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")]
    ])
    await message.reply("⚠️ هل أنت متأكد من حذف <b>كل</b> البيانات؟", reply_markup=buttons)

@app.on_callback_query(filters.regex("^confirm_delete_all$"))
async def delete_all_confirmed(client: Client, callback):
    if not is_owner(callback.from_user.id):
        return
    await callback.answer()
    delete_all_combos()
    await callback.message.edit_text("✅ تم حذف كل البيانات بنجاح.")

@app.on_callback_query(filters.regex("^cancel_delete$"))
async def cancel_delete(client: Client, callback):
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء عملية الحذف.")

@app.on_message(filters.regex("^🗑 حذف حسب دومين$") & filters.user(OWNER_IDS))
async def ask_domain_delete(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_domain_delete"
    await message.reply("📝 أرسل اسم الدومين الذي تريد حذفه بالكامل:")

# ==================== رفع الملفات ====================
@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def ask_file(client: Client, message: Message):
    await message.reply("📤 أرسل ملفات الـ <b>ULP</b> الآن...")

@app.on_message(filters.document & filters.user(OWNER_IDS))
async def handle_large_document(client: Client, message: Message):
    try:
        file_name = message.document.file_name or "unknown.txt"
        file_size = message.document.file_size or 0

        msg = await message.reply(f"⏳ جاري تحميل الملف: <b>{file_name}</b> ({file_size / 1024 / 1024:.2f} MB)...")
        temp_path = await message.download(file_name=f"/tmp/temp_{message.id}_{file_name}")

        await msg.edit_text("⏳ جاري إضافة الكومبوهات إلى قاعدة البيانات...")
        added = add_combos_from_file(temp_path)
        
        try:
            os.remove(temp_path)
        except Exception:
            pass

        await msg.edit_text(f"✅ تم بنجاح!\n\nالملف: <b>{file_name}</b>\nأُضيف: <b>{added:,}</b> كومبو")

    except Exception as e:
        await message.reply(f"❌ خطأ أثناء الرفع:\n<code>{str(e)}</code>")

# ==================== نظام البحث والاستخراج ====================
@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        if not bot_enabled_for_users:
            await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
            return
        if not await check_subscription(client, user_id):
            await message.reply("⚠️ يجب عليك الاشتراك في القنوات أولاً.")
            return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("✍️ <b>أرسل اسم الموقع أو اللعبة الذي تريد البحث عنه:</b>")

@app.on_message(filters.text & \~filters.command(["start", "bc", "add_ad", "make_gift", "send_pts", "add_channel", "del_channel", "set_ref_points", "set_price_1k", "set_price_under"]))
async def process_domain_input(client: Client, message: Message):
    user_id = message.from_user.id
    
    # تجاهل أزرار الكيبورد
    keyboard_buttons = [
        "🔍 بحث عن دومين", "📤 رفع ملف ULP", "📊 الإحصائيات", "🗑 حذف حسب دومين",
        "✅ تفعيل البوت", "🚫 إغلاق البوت", "📢 إذاعة للأعضاء", "⚙️ إعدادات الاشتراك",
        "📈 عدد العمليات", "🔥 الأكثر والأقل طلباً", "🎁 إنشاء رابط هدية", "➕ إرسال نقاط ID",
        "⚙️ نقاط الإحالة", "📢 إضافة إعلان قناة", "💣 حذف كل البيانات", "📈 حالة البوت",
        "💰 رصيدي ونقاطي", "🔗 رابط الإحالة", "📺 قنوات الإعلانات", "💰 تحكم بالأسعار"
    ]
    if message.text in keyboard_buttons:
        return

    current_state = user_action_state.get(user_id)
    if not current_state:
        return

    domain = message.text.strip().lower()
    if len(domain) < 2:
        return

    if current_state == "awaiting_domain_delete" and is_owner(user_id):
        user_action_state.pop(user_id, None)
        try:
            deleted = await asyncio.to_thread(delete_by_domain, domain)
            await message.reply(f"✅ تم حذف <b>{deleted:,}</b> كومبو متعلق بـ <b>{domain}</b>")
        except Exception as e:
            await message.reply(f"❌ فشل الحذف: <code>{e}</code>")
        return

    if current_state != "awaiting_search_domain":
        return

    user_action_state.pop(user_id, None)

    is_owner_user = is_owner(user_id)
    if not is_owner_user:
        if not bot_enabled_for_users:
            await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
            return
        if not await check_subscription(client, user_id):
            await message.reply("⚠️ يجب عليك الاشتراك في القنوات الإجبارية.")
            return

    available_count = await asyncio.to_thread(count_available_combos, domain)

    if available_count <= 0:
        await message.reply(f"❌ لا توجد حسابات متوفرة حالياً لموقع <b>{domain}</b>.")
        for owner in OWNER_IDS:
            try:
                await client.send_message(owner, f"⚠️ طلب على <code>{domain}</code> وهو غير متوفر!")
            except Exception:
                pass
        return

    pts = get_user_points(user_id)

    buttons_list = []
    max_k = available_count // 1000

    row = []
    for k in range(1, min(max_k + 1, 11)):
        amount = k * 1000
        price = calculate_price(amount, is_owner_user)
        btn = InlineKeyboardButton(
            f"📥 {k}K ({price} نقطة)", 
            callback_data=f"buy_{amount}_{price}_{domain}"
        )
        row.append(btn)
        if len(row) == 2:
            buttons_list.append(row)
            row = []
            
    if row:
        buttons_list.append(row)

    # زر سحب الكل
    total_price = calculate_price(available_count, is_owner_user)
    buttons_list.append([
        InlineKeyboardButton(
            f"🚀 سحب الكل ({available_count:,}) بـ {total_price} نقطة", 
            callback_data=f"buy_{available_count}_{total_price}_{domain}"
        )
    ])
    
    buttons_list.append([
        InlineKeyboardButton("❌ إلغاء", callback_data="cancel_pull")
    ])

    await message.reply(
        f"🎯 <b>الموقع:</b> <code>{domain}</code>\n"
        f"📊 <b>المتاح:</b> <b>{available_count:,}</b> حساب\n"
        f"💳 <b>رصيدك:</b> <b>{pts}</b> نقطة\n\n"
        f"<b>اختر الكمية:</b>",
        reply_markup=InlineKeyboardMarkup(buttons_list)
    )

@app.on_callback_query(filters.regex(r"^buy_(\d+)_(.+)_(.+)"))
async def handle_buy_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_owner_user = is_owner(user_id)

    parts = callback.data.split("_", 3)
    amount_to_pull = int(parts[1])
    required_points = float(parts[2])
    domain = parts[3]

    pts = get_user_points(user_id)

    if not is_owner_user and pts < required_points:
        await callback.answer(f"❌ رصيدك غير كافٍ! تحتاج {required_points} نقطة.", show_alert=True)
        return

    await callback.answer("⏳ جاري الاستخراج...")
    try:
        status_msg = await callback.message.edit_text(
            f"⚡ جاري استخراج <b>{amount_to_pull:,}</b> كومبو لموقع <b>{domain}</b>..."
        )
    except Exception:
        status_msg = await client.send_message(user_id, f"⚡ جاري استخراج <b>{amount_to_pull:,}</b> كومبو...")

    try:
        log_search_domain(domain)
    except Exception:
        pass

    filename = None
    try:
        results = await fetch_and_delete_combos(domain, amount_to_pull)

        if not results:
            await status_msg.edit_text(f"❌ لم يتم العثور على نتائج أو تم سحبها من قبل لموقع <b>{domain}</b>.")
            return

        fetched_count = len(results)

        filename = f"/tmp/results_{domain}_{user_id}_{uuid.uuid4().hex[:8]}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(results))

        caption = (
            f"✅ تم استخراج <b>{fetched_count:,}</b> كومبو لـ <b>{domain}</b>\n"
            f"💳 الخصم: <b>{required_points}</b> نقطة"
        )
        
        await client.send_document(
            chat_id=user_id,
            document=filename,
            caption=caption
        )

        if not is_owner_user and required_points > 0:
            deduct_user_points(user_id, required_points)
        
        increment_operations()

        try:
            await status_msg.delete()
        except Exception:
            pass

    except FloodWait as e:
        await client.send_message(user_id, f"⏳ انتظر {e.value} ثانية بسبب FloodWait.")
    except Exception as e:
        await client.send_message(user_id, f"❌ خطأ أثناء الاستخراج:\n<code>{str(e)[:300]}</code>")
        print(f"[EXTRACT ERROR] user={user_id} domain={domain} → {e}")
    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

@app.on_callback_query(filters.regex("^cancel_pull$"))
async def cancel_pull_cb(client: Client, callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء العملية.")

# ==================== التشغيل ====================
print("⚡ Bot is starting...")
app.run()
