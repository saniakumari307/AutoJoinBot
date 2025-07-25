import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatJoinRequestHandler, ContextTypes, filters as tg_filters
)
from config import BOT_TOKEN, CHANNEL_ID, CHANNEL_URL
from db import add_user, save_message
import datetime

# --- Handlers from previous api.py ---

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
    if message.text:
        save_message(user.id, 'user', message.text)

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
    welcome = (
        "🎉 Thank you for joining our channel!\n\n"
        "You are now a full member. You can chat with me here anytime."
    )
    await context.bot.send_message(chat_id=user.id, text=welcome)
    # Optionally, notify admin (bot owner)
    # try:
    #     await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"User {user.full_name} (@{user.username}) [{user.id}] has joined the channel and can now chat.")
    # except Exception:
    #     pass

async def approve_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.chat_join_request.approve()
    user = update.chat_join_request.from_user
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    username = user.username or ''
    join_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invite_link = update.chat_join_request.invite_link.invite_link if update.chat_join_request.invite_link else None
    add_user(user.id, full_name, username, join_date, invite_link)
    try:
        await context.bot.send_message(user.id, "🎉 Welcome! You are now a member. Feel free to chat with me.")
    except Exception as e:
        print(f"Failed to send welcome message: {e}")

# --- Application Setup ---

application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler('start', start))
application.add_handler(CallbackQueryHandler(channel_joined_callback, pattern='^joined_channel$'))
application.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, user_message_handler))
application.add_handler(ChatJoinRequestHandler(approve_join))

if __name__ == '__main__':
    print("Telegram bot running and waiting for user messages...")
    asyncio.set_event_loop(asyncio.new_event_loop())
    application.run_polling() 