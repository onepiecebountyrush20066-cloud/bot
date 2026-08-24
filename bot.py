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

# ==================== الإعدادات ومسار التخزين ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]

if os.path.exists("/storage/emulated/0/"):
    BASE_DIR = "/storage/emulated/0/combo-bot"
else:
    BASE_DIR = os.path.join(os.getcwd(), "combo_data")

DB_PATH = os.path.join(BASE_DIR, "combos.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_ulp")
MEMBERS_EXPORT_PATH = os.path.join(BASE_DIR, "users_points.txt")

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

bot_enabled_for_users = True
user_action_state = {}

# قائمة الأيقونات الملونة Custom Emoji IDs
E = {
    'fire': '5424972470023104089',
    'check': '5206607081334906820',
    'sparkles': '5325547803936572038',
    'gem': '5427168083074628963',
    'pencil': '5395444784611480792',
    'settings': '5341715473882955310',
    'crown': '5217822164362739968',
    'chart': '5231200819986047254',
    'warning': '5447644880824181073',
    'trophy': '5188344996356448758',
    'people': '5258513401784573443',
    'link': '5271604874419647061',
    'arrow': '5416117059207572332',
    'cross': '5210952531676504517',
    'bulb': '5422439311196834318',
    'bell': '5458603043203327669',
    'search': '5422439311196834318',
}

app = Client(
    "combo_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp" if os.path.exists("/tmp") else "."
)

# ==================== إدارة قاعدة البيانات ====================
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
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("total_operations", "0")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("referral_points", "1.0")')
    
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

# ==================== تصدير وحفظ ملف الأعضاء ====================
def save_members_points_to_file():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, points, is_blocked, referred_by FROM users")
        rows = cursor.fetchall()
        conn.close()

        with open(MEMBERS_EXPORT_PATH, "w", encoding="utf-8") as f:
            f.write("User ID | Points | Blocked Status | Referred By\n")
            f.write("="*50 + "\n")
            for r in rows:
                status = "Blocked" if r[2] == 1 else "Active"
                f.write(f"{r[0]} | {r[1]} | {status} | {r[3]}\n")
        return len(rows)
    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        return 0

# ==================== إدارة النقاط والمهمات ====================
def get_user_points(user_id: int) -> float:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, points) VALUES (?, 0)", (user_id,))
        conn.commit()
        conn.close()
        save_members_points_to_file()
        return 0.0
    conn.close()
    return float(row[0])

def add_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, points) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET points = points + ?", (user_id, points, points))
    conn.commit()
    conn.close()
    save_members_points_to_file()

def deduct_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()
    save_members_points_to_file()

def update_user_block_status(user_id: int, status: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()
    save_members_points_to_file()

def increment_operations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_operations'")
    conn.commit()
    conn.close()

def get_total_operations() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'total_operations'")
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else 0

def get_referral_points() -> float:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'referral_points'")
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 1.0

def set_referral_points(points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET value = ? WHERE key = 'referral_points'", (str(points),))
    conn.commit()
    conn.close()

def log_search_domain(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO search_stats (domain, search_count) VALUES (?, 1) ON CONFLICT(domain) DO UPDATE SET search_count = search_count + 1", (domain.lower(),))
    conn.commit()
    conn.close()

# ==================== فحص الاشتراكات والإعلانات ====================
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

# ==================== معالجة قاعدة البيانات للكومبو ====================
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

# ==================== لوحات التحكم مع الرموز والإيموجيات الملونة ====================
def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("📤 رفع ملف ULP")],
        [KeyboardButton("📊 الإحصائيات"), KeyboardButton("🗑 حذف حسب دومين")],
        [KeyboardButton("✅ تفعيل البوت"), KeyboardButton("🚫 إغلاق البوت")],
        [KeyboardButton("📢 إذاعة للأعضاء"), KeyboardButton("⚙️ إعدادات الاشتراك")],
        [KeyboardButton("📈 عدد العمليات"), KeyboardButton("🔥 الأكثر والأقل طلباً")],
        [KeyboardButton("🎁 إنشاء رابط هدية"), KeyboardButton("➕ إرسال نقاط ID")],
        [KeyboardButton("⚙️ نقاط الإحالة"), KeyboardButton("📢 إضافة إعلان قناة")],
        [KeyboardButton("📁 حفظ ملف الأعضاء"), KeyboardButton("💣 حذف كل البيانات")],
        [KeyboardButton("📈 حالة البوت")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("💰 رصيدي ونقاطي")],
        [KeyboardButton("🔗 رابط الإحالة"), KeyboardButton("📺 قنوات الإعلانات")]
    ], resize_keyboard=True)

