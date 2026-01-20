import os
import time
import sqlite3
import logging
import asyncio
import random
import base64
import io

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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

# ===================== CONFIG =====================
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID") or 0)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mp = mercadopago.SDK(MP_ACCESS_TOKEN)
DB_PATH = "payments.db"

# ===================== DATABASE =====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        amount REAL,
        status TEXT,
        created_at INTEGER
    )
    """)
    conn.commit()
    conn.close()

def save_payment(payment_id, user_id, amount, status="pending"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO payments(payment_id, user_id, amount, status, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (str(payment_id), str(user_id), float(amount), status, int(time.time())))
    conn.commit()
    conn.close()

# ===================== TEXTOS =====================
HEADER_TEXT = """🜂 ⚛ Bem-vindo à irmandade mais foda do Brasil.
Aqui não existe Gados — só homens que Pegam Mulheres, Facil.💪

⚠️ Aviso rápido:
Isso não é grátis. O acesso custa R$10 — e existe um motivo pra isso.
"""

MAIN_TEXT = """
🔱 Aqui eu te ensino:
🔞 Como se comportar.
🔞 Como falar perto dela.
😈Oque Falar Pra Ela..
❤️‍🔥A psicologia por trás dos perfumes que acende desejos nas mentes femininas.
😈
E muito mais...

⚠️ Usando:
⚜ Psicologia Obscura
🌀 Manipulação Emocional 🚷
🧠 Neurolinguística
📘 Princípios de Persuasão
🏹 Elaboração de Elogios Subjetivos
⚠️ Temos Conteúdos proibidos em +24 países 
etc..
📲 2Mil Mensagens Prontas Baseadas em Psicologia e Manipulação, Faz ela responder na mesma hora.🔞

🔥Faça Qualquer Pessoa Comer Na sua mão. E Ficar Louca pra te dar,😈🔞

Para manter tudo funcionando e Ajudar nas Manutenções, cobramos apenas um valor simbólico de R$10.
Quem entra aqui não paga… investe em si mesmo🔞 """

# ===================== PLANO =====================
PLANS = {
    "vip": {"label": "🔥 Acesso VIP", "amount": 10.00}
}

awaiting_promo = {}
bot_app = None
user_last_payment = {}

# ===================== START =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Por que não é grátis?", callback_data="why_not_free")]
    ])

    await update.message.reply_text(
        HEADER_TEXT,
        reply_markup=keyboard
    )

# ===================== PAYMENT =====================
async def process_payment(update, context):
    user_id = update.effective_user.id
    amount = PLANS["vip"]["amount"]

    data = {
        "transaction_amount": float(amount),
        "description": f"Acesso VIP user:{user_id}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@mail.com"},
    }

    result = mp.payment().create(data)
    response = result.get("response", {})
    payment_id = response.get("id")

    qr = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
    qr_b64 = response.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64")

    save_payment(payment_id, user_id, amount)
    user_last_payment[user_id] = payment_id

    msg = update.callback_query.message

    await msg.reply_text(
        f"""✅ Falta só 1 passo

💰 Valor: R$ {amount:.2f}

🪙 PIX Copia e Cola:
`{qr}`""",
        parse_mode="Markdown"
    )

    if qr_b64:
        img = io.BytesIO(base64.b64decode(qr_b64))
        await msg.reply_photo(img)

# ===================== CHECK PAYMENT =====================
async def check_payment(update, context):
    uid = update.effective_user.id
    payment_id = user_last_payment.get(uid)

    if not payment_id:
        await update.callback_query.message.reply_text(
            "❌ Nenhum pagamento encontrado."
        )
        return

    info = mp.payment().get(payment_id)
    status = info.get("response", {}).get("status")

    if status == "approved":
        invite = await bot_app.bot.create_chat_invite_link(
            GROUP_CHAT_ID,
            member_limit=1
        )
        await update.callback_query.message.reply_text(
            f"🎉 Pagamento confirmado!\n{invite.invite_link}"
        )
    else:
        await update.callback_query.message.reply_text(
            f"⏳ Status do pagamento: {status}"
        )

# ===================== BUTTON HANDLER =====================
async def button(update: Update, context):
    q = update.callback_query
    await q.answer()

    if q.data == "why_not_free":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Quero Entrar!!", callback_data="confirm")]
        ])
        await q.message.reply_text(MAIN_TEXT, reply_markup=keyboard)
        return

    if q.data == "confirm":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Liberar Acesso!", callback_data="pay")],
            [InlineKeyboardButton("❌ Vou sair", callback_data="exit")]
        ])
        await q.message.reply_text(
            "⚠️ Último aviso:\nEsse acesso não é pra curiosos.",
            reply_markup=keyboard
        )
        return

    if q.data == "pay":
        await process_payment(update, context)
        return

    if q.data == "exit":
        await q.message.reply_text(
            "Tudo certo. Esse acesso não aparece duas vezes."
        )
        return

# ===================== FASTAPI =====================
app = FastAPI()

@app.post("/webhook/mp")
async def mp_webhook(request: Request):
    return {"status": "ok"}

# ===================== MAIN =====================
def main():
    init_db()

    global bot_app
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(button))

    loop = asyncio.get_event_loop()
    loop.create_task(bot_app.run_polling())

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
