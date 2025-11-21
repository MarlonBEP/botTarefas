#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------- CONFIG ----------
TOKEN = os.getenv("BOT_TOKEN")
# nome do grupo para mensagens (só texto usado nas mensagens)
GROUP_NAME = os.getenv("GROUP_NAME", "Organização Familia Porto Pedroso")
# timezone - America/Sao_Paulo (conforme você)
TZ = ZoneInfo("America/Sao_Paulo")
# horário diário de lembrete (15:00)
DAILY_HOUR = 15
DAILY_MINUTE = 0
# dia do mês para notificação mensal (6)
MONTHLY_DAY = 6
# checagem do job (segundos)
JOB_INTERVAL_SECONDS = 60
DB_FILE = "bot_data.db"
# ----------------------------

# ---------- DB helpers ----------
def init_db():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    # settings: key, value
    cur.execute(
        "CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)"
    )
    # tasks: id, text, owner, due (ISO), done (0/1), chat_id
    cur.execute(
        "CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, owner TEXT, due TEXT, done INTEGER DEFAULT 0, chat_id INTEGER)"
    )
    # shopping items: id, name, checked (0/1)
    cur.execute(
        "CREATE TABLE IF NOT EXISTS shopping (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, checked INTEGER DEFAULT 0)"
    )
    # savings: id (always 1), saved (float), goal (float)
    cur.execute(
        "CREATE TABLE IF NOT EXISTS savings (id INTEGER PRIMARY KEY CHECK (id=1), saved REAL DEFAULT 0, goal REAL DEFAULT 0)"
    )
    # ensure a single savings row exists
    cur.execute("INSERT OR IGNORE INTO savings (id, saved, goal) VALUES (1, 0, 0)")
    con.commit()
    con.close()

