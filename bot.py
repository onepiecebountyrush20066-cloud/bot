import telebot
import re
import ast
import os
import uuid
import json
import time
from pathlib import Path
from telebot import types
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# توكن البوت والآيدي الخاص بك
API_KEY = '8433431820:AAFeeWTaoCUjs7mtDnK9tuTIcZ10Ezm7Q7U'
ADMIN_ID = 5957527254

bot = telebot.TeleBot(API_KEY)

WORK_DIR = Path("workdir")
DATA_DIR = Path("data")
WORK_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

DEVELOPER_USERNAME = "@i_mmx"
CHANNEL_USERNAME = "@ULTRA_CODE_1"
DEVELOPER_NAME = "𝙰𝙿𝙾 𝙵𝙰𝚁𝙴𝚂"

USERS_FILE = DATA_DIR / "users.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
STATS_FILE = DATA_DIR / "stats.json"

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
    'picture': '5375074927252621134',
    'arrow': '5416117059207572332',
    'cross': '5210952531676504517',
    'bulb': '5422439311196834318',
    'bell': '5458603043203327669',
    'python': '5260480440971570446',
    '1': '5141109049114232089',
    '2': '5140871649091912628',
    '3': '5141399818400170896',
    '4': '5138822752123225428',
    '5': '5141062672057369534',
}

user_states = {}
user_sessions = {}

COLOR_STYLES = {
    "blue": "primary",
    "green": "success",
    "red": "danger",
}
ROW_COLORS = ["blue", "green", "red"]

COLOR_NAMES_AR = {
    "blue": "أزرق",
    "green": "أخضر",
    "red": "أحمر",
}

COLOR_EMOJI = {
    "blue": "🔵",
    "green": "🟢",
    "red": "🔴",
}

DEFAULT_SETTINGS = {
    "welcome_photo": None,
}

def load_json(file_path: Path, default=None):
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default or {}

def save_json(file_path: Path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_users():
    return load_json(USERS_FILE, {})

def save_users(users):
    save_json(USERS_FILE, users)

def add_user(user_id, username, first_name):
    users = get_users()
    if str(user_id) not in users:
        users[str(user_id)] = {
            'username': username,
            'first_name': first_name,
            'joined_at': datetime.now().isoformat(),
        }
        save_users(users)
        return True
    return False

def get_settings():
    return load_json(SETTINGS_FILE, DEFAULT_SETTINGS)

def save_settings(settings):
    save_json(SETTINGS_FILE, settings)

def get_stats():
    return load_json(STATS_FILE, {'total_files': 0, 'total_buttons': 0})

def increment_stats(files=0, buttons=0):
    stats = get_stats()
    stats['total_files'] += files
    stats['total_buttons'] += buttons
    save_json(STATS_FILE, stats)

def notify_admin(text):
    try:
        bot.send_message(ADMIN_ID, text, parse_mode='HTML')
    except:
        pass

class ButtonInfo:
    def __init__(self, text: str, row_index: int, col_index: int,
                 button_index: int, line_start: int, line_end: int,
                 full_line: str, indent: str, col_offset: int = 0):
        self.text = text
        self.original_text = text
        self.row_index = row_index
        self.col_index = col_index
        self.button_index = button_index
        self.line_start = line_start
        self.line_end = line_end
        self.full_line = full_line
        self.indent = indent
        self.col_offset = col_offset
        self.chosen_color: Optional[str] = None
        self.chosen_emoji_id: Optional[str] = None

# ==================== أزرار ودوال التلوين ====================
def create_emoji_btn(text, callback=None, url=None, emoji_id=None, color=None):
    if emoji_id:
        text = strip_emoji_from_text(text)
        
    btn = types.InlineKeyboardButton(text=text, callback_data=callback, url=url)
    if emoji_id:
        try:
            btn.icon_custom_emoji_id = emoji_id
        except:
            pass
    if color:
        btn.style = color
    return btn

def strip_emoji_from_text(text: str) -> str:
    emoji_pattern = re.compile(
        r'[\U00010000-\U0010ffff]|[\u2600-\u27BF]|[\uFE00-\uFE0F]|[\u2300-\u23FF]'
    )
    return emoji_pattern.sub('', text).strip()

def color_mode_menu():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.row(
        create_emoji_btn("يدوي", callback="color:manual", emoji_id=E['pencil'], color="primary"),
        create_emoji_btn("عشوائي", callback="color:random", emoji_id=E['sparkles'], color="success")
    )
    m.add(create_emoji_btn("رجوع", callback="back_to_home", emoji_id=E['arrow'], color="primary"))
    return m

def color_picker_for_button(btn_idx: int, btn_text: str, current_color=None, current_emoji_id=None):
    m = types.InlineKeyboardMarkup(row_width=3)
    preview_text = strip_emoji_from_text(btn_text[:20])
    btn_preview = create_emoji_btn(
        preview_text,
        callback="preview",
        emoji_id=current_emoji_id,
        color=COLOR_STYLES.get(current_color) if current_color else None
    )
    m.add(btn_preview)
    m.row(
        create_emoji_btn("أحمر", callback=f"pick_color:red:{btn_idx}", color="danger"),
        create_emoji_btn("أزرق", callback=f"pick_color:blue:{btn_idx}", color="primary"),
        create_emoji_btn("أخضر", callback=f"pick_color:green:{btn_idx}", color="success")
    )
    if current_color and current_emoji_id:
        m.add(create_emoji_btn("التالي", callback=f"next_btn:{btn_idx}", emoji_id=E['arrow'], color="success"))
    elif current_color:
        m.add(create_emoji_btn("تخطي إيموجي", callback=f"skip_emoji:{btn_idx}", emoji_id=E['arrow'], color="primary"))
    return m

def emoji_question_menu():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        create_emoji_btn("نعم", callback="emoji_ask:yes", emoji_id=E['check'], color="success"),
        create_emoji_btn("لا", callback="emoji_ask:no", emoji_id=E['cross'], color="danger")
    )
    return m
