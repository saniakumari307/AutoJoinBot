import sqlite3
import asyncio
import os
from flask import Flask, jsonify, request, session, redirect, url_for, flash
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from threading import Thread
from config import BOT_TOKEN, DASHBOARD_PASSWORD, CHANNEL_ID, GROUP_INVITE_LINK, CHANNEL_URL
import datetime
import traceback

from db import init_db

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram.ext import ChatJoinRequestHandler

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest
import config  # config.py should have BOT_TOKEN, API_ID, API_HASH, CHAT_ID, WELCOME_TEXT

from telegram.ext import filters as tg_filters
from pyrogram import filters as pyro_filters
from telegram import InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaAnimation

from collections import defaultdict
import time

app = Flask(__name__)
app.secret_key = 'change_this_secret_key'
CORS(app, origins=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.1.3:3000"
], supports_credentials=True)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.1.3:3000"
])

DB_NAME = 'users.db'

# Ensure DB tables exist
init_db()

# --- Database helpers ---
def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id, full_name, username, join_date, invite_link, photo_url, label FROM users')
    users = c.fetchall()
    conn.close()
    return users

def get_total_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total = c.fetchone()[0]
    conn.close()
    return total

def get_messages_for_user(user_id, limit=100):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT sender, message, timestamp FROM messages WHERE user_id = ? ORDER BY id ASC LIMIT ?', (user_id, limit))
    messages = c.fetchall()
    conn.close()
    return messages

