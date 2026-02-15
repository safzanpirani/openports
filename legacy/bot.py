import logging
import asyncio
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from scanner import scan_network
import ipaddress
from dotenv import load_dotenv

load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Constants
# You can set this via environment variable or hardcode for testing (not recommended for production)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="Hello! I'm your scanner bot. Use /scan <ip/cidr> to scan for ComfyUI and Ollama."
    )

def parse_target(target: str):
    """Simple parser for single IP or CIDR"""
    try:
        # Check if CIDR
        network = ipaddress.ip_network(target, strict=False)
        # return list of string IPs
        return [str(ip) for ip in network.hosts()]
    except ValueError:
        pass
    
    try:
        # Check if single IP
        ip = ipaddress.ip_address(target)
        return [str(ip)]
    except ValueError:
        return None

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /scan <ip_or_cidr>")
        return

    target = context.args[0]
    ips = parse_target(target)
    
    if not ips:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Invalid IP or network: {target}")
        return

    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Scanning {len(ips)} IPs in {target}...")
    
    # Run the scan
    try:
        results = await scan_network(ips)
    except Exception as e:
        logging.error(f"Scan failed: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Scan error: {e}")
        return

    if not results:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="No ComfyUI or Ollama instances found.")
    else:
        msg = "<b>Found Instances:</b>\n"
        for res in results:
            msg += f"• {res['service']} at <code>{res['ip']}:{res['port']}</code>\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='HTML')

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set.")
        print("Export it: export TELEGRAM_BOT_TOKEN='your_token'")
        exit(1)
        
    application = ApplicationBuilder().token(TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    scan_handler = CommandHandler('scan', scan)
    
    application.add_handler(start_handler)
    application.add_handler(scan_handler)
    
    print("Bot is polling...")
    application.run_polling()