# ============================================================

def send_with_photo(chat_id, text, reply_markup=None, parse_mode='HTML'):
    settings = get_settings()
    photo = settings.get('welcome_photo')
    
    if photo:
        try:
            return bot.send_photo(chat_id, photo, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except:
            return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode='HTML'):
    try:
        bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
        except:
            pass

class ASTButtonVisitor(ast.NodeVisitor):
    def __init__(self):
        self.buttons = []
        self.current_row_index = 0
        self.current_col_index = 0
        self.button_index = 0
        self.in_keyboard_definition = False

    def visit_Call(self, node: ast.Call):
        is_btn = False
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and node.func.value.id in ['types', 'telebot.types'] and 
                    node.func.attr == 'InlineKeyboardButton'):
                is_btn = True
            elif isinstance(node.func.value, ast.Name) and node.func.attr == 'create_emoji_btn':
                is_btn = True
        elif isinstance(node.func, ast.Name) and node.func.id in ['create_emoji_btn', 'InlineKeyboardButton']:
            is_btn = True

        if is_btn:
            button_text = None
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    button_text = arg.value
                    break
            if not button_text:
                for kw in node.keywords:
                    if kw.arg == 'text' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        button_text = kw.value.value
                        break
            
            if button_text:
                self.buttons.append(ButtonInfo(
                    text=button_text,
                    row_index=self.current_row_index,
                    col_index=self.current_col_index,
                    button_index=self.button_index,
                    line_start=node.lineno - 1,
                    line_end=node.end_lineno - 1 if hasattr(node, 'end_lineno') else node.lineno - 1,
                    full_line="",
                    indent="",
                    col_offset=node.col_offset
                ))
                self.current_col_index += 1
                self.button_index += 1
        self.generic_visit(node)

    def visit_List(self, node: ast.List):
        if self.in_keyboard_definition:
            self.current_col_index = 0
            if any(isinstance(el, ast.Call) for el in node.elts):
                self.current_row_index += 1
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'InlineKeyboardMarkup':
            self.in_keyboard_definition = True
            self.current_row_index = 0
        self.generic_visit(node)
        self.in_keyboard_definition = False

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr in ['add', 'row']:
            self.current_col_index = 0
            self.current_row_index += 1
        self.generic_visit(node)

class SmartButtonExtractor:
    @staticmethod
    def extract_buttons(content: str) -> List[ButtonInfo]:
        try:
            tree = ast.parse(content)
            visitor = ASTButtonVisitor()
            visitor.visit(tree)
            return visitor.buttons
        except:
            return []

