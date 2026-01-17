import os
import time
import sqlite3
import logging
import asyncio
import random
import base64
import io

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv
import mercadopago
from fastapi import FastAPI, Request
import uvicorn

# ================= CONFIG =================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID") or 0)

START_VIDEO_URL = "https://files.catbox.moe/fr10m2.mp4"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mp = mercadopago.SDK(MP_ACCESS_TOKEN)
DB_PATH = "payments.db"

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id TEXT,
        plan TEXT,
        amount REAL,
        status TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()
    conn.close()

def save_payment(payment_id, user_id, plan, amount, status="pending"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO payments
    VALUES (?, ?, ?, ?, ?, ?)
    """, (str(payment_id), str(user_id), plan, amount, status, int(time.time())))
    conn.commit()
    conn.close()

# ================= TEXTOS =================
MAIN_TEXT = """🔥Vazados BR ofc.🇧🇷🔞
   
              ⚠️ÚNICO!
✅Grupo Com + de 36 mil vídeos de vazados Reais Brasileiros.

🔱Você Está Quase lá 💥
👇🏼Escolha Um Plano👇
"""

START_COUNTER = 135920
STOP_COUNTER = 137500
counter_value = START_COUNTER

PLANS = {
    "mensal": {"label": "💳 Mensal — R$13", "amount": 13.00},
    "vitalicio": {"label": "🔥 Vitalício — R$16", "amount": 16.00},
}

PROMO_CODES = {"THG100", "FLP100"}
awaiting_promo = {}
user_last_payment = {}
bot_app = None

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global counter_value
    counter_value = START_COUNTER

    keyboard = [
        [InlineKeyboardButton(PLANS["mensal"]["label"], callback_data="buy_mensal")],
        [InlineKeyboardButton(PLANS["vitalicio"]["label"], callback_data="buy_vitalicio")],
        [InlineKeyboardButton("🎟️ Código", callback_data="promo")],
        [InlineKeyboardButton("🔄 Já paguei", callback_data="check_payment")]
    ]

    await update.message.reply_video(video=START_VIDEO_URL)

    await update.message.reply_text(
        MAIN_TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    counter_msg = await update.message.reply_text(
        f"🔥🔞 *Membros Atuais 👥⬆:* {counter_value:,}".replace(",", "."),
        parse_mode="Markdown"
    )

    asyncio.create_task(counter_task(context, counter_msg.chat_id, counter_msg.message_id))

# ================= CONTADOR =================
async def counter_task(context, chat_id, message_id):
    global counter_value
    while counter_value < STOP_COUNTER:
        await asyncio.sleep(1.8)
        counter_value += random.randint(1, 3)
        if counter_value > STOP_COUNTER:
            counter_value = STOP_COUNTER
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"🔥🔞 *Membros Atuais 👥⬆:* {counter_value:,}".replace(",", "."),
                parse_mode="Markdown"
            )
        except:
            break

# ================= PAGAMENTO =================
async def process_payment(update, context, plan_key):
    plan = PLANS[plan_key]
    user_id = update.effective_user.id

    data = {
        "transaction_amount": plan["amount"],
        "description": f"{plan_key.upper()} user:{user_id}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@mail.com"},
    }

    result = mp.payment().create(data)
    response = result.get("response", {})
    payment_id = response.get("id")

    qr = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
    qr_b64 = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64")

    save_payment(payment_id, user_id, plan_key, plan["amount"])
    user_last_payment[user_id] = payment_id

    msg = update.callback_query.message

    await msg.reply_text(
        f"💰 *{plan['label']}*\n\n🪙 *PIX Copia e Cola:*\n`{qr}`",
        parse_mode="Markdown"
    )

    if qr_b64:
        img = io.BytesIO(base64.b64decode(qr_b64))
        await msg.reply_photo(img)

# ================= CHECK =================
async def check_payment_status(update, context):
    uid = update.effective_user.id

    if uid not in user_last_payment:
        await update.callback_query.message.reply_text(
            "❌ "
        )
        return

    payment_id = user_last_payment[uid]
    info = mp.payment().get(payment_id)
    status = info.get("response", {}).get("status")

    if status == "approved":
        invite = await bot_app.bot.create_chat_invite_link(GROUP_CHAT_ID, member_limit=1)
        await update.callback_query.message.reply_text(
            f"✅ *Pagamento aprovado!*\n{invite.invite_link}",
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.message.reply_text(
            f"⏳ Status atual: *{status}*",
            parse_mode="Markdown"
        )

# ================= BUTTON =================
async def button(update: Update, context):
    q = update.callback_query
    await q.answer()

    if q.data == "buy_mensal":
        await process_payment(update, context, "mensal")

    elif q.data == "buy_vitalicio":
        await process_payment(update, context, "vitalicio")

    elif q.data == "promo":
        awaiting_promo[q.from_user.id] = True
        await q.message.reply_text("🎟️ Envie o código:")

    elif q.data == "check_payment":
        await check_payment_status(update, context)

# ================= PROMO =================
async def handle_message(update: Update, context):
    uid = update.effective_user.id
    if not awaiting_promo.get(uid):
        return

    awaiting_promo[uid] = False
    code = update.message.text.strip().upper()

    if code in PROMO_CODES:
        invite = await context.bot.create_chat_invite_link(GROUP_CHAT_ID, member_limit=1)
        await update.message.reply_text(invite.invite_link)
    else:
        await update.message.reply_text("❌ Código inválido.")

# ================= FASTAPI =================
app = FastAPI()

@app.post("/webhook/mp")
async def mp_webhook(request: Request):
    return {"status": "disabled"}

# ================= MAIN =================
def main():
    init_db()

    global bot_app
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(button))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop = asyncio.get_event_loop()
    loop.create_task(bot_app.run_polling())

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    main()
