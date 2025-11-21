import os
import sqlite3
import logging
from datetime import datetime, time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ------------------------------- LOG -----------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------------- CONFIG --------------------------------------

TOKEN = os.getenv("BOT_TOKEN")  # configure no Railway
DB_PATH = "database.db"

GROUP_NAME = "Organização Familia Porto Pedroso"

DAILY_HOUR = 15
MONTHLY_DAY = 6

# Quanto queremos guardar por mês (meta)
META_MENSAL = 1000

# Intervalo dos periodic jobs (Railway não gosta de cron real, então simulamos)
JOB_INTERVAL_SECONDS = 60  # a cada 1 minuto

# ------------------------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------------------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS financeiro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT,
            valor REAL,
            data TEXT
        )
    """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS grupos (
            id INTEGER PRIMARY KEY,
            group_id INTEGER
        )
        """
    )

    conn.commit()
    conn.close()

def add_finance(tipo, valor):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO financeiro (tipo, valor, data) VALUES (?, ?, ?)",
        (tipo, valor, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

def get_resumo():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT SUM(valor) FROM financeiro WHERE tipo='entrada'")
    entradas = c.fetchone()[0] or 0

    c.execute("SELECT SUM(valor) FROM financeiro WHERE tipo='saida'")
    saidas = c.fetchone()[0] or 0

    conn.close()

    guardado = entradas - saidas

    return entradas, saidas, guardado

def save_group_id(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM grupos")
    c.execute("INSERT INTO grupos (id, group_id) VALUES (1, ?)", (chat_id,))
    conn.commit()
    conn.close()

def get_group_id():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM grupos WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ------------------------------------------------------------------------------
#   BOT LOGIC
# ------------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
    f"""Bem vindo ao {GROUP_NAME}!
Use /menu para ver as opções."""
)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Adicionar Entrada", callback_data="add_entrada")],
        [InlineKeyboardButton("Adicionar Saída", callback_data="add_saida")],
        [InlineKeyboardButton("Resumo Atual", callback_data="resumo")],
    ]
    await update.message.reply_text("Escolha uma opção:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "add_entrada":
        await query.message.reply_text("Digite o valor da ENTRADA:")
        context.user_data["mode"] = "entrada"
    elif data == "add_saida":
        await query.message.reply_text("Digite o valor da SAÍDA:")
        context.user_data["mode"] = "saida"
    elif data == "resumo":
        entradas, saidas, guardado = get_resumo()
        await query.message.reply_text(
            f"Entradas: R$ {entradas:.2f}\n"
            f"Saídas: R$ {saidas:.2f}\n"
            f"Guardado: R$ {guardado:.2f}\n"
            f"Meta: R$ {META_MENSAL:.2f}"
        )

    await query.answer()

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "mode" in context.user_data:
        try:
            valor = float(update.message.text.replace(",", "."))
        except:
            await update.message.reply_text("Valor inválido. Tenta de novo.")
            return

        tipo = context.user_data["mode"]
        add_finance(tipo, valor)

        await update.message.reply_text(f"{tipo.capitalize()} registrada com sucesso!")

        del context.user_data["mode"]

async def capture_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            save_group_id(update.message.chat_id)
            await update.message.reply_text("Grupo registrado com sucesso!")

# ------------------------------------------------------------------------------
#   NOTIFICAÇÕES AUTOMÁTICAS
# ------------------------------------------------------------------------------

async def periodic_jobs(context: ContextTypes.DEFAULT_TYPE):
    group_id = get_group_id()
    if not group_id:
        return

    now = datetime.now()

    # diária
    if now.hour == DAILY_HOUR:
        await context.bot.send_message(
            group_id, "Lembrete diário: organizem as finanças hoje!"
        )

    # mensal
    if now.day == MONTHLY_DAY and now.hour == DAILY_HOUR:
        entradas, saidas, guardado = get_resumo()
        await context.bot.send_message(
            group_id,
            f"Resumo mensal do dia {MONTHLY_DAY}:\n"
            f"Entradas: {entradas:.2f}\n"
            f"Saídas: {saidas:.2f}\n"
            f"Guardado: {guardado:.2f}\n"
            f"Meta: {META_MENSAL:.2f}",
        )

# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    init_db()

    if not TOKEN:
        print("ERRO: faltou BOT_TOKEN no Railway!")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    job_queue = app.job_queue

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, capture_group_id))

    # inicia periodic job
    job_queue.run_repeating(periodic_jobs, interval=JOB_INTERVAL_SECONDS, first=10)

    print("Bot rodando bonitão...")
    app.run_polling()

if __name__ == "__main__":
    main()