class CodeModifier:
    @staticmethod
    def apply_changes(content: str, buttons: List[ButtonInfo]) -> str:
        lines = content.split('\n')
        line_map = {}
        for btn in buttons:
            if btn.line_start not in line_map: line_map[btn.line_start] = []
            line_map[btn.line_start].append(btn)
        
        for line_idx in sorted(line_map.keys(), reverse=True):
            line_buttons = sorted(line_map[line_idx], key=lambda x: x.col_offset, reverse=True)
            current_line = lines[line_idx]
            for btn in line_buttons:
                if not btn.chosen_color and not btn.chosen_emoji_id: continue
                
                cleaned_text = strip_emoji_from_text(btn.original_text)
                if cleaned_text != btn.original_text:
                    current_line = current_line.replace(f'"{btn.original_text}"', f'"{cleaned_text}"').replace(f"'{btn.original_text}'", f"'{cleaned_text}'")
                
                current_line = re.sub(r',?\s*style\s*=\s*["\'][^"\']*["\']', '', current_line)
                current_line = re.sub(r',?\s*icon_custom_emoji_id\s*=\s*["\'][^"\']*["\']', '', current_line)
                
                additions = ""
                if btn.chosen_color: 
                    additions += f', style="{COLOR_STYLES.get(btn.chosen_color, "primary")}"'
                if btn.chosen_emoji_id: 
                    additions += f', icon_custom_emoji_id="{btn.chosen_emoji_id}"'
                
                paren_idx = current_line.find(')', btn.col_offset)
                if paren_idx != -1: 
                    current_line = current_line[:paren_idx] + additions + current_line[paren_idx:]
            lines[line_idx] = current_line
        return '\n'.join(lines)

    @staticmethod
    def apply_random_colors(buttons: List[ButtonInfo]):
        row_colors = {}
        for btn in buttons:
            if btn.row_index not in row_colors: row_colors[btn.row_index] = ROW_COLORS[btn.row_index % len(ROW_COLORS)]
            btn.chosen_color = row_colors[btn.row_index]

def main_menu():
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        create_emoji_btn("ابدأ الآن", callback="start_now", emoji_id=E['sparkles'], color="success"),
        create_emoji_btn("كيفية الاستخدام", callback="how_to_use", emoji_id=E['bulb'], color="primary")
    )
    m.row(
        create_emoji_btn("المطور", url=f"https://t.me/{DEVELOPER_USERNAME[1:]}", emoji_id=E['crown'], color="danger"),
        create_emoji_btn("قناة المطور", url=f"https://t.me/{CHANNEL_USERNAME[1:]}", emoji_id=E['link'], color="primary")
    )
    if ADMIN_ID > 0:
        m.add(create_emoji_btn("لوحة التحكم", callback="admin_panel", emoji_id=E['settings'], color="primary"))
    return m

def admin_menu():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        create_emoji_btn("الإحصائيات", callback="admin:stats", emoji_id=E['chart'], color="success"),
        create_emoji_btn("المستخدمين", callback="admin:users", emoji_id=E['people'], color="primary")
    )
    m.add(
        create_emoji_btn("تعيين صورة", callback="admin:set_photo", emoji_id=E['picture'], color="primary"),
        create_emoji_btn("إذاعة", callback="admin:broadcast", emoji_id=E['bell'], color="danger")
    )
    m.add(create_emoji_btn("رجوع", callback="back_to_home", emoji_id=E['arrow'], color="primary"))
    return m

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    username = message.from_user.username or "بدون يوزر"
    first_name = message.from_user.first_name or "مستخدم"
    
    is_new = add_user(uid, username, first_name)
    
    if is_new and ADMIN_ID > 0:
        users = get_users()
        notify_admin(f"""
<blockquote><b>مستخدم جديد</b> <tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji></blockquote>

<blockquote><b>الاسم:</b> {first_name}
<b>اليوزر:</b> @{username}
<b>الآيدي:</b> <code>{uid}</code></blockquote>

<blockquote><b>إجمالي المستخدمين:</b> {len(users)}</blockquote>
""")
    
    user_states[uid] = None
    user_sessions.pop(uid, None)
    
    text = f"""
<blockquote><b>مرحباً بك {first_name}</b> <tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji></blockquote>

<blockquote><b>بوت تلوين الأزرار الاحترافي</b> <tg-emoji emoji-id='{E['sparkles']}'>✨</tg-emoji></blockquote>

<blockquote><b>دعم Python</b> <tg-emoji emoji-id='{E['python']}'>💻</tg-emoji>
<b>تلوين يدوي وعشوائي</b> <tg-emoji emoji-id='{E['pencil']}'>✍️</tg-emoji>
<b>إيموجيات مميزة Premium</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji>
<b>معالجة ذكية للكود</b> <tg-emoji emoji-id='{E['trophy']}'>🏆</tg-emoji></blockquote>

<blockquote><b>اضغط على زر ابدأ الآن</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>

<blockquote>المطور: <a href="https://t.me/{DEVELOPER_USERNAME[1:]}">{DEVELOPER_NAME}</a></blockquote>
"""
    
    msg = send_with_photo(message.chat.id, text, reply_markup=main_menu())
    if uid not in user_sessions:
        user_sessions[uid] = {}
    user_sessions[uid]['main_msg_id'] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == "how_to_use")