def save_message(user_id, sender, message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)',
              (user_id, sender, message, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def add_user(user_id, full_name, username, join_date, invite_link, photo_url=None, label=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, full_name, username, join_date, invite_link, photo_url, label) VALUES (?, ?, ?, ?, ?, ?, ?)', (user_id, full_name, username, join_date, invite_link, photo_url, label))
    conn.commit()
    conn.close()

def get_active_users(minutes=60):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute('SELECT COUNT(DISTINCT user_id) FROM messages WHERE timestamp >= ?', (since,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_total_messages():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM messages')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_new_joins_today():
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE join_date LIKE ?', (f'{today}%',))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_online_status(user_id, minutes=5):
    """Check if user has been active in the last N minutes"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute('SELECT 1 FROM messages WHERE user_id = ? AND timestamp >= ? LIMIT 1', (user_id, since))
    is_online = c.fetchone() is not None
    conn.close()
    return is_online

@app.route('/user-status/<int:user_id>')
def user_status(user_id):
    """Get user online status and last activity"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get last message timestamp
    c.execute('SELECT timestamp FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1', (user_id,))
    last_message = c.fetchone()
    
    # Check if online (active in last 5 minutes)
    is_online = get_user_online_status(user_id, 5)
    
    # Get user info
    c.execute('SELECT full_name, username, photo_url FROM users WHERE user_id = ?', (user_id,))
    user_info = c.fetchone()
    
    conn.close()
    
    return jsonify({
        'user_id': user_id,
        'full_name': user_info[0] if user_info else '',
        'username': user_info[1] if user_info else '',
        'photo_url': user_info[2] if user_info else None,
        'is_online': is_online,
        'last_activity': last_message[0] if last_message else None
    })

# --- Flask API Endpoints ---
@app.route('/dashboard-users')
def dashboard_users():
    # Get page and page_size from query params, default page=1, page_size=10
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 10))
    offset = (page - 1) * page_size

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total = c.fetchone()[0]
    c.execute('SELECT user_id, full_name, username, join_date, invite_link, photo_url, label FROM users ORDER BY join_date DESC LIMIT ? OFFSET ?', (page_size, offset))
    users = c.fetchall()
    conn.close()

    # Add online status for each user
    users_with_status = []
    for u in users:
        is_online = get_user_online_status(u[0], 5)
        users_with_status.append({
                'user_id': u[0],
                'full_name': u[1],
                'username': u[2],
                'join_date': u[3],
            'invite_link': u[4],
            'photo_url': u[5],
            'is_online': is_online,
            'label': u[6]
        })

    return jsonify({
        'users': users_with_status,
        'total': total,
        'page': page,
        'page_size': page_size
    })

@app.route('/dashboard-stats')
def dashboard_stats():
    # Total users in the database
    total_users = get_total_users()
    # Active users: users who sent messages in the last 60 minutes
    active_users = get_active_users()  # last 60 minutes
    # Total messages sent (all time)
    total_messages = get_total_messages()
    # New joins today
    new_joins_today = get_new_joins_today()
    return jsonify({
        'total_users': total_users,
        'active_users': active_users,
        'total_messages': total_messages,
        'new_joins_today': new_joins_today
    })

@app.route('/chat/<int:user_id>/messages')
def chat_messages(user_id):
    messages = get_messages_for_user(user_id)
    # messages is a list of (sender, message, timestamp)
    return jsonify([
        [sender, message, timestamp] for sender, message, timestamp in messages
    ])

@app.route('/get_channel_invite_link', methods=['GET'])
def get_channel_invite_link():
    try:
        future = asyncio.run_coroutine_threadsafe(
            bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                name=f"AdminPanelInvite-{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            loop
        )
        chat = future.result()
        invite_link = chat.invite_link
        return jsonify({'invite_link': invite_link})
    except Exception as e:
        print(f"Error getting invite link: {e}")
        return jsonify({'error': str(e)}), 500

# --- Telegram Bot Handlers ---
bot = Bot(BOT_TOKEN)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# In-memory cache for media groups: {media_group_id: {'user_id': ..., 'media': [...], 'type': ..., 'timestamp': ...}}
media_group_cache = defaultdict(dict)
MEDIA_GROUP_TIMEOUT = 20  # seconds

async def cleanup_media_groups():
    while True:
        now = time.time()
        to_delete = []
        for group_id, group in media_group_cache.items():
            if now - group.get('timestamp', now) > MEDIA_GROUP_TIMEOUT:
                to_delete.append(group_id)
        for group_id in to_delete:
            print(f"Cleaning up expired media group: {group_id}")
            del media_group_cache[group_id]
        await asyncio.sleep(10)

# Start cleanup task (only once)
if not hasattr(asyncio, '_media_group_cleanup_started'):
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(cleanup_media_groups())
        asyncio._media_group_cleanup_started = True
    except Exception as e:
        print('Could not start media group cleanup:', e)

async def user_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = user.username or ''
    join_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Fetch profile photo URL
    photo_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            file = await context.bot.get_file(photos.photos[0][0].file_id)
            photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    except Exception as e:
        print(f"Could not fetch profile photo for user {user.id}: {e}")
    add_user(user.id, full_name, username, join_date, None, photo_url)

    message = update.message
    media_group_id = getattr(message, 'media_group_id', None)
    media_type = None
    file_id = None
    if message.photo:
        media_type = 'image'
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = 'video'
        file_id = message.video.file_id
    elif message.voice:
        media_type = 'voice'
        file_id = message.voice.file_id
    elif message.audio:
        media_type = 'audio'
        file_id = message.audio.file_id
    elif message.animation:
        media_type = 'gif'
        file_id = message.animation.file_id

    if media_group_id and media_type in ['image', 'video', 'voice', 'gif']:
        group = media_group_cache.get(media_group_id)
        if not group:
            group = {
                'user_id': user.id,
                'media': [],
                'type': media_type,
                'timestamp': time.time()
            }
            media_group_cache[media_group_id] = group
        file = await context.bot.get_file(file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        group['media'].append(file_url)
        group['timestamp'] = time.time()
        async def process_group_later(group_id, expected_count=len(group['media'])):
            await asyncio.sleep(1.5)
            group = media_group_cache.get(group_id)
            if group and len(group['media']) == expected_count:
                label = {'image': '[images]', 'video': '[videos]', 'voice': '[voices]', 'gif': '[gifs]'}[group['type']]
                save_message(group['user_id'], 'user', f"{label}" + '\n' + '\n'.join(group['media']))
                print(f"Saved media group {group_id} for user {group['user_id']}: {group['media']}")
                del media_group_cache[group_id]
                socketio.emit('new_message', {'user_id': group['user_id'], 'full_name': full_name, 'username': username})
        loop = asyncio.get_event_loop()
        loop.create_task(process_group_later(media_group_id, len(group['media'])))
        return

    if message.photo:
        file = await context.bot.get_file(message.photo[-1].file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        save_message(user.id, 'user', f"[image]{file_url}")
    elif message.video:
        file = await context.bot.get_file(message.video.file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        save_message(user.id, 'user', f"[video]{file_url}")
    elif message.voice:
        file = await context.bot.get_file(message.voice.file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        save_message(user.id, 'user', f"[voice]{file_url}")
    elif message.audio:
        file = await context.bot.get_file(message.audio.file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        save_message(user.id, 'user', f"[audio]{file_url}")
    elif message.animation:
        file = await context.bot.get_file(message.animation.file_id)
        if file.file_path.startswith('http'):
            file_url = file.file_path
        else:
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        save_message(user.id, 'user', f"[gif]{file_url}")
    elif message.text:
        save_message(user.id, 'user', message.text)

    socketio.emit('new_message', {'user_id': user.id, 'full_name': full_name, 'username': username})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = user.username or ''
    join_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Try to generate a unique invite link for this user
    invite_link = None
    try:
        chat = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            name=f"{full_name} ({user.id})"
        )
        invite_link = chat.invite_link
    except Exception as e:
        print(f"Failed to create unique invite link: {e}")
        from config import CHANNEL_URL
        invite_link = CHANNEL_URL
    add_user(user.id, full_name, username, join_date, invite_link)
    keyboard = [
        [InlineKeyboardButton('Join Channel', url=invite_link)],
        [InlineKeyboardButton('I have joined', callback_data='joined_channel')]
    ]
    text = (
        "👋 Welcome!\n\n"
        "To access all features, please join our channel first.\n"
        f"{invite_link}\n\n"
        "After joining, click the button below."
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def channel_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    # Send professional welcome message
    welcome = (
        "🎉 Thank you for joining our channel!\n\n"
        "You are now a full member. You can chat with me here anytime."
    )
    await context.bot.send_message(chat_id=user.id, text=welcome)
    # Optionally, notify admin (bot owner)
    try:
        # ADMIN_USER_ID is not defined in the original file, so this line is commented out
        # await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"User {user.full_name} (@{user.username}) [{user.id}] has joined the channel and can now chat.")
        pass # Placeholder for ADMIN_USER_ID
    except Exception:
        pass

async def approve_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.chat_join_request.approve()
    user = update.chat_join_request.from_user
    # Store user info in DB
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = user.username or ''
    join_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invite_link = update.chat_join_request.invite_link.invite_link if update.chat_join_request.invite_link else None
    add_user(user.id, full_name, username, join_date, invite_link)
    try:
        await context.bot.send_message(user.id, "🎉 Welcome! You are now a member. Feel free to chat with me.")
    except Exception as e:
        print(f"Failed to send welcome message: {e}")

# Register handlers for Telegram bot
application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler('start', start))
application.add_handler(CallbackQueryHandler(channel_joined_callback, pattern='^joined_channel$'))
application.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, user_message_handler))
application.add_handler(MessageHandler(tg_filters.PHOTO, user_message_handler))
application.add_handler(MessageHandler(tg_filters.VIDEO, user_message_handler))
application.add_handler(MessageHandler(tg_filters.VOICE, user_message_handler))
application.add_handler(MessageHandler(tg_filters.AUDIO, user_message_handler))
application.add_handler(ChatJoinRequestHandler(approve_join))

# Pyrogram Bot Setup
pyro_app = Client(
    "AutoApproveBot",
    bot_token=config.BOT_TOKEN,
    api_id=config.API_ID,
    api_hash=config.API_HASH
)

CHAT_ID = config.CHAT_ID
WELCOME_TEXT = getattr(config, "WELCOME_TEXT", "🎉 Hi {mention}, you are now a member of {title}!")

@pyro_app.on_chat_join_request(pyro_filters.chat(CHAT_ID))
async def approve_and_dm(client: Client, join_request: ChatJoinRequest):
    user = join_request.from_user
    chat = join_request.chat

    await client.approve_chat_join_request(chat.id, user.id)
    print(f"Approved: {user.first_name} ({user.id}) in {chat.title}")

    # Add user to DB (reuse add_user from api.py)
    from datetime import datetime
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = user.username or ''
    join_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invite_link = None  # Pyrogram does not provide invite_link in join request
    add_user(user.id, full_name, username, join_date, invite_link)

    try:
        await client.send_message(
            user.id,
            WELCOME_TEXT.format(mention=user.mention, title=chat.title)
        )
        print(f"DM sent to {user.first_name} ({user.id})")
    except Exception as e:
        print(f"Failed to send DM to {user.first_name} ({user.id}): {e}")


# --- ADMIN GIF SUPPORT ---
@app.route('/chat/<int:user_id>', methods=['POST'])
def chat_send(user_id):
    message = request.form.get('message')
    files = request.files.getlist('files')
    if not files:
        single_file = request.files.get('file')
        if single_file:
            files = [single_file]
    print('Incoming request.form keys:', list(request.form.keys()))
    print('Incoming request.files keys:', list(request.files.keys()))
    sent = False
    response = {'status': 'error', 'message': 'No message or files sent'}
    message_handled = False
    file_handled = False

    if message:
        save_message(user_id, 'admin', message)
        try:
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=int(user_id), text=message), loop
            )
            sent = True
            response = {'status': 'success', 'message': 'Message sent'}
            message_handled = True
        except Exception as e:
            print(f"Telegram send error: {e}")
            response = {'status': 'error', 'message': str(e)}

    if files and len(files) > 0:
        images = []
        videos = []
        audios = []
        gifs = []
        temp_paths = []
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
        MAX_PHOTO_SIZE = 20 * 1024 * 1024  # 20MB
        for file in files:
            filename = file.filename
            mimetype = file.mimetype
            print('File received:', filename, mimetype)
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            if mimetype == 'image/gif':
                gifs.append(InputMediaAnimation(open(f'temp_{filename}', 'rb')))
            elif mimetype.startswith('image/') and file_size > MAX_PHOTO_SIZE:
                return jsonify({'status': 'error', 'message': f'Image {filename} is too large. Maximum size is 20MB.'}), 400
            elif file_size > MAX_FILE_SIZE:
                return jsonify({'status': 'error', 'message': f'File {filename} is too large. Maximum size is 50MB.'}), 400
            temp_path = f'temp_{filename}'
            file.save(temp_path)
            temp_paths.append(temp_path)
            if mimetype.startswith('image/') and mimetype != 'image/gif':
                images.append(InputMediaPhoto(open(temp_path, 'rb')))
            elif mimetype.startswith('video/'):
                videos.append(InputMediaVideo(open(temp_path, 'rb')))
            elif mimetype.startswith('audio/'):
                audios.append(InputMediaAudio(open(temp_path, 'rb')))
        try:
            if gifs:
                if len(gifs) > 1:
                    print('Sending media group (gifs)...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_media_group(chat_id=int(user_id), media=gifs), loop
                    )
                    result = fut.result()
                    for i, msg in enumerate(result):
                        if msg.animation:
                            file = asyncio.run_coroutine_threadsafe(
                                bot.get_file(msg.animation.file_id), loop
                            ).result()
                            if file.file_path.startswith('http'):
                                file_url = file.file_path
                            else:
                                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                            save_message(user_id, 'admin', f'[gif]{file_url}')
                else:
                    print('Sending single gif...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_animation(chat_id=int(user_id), animation=gifs[0].media), loop
                    )
                    result = fut.result()
                    if result.animation:
                        file = asyncio.run_coroutine_threadsafe(
                            bot.get_file(result.animation.file_id), loop
                        ).result()
                        if file.file_path.startswith('http'):
                            file_url = file.file_path
                        else:
                            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                        save_message(user_id, 'admin', f'[gif]{file_url}')
                sent = True
                file_handled = True
            if images:
                if len(images) > 1:
                    print('Sending media group (images)...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_media_group(chat_id=int(user_id), media=images), loop
                    )
                    result = fut.result()
                    for i, msg in enumerate(result):
                        if msg.photo:
                            file = asyncio.run_coroutine_threadsafe(
                                bot.get_file(msg.photo[-1].file_id), loop
                            ).result()
                            if file.file_path.startswith('http'):
                                file_url = file.file_path
                            else:
                                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                            print(f"Debug - file.file_path: {file.file_path}")
                            print(f"Debug - constructed URL: {file_url}")
                            save_message(user_id, 'admin', f'[image]{file_url}')
                else:
                    print('Sending single image...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_photo(chat_id=int(user_id), photo=images[0].media), loop
                    )
                    result = fut.result()
                    if result.photo:
                        file = asyncio.run_coroutine_threadsafe(
                            bot.get_file(result.photo[-1].file_id), loop
                        ).result()
                        if file.file_path.startswith('http'):
                            file_url = file.file_path
                        else:
                            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                        print(f"Debug - file.file_path: {file.file_path}")
                        print(f"Debug - constructed URL: {file_url}")
                        save_message(user_id, 'admin', f'[image]{file_url}')
                sent = True
                file_handled = True
            if videos:
                if len(videos) > 1:
                    print('Sending media group (videos)...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_media_group(chat_id=int(user_id), media=videos), loop
                    )
                    result = fut.result()
                    for i, msg in enumerate(result):
                        if msg.video:
                            file = asyncio.run_coroutine_threadsafe(
                                bot.get_file(msg.video.file_id), loop
                            ).result()
                            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                            save_message(user_id, 'admin', f'[video]{file_url}')
                else:
                    print('Sending single video...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_video(chat_id=int(user_id), video=videos[0].media), loop
                    )
                    result = fut.result()
                    if result.video:
                        file = asyncio.run_coroutine_threadsafe(
                            bot.get_file(result.video.file_id), loop
                        ).result()
                        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                        save_message(user_id, 'admin', f'[video]{file_url}')
                sent = True
                file_handled = True
            if audios:
                if len(audios) > 1:
                    print('Sending media group (audios)...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_media_group(chat_id=int(user_id), media=audios), loop
                    )
                    result = fut.result()
                    for i, msg in enumerate(result):
                        if msg.audio:
                            file = asyncio.run_coroutine_threadsafe(
                                bot.get_file(msg.audio.file_id), loop
                            ).result()
                            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                            save_message(user_id, 'admin', f'[audio]{file_url}')
                else:
                    print('Sending single audio...')
                    fut = asyncio.run_coroutine_threadsafe(
                        bot.send_audio(chat_id=int(user_id), audio=audios[0].media), loop
                    )
                    result = fut.result()
                    if result.audio:
                        file = asyncio.run_coroutine_threadsafe(
                            bot.get_file(result.audio.file_id), loop
                        ).result()
                        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                        save_message(user_id, 'admin', f'[audio]{file_url}')
                sent = True
                file_handled = True
        except Exception as e:
            print(f"Telegram file send error: {e}")
            traceback.print_exc()
            response = {'status': 'error', 'message': f'Failed to send media: {str(e)}'}
            return jsonify(response), 500
        finally:
            for temp_path in temp_paths:
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print('Error removing temp file:', temp_path, e)
        response = {'status': 'success', 'message': 'Media sent successfully'}
        socketio.emit('new_message', {'user_id': user_id}, room='chat_' + str(user_id))
        return jsonify(response), 200

    # If neither message nor files were handled
    if not message_handled and not file_handled:
        response = {'status': 'error', 'message': 'No message or files sent'}
        return jsonify(response), 400

    # If only message was handled
    socketio.emit('new_message', {'user_id': user_id}, room='chat_' + str(user_id))
    return jsonify(response), 200

@app.route('/send_one', methods=['POST'])
def send_one():
    user_id = request.form.get('user_id')
    message = request.form.get('message')
    if not user_id or not message:
        return {'status': 'error', 'msg': 'Missing user_id or message'}, 400
    save_message(int(user_id), 'admin', message)
    try:
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=int(user_id), text=message), loop
        )
    except Exception as e:
        print(f"Telegram send error: {e}")
    socketio.emit('new_message', {'user_id': int(user_id)}, room='chat_' + str(user_id))
    return {'status': 'ok'}