def db_get(k):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("SELECT v FROM settings WHERE k=?", (k,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

def db_set(k, v):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    con.commit()
    con.close()

# tasks
def add_task(text, owner, due, chat_id):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("INSERT INTO tasks (text, owner, due, chat_id) VALUES (?, ?, ?, ?)", (text, owner or "ambos", due, chat_id))
    con.commit()
    tid = cur.lastrowid
    con.close()
    return tid

def list_tasks(chat_id=None, only_pending=True):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    q = "SELECT id, text, owner, due, done FROM tasks"
    args = []
    if chat_id is not None:
        q += " WHERE chat_id=?"
        args.append(chat_id)
        if only_pending:
            q += " AND done=0"
    elif only_pending:
        q += " WHERE done=0"
    cur.execute(q, tuple(args))
    rows = cur.fetchall()
    con.close()
    return rows

def mark_done(task_id):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok

def remove_task(task_id):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok

# shopping
def add_item(name):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    try:
        cur.execute("INSERT INTO shopping (name, checked) VALUES (?, 0)", (name,))
        con.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    con.close()
    return ok

def list_items():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("SELECT id, name, checked FROM shopping ORDER BY id")
    rows = cur.fetchall()
    con.close()
    return rows

def toggle_item(item_id):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("SELECT checked FROM shopping WHERE id=?", (item_id,))
    r = cur.fetchone()
    if not r:
        con.close()
        return None
    new = 0 if r[0] else 1
    cur.execute("UPDATE shopping SET checked=? WHERE id=?", (new, item_id))
    con.commit()
    con.close()
    return new

def reset_shopping():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("UPDATE shopping SET checked=0")
    con.commit()
    con.close()

def clear_shopping():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("DELETE FROM shopping")
    con.commit()
    con.close()

# savings
def get_savings():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("SELECT saved, goal FROM savings WHERE id=1")
    r = cur.fetchone()
    con.close()
    return r if r else (0.0, 0.0)

def update_savings(add_amount=None, set_goal=None):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    if add_amount is not None:
        cur.execute("UPDATE savings SET saved = saved + ? WHERE id=1", (add_amount,))
    if set_goal is not None:
        cur.execute("UPDATE savings SET goal = ? WHERE id=1", (set_goal,))
    con.commit()
    cur.execute("SELECT saved, goal FROM savings WHERE id=1")
    r = cur.fetchone()
    con.close()
    return r

# ---------- UI helpers ----------
def main_menu_keyboard():
    kb = [
        [InlineKeyboardButton("🧹 Tarefas", callback_data="menu_tasks"),
         InlineKeyboardButton("🛒 Compras", callback_data="menu_shopping")],
        [InlineKeyboardButton("💰 Poupança", callback_data="menu_savings"),
         InlineKeyboardButton("⚙️ Config", callback_data="menu_config")],
    ]
    return InlineKeyboardMarkup(kb)

def tasks_keyboard(rows):
    kb = []
    for r in rows:
        tid, text, owner, due, done = r
        label = f"{'✅' if done else '⬜'} [{tid}] {text} ({owner})"
        kb.append([InlineKeyboardButton(label, callback_data=f"task_view:{tid}")])
    kb.append([InlineKeyboardButton("➕ Adicionar tarefa", callback_data="task_add"),
               InlineKeyboardButton("⏮ Voltar", callback_data="menu_back")])
    return InlineKeyboardMarkup(kb)

def shopping_keyboard(rows):
    kb = []
    for r in rows:
        iid, name, checked = r
        label = f"{'✅' if checked else '⬜'} {name}"
        kb.append([InlineKeyboardButton(label, callback_data=f"shop_toggle:{iid}")])
    kb.append([InlineKeyboardButton("➕ Adicionar item", callback_data="shop_add"),
               InlineKeyboardButton("🔁 Resetar mês", callback_data="shop_reset")])
    kb.append([InlineKeyboardButton("⏮ Voltar", callback_data="menu_back")])
    return InlineKeyboardMarkup(kb)

def savings_keyboard(saved, goal):
    pct = (saved / goal * 100) if goal and goal > 0 else 0
    kb = [
        [InlineKeyboardButton("➕ Adicionar valor", callback_data="save_add"),
         InlineKeyboardButton("🎯 Definir objetivo", callback_data="save_setgoal")],
        [InlineKeyboardButton("⏮ Voltar", callback_data="menu_back")]
    ]
    return InlineKeyboardMarkup(kb)

# ---------- Handlers ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = f"🏠 Bem-vindos ao painel *{GROUP_NAME}*.\nUse o menu para gerenciar tarefas, compras e poupança."
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # send main menu
    target = update.effective_message
    await target.reply_text(f"📋 Menu Principal — {GROUP_NAME}", reply_markup=main_menu_keyboard())

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    # main menu
    if data == "menu_tasks":
        rows = list_tasks(chat_id=chat_id)
        await query.message.edit_text("🧹 Tarefas pendentes:", reply_markup=tasks_keyboard(rows))
        return

    if data == "menu_shopping":
        rows = list_items()
        await query.message.edit_text("🛒 Lista de Compras (mensal):", reply_markup=shopping_keyboard(rows))
        return

    if data == "menu_savings":
        saved, goal = get_savings()
        txt = f"💰 Poupança\nSalvo: R${saved:.2f}\nObjetivo: R${goal:.2f}\nProgresso: { (saved/goal*100):.1f}% " if goal and goal>0 else f"💰 Poupança\nSalvo: R${saved:.2f}\nObjetivo: não definido"
        await query.message.edit_text(txt, reply_markup=savings_keyboard(saved, goal))
        return

    if data == "menu_config":
        await query.message.edit_text("⚙️ Configurações\nPor enquanto nada aqui. Volte em breve.", reply_markup=main_menu_keyboard())
        return

    if data == "menu_back":
        await query.message.edit_text(f"📋 Menu Principal — {GROUP_NAME}", reply_markup=main_menu_keyboard())
        return

    # tasks actions
    if data == "task_add":
        await query.message.reply_text("✏️ Envie a tarefa no formato:\n<descrição> |op=Nome (opcional) |due=YYYY-MM-DDTHH:MM (opcional)\nEx: Lavar louça |op=Marlon|due=2025-11-21T18:00")
        return

    if data.startswith("task_view:"):
        tid = int(data.split(":",1)[1])
        rows = [r for r in list_tasks(chat_id=chat_id, only_pending=False) if r[0]==tid]
        if not rows:
            await query.message.reply_text("Tarefa não encontrada.")
            return
        _, textt, owner, due, done = rows[0]
        done_label = "✅" if done else "⬜"
        txt = f"{done_label} [{tid}] {textt}\nOwner: {owner}\nDue: {due or '—'}"
        kb = [
            [InlineKeyboardButton("Marcar como feito", callback_data=f"task_done:{tid}"),
             InlineKeyboardButton("Remover", callback_data=f"task_remove:{tid}")],
            [InlineKeyboardButton("⏮ Voltar", callback_data="menu_tasks")]
        ]
        await query.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("task_done:"):
        tid = int(data.split(":",1)[1])
        ok = mark_done(tid)
        await query.message.reply_text("Marcado como feito." if ok else "Não achei essa tarefa.")
        # refresh tasks menu
        rows = list_tasks(chat_id=chat_id)
        await query.message.reply_text("🧹 Tarefas pendentes:", reply_markup=tasks_keyboard(rows))
        return

    if data.startswith("task_remove:"):
        tid = int(data.split(":",1)[1])
        ok = remove_task(tid)
        await query.message.reply_text("Removido." if ok else "Não achei essa tarefa.")
        rows = list_tasks(chat_id=chat_id)
        await query.message.reply_text("🧹 Tarefas pendentes:", reply_markup=tasks_keyboard(rows))
        return

    # shopping actions
    if data == "shop_add":
        await query.message.reply_text("✏️ Envie o nome do item para adicionar na lista de compras:")
        return

    if data.startswith("shop_toggle:"):
        iid = int(data.split(":",1)[1])
        new = toggle_item(iid)
        if new is None:
            await query.message.reply_text("Item não encontrado.")
        else:
            await query.message.reply_text("Marcado." if new else "Desmarcado.")
        rows = list_items()
        await query.message.reply_text("🛒 Lista de Compras (mensal):", reply_markup=shopping_keyboard(rows))
        return

    if data == "shop_reset":
        reset_shopping()
        await query.message.reply_text("✅ Lista zerada (itens marcados como não comprados).")
        rows = list_items()
        await query.message.reply_text("🛒 Lista de Compras (mensal):", reply_markup=shopping_keyboard(rows))
        return

    # savings actions
    if data == "save_add":
        await query.message.reply_text("✏️ Envie o valor que você quer adicionar (ex: 50.25):")
        return

    if data == "save_setgoal":
        await query.message.reply_text("✏️ Envie o objetivo de meta em reais (ex: 500):")
        return

# text message handler (catches user inputs for quick commands)
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    chat_id = update.effective_chat.id

    # quick command: /add style via plain text if user was told to send
    # Detect patterns:
    if "|" in txt or txt.lower().startswith("/add "):
        # try parse add task: descricao |op=Nome|due=YYYY...
        raw = txt
        if txt.lower().startswith("/add "):
            raw = txt[5:].strip()
        parts = raw.split("|")
        desc = parts[0].strip()
        owner = None
        due = None
        for p in parts[1:]:
            if p.strip().lower().startswith("op="):
                owner = p.split("=",1)[1].strip()
            if p.strip().lower().startswith("due="):
                due = p.split("=",1)[1].strip()
        tid = add_task(desc, owner, due, chat_id)
        await update.message.reply_text(f"✅ Tarefa adicionada: [{tid}] {desc} (owner: {owner or 'ambos'})")
        return

    # shopping add (when user previously pressed shop_add, simplest: accept any single-word send)
    # We can't manage full dialog state here but detect if message starts with "additem:" or user simply sends "item: X"
    if txt.lower().startswith("item:") or txt.lower().startswith("/item "):
        name = txt.split(":",1)[1].strip() if ":" in txt else txt[6:].strip()
        ok = add_item(name)
        await update.message.reply_text("Item adicionado." if ok else "Item já existe.")
        return

    # quick savings commands
    if txt.lower().startswith("addsave "):
        try:
            val = float(txt.split(None,1)[1].replace(",","."))
            saved, goal = update_savings(add_amount=val)
            await update.message.reply_text(f"✅ Adicionado R${val:.2f}. Total salvo: R${saved:.2f}")
        except Exception:
            await update.message.reply_text("Formato inválido. Use: addsave 50.25")
        return

    if txt.lower().startswith("setgoal "):
        try:
            val = float(txt.split(None,1)[1].replace(",","."))
            saved, goal = update_savings(set_goal=val)
            await update.message.reply_text(f"🎯 Objetivo definido: R${goal:.2f}")
        except Exception:
            await update.message.reply_text("Formato inválido. Use: setgoal 500")
        return

    # fallback: show menu
    await update.message.reply_text("Use o menu:", reply_markup=main_menu_keyboard())

# ---------- Scheduler job (checa a cada JOB_INTERVAL_SECONDS) ----------
async def periodic_jobs(context: ContextTypes.DEFAULT_TYPE):
    now_utc = datetime.now(tz=ZoneInfo("UTC"))
    now_local = now_utc.astimezone(TZ)
    chat_id = None
    # get saved group id if set
    gid = db_get("group_chat_id")
    if gid:
        try:
            chat_id = int(gid)
        except:
            chat_id = None

    # DAILY reminder at DAILY_HOUR:DAILY_MINUTE (once per day)
    last_daily = db_get("last_daily_sent")
    today_str = now_local.strftime("%Y-%m-%d")
    if (now_local.hour == DAILY_HOUR and now_local.minute == DAILY_MINUTE and last_daily != today_str):
        # send reminder with pending tasks and shopping summary
        if chat_id:
            tasks = list_tasks(chat_id=chat_id)
            tasks_txt = "\n".join([f"[{r[0]}] {r[1]} ({r[2]})" for r in tasks]) or "Nenhuma tarefa pendente."
            items = list_items()
            unchecked = [i for i in items if i[2]==0]
            shop_txt = "\n".join([f"- {i[1]}" for i in unchecked]) or "Nenhum item pendente."
            text = f"⏰ *Lembrete diário* — {GROUP_NAME}\n\n🧹 Tarefas pendentes:\n{tasks_txt}\n\n🛒 Itens de compras pendentes:\n{shop_txt}"
            await context.bot.send_message(chat_id=chat_id, text=text)
        db_set("last_daily_sent", today_str)

    # MONTHLY action on MONTHLY_DAY at 09:00 local (reset monthly shop and notify)
    last_month = db_get("last_monthly_sent")
    month_key = now_local.strftime("%Y-%m")
    if (now_local.day == MONTHLY_DAY and now_local.hour == 9 and (last_month != month_key)):
        if chat_id:
            reset_shopping()
            text = f"📅 *Lembrete mensal* — {GROUP_NAME}\nA lista de compras do mês foi reiniciada. Revisem e atualizem os itens que precisam."
            await context.bot.send_message(chat_id=chat_id, text=text)
        db_set("last_monthly_sent", month_key)

# ---------- utility to capture group id when bot is added or first message arrives ----------
async def capture_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        db_set("group_chat_id", str(chat.id))
    # just pass to menu
    await cmd_menu(update, context)

# ---------- main ----------
def main():
    init_db()
    if not TOKEN:
        print("ERROR: set BOT_TOKEN env var")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))

    # callbacks and messages
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    # catch when added to group or first message (to register group id)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, capture_group_id))

    # job queue - run periodic_jobs every JOB_INTERVAL_SECONDS
    app.job_queue.run_repeating(periodic_jobs, interval=JOB_INTERVAL_SECONDS, first=10)

    print("Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()