def how_to_use_handler(call):
    text = f"""
<blockquote><b>كيفية الاستخدام</b> <tg-emoji emoji-id='{E['bulb']}'>💡</tg-emoji></blockquote>

<blockquote><tg-emoji emoji-id='{E['1']}'>1️⃣</tg-emoji> <b>اضغط على ابدأ الآن</b>
<tg-emoji emoji-id='{E['2']}'>2️⃣</tg-emoji> <b>أرسل ملف البوت Python</b>
<tg-emoji emoji-id='{E['3']}'>3️⃣</tg-emoji> <b>اختر وضع التلوين</b>
<tg-emoji emoji-id='{E['4']}'>4️⃣</tg-emoji> <b>اختر الألوان والإيموجيات</b>
<tg-emoji emoji-id='{E['5']}'>5️⃣</tg-emoji> <b>استلم الملف المعدل</b></blockquote>

<blockquote><b>وضع التلوين:</b></blockquote>

<blockquote><b>يدوي:</b> تختار لون وإيموجي لكل زر
<b>عشوائي:</b> ألوان تلقائية + اختيار الإيموجيات</blockquote>

<blockquote><b>الألوان المتاحة:</b>
🔵 أزرق - 🟢 أخضر - 🔴 أحمر</blockquote>

<blockquote><tg-emoji emoji-id='{E['warning']}'>⚠️</tg-emoji> <b>ملاحظة:</b> الإيموجيات المميزة تعمل فقط مع البوتات Premium</blockquote>
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(create_emoji_btn("رجوع", callback="back_to_home", emoji_id=E['arrow'], color="primary"))
    
    edit_message(call.message.chat.id, call.message.id, text, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_home")
def back_to_home(call):
    uid = call.from_user.id
    user_states[uid] = None
    user_sessions.pop(uid, None)
    
    first_name = call.from_user.first_name or "مستخدم"
    
    text = f"""
<blockquote><b>مرحباً بك {first_name}</b> <tg-emoji emoji-id='{E['fire']}'>🔥</tg-emoji></blockquote>

<blockquote><b>بوت تلوين الأزرار الاحترافي</b> <tg-emoji emoji-id='{E['sparkles']}'>✨</tg-emoji></blockquote>

<blockquote><b>دعم Python</b> <tg-emoji emoji-id='{E['python']}'>💻</tg-emoji>
<b>تلوين يدوي وعشوائي</b> <tg-emoji emoji-id='{E['pencil']}'>✍️</tg-emoji>
<b>إيموجيات مميزة Premium</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji>
<b>معالجة ذكية للكود</b> <tg-emoji emoji-id='{E['trophy']}'>🏆</tg-emoji></blockquote>

<blockquote><b>اضغط على زر ابدأ الآن</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>

<blockquote>المطور: <a href="https://t.me/{DEVELOPER_USERNAME[1:]}">{DEVELOPER_NAME}</a></blockquote>
"""
    
    edit_message(call.message.chat.id, call.message.id, text, reply_markup=main_menu())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ غير مصرح", show_alert=True)
        return
    
    users = get_users()
    stats = get_stats()
    
    text = f"""
<blockquote><b>لوحة التحكم</b> <tg-emoji emoji-id='{E['settings']}'>⚙️</tg-emoji></blockquote>

<blockquote><b>المستخدمين:</b> {len(users)}
<b>الملفات:</b> {stats.get('total_files', 0)}
<b>الأزرار:</b> {stats.get('total_buttons', 0)}</blockquote>
"""
    
    edit_message(call.message.chat.id, call.message.id, text, reply_markup=admin_menu())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin:"))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ غير مصرح", show_alert=True)
        return
    
    action = call.data.split(":")[1]
    
    if action == "stats":
        users = get_users()
        stats = get_stats()
        
        text = f"""
<blockquote><b>الإحصائيات التفصيلية</b> <tg-emoji emoji-id='{E['chart']}'>📊</tg-emoji></blockquote>

<blockquote><b>المستخدمين:</b> {len(users)}
<b>الملفات المعالجة:</b> {stats.get('total_files', 0)}
<b>الأزرار الملونة:</b> {stats.get('total_buttons', 0)}</blockquote>
"""
        
        edit_message(call.message.chat.id, call.message.id, text, reply_markup=admin_menu())
    
    elif action == "users":
        users = get_users()
        user_list = "\n".join([
            f"<b>{u['first_name']}</b> (@{u['username']})"
            for uid, u in list(users.items())[:10]
        ])
        
        text = f"""