@app.route('/send_all', methods=['POST'])
def send_all():
    message = request.form.get('message')
    if not message:
        return {'status': 'error', 'msg': 'Missing message'}, 400
    users = get_all_users()
    for u in users:
        save_message(u[0], 'admin', message)
        try:
            asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=int(u[0]), text=message), loop
            )
        except Exception as e:
            print(f"Telegram send error: {e}")
        socketio.emit('new_message', {'user_id': u[0]}, room='chat_' + str(u[0]))
    return {'status': 'ok', 'count': len(users)}

@app.route('/user/<int:user_id>/label', methods=['POST'])
def set_user_label(user_id):
    label = request.json.get('label')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE users SET label = ? WHERE user_id = ?', (label, user_id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'user_id': user_id, 'label': label})

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    join_room(room)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5001))

    # Flask-SocketIO আলাদা থ্রেডে
    flask_thread = Thread(target=lambda: socketio.run(app, port=port, debug=False, allow_unsafe_werkzeug=True), daemon=True)
    flask_thread.start()

    # Pyrogram bot আলাদা থ্রেডে (event loop সহ)
    def run_pyrogram_bot():
        print("Pyrogram bot running and waiting for join requests...")
        import asyncio
        asyncio.set_event_loop(asyncio.new_event_loop())
        pyro_app.run()

    pyrogram_thread = Thread(target=run_pyrogram_bot, daemon=True)
    pyrogram_thread.start()

    # python-telegram-bot main thread-এ
    print("Telegram bot running and waiting for user messages...")
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    application.run_polling() 
