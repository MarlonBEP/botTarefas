import os
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

TOKEN = os.environ.get("BOT_TOKEN")

def start(update, context):
    update.message.reply_text("Bot de tarefas ativado! Me envie atividades e eu organizo!")

def registrar(update, context):
    texto = update.message.text
    update.message.reply_text("Anotado! 👍")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, registrar))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