<blockquote><b>المستخدمين</b> <tg-emoji emoji-id='{E['people']}'>👥</tg-emoji></blockquote>

<blockquote><b>الإجمالي:</b> {len(users)}</blockquote>

<blockquote><b>آخر 10 مستخدمين:</b>
{user_list}</blockquote>
"""
        
        edit_message(call.message.chat.id, call.message.id, text, reply_markup=admin_menu())
    
    elif action == "set_photo":
        user_states[call.from_user.id] = 'admin_waiting_photo'
        
        text = f"""
<blockquote><b>تعيين صورة الترحيب</b> <tg-emoji emoji-id='{E['picture']}'>🖼</tg-emoji></blockquote>

<blockquote><b>أرسل الصورة الآن</b></blockquote>
"""
        edit_message(call.message.chat.id, call.message.id, text, reply_markup=admin_menu())
    
    elif action == "broadcast":
        user_states[call.from_user.id] = 'admin_waiting_broadcast'
        
        text = f"""
<blockquote><b>الإذاعة للمستخدمين</b> <tg-emoji emoji-id='{E['bell']}'>🔔</tg-emoji></blockquote>

<blockquote><b>أرسل الرسالة الآن</b></blockquote>
"""
        edit_message(call.message.chat.id, call.message.id, text, reply_markup=admin_menu())
    
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    uid = message.from_user.id
    
    if user_states.get(uid) == 'admin_waiting_photo':
        if uid == ADMIN_ID:
            photo_id = message.photo[-1].file_id
            settings = get_settings()
            settings['welcome_photo'] = photo_id
            save_settings(settings)
            
            bot.reply_to(message, 
                        f"<blockquote><b>تم تعيين الصورة بنجاح</b> <tg-emoji emoji-id='{E['check']}'>✅</tg-emoji></blockquote>", 
                        parse_mode='HTML')
            user_states[uid] = None

@bot.callback_query_handler(func=lambda call: call.data == "start_now")
def start_now_handler(call):
    uid = call.from_user.id
    user_states[uid] = 'waiting_file'
    
    text = f"""
<blockquote><b>تلوين الأزرار</b> <tg-emoji emoji-id='{E['sparkles']}'>🎨</tg-emoji></blockquote>

<blockquote><b>أرسل ملف البوت الآن (.py)</b> <tg-emoji emoji-id='{E['python']}'>💻</tg-emoji></blockquote>

<blockquote><b>سيتم تحليل الملف واستخراج الأزرار تلقائياً</b> <tg-emoji emoji-id='{E['trophy']}'>🏆</tg-emoji></blockquote>
"""
    
    edit_message(call.message.chat.id, call.message.id, text, reply_markup=None)
    
    if uid not in user_sessions:
        user_sessions[uid] = {}
    user_sessions[uid]['main_msg_id'] = call.message.id
    
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['document'])
def file_handler(message):
    uid = message.from_user.id
    
    if user_states.get(uid) != 'waiting_file':
        return
    
    document = message.document
    filename = document.file_name or "file"
    ext = Path(filename).suffix.lower()
    
    if ext != '.py':
        bot.reply_to(message, 
                    f"<blockquote><b>نوع ملف غير مدعوم</b> <tg-emoji emoji-id='{E['cross']}'>❌</tg-emoji></blockquote>\n\n"
                    f"<blockquote><b>أرسل ملف .py فقط</b></blockquote>",
                    parse_mode='HTML')
        return
    
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
    
    session = user_sessions.get(uid, {})
    main_msg_id = session.get('main_msg_id')
    
    if main_msg_id:
        edit_message(message.chat.id, main_msg_id, 
                    f"<blockquote><b>جاري التحليل...</b> <tg-emoji emoji-id='{E['sparkles']}'>⏳</tg-emoji></blockquote>")
    
    try:
        file_info = bot.get_file(document.file_id)
        local_path = WORK_DIR / f"{uuid.uuid4().hex}_{filename}"
        
        downloaded = bot.download_file(file_info.file_path)
        with open(local_path, 'wb') as f:
            f.write(downloaded)
        
        with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        buttons = SmartButtonExtractor.extract_buttons(content)
        
        if not buttons:
            if main_msg_id:
                edit_message(message.chat.id, main_msg_id,
                           f"<blockquote><b>لم أجد أزرار في هذا الملف</b> <tg-emoji emoji-id='{E['warning']}'>⚠️</tg-emoji></blockquote>")
            local_path.unlink(missing_ok=True)
            return
        
        user_sessions[uid] = {
            'content': content,
            'buttons': buttons,
            'filename': filename,
            'file_path': str(local_path),
            'main_msg_id': main_msg_id
        }
        
        rows = len(set(b.row_index for b in buttons))
        
        summary = f"""
