import os
import io
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
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, ChatAdminRequired, UserNotParticipant, ChannelPrivate

# ==================== الإعدادات ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "combos.db")

bot_enabled_for_users = True
ulp_feature_enabled = False  # الفرز طافي افتراضياً ولا يعمل إلا بعد إرسال /on

user_action_state = {}
user_filter_keywords = {}

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
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("total_operations", "0")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("referral_points", "1.0")')
    cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES ("log_channel", "")')
    
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
    conn.execute('PRAGMA synchronous = OFF;')
    return conn

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

# ==================== النقاط والإعدادات ====================
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

def get_log_channel() -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'log_channel'")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def set_log_channel(channel_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET value = ? WHERE key = 'log_channel'", (channel_id,))
    conn.commit()
    conn.close()

def log_search_domain(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO search_stats (domain, search_count) VALUES (?, 1) ON CONFLICT(domain) DO UPDATE SET search_count = search_count + 1", (domain.lower(),))
    conn.commit()
    conn.close()

async def send_audit_log(client: Client, user, domain: str, amount: int, points: float):
    log_ch = get_log_channel()
    if not log_ch:
        return
    try:
        user_id = user.id
        first_name = user.first_name or "مستخدم"
        username = f"@{user.username}" if user.username else "بدون يوزر"
        
        log_text = (
            f"📥 **عملية سحب جديدة (Audit Log)**\n\n"
            f"👤 **المستخدم:** {first_name}\n"
            f"🆔 **الآيدي:** <code>{user_id}</code>\n"
            f"🌐 **اليوزر:** {username}\n"
            f"🎯 **الدومين المطلوب:** <code>{domain}</code>\n"
            f"📊 **العدد المستخرج:** <b>{amount:,}</b> حساب\n"
            f"💳 **النقاط المستهلكة:** <b>{points}</b> نقطة"
        )
        chat_id = int(log_ch) if (log_ch.startswith("-") or log_ch.isdigit()) else log_ch
        await client.send_message(chat_id, log_text)
    except Exception as e:
        print(f"[AUDIT LOG ERROR] {e}")

# ==================== نظام الاشتراك الإجباري المحدث ====================
def get_forced_channels():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, title, invite_link FROM channels")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1] or "قناة", "link": r[2]} for r in rows]

async def is_user_in_channel(client: Client, user_id: int, channel_id: str) -> bool:
    try:
        chat_id = int(channel_id) if (channel_id.startswith("-") or channel_id.isdigit()) else channel_id
        member = await client.get_chat_member(chat_id, user_id)
        status = member.status
        
        # الحالات الصحيحة التي تعتبر العضو مشتركاً
        valid_statuses = {"creator", "administrator", "member"}
        if status in valid_statuses:
            return True
        elif status == "restricted":
            return getattr(member, "is_member", False)
        return False
    except (UserNotParticipant, ChannelPrivate, ChatAdminRequired):
        return False
    except Exception as e:
        print(f"[SUB CHECK ERROR] channel={channel_id} user={user_id} → {e}")
        return False

async def check_subscription(client: Client, user_id: int) -> tuple:
    if is_owner(user_id):
        return True, []
    
    channels = get_forced_channels()
    if not channels:
        return True, []
    
    missing = []
    for ch in channels:
        if not await is_user_in_channel(client, user_id, ch["id"]):
            missing.append(ch)
    
    return len(missing) == 0, missing

def build_subscription_keyboard(missing_channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in missing_channels:
        link = ch.get("link")
        if not link:
            if ch["id"].startswith("@"):
                link = f"https://t.me/{ch['id'][1:]}"
            elif ch["id"].startswith("-100"):
                link = f"https://t.me/c/{ch['id'][4:]}"
            else:
                link = f"https://t.me/{ch['id']}"
        
        buttons.append([
            InlineKeyboardButton(text=f"📢 {ch['title']}", url=link)
        ])
    
    buttons.append([
        InlineKeyboardButton(text="✅ تحقق من الاشتراك", callback_data="check_force_sub")
    ])
    return InlineKeyboardMarkup(buttons)

async def send_force_sub_message(client: Client, chat_id: int, missing: list, edit_message: Message = None):
    text = (
        "⛔️ <b>يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:</b>\n\n"
        "اشترك بالقنوات ثم اضغط على زر «✅ تحقق من الاشتراك»"
    )
    kb = build_subscription_keyboard(missing)
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await client.send_message(chat_id, text, reply_markup=kb)

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

# ==================== الكومبو معالجة ودقة كاملة ====================
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
            
            # جلب عدد كافٍ مع الأخذ بعين الاعتبار التكرار والتنظيف لضمان اكتمال العدد المطلوب بالتمام والكمال
            fetch_limit = int(limit_count * 1.5) + 100
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
                cleaned = extract_email_pass(r[1])
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    results.append(cleaned)
                    ids_to_delete.append(r[0])
            
            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                cursor.execute(f"DELETE FROM combos WHERE id IN ({placeholders})", ids_to_delete)
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

# ==================== الكيبوردات (مع إخفاء زر ULP عن الأعضاء) ====================
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
        [KeyboardButton("💣 حذف كل البيانات"), KeyboardButton("📈 حالة البوت")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين")],
        [KeyboardButton("💰 رصيدي ونقاطي"), KeyboardButton("🔗 رابط الإحالة")],
        [KeyboardButton("📺 قنوات الإعلانات")]
    ], resize_keyboard=True)

# ==================== /start ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "عضو"
    username = f"@{message.from_user.username}" if message.from_user.username else "بدون يوزر"
    
    args = message.command
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    is_existing_user = cursor.fetchone() is not None
    
    if not is_existing_user:
        cursor.execute("INSERT INTO users (user_id, points, is_blocked) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
        
        notify_text = (
            f"👤 **عضو جديد دخل البوت!**\n\n"
            f"• الاسم: **{first_name}**\n"
            f"• اليوزر: {username}\n"
            f"• الآيدي: <code>{user_id}</code>"
        )
        for owner in OWNER_IDS:
            try: await client.send_message(owner, notify_text)
            except Exception: pass
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
                    await client.send_message(referrer_id, f"🎉 انضم عضو جديد عبر رابطك! حصلت على **{ref_pts}** نقطة.")
                except Exception: pass

    conn.close()

    if is_owner(user_id):
        text = f"""اهلا بك في <b>بوت الكومبو والخدمات السريعة</b>

نقاطك الحالية: <b>{get_user_points(user_id)}</b>

قناتي: https://t.me/+91X31VNWIU1iNDM8
يوزري: @D3_1D"""
        await message.reply(text, reply_markup=owner_keyboard())
        return

    if not bot_enabled_for_users:
        await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
        return

    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return

    text = f"""اهلا بك في <b>بوت الكومبو والخدمات السريعة</b>

نقاطك الحالية: <b>{get_user_points(user_id)}</b>

قناتي: https://t.me/+91X31VNWIU1iNDM8
يوزري: @D3_1D"""
    await message.reply(text, reply_markup=user_keyboard())

# ==================== زر التحقق من الاشتراك ====================
@app.on_callback_query(filters.regex("^check_force_sub$"))
async def check_force_sub_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_ok, missing = await check_subscription(client, user_id)
    
    if is_ok:
        await callback.answer("✅ تم التحقق بنجاح! أهلاً بك", show_alert=False)
        text = f"""اهلا بك في <b>بوت الكومبو والخدمات السريعة</b>

نقاطك الحالية: <b>{get_user_points(user_id)}</b>

قناتي: https://t.me/+91X31VNWIU1iNDM8
يوزري: @D3_1D"""
        try:
            await callback.message.edit_text(text)
        except Exception:
            await callback.message.reply(text, reply_markup=user_keyboard())
        
        await client.send_message(user_id, "🏠 القائمة الرئيسية جاهزة:", reply_markup=user_keyboard() if not is_owner(user_id) else owner_keyboard())
    else:
        await callback.answer("❌ لم تشترك في كل القنوات بعد!\nتأكد من الاشتراك ثم اضغط مرة أخرى.", show_alert=True)
        await send_force_sub_message(client, user_id, missing, edit_message=callback.message)

# ==================== حماية الأوامر ====================
async def force_sub_guard(client: Client, message: Message) -> bool:
    user_id = message.from_user.id
    if is_owner(user_id):
        return True
    
    if not bot_enabled_for_users:
        await message.reply("⚠️ البوت حالياً مغلق عن الأعضاء.")
        return False
    
    is_ok, missing = await check_subscription(client, user_id)
    if not is_ok:
        await send_force_sub_message(client, user_id, missing)
        return False
    
    return True

# ==================== تحكم المالك بفرز ULP (/stop و /on) ====================
@app.on_message(filters.command("stop") & filters.user(OWNER_IDS))
async def stop_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = False
    await message.reply("🛑 تم إيقاف قسم فرز ملفات ULP بنجاح. لن يستجيب لأي طلبات فرز حالياً.")

@app.on_message(filters.command("on") & filters.user(OWNER_IDS))
async def on_ulp_feature(client: Client, message: Message):
    global ulp_feature_enabled
    ulp_feature_enabled = True
    await message.reply("✅ تم تفعيل قسم فرز ملفات ULP بنجاح وعاد للعمل.")

# ==================== قسم فرز ملفات ULP (للمالك فقط) ====================
@app.on_message(filters.regex("^📂 فرز ملفات ULP$") & filters.user(OWNER_IDS))
async def start_ulp_filter(client: Client, message: Message):
    global ulp_feature_enabled
    if not ulp_feature_enabled:
        await message.reply("⚠️ قسم فرز ملفات ULP متوقف حالياً من قبل المالك.")
        return

    user_id = message.from_user.id
    user_action_state[user_id] = "awaiting_filter_keywords"
    
    cancel_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_ulp_filter")]
    ])
    
    await message.reply(
        "🎯 **قسم فرز ملفات ULP المستهدفة**\n\n"
        "أرسل الكلمات المفتاحية أو اسم الدومين/الخدمة التي تريد استخراجها من الملف.\n"
        "يمكنك إرسال كلمة واحدة أو عدة كلمات تفصل بينها بفارزة `,` (مثال: `ludo, bandainamcoid.com`):",
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
    
    # حالة رفع ملفات للكومبو (للمالك)
    if is_owner(user_id) and user_action_state.get(user_id) == "awaiting_ulp_upload":
        await handle_large_document(client, message)
        return

    # للفرز: مخصص للمالك فقط
    if not is_owner(user_id):
        return

    global ulp_feature_enabled
    if not ulp_feature_enabled:
        return

    keywords = user_filter_keywords.get(user_id)
    if not keywords:
        await message.reply(
            "⚠️ **يرجى تحديد الكلمات المراد فرزها أولاً!**\n"
            "اضغط على زر **`📂 فرز ملفات ULP`** وحدد الخدمات أولاً ثم أرسل الملف."
        )
        return

    saved_ulp_path = None
    output_filename = None

    try:
        file_name = message.document.file_name or "data.ulp"
        msg = await message.reply(f"⏳ جاري تنزيل ملف الـ ULP: <b>{file_name}</b>...")

        saved_ulp_path = await client.download_media(message)
        await msg.edit_text("🔍 تم تنزيل الملف.. جاري قراءة البيانات والتصفية بسرعة...")

        filtered_lines = []
        seen = set()

        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']
        for enc in encodings:
            try:
                with open(saved_ulp_path, 'r', encoding=enc, errors='ignore') as f:
                    for line in f:
                        line_str = line.strip()
                        line_lower = line_str.lower()
                        if line_str and any(key in line_lower for key in keywords):
                            cleaned = extract_email_pass(line_str)
                            if cleaned not in seen:
                                seen.add(cleaned)
                                filtered_lines.append(cleaned)
                break
            except Exception:
                continue

        if not filtered_lines:
            await msg.edit_text("❌ لم يتم العثور على أية نتائج تطابق الكلمات والمواقع المفتاحية المحددة في هذا الملف!")
        else:
            await msg.edit_text("📤 جاري تجهيز وإرسال ملف النتائج المفروز...")
            
            output_filename = f"Filtered_{os.path.splitext(file_name)[0]}.txt"
            with open(output_filename, "w", encoding="utf-8") as out_f:
                out_f.write("\n".join(filtered_lines))

            kw_text = ", ".join([f"`{k}`" for k in keywords])
            
            await client.send_document(
                chat_id=message.chat.id,
                document=output_filename,
                caption=(
                    f"✅ **تم اكتمال عملية الفرز بنجاح!**\n\n"
                    f"📄 الملف الأصلي: <code>{file_name}</code>\n"
                    f"🎯 عدد الأسطر المفروزة: <b>{len(filtered_lines):,}</b>\n"
                    f"🔍 الخدمات المحددة: {kw_text}"
                )
            )
            await msg.delete()

    except Exception as e:
        await message.reply(f"❌ حدث خطأ أثناء عملية الفرز:\n<code>{str(e)}</code>")

    finally:
        if saved_ulp_path and os.path.exists(saved_ulp_path):
            try: os.remove(saved_ulp_path)
            except Exception: pass

        if output_filename and os.path.exists(output_filename):
            try: os.remove(output_filename)
            except Exception: pass

        user_filter_keywords.pop(user_id, None)
        user_action_state.pop(user_id, None)

# ==================== أوامر الأعضاء والمالك ====================
@app.on_message(filters.regex("^💰 رصيدي ونقاطي$"))
async def check_balance(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    pts = get_user_points(message.from_user.id)
    await message.reply(f"💎 رصيدك الحالي هو: <b>{pts}</b> نقطة.")

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    if not await force_sub_guard(client, message):
        return
    bot_username = (await client.get_me()).username
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start={user_id}"
    ref_pts = get_referral_points()
    await message.reply(
        f"🔗 <b>رابط الإحالة الخاص بك:</b>\n<code>{link}</code>\n\n"
        f"شاركه مع أصدقائك للحصول على **{ref_pts} نقطة** عند انضمام أي عضو جديد عبر رابطك!"
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
        await message.reply("📺 لا توجد قنوات إعلانية متاحة حالياً لكسب النقاط.")
        return
        
    txt = "📺 <b>اشترك في القنوات التالية للحصول على نقاط:</b>\n\n"
    btns = []
    for ch, pts in ads:
        ch_link = f"https://t.me/{ch.replace('@', '')}" if ch.startswith("@") else ch
        txt += f"• القناة: {ch} (المكافأة: **{pts}** نقطة)\n"
        btns.append([InlineKeyboardButton(f"الانضمام إلى {ch} (+{pts} نقطة)", url=ch_link)])
        
    await message.reply(txt, reply_markup=InlineKeyboardMarkup(btns))

# ==================== إعدادات قناة السجل (Audit Log) ====================
@app.on_message(filters.regex("^🧾 قناة السجل \(Audit Log\)$") & filters.user(OWNER_IDS))
async def audit_log_settings(client: Client, message: Message):
    curr_log = get_log_channel()
    log_info = f"<code>{curr_log}</code>" if curr_log else "غير محددة"
    await message.reply(
        f"🧾 **قناة السجل الحالية (Audit Log):** {log_info}\n\n"
        "لتحديد أو تغيير قناة إشعارات السجل أرسل الأمر:\n"
        "`/set_log_channel -100xxxxxxxxxx`"
    )

@app.on_message(filters.command("set_log_channel") & filters.user(OWNER_IDS))
async def set_log_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى كتابة ID القناة! مثال:\n`/set_log_channel -1001234567890`")
        return
    ch_id = message.command[1].strip()
    set_log_channel(ch_id)
    await message.reply(f"✅ تم ضبط قناة السجل إلى: <code>{ch_id}</code> بنجاح.")

# ==================== أوامر الإدارة ====================
@app.on_message(filters.regex("^⚙️ نقاط الإحالة$") & filters.user(OWNER_IDS))
async def ref_pts_settings(client: Client, message: Message):
    current_pts = get_referral_points()
    await message.reply(
        f"⚙️ **نقاط الإحالة الحالية:** <b>{current_pts}</b> نقطة لكتابة إحالة جديدة.\n\n"
        "لتغيير القيمة أرسل الأمر التالي:\n"
        "`/set_ref_points 2`"
    )

@app.on_message(filters.command("set_ref_points") & filters.user(OWNER_IDS))
async def set_ref_pts_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى إدخال القيمة الجديدة! مثال:\n`/set_ref_points 1.5`")
        return
    try:
        pts = float(message.command[1])
        set_referral_points(pts)
        await message.reply(f"✅ تم تغيير قيمة مكافأة الإحالة إلى <b>{pts}</b> نقطة بنجاح!")
    except ValueError:
        await message.reply("❌ يرجى إدخال رقم صحيح أو عشري.")

@app.on_message(filters.regex("^📢 إضافة إعلان قناة$") & filters.user(OWNER_IDS))
async def add_ad_info(client: Client, message: Message):
    await message.reply("📝 لإضافة قناة إعلانية مع نقاط مكافأة، استخدم الأمر:\n`/add_ad @channel 2`")

@app.on_message(filters.command("add_ad") & filters.user(OWNER_IDS))
async def add_ad_cmd(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ الصيغة خاطئة! استخدم:\n`/add_ad @channel_username POINTS`")
        return
    ch = message.command[1]
    pts = float(message.command[2])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO ad_channels (channel_id, points_reward) VALUES (?, ?)", (ch, pts))
    conn.commit()
    conn.close()
    
    await message.reply(f"✅ تم إضافة القناة الإعلانية <code>{ch}</code> بمكافأة <b>{pts}</b> نقطة.")

@app.on_message(filters.regex("^🎁 إنشاء رابط هدية$") & filters.user(OWNER_IDS))
async def create_gift_cmd(client: Client, message: Message):
    await message.reply("📝 أرسل عدد النقاط للهدية بالشكل التالي:\n`/make_gift 5`")

@app.on_message(filters.command("make_gift") & filters.user(OWNER_IDS))
async def make_gift_process(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ الاستخدام الصحيح: `/make_gift 5`")
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
    await message.reply(f"✅ تم إنشاء رابط الهدية بنجاح بقيمة <b>{pts}</b> نقطة:\n\n{link}")

@app.on_message(filters.regex("^➕ إرسال نقاط ID$") & filters.user(OWNER_IDS))
async def send_points_id_cmd(client: Client, message: Message):
    await message.reply("📝 لإرسال نقاط لشخص عبر الآيدي استخدم الأمر:\n`/send_pts USER_ID POINTS`")

@app.on_message(filters.command("send_pts") & filters.user(OWNER_IDS))
async def process_send_pts(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply("❌ صيغة غير صحيحة! استخدم:\n`/send_pts USER_ID POINTS`")
        return
    target_id = int(message.command[1])
    pts = float(message.command[2])
    add_user_points(target_id, pts)
    await message.reply(f"✅ تم إضافة <b>{pts}</b> نقطة للمستخدم <code>{target_id}</code> بنجاح.")

# ==================== إعدادات الاشتراك ====================
@app.on_message(filters.regex("^⚙️ إعدادات الاشتراك$") & filters.user(OWNER_IDS))
async def channel_settings(client: Client, message: Message):
    channels = get_forced_channels()
    txt = "📢 <b>قنوات الاشتراك الإجباري الحالية:</b>\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            link_info = f"\n   🔗 {ch['link']}" if ch.get('link') else ""
            txt += f"{i}. <b>{ch['title']}</b>\n   ID: <code>{ch['id']}</code>{link_info}\n\n"
    else:
        txt += "لا توجد قنوات إجبارية مضافة حالياً.\n\n"
        
    txt += (
        "➕ <b>لإضافة قناة:</b>\n"
        "`/add_channel -1001234567890 عنوان القناة https://t.me/+xxxx`\n\n"
        "أو للعامه:\n"
        "`/add_channel @username عنوان القناة`\n\n"
        "🗑 <b>لحذف قناة:</b>\n"
        "`/del_channel -1001234567890`\n"
        "أو\n"
        "`/del_channel @username`"
    )
    await message.reply(txt)

@app.on_message(filters.command("add_channel") & filters.user(OWNER_IDS))
async def add_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى إدخال البيانات الصحيحة للقناة!")
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
    
    ch_id = ch_id.strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)", (ch_id, title, invite_link))
    conn.commit()
    conn.close()
    
    await message.reply(f"✅ تم إضافة القناة بنجاح!\n\n• العنوان: <b>{title}</b>\n• ID: <code>{ch_id}</code>")

@app.on_message(filters.command("del_channel") & filters.user(OWNER_IDS))
async def del_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("❌ يرجى كتابة أيدي أو يوزر القناة!")
        return
    ch = message.command[1].strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (ch,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted:
        await message.reply(f"🗑 تم حذف القناة <code>{ch}</code> بنجاح.")
    else:
        await message.reply(f"⚠️ لم يتم العثور على القناة <code>{ch}</code>.")

@app.on_message(filters.regex("^📢 إذاعة للأعضاء$") & filters.user(OWNER_IDS))
async def broadcast_ask(client: Client, message: Message):
    await message.reply("📝 قم بعمل Reply على الرسالة التي تريد إذاعتها واكتب `/bc`")

@app.on_message(filters.command("bc") & filters.user(OWNER_IDS))
async def start_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply("❌ يجب الرد على الرسالة المراد إذاعتها بـ `/bc`")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    await message.reply(f"🚀 جاري بدء الإذاعة لـ <b>{len(users)}</b> عضو وتحديث كشف الحظر...")
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
            
    await message.reply(f"✅ اكتملت الإذاعة!\n🟢 النجاح (النشطين): {success}\n🔴 الفشل (المحظورين): {failed}")

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
    for d, c in top_searches: txt += f"• <code>{d}</code> → {c} مرة\n"
    txt += "\n❄️ <b>أقل المواقع طلباً:</b>\n"
    for d, c in least_searches: txt += f"• <code>{d}</code> → {c} مرة\n"
        
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 حذف الكومبو للمواقع غير المطلوبة", callback_data="clean_unused_domains")]])
    await message.reply(txt, reply_markup=buttons)

@app.on_callback_query(filters.regex("^clean_unused_domains$"))
async def clean_unused(client: Client, callback: CallbackQuery):
    if not is_owner(callback.from_user.id): return
    await callback.answer()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain FROM search_stats WHERE search_count <= 1")
    rows = cursor.fetchall()
    deleted_total = sum(delete_by_domain(dom) for (dom,) in rows)
    conn.close()
    await callback.message.edit_text(f"✅ تم حذف <b>{deleted_total:,}</b> كومبو للمواقع الضعيفة الطلب.")

@app.on_message(filters.regex("^✅ تفعيل البوت$") & filters.user(OWNER_IDS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = True
    await message.reply("✅ تم تفعيل البوت للأعضاء بنجاح.")

@app.on_message(filters.regex("^🚫 إغلاق البوت$") & filters.user(OWNER_IDS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = False
    await message.reply("🚫 تم إغلاق البوت عن الأعضاء.")

@app.on_message(filters.regex("^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def bot_status(client: Client, message: Message):
    status = "🟢 مفعل للأعضاء" if bot_enabled_for_users else "🔴 مغلق عن الأعضاء"
    ulp_st = "🟢 مفعل" if ulp_feature_enabled else "🔴 متوقف"
    await message.reply(f"حالة البوت حالياً:\n\n• البوت العام: {status}\n• فرز ملفات ULP: {ulp_st}")

@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, top_domains, total_users, blocked_users, active_users = get_stats()
    text = f"""📊 <b>إحصائيات البوت الكاملة</b>

👥 <b>إحصائيات الأعضاء:</b>
• إجمالي المسجلين: <b>{total_users:,}</b>
• الأعضاء النشطين: <b>{active_users:,}</b>
• قامت بحظر البوت: <b>{blocked_users:,}</b>

📦 <b>إحصائيات الكومبو:</b>
• إجمالي الكومبوهات: <b>{total:,}</b>

🔥 <b>أكثر الدومينات توفراً:</b>
"""
    if top_domains:
        for i, (domain, count) in enumerate(top_domains, 1): text += f"{i}. <code>{domain}</code> → {count:,}\n"
    else: text += "لا توجد بيانات كافية.\n"
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
    if not is_owner(callback.from_user.id): return
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

# ==================== رفع ملفات ULP من المالك ====================
@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def ask_file(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ulp_upload"
    await message.reply(
        "📤 **وضع رفع ملفات الكومبو مفعّل الآن!**\n\n"
        "أرسل ملفاً واحداً أو مجموعة ملفات دفعة واحدة وسيقوم البوت بمعالجتها وإضافتها لقاعدة البيانات بالتوالي."
    )

async def handle_large_document(client: Client, message: Message):
    user_id = message.from_user.id
    try:
        file_name = message.document.file_name or "unknown.txt"
        file_size = message.document.file_size or 0
        msg = await message.reply(f"⏳ جاري تحميل الملف: <b>{file_name}</b> ({file_size / 1024 / 1024:.2f} MB)...")
        
        safe_name = re.sub(r'[^\w\-_\.]', '_', file_name)
        temp_path = await message.download(file_name=f"temp_{message.id}_{safe_name}")

        await msg.edit_text("⏳ جاري معالجة الترميز وإضافة الكومبوهات إلى قاعدة البيانات...")
        added = await asyncio.to_thread(add_combos_from_file, temp_path)
        
        try: os.remove(temp_path)
        except Exception: pass

        await msg.edit_text(f"✅ تم رفع الملف بنجاح!\n\nالملف: <b>{file_name}</b>\nتمت إضافة: <b>{added:,}</b> كومبو")
    except Exception as e:
        await message.reply(f"❌ حصل خطأ أثناء رفع الملف:\n<code>{str(e)}</code>")

# ==================== البحث والمعالجة النصية ====================
@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        if not await force_sub_guard(client, message):
            return
    user_action_state[user_id] = "awaiting_search_domain"
    await message.reply("📝 أرسل اسم الموقع أو اللعبة الذي تريد البحث عنه الآن:")

@app.on_message(filters.text & ~filters.regex(r"^(🔍|📤|📊|🗑|✅|🚫|💣|📈|📢|⚙️|🔥|🎁|➕|💰|🔗|📺|📂|🧾)"))
async def process_text_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    text_input = message.text.strip()

    if user_action_state.get(user_id) == "awaiting_filter_keywords":
        global ulp_feature_enabled
        if not ulp_feature_enabled:
            user_action_state.pop(user_id, None)
            await message.reply("⚠️ قسم فرز ملفات ULP متوقف حالياً.")
            return

        user_action_state.pop(user_id, None)
        raw_keys = [k.strip().lower() for k in re.split(r'[,||\n]', text_input) if k.strip()]
        if not raw_keys:
            await message.reply("❌ لم تقم بإدخال كلمات صحيحة! جرب مجدداً الضغط على زر فرز ملفات ULP.")
            return
        
        user_filter_keywords[user_id] = raw_keys
        kw_formatted = ", ".join([f"<code>{k}</code>" for k in raw_keys])
        
        cancel_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_ulp_filter")]
        ])
        
        await message.reply(
            f"✅ **تم اعتماد الكلمات المستهدفة بنجاح:**\n{kw_formatted}\n\n"
            f"📥 **أرسل ملف ULP الآن** وسيتم فرزه حالياً وتسليمك النتائج ثم حذفه تلقائياً.",
            reply_markup=cancel_kb
        )
        return

    if user_action_state.get(user_id) == "awaiting_domain_delete" and is_owner(user_id):
        user_action_state.pop(user_id, None)
        try:
            deleted = await asyncio.to_thread(delete_by_domain, text_input.lower())
            await message.reply(f"✅ تم حذف <b>{deleted:,}</b> كومبو متعلق بـ <b>{text_input}</b>")
        except Exception as e:
            await message.reply(f"❌ فشل الحذف: <code>{e}</code>")
        return

    user_action_state.pop(user_id, None)

    domain = text_input.lower()
    if len(domain) < 2:
        return

    is_owner_user = is_owner(user_id)
    if not is_owner_user:
        if not await force_sub_guard(client, message):
            return

    available_count = await asyncio.to_thread(count_available_combos, domain)

    if available_count <= 0:
        await message.reply(f"❌ للأسف، لا توجد أية حسابات متوفرة حالياً لموقع <b>{domain}</b>.")
        for owner in OWNER_IDS:
            try: await client.send_message(owner, f"⚠️ **إشعار طلب:** تم البحث عن <code>{domain}</code> وهو غير متوفر!")
            except Exception: pass
        return

    pts = get_user_points(user_id)
    buttons_list = []
    max_k = available_count // 1000

    row = []
    for k in range(1, min(max_k + 1, 11)):
        amount = k * 1000
        price = 0.0 if is_owner_user else float(k)
        btn = InlineKeyboardButton(f"📥 {k}K ({price} ن)", callback_data=f"buy_{amount}_{price}_{domain}")
        row.append(btn)
        if len(row) == 2:
            buttons_list.append(row)
            row = []
            
    if row: buttons_list.append(row)

    total_price = 0.0 if is_owner_user else float(math.ceil(available_count / 1000))
    buttons_list.append([
        InlineKeyboardButton(f"🚀 سحب الكل ({available_count:,} حساب) بـ {total_price} نقطة", callback_data=f"buy_{available_count}_{total_price}_{domain}")
    ])
    buttons_list.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_pull")])

    await message.reply(
        f"🎯 **الموقع المطلوب:** <code>{domain}</code>\n"
        f"📊 **الحسابات المتوفرة:** <b>{available_count:,}</b> حساب\n"
        f"💳 **رصيدك الحالي:** <b>{pts}</b> نقطة\n\n"
        "اختر الكمية التي تريد سحبها من الأزرار أدناه:",
        reply_markup=InlineKeyboardMarkup(buttons_list)
    )

@app.on_callback_query(filters.regex(r"^buy_(\d+)_(.+)_(.+)"))
async def handle_buy_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    is_owner_user = is_owner(user_id)

    if not is_owner_user:
        is_ok, missing = await check_subscription(client, user_id)
        if not is_ok:
            await callback.answer("❌ يجب الاشتراك في القنوات أولاً!", show_alert=True)
            await send_force_sub_message(client, user_id, missing)
            return

    match = callback.data.split("_", 3)
    amount_to_pull = int(match[1])
    required_points = float(match[2])
    domain = match[3]

    pts = get_user_points(user_id)
    if not is_owner_user and pts < required_points:
        await callback.answer(f"❌ رصيدك غير كافٍ! تحتاج {required_points} نقطة.", show_alert=True)
        return

    await callback.answer("⏳ جاري بدء الاستخراج والمعالجة...")
    status_msg = await callback.message.edit_text(f"⚡ جاري استخراج <b>{amount_to_pull:,}</b> كومبو لموقع <b>{domain}</b>...")

    try: log_search_domain(domain)
    except Exception: pass

    filename = None
    try:
        results = await fetch_and_delete_combos(domain, amount_to_pull)

        if not results:
            await status_msg.edit_text(f"❌ حدث خطأ أو تم سحب البيانات من قبل مستخدم آخر لموقع <b>{domain}</b>.")
            return

        fetched_count = len(results)

        filename = f"results_{domain}_{user_id}_{uuid.uuid4().hex[:8]}.txt"
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

        await send_audit_log(client, callback.from_user, domain, fetched_count, required_points)

        try: await status_msg.delete()
        except Exception: pass

    except FloodWait as e:
        await client.send_message(user_id, f"⏳ انتظر {e.value} ثانية بسبب FloodWait ثم حاول مرة أخرى.")
    except Exception as e:
        await client.send_message(user_id, f"❌ حدث خطأ أثناء الاستخراج:\n<code>{str(e)[:300]}</code>")
        print(f"[EXTRACT ERROR] user={user_id} domain={domain} → {e}")
    finally:
        if filename and os.path.exists(filename):
            try: os.remove(filename)
            except Exception: pass

@app.on_callback_query(filters.regex("^cancel_pull$"))
async def cancel_pull_cb(client: Client, callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء العملية.")

# ==================== التشغيل ====================
if __name__ == "__main__":
    print("⚡ البوت يعمل الآن بنجاح ومستعد للاستجابة...")
    app.run()