# ==================== الأوامر العامة والبدء ====================
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
        save_members_points_to_file()
        
        notify_text = (
            f"👤 <b>عضو جديد دخل البوت!</b> <tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji>\n\n"
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

    text = f"""
<blockquote><b>أهلاً بك في بوت استخراج الكومبو والـ ULP الاحترافي</b> <tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji></blockquote>

<blockquote><b>رصيدك ونقاطك الحالية:</b> <b>{get_user_points(user_id)}</b> نقطة <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji></blockquote>

<blockquote><b>قناة التحديثات:</b> https://t.me/+91X31VNWIU1iNDM8
<b>المطور:</b> @D3_1D</blockquote>
"""

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
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji> <b>رصيدك الحالي هو:</b> <b>{pts}</b> نقطة.</blockquote>")

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    user_action_state.pop(message.from_user.id, None)
    bot_username = (await client.get_me()).username
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start={user_id}"
    ref_pts = get_referral_points()
    await message.reply(
        f"<blockquote><tg-emoji emoji-id='{E['link']}'>🔗</tg-emoji> <b>رابط الإحالة الخاص بك:</b>\n<code>{link}</code>\n\n"
        f"شاركه مع أصدقائك للحصول على <b>{ref_pts} نقطة</b> عند انضمام أي عضو جديد عبر رابطك!</blockquote>"
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
        await message.reply("<blockquote>📺 لا توجد قنوات إعلانية متاحة حالياً لكسب النقاط.</blockquote>")
        return
        
    txt = f"<blockquote><tg-emoji emoji-id='{E['bell']}'>📺</tg-emoji> <b>اشترك في القنوات التالية للحصول على نقاط:</b></blockquote>\n\n"
    btns = []
    for ch, pts in ads:
        ch_link = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        txt += f"• القناة: {ch} (المكافأة: <b>{pts}</b> نقطة)\n"
        btns.append([InlineKeyboardButton(f"الانضمام إلى {ch} (+{pts} نقطة)", url=ch_link)])
        
    await message.reply(txt, reply_markup=InlineKeyboardMarkup(btns))

# ==================== أوامر المالك ====================
@app.on_message(filters.regex("^📁 حفظ ملف الأعضاء$") & filters.user(OWNER_IDS))
async def manual_export_members(client: Client, message: Message):
    total = save_members_points_to_file()
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم حفظ بيانات ونقاط <b>{total}</b> عضو بنجاح في المسار:\n<code>{MEMBERS_EXPORT_PATH}</code></blockquote>")

@app.on_message(filters.regex("^⚙️ نقاط الإحالة$") & filters.user(OWNER_IDS))
async def ref_pts_settings(client: Client, message: Message):
    current_pts = get_referral_points()
    await message.reply(
        f"<blockquote><tg-emoji emoji-id='{E['settings']}'>⚙️</tg-emoji> <b>نقاط الإحالة الحالية:</b> <b>{current_pts}</b> نقطة.\n\n"
        "لتغيير القيمة أرسل الأمر التالي:\n"
        "<code>/set_ref_points 2</code></blockquote>"
    )

@app.on_message(filters.command("set_ref_points") & filters.user(OWNER_IDS))
async def set_ref_pts_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى إدخال القيمة الجديدة! مثال:\n<code>/set_ref_points 1.5</code>")
        return
    try:
        pts = float(message.command[1])
        set_referral_points(pts)
        await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم تغيير قيمة مكافأة الإحالة إلى <b>{pts}</b> نقطة بنجاح!</blockquote>")
    except ValueError:
        await message.reply("❌ يرجى إدخال رقم صحيح أو عشري.")

@app.on_message(filters.regex("^📢 إضافة إعلان قناة$") & filters.user(OWNER_IDS))
async def add_ad_info(client: Client, message: Message):
    await message.reply("📝 لإضافة قناة إعلانية مع نقاط مكافأة، استخدم الأمر:\n<code>/add_ad @channel 2</code>")

@app.on_message(filters.command("add_ad") & filters.user(OWNER_IDS))
async def add_ad_cmd(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ الصيغة خاطئة! استخدم:\n<code>/add_ad @channel_username POINTS</code>")
        return
    ch = message.command[1]
    pts = float(message.command[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO ad_channels (channel_id, points_reward) VALUES (?, ?)", (ch, pts))
    conn.commit()
    conn.close()
    
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم إضافة القناة الإعلانية <code>{ch}</code> بمكافأة <b>{pts}</b> نقطة.</blockquote>")

@app.on_message(filters.regex("^🎁 إنشاء رابط هدية$") & filters.user(OWNER_IDS))
async def create_gift_cmd(client: Client, message: Message):
    await message.reply("📝 أرسل عدد النقاط للهدية بالشكل التالي:\n<code>/make_gift 5</code>")

@app.on_message(filters.command("make_gift") & filters.user(OWNER_IDS))
async def make_gift_process(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ الاستخدام الصحيح: <code>/make_gift 5</code>")
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
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم إنشاء رابط الهدية بنجاح بقيمة <b>{pts}</b> نقطة:\n\n{link}</blockquote>")

@app.on_message(filters.regex("^➕ إرسال نقاط ID$") & filters.user(OWNER_IDS))
async def send_points_id_cmd(client: Client, message: Message):
    await message.reply("📝 لإرسال نقاط لشخص عبر الآيدي استخدم الأمر:\n<code>/send_pts USER_ID POINTS</code>")

@app.on_message(filters.command("send_pts") & filters.user(OWNER_IDS))
async def process_send_pts(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ صيغة غير صحيحة! استخدم:\n<code>/send_pts USER_ID POINTS</code>")
        return
    target_id = int(message.command[1])
    pts = float(message.command[2])
    add_user_points(target_id, pts)
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم إضافة <b>{pts}</b> نقطة للمستخدم <code>{target_id}</code> بنجاح.</blockquote>")

@app.on_message(filters.regex("^⚙️ إعدادات الاشتراك$") & filters.user(OWNER_IDS))
async def channel_settings(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM channels")
    rows = cursor.fetchall()
    conn.close()
    
    txt = f"<blockquote><tg-emoji emoji-id='{E['settings']}'>⚙️</tg-emoji> <b>قنوات الاشتراك الإجباري الحالية:</b></blockquote>\n\n"
    if rows:
        for (ch,) in rows:
            txt += f"• <code>{ch}</code>\n"
    else:
        txt += "لا توجد قنوات إجبارية مضافة حالياً.\n"
        
    txt += "\n➕ لإضافة قناة استخدم: <code>/add_channel @username</code>\n"
    txt += "🗑 لإزالة قناة استخدم: <code>/del_channel @username</code>"
    await message.reply(txt)

@app.on_message(filters.command("add_channel") & filters.user(OWNER_IDS))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى كتابة أيدي أو يوزر القناة!")
        return
    ch = message.command[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels (channel_id) VALUES (?)", (ch,))
    conn.commit()
    conn.close()
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم إضافة القناة <code>{ch}</code> للاشتراك الإجباري.</blockquote>")

@app.on_message(filters.command("del_channel") & filters.user(OWNER_IDS))
async def del_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى كتابة أيدي أو يوزر القناة!")
        return
    ch = message.command[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch,))
    conn.commit()
    conn.close()
    await message.reply(f"<blockquote>🗑 تم حذف القناة <code>{ch}</code> بنجاح.</blockquote>")

@app.on_message(filters.regex("^📢 إذاعة للأعضاء$") & filters.user(OWNER_IDS))
async def broadcast_ask(client: Client, message: Message):
    await message.reply("📝 قم بعمل Reply على الرسالة التي تريد إذاعتها واكتب <code>/bc</code>")

@app.on_message(filters.command("bc") & filters.user(OWNER_IDS))
async def start_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply("❌ يجب الرد على الرسالة المراد إذاعتها بـ <code>/bc</code>")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    await message.reply(f"<blockquote>🚀 جاري بدء الإذاعة لـ <b>{len(users)}</b> عضو وتحديث كشف الحظر...</blockquote>")
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
            
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> اكتملت الإذاعة!\n🟢 النجاح (النشطين): {success}\n🔴 الفشل (المحظورين): {failed}</blockquote>")

@app.on_message(filters.regex("^📈 عدد العمليات$") & filters.user(OWNER_IDS))
async def ops_count(client: Client, message: Message):
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['chart']}'>📊</tg-emoji> <b>إجمالي عمليات الاستخراج:</b> <b>{get_total_operations():,}</b></blockquote>")

@app.on_message(filters.regex("^🔥 الأكثر والأقل طلباً$") & filters.user(OWNER_IDS))
async def top_and_least_searched(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, search_count FROM search_stats ORDER BY search_count DESC LIMIT 10")
    top_searches = cursor.fetchall()
    
    cursor.execute("SELECT domain, search_count FROM search_stats ORDER BY search_count ASC LIMIT 10")
    least_searches = cursor.fetchall()
    conn.close()
    
    txt = f"<blockquote><tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji> <b>أكثر المواقع طلباً:</b></blockquote>\n"
    for d, c in top_searches:
        txt += f"• <code>{d}</code> → {c} مرة\n"
        
    txt += "\n<blockquote>❄️ <b>أقل المواقع طلباً:</b></blockquote>\n"
    for d, c in least_searches:
        txt += f"• <code>{d}</code> → {c} مرة\n"
        
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 حذف الكومبو للمواقع غير المطلوبة", callback_data="clean_unused_domains")]
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
    await callback.message.edit_text(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم حذف <b>{deleted_total:,}</b> كومبو للمواقع الضعيفة الطلب.</blockquote>")

@app.on_message(filters.regex("^✅ تفعيل البوت$") & filters.user(OWNER_IDS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = True
    await message.reply("<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم تفعيل البوت للأعضاء بنجاح.</blockquote>")

@app.on_message(filters.regex("^🚫 إغلاق البوت$") & filters.user(OWNER_IDS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = False
    await message.reply("<blockquote>🚫 تم إغلاق البوت عن الأعضاء.</blockquote>")

@app.on_message(filters.regex("^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def bot_status(client: Client, message: Message):
    status = "🟢 مفعل للأعضاء" if bot_enabled_for_users else "🔴 مغلق عن الأعضاء"
    await message.reply(f"<blockquote>حالة البوت حالياً:\n\n<b>{status}</b></blockquote>")

@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, top_domains, total_users, blocked_users, active_users = get_stats()
    text = f"""<blockquote><tg-emoji emoji-id='{E['chart']}'>📊</tg-emoji> <b>إحصائيات البوت الكاملة</b>

👥 <b>إحصائيات الأعضاء:</b>
• إجمالي المسجلين: <b>{total_users:,}</b>
• الأعضاء النشطين: <b>{active_users:,}</b>
• قامت بحظر البوت: <b>{blocked_users:,}</b>

📦 <b>إحصائيات الكومبو:</b>
• إجمالي الكومبوهات: <b>{total:,}</b>

🔥 <b>أكثر الدومينات توفراً:</b></blockquote>
"""
    if top_domains:
        for i, (domain, count) in enumerate(top_domains, 1):
            text += f"{i}. <code>{domain}</code> → {count:,}\n"
    else:
        text += "لا توجد بيانات كافية.\n"
    await message.reply(text)

@app.on_message(filters.regex("^💣 حذف كل البيانات$") & filters.user(OWNER_IDS))
async def confirm_delete_all(client: Client, message: Message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم احذف الكل", callback_data="confirm_delete_all"),
         InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete")]
    ])
    await message.reply("<blockquote>⚠️ هل أنت متأكد من حذف <b>كل</b> البيانات؟</blockquote>", reply_markup=buttons)

@app.on_callback_query(filters.regex("^confirm_delete_all$"))
async def delete_all_confirmed(client: Client, callback):
    if not is_owner(callback.from_user.id):
        return
    await callback.answer()
    delete_all_combos()
    await callback.message.edit_text("<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم حذف كل البيانات بنجاح.</blockquote>")

@app.on_callback_query(filters.regex("^cancel_delete$"))
async def cancel_delete(client: Client, callback):
    await callback.answer()
    await callback.message.edit_text("<blockquote>❌ تم إلغاء عملية الحذف.</blockquote>")

@app.on_message(filters.regex("^🗑 حذف حسب دومين$") & filters.user(OWNER_IDS))
async def ask_domain_delete(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_domain_delete"
    await message.reply("<blockquote>📝 أرسل اسم الدومين الذي تريد حذفه بالكامل:</blockquote>")

# ==================== رفع الملفات ====================
@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def ask_file(client: Client, message: Message):
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['sparkles']}'>📤</tg-emoji> أرسل ملفات الـ <b>ULP</b> الآن لمعالجتها وإضافتها للكومبو وحفظها...</blockquote>")

@app.on_message(filters.document & filters.user(OWNER_IDS))
async def handle_large_document(client: Client, message: Message):
    try:
        file_name = message.document.file_name or "unknown.txt"
        file_size = message.document.file_size or 0

        saved_file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex[:6]}_{file_name}")

        msg = await message.reply(f"<blockquote>⏳ جاري تحميل وحفظ الملف: <b>{file_name}</b> ({file_size / 1024 / 1024:.2f} MB)...</blockquote>")
        await message.download(file_name=saved_file_path)

        await msg.edit_text("<blockquote>⏳ جاري معالجة الترميز وإضافة الكومبوهات إلى قاعدة البيانات...</blockquote>")
        added = add_combos_from_file(saved_file_path)

        await msg.edit_text(
            f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> <b>تم رفع ومعالجة الملف بنجاح!</b>\n\n"
            f"📁 اسم الملف: <b>{file_name}</b>\n"
            f"➕ عدد الكومبو المضاف: <b>{added:,}</b>\n"
            f"💾 تم حفظ النسخة في المسار:\n<code>{saved_file_path}</code></blockquote>"
        )

    except Exception as e:
        await message.reply(f"❌ حصل خطأ أثناء رفع الملف:\n<code>{str(e)}</code>")

# ==================== نظام الاستخراج والبحث ====================
@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        if not bot_enabled_for_users:
            await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
            return
        if not await check_subscription(client, user_id):
            await message.reply("⚠️ يجب عليك الاشتراك في القنوات المحددة أولاً للاستخدام.")
            return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply(f"<blockquote><tg-emoji emoji-id='{E['pencil']}'>✍️</tg-emoji> <b>أرسل اسم الموقع أو اللعبة الذي تريد البحث عنه الآن:</b></blockquote>")

@app.on_message(filters.text & ~filters.command(["start", "bc", "add_ad", "make_gift", "send_pts", "add_channel", "del_channel", "set_ref_points"]))
async def process_domain_input(client: Client, message: Message):
    user_id = message.from_user.id
    
    if message.text in [
        "🔍 بحث عن دومين", "📤 رفع ملف ULP", "📊 الإحصائيات", "🗑 حذف حسب دومين",
        "✅ تفعيل البوت", "🚫 إغلاق البوت", "📢 إذاعة للأعضاء", "⚙️ إعدادات الاشتراك",
        "📈 عدد العمليات", "🔥 الأكثر والأقل طلباً", "🎁 إنشاء رابط هدية", "➕ إرسال نقاط ID",
        "⚙️ نقاط الإحالة", "📢 إضافة إعلان قناة", "💣 حذف كل البيانات", "📈 حالة البوت",
        "💰 رصيدي ونقاطي", "🔗 رابط الإحالة", "📺 قنوات الإعلانات", "📁 حفظ ملف الأعضاء"
    ]:
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
            await message.reply(f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم حذف <b>{deleted:,}</b> كومبو متعلق بـ <b>{domain}</b></blockquote>")
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
            await message.reply("⚠️ يجب عليك الاشتراك في القنوات الإجبارية لاستخدام البوت.")
            return

    available_count = await asyncio.to_thread(count_available_combos, domain)

    if available_count <= 0:
        await message.reply(f"<blockquote>❌ للأسف، لا توجد أية حسابات متوفرة حالياً لموقع <b>{domain}</b>.</blockquote>")
        for owner in OWNER_IDS:
            try:
                await client.send_message(owner, f"⚠️ <b>إشعار طلب:</b> تم البحث عن <code>{domain}</code> وهو غير متوفر!")
            except Exception:
                pass
        return

    pts = get_user_points(user_id)

    buttons_list = []
    max_k = available_count // 1000

    row = []
    for k in range(1, min(max_k + 1, 11)):
        amount = k * 1000
        price = 0.0 if is_owner_user else float(k)
        btn = InlineKeyboardButton(
            f"📥 {k}K ({price} ن)", 
            callback_data=f"buy_{amount}_{price}_{domain}"
        )
        row.append(btn)
        if len(row) == 2:
            buttons_list.append(row)
            row = []
            
    if row:
        buttons_list.append(row)

    total_price = 0.0 if is_owner_user else float(math.ceil(available_count / 1000))
    buttons_list.append([
        InlineKeyboardButton(
            f"🚀 سحب الكل ({available_count:,} حساب) بـ {total_price} نقطة", 
            callback_data=f"buy_{available_count}_{total_price}_{domain}"
        )
    ])
    
    buttons_list.append([
        InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_pull")
    ])

    await message.reply(
        f"<blockquote>🎯 <b>الموقع المطلوب:</b> <code>{domain}</code>\n"
        f"📊 <b>الحسابات المتوفرة:</b> <b>{available_count:,}</b> حساب\n"
        f"💳 <b>رصيدك الحالي:</b> <b>{pts}</b> نقطة\n\n"
        "<b>اختر الكمية التي تريد سحبها من الأزرار أدناه:</b></blockquote>",
        reply_markup=InlineKeyboardMarkup(buttons_list)
    )

@app.on_callback_query(filters.regex(r"^buy_(\d+)_(.+)_(.+)"))
async def handle_buy_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_owner_user = is_owner(user_id)

    match = callback.data.split("_", 3)
    amount_to_pull = int(match[1])
    required_points = float(match[2])
    domain = match[3]

    pts = get_user_points(user_id)

    if not is_owner_user and pts < required_points:
        await callback.answer(f"❌ رصيدك غير كافٍ! تحتاج {required_points} نقطة.", show_alert=True)
        return

    await callback.answer("⏳ جاري بدء الاستخراج والمعالجة...")
    status_msg = await callback.message.edit_text(
        f"<blockquote>⚡ جاري استخراج <b>{amount_to_pull:,}</b> كومبو لموقع <b>{domain}</b>...</blockquote>"
    )

    try:
        log_search_domain(domain)
    except Exception:
        pass

    filename = None
    try:
        results = await fetch_and_delete_combos(domain, amount_to_pull)

        if not results:
            await status_msg.edit_text(f"<blockquote>❌ حدث خطأ أو تم سحب البيانات من قبل مستخدم آخر لموقع <b>{domain}</b>.</blockquote>")
            return

        fetched_count = len(results)

        filename = f"results_{domain}_{user_id}_{uuid.uuid4().hex[:8]}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(results))

        caption = (
            f"<blockquote><tg-emoji emoji-id='{E['check']}'>✅</tg-emoji> تم استخراج <b>{fetched_count:,}</b> كومبو لـ <b>{domain}</b>\n"
            f"💳 الخصم: <b>{required_points}</b> نقطة</blockquote>"
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
        await client.send_message(user_id, f"⏳ انتظر {e.value} ثانية بسبب FloodWait ثم حاول مرة أخرى.")
    except Exception as e:
        await client.send_message(user_id, f"❌ حدث خطأ أثناء الاستخراج:\n<code>{str(e)[:300]}</code>")
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
    await callback.message.edit_text("<blockquote>❌ تم إلغاء العملية.</blockquote>")

# ==================== التشغيل ====================
print("⚡ Bot is starting...")
app.run()