<blockquote><b>تم تحليل الملف بنجاح</b> <tg-emoji emoji-id='{E['check']}'>✅</tg-emoji></blockquote>

<blockquote><b>اللغة:</b> Python <tg-emoji emoji-id='{E['python']}'>💻</tg-emoji>
<b>الملف:</b> {filename}
<b>عدد الأزرار:</b> {len(buttons)}
<b>عدد الصفوف:</b> {rows}</blockquote>

<blockquote><b>اختر وضع التلوين:</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>
"""
        
        if main_msg_id:
            edit_message(message.chat.id, main_msg_id, summary, reply_markup=color_mode_menu())
        
        user_states[uid] = 'choosing_color_mode'
    
    except Exception as ex:
        if main_msg_id:
            edit_message(message.chat.id, main_msg_id,
                       f"<blockquote><b>حدث خطأ:</b> <tg-emoji emoji-id='{E['cross']}'>❌</tg-emoji></blockquote>\n\n"
                       f"<blockquote><code>{str(ex)}</code></blockquote>")

@bot.callback_query_handler(func=lambda call: call.data.startswith("color:"))
def color_mode_handler(call):
    uid = call.from_user.id
    mode = call.data.split(":")[1]
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    session = user_sessions[uid]
    session['color_mode'] = mode
    
    if mode == 'random':
        CodeModifier.apply_random_colors(session['buttons'])
        
        text = f"""
<blockquote><b>تم تطبيق الألوان العشوائية</b> <tg-emoji emoji-id='{E['check']}'>✅</tg-emoji></blockquote>

<blockquote><b>هل تريد إضافة إيموجي مميز للأزرار؟</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji></blockquote>
"""
        
        edit_message(call.message.chat.id, call.message.id, text, reply_markup=emoji_question_menu())
        user_states[uid] = 'emoji_question'
    
    else:
        text = f"""
<blockquote><b>التلوين اليدوي</b> <tg-emoji emoji-id='{E['pencil']}'>✍️</tg-emoji></blockquote>

<blockquote><b>سأعرض عليك كل زر لتختار لونه وإيموجيه</b> <tg-emoji emoji-id='{E['sparkles']}'>✨</tg-emoji></blockquote>

<blockquote><b>جاري البدء...</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>
"""
        
        edit_message(call.message.chat.id, call.message.id, text)
        
        time.sleep(1)
        
        user_states[uid] = 'manual_coloring'
        session['current_btn_idx'] = 0
        show_manual_color_step(call.message.chat.id, call.message.id, uid, session, 0)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("emoji_ask:"))
def emoji_ask_handler(call):
    uid = call.from_user.id
    answer = call.data.split(":")[1]
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    session = user_sessions[uid]
    
    if answer == 'no':
        finish_and_send(call.message.chat.id, uid, session)
    else:
        text = f"""
<blockquote><b>إضافة إيموجيات مميزة</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji></blockquote>

<blockquote><b>سأسألك عن كل زر</b> <tg-emoji emoji-id='{E['pencil']}'>✍️</tg-emoji></blockquote>

<blockquote><b>جاري البدء...</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>
"""
        edit_message(call.message.chat.id, call.message.id, text)
        
        time.sleep(1)
        
        user_states[uid] = 'asking_emoji_random'
        session['current_btn_idx'] = 0
        show_emoji_question_random(call.message.chat.id, call.message.id, uid, session, 0)
    
    bot.answer_callback_query(call.id)

def show_emoji_question_random(chat_id: int, msg_id: int, user_id: int, session: dict, idx: int):
    buttons = session['buttons']
    btn = buttons[idx]
    
    text = f"""
<blockquote><b>الزر {idx + 1} من {len(buttons)}</b> <tg-emoji emoji-id='{E['sparkles']}'>🎨</tg-emoji></blockquote>

<blockquote><b>النص:</b> {strip_emoji_from_text(btn.text[:40])}
<b>اللون:</b> {COLOR_EMOJI[btn.chosen_color]} {COLOR_NAMES_AR[btn.chosen_color]}</blockquote>

<blockquote><b>أرسل إيموجي مميز أو اضغط تخطي</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji></blockquote>
"""
    
    markup = types.InlineKeyboardMarkup()
    preview_btn = create_emoji_btn(
        strip_emoji_from_text(btn.text[:20]),
        callback="preview",
        emoji_id=btn.chosen_emoji_id,
        color=COLOR_STYLES.get(btn.chosen_color)
    )
    markup.add(preview_btn)
    
    if btn.chosen_emoji_id:
        markup.add(create_emoji_btn("التالي", callback=f"next_random:{idx}", emoji_id=E['arrow'], color="success"))
    else:
        markup.add(create_emoji_btn("تخطي", callback=f"skip_random_emoji:{idx}", emoji_id=E['arrow']))
    
    edit_message(chat_id, msg_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("skip_random_emoji:") or call.data.startswith("next_random:"))
def skip_next_random_emoji_handler(call):
    uid = call.from_user.id
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    idx = int(call.data.split(":")[1])
    session = user_sessions[uid]
    
    next_idx = idx + 1
    if next_idx >= len(session['buttons']):
        finish_and_send(call.message.chat.id, uid, session)
    else:
        session['current_btn_idx'] = next_idx
        show_emoji_question_random(call.message.chat.id, call.message.id, uid, session, next_idx)
    
    bot.answer_callback_query(call.id)

def show_manual_color_step(chat_id: int, msg_id: int, user_id: int, session: dict, idx: int):
    buttons = session['buttons']
    btn = buttons[idx]
    
    text = f"""
<blockquote><b>الزر {idx + 1} من {len(buttons)}</b> <tg-emoji emoji-id='{E['sparkles']}'>🎨</tg-emoji></blockquote>

<blockquote><b>الصف:</b> {btn.row_index + 1}
<b>النص:</b> {strip_emoji_from_text(btn.text[:40])}</blockquote>

<blockquote><b>اختر اللون:</b> <tg-emoji emoji-id='{E['arrow']}'>➡️</tg-emoji></blockquote>
"""
    
    edit_message(chat_id, msg_id, text, 
                reply_markup=color_picker_for_button(idx, btn.text, btn.chosen_color, btn.chosen_emoji_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith("pick_color:"))
def pick_color_handler(call):
    uid = call.from_user.id
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    parts = call.data.split(":")
    color = parts[1]
    idx = int(parts[2])
    
    session = user_sessions[uid]
    session['buttons'][idx].chosen_color = color
    
    bot.answer_callback_query(call.id, f"تم اختيار {COLOR_NAMES_AR[color]} {COLOR_EMOJI[color]}", show_alert=True)
    
    btn = session['buttons'][idx]
    
    text = f"""
<blockquote><b>الزر {idx + 1} من {len(session['buttons'])}</b> <tg-emoji emoji-id='{E['sparkles']}'>🎨</tg-emoji></blockquote>

<blockquote><b>النص:</b> {strip_emoji_from_text(btn.text[:40])}
<b>اللون:</b> {COLOR_EMOJI[color]} {COLOR_NAMES_AR[color]}</blockquote>

<blockquote><b>أرسل إيموجي مميز أو اضغط تخطي</b> <tg-emoji emoji-id='{E['gem']}'>💎</tg-emoji></blockquote>
"""
    
    edit_message(call.message.chat.id, call.message.id, text, 
                reply_markup=color_picker_for_button(idx, btn.text, color, btn.chosen_emoji_id))
    
    user_states[uid] = 'waiting_emoji_for_button'
    session['current_btn_idx'] = idx

@bot.callback_query_handler(func=lambda call: call.data.startswith("skip_emoji:"))
def skip_emoji_handler(call):
    uid = call.from_user.id
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    idx = int(call.data.split(":")[1])
    session = user_sessions[uid]
    
    next_idx = idx + 1
    if next_idx >= len(session['buttons']):
        finish_and_send(call.message.chat.id, uid, session)
    else:
        user_states[uid] = 'manual_coloring'
        session['current_btn_idx'] = next_idx
        show_manual_color_step(call.message.chat.id, call.message.id, uid, session, next_idx)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("next_btn:"))
def next_btn_handler(call):
    uid = call.from_user.id
    
    if uid not in user_sessions:
        bot.answer_callback_query(call.id, "❌ انتهت الجلسة", show_alert=True)
        return
    
    idx = int(call.data.split(":")[1])
    session = user_sessions[uid]
    
    next_idx = idx + 1
    if next_idx >= len(session['buttons']):
        finish_and_send(call.message.chat.id, uid, session)
    else:
        user_states[uid] = 'manual_coloring'
        session['current_btn_idx'] = next_idx
        show_manual_color_step(call.message.chat.id, call.message.id, uid, session, next_idx)
    
    bot.answer_callback_query(call.id, "✅ التالي")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def text_handler(message):
    uid = message.from_user.id
    state = user_states.get(uid)
    
    if state == 'admin_waiting_broadcast' and uid == ADMIN_ID:
        users = get_users()
        success = 0
        
        for user_id in users.keys():
            try:
                bot.send_message(int(user_id), message.text, parse_mode='HTML')
                success += 1
            except:
                pass
        
        bot.reply_to(message, 
                    f"<blockquote><b>تم الإرسال إلى {success} مستخدم</b> <tg-emoji emoji-id='{E['check']}'>✅</tg-emoji></blockquote>", 
                    parse_mode='HTML')
        user_states[uid] = None
        return
    
    if state in ['asking_emoji_random', 'waiting_emoji_for_button']:
        session = user_sessions.get(uid)
        if not session:
            return
        
        current_idx = session.get('current_btn_idx', 0)
        buttons = session['buttons']
        main_msg_id = session.get('main_msg_id')
        
        emoji_id = None
        if message.entities:
            for ent in message.entities:
                if ent.type == 'custom_emoji':
                    emoji_id = ent.custom_emoji_id
                    break
        
        if not emoji_id:
            bot.reply_to(message, 
                        f"<blockquote><b>لم أتعرف على إيموجي مميز</b> <tg-emoji emoji-id='{E['warning']}'>⚠️</tg-emoji></blockquote>", 
                        parse_mode='HTML')
            return
        
        buttons[current_idx].chosen_emoji_id = emoji_id
        
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        
        if main_msg_id:
            if state == 'asking_emoji_random':
                show_emoji_question_random(message.chat.id, main_msg_id, uid, session, current_idx)
            else:
                btn = buttons[current_idx]
                color = btn.chosen_color
                
                text = f"""
<blockquote><b>الزر {current_idx + 1} من {len(buttons)}</b> <tg-emoji emoji-id='{E['check']}'>✅</tg-emoji></blockquote>

<blockquote><b>النص:</b> {strip_emoji_from_text(btn.text[:40])}
<b>اللون:</b> {COLOR_EMOJI[color]} {COLOR_NAMES_AR[color]}
<b>الإيموجي:</b> تم الإضافة <tg-emoji emoji-id='{emoji_id}'>💎</tg-emoji></blockquote>

<blockquote><b>معاينة الزر:</b></blockquote>
"""
                
                edit_message(message.chat.id, main_msg_id, text,
                            reply_markup=color_picker_for_button(current_idx, btn.text, color, emoji_id))

@bot.callback_query_handler(func=lambda call: call.data == "preview")
def preview_handler(call):
    bot.answer_callback_query(call.id)

def finish_and_send(chat_id: int, user_id: int, session: dict):
    buttons = session['buttons']
    content = session['content']
    filename = session['filename']
    
    new_content = CodeModifier.apply_changes(content, buttons)
    header = f"# Colored by {DEVELOPER_NAME} ({DEVELOPER_USERNAME})\n"
    new_content = header + new_content
    
    out_path = WORK_DIR / f"colored_{filename}"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    colored = sum(1 for b in buttons if b.chosen_color)
    with_emoji = sum(1 for b in buttons if b.chosen_emoji_id)
    
    color_stats = {}
    for btn in buttons:
        if btn.chosen_color:
            color_stats[btn.chosen_color] = color_stats.get(btn.chosen_color, 0) + 1
    
    color_lines = " - ".join([
        f"{COLOR_EMOJI[c]} {count}"
        for c, count in color_stats.items()
    ])
    
    report = f"""
<blockquote><b>تم التعديل بنجاح</b> <tg-emoji emoji-id='{E['trophy']}'>🏆</tg-emoji></blockquote>

<blockquote><b>الملف:</b> {filename}
<b>أزرار ملونة:</b> {colored}
<b>بإيموجي مميز:</b> {with_emoji}
<b>الإجمالي:</b> {len(buttons)}</blockquote>

<blockquote><b>الألوان:</b> {color_lines if color_lines else 'بدون'}</blockquote>

<blockquote>المطور: <a href="https://t.me/{DEVELOPER_USERNAME[1:]}">{DEVELOPER_NAME}</a></blockquote>
"""
    
    with open(out_path, 'rb') as f:
        bot.send_document(chat_id, f, caption=report, parse_mode='HTML')
    
    out_path.unlink(missing_ok=True)
    
    increment_stats(files=1, buttons=len(buttons))
    
    user_sessions.pop(user_id, None)
    user_states[user_id] = None

print(f"""
🚀 البوت يعمل الآن...
""")

bot.infinity_polling(skip_pending=True)
