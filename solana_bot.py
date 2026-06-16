"""
Simple Solana Telegram Bot
--------------------------
A beginner-friendly Telegram bot that shows Solana token prices/info
and has basic buy/sell buttons (UI only - no real wallet connected by default).

SETUP STEPS:
1. Install dependencies:  pip install python-telegram-bot requests
2. Get your Telegram Bot Token from @BotFather on Telegram
3. Replace BOT_TOKEN below with your token
4. Run:  python solana_bot.py
"""

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
# 🔑 REPLACE THIS WITH YOUR BOT TOKEN FROM @BotFather
# ──────────────────────────────────────────────
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"


# ──────────────────────────────────────────────
# Fetch token info from DexScreener (free, no API key needed)
# ──────────────────────────────────────────────
def get_token_info(contract_address: str) -> dict | None:
    """
    Fetches token data from DexScreener for a Solana contract address.
    Returns a dict with token info, or None if not found.
    """
    url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        pairs = data.get("pairs")
        if not pairs:
            return None
        # Pick the pair with the highest liquidity
        pair = sorted(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
        return pair
    except Exception:
        return None


def format_number(n) -> str:
    """Formats large numbers nicely (e.g. 1200000 → $1.2M)"""
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
    """Builds a nicely formatted message from token pair data."""
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


# ──────────────────────────────────────────────
# Bot command: /start
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Lookup Token", callback_data="lookup")],
        [InlineKeyboardButton("💰 My Wallet", callback_data="wallet")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to *SolBot* — your simple Solana trading assistant!\n\n"
        "Paste any Solana token contract address to get price info and trade options.\n\n"
        "Or choose an option below:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


# ──────────────────────────────────────────────
# Bot command: /help
# ──────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use SolBot:*\n\n"
        "1️⃣ Paste a Solana token contract address in the chat\n"
        "2️⃣ The bot will fetch live price & market info\n"
        "3️⃣ Tap Buy or Sell to place a trade (wallet required)\n\n"
        "Commands:\n"
        "/start — Main menu\n"
        "/help  — This message\n"
        "/wallet — View your wallet info\n\n"
        "⚠️ *This is a demo bot. Real trades require wallet integration.*",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# Bot command: /wallet
# ──────────────────────────────────────────────
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💼 *Your Wallet*\n\n"
        "🔗 Address: `Not connected`\n"
        "💰 SOL Balance: —\n\n"
        "To connect a wallet, you would integrate a Solana wallet library here.\n"
        "_(For a real bot, you'd generate or import a Solana keypair.)_",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────────
# Handle inline button presses
# ──────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lookup":
        await query.message.reply_text(
            "🔍 Paste a Solana token contract address and I'll look it up for you!"
        )

    elif data == "wallet":
        await query.message.reply_text(
            "💼 *Your Wallet*\n\n"
            "🔗 Address: `Not connected`\n"
            "💰 SOL Balance: —\n\n"
            "_(Wallet integration coming soon!)_",
            parse_mode="Markdown",
        )

    elif data == "help":
        await query.message.reply_text(
            "📖 Paste any Solana token contract address in the chat to get live price info!\n\n"
            "Example address:\n`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`\n(USDC on Solana)",
            parse_mode="Markdown",
        )

    elif data.startswith("buy:"):
        token_symbol = data.split(":")[1]
        await query.message.reply_text(
            f"🟢 *Buy {token_symbol}*\n\n"
            "In a full bot, you would:\n"
            "1. Enter the SOL amount\n"
            "2. Confirm the swap\n"
            "3. The bot routes through Jupiter DEX\n\n"
            "⚠️ *Wallet not connected. This is a demo.*",
            parse_mode="Markdown",
        )

    elif data.startswith("sell:"):
        token_symbol = data.split(":")[1]
        await query.message.reply_text(
            f"🔴 *Sell {token_symbol}*\n\n"
            "In a full bot, you would:\n"
            "1. Enter the token amount\n"
            "2. Confirm the swap\n"
            "3. The bot routes through Jupiter DEX\n\n"
            "⚠️ *Wallet not connected. This is a demo.*",
            parse_mode="Markdown",
        )

    elif data.startswith("refresh:"):
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            msg = format_token_message_with_keyboard(pair, address, symbol)
            await query.message.edit_text(
                msg["text"], parse_mode="Markdown", reply_markup=msg["markup"]
            )
        else:
            await query.message.reply_text("⚠️ Could not refresh token data.")


def format_token_message_with_keyboard(pair, address, symbol):
    """Returns formatted text + keyboard for a token lookup."""
    text = build_token_message(pair)
    keyboard = [
        [
            InlineKeyboardButton(f"🟢 Buy {symbol}", callback_data=f"buy:{symbol}"),
            InlineKeyboardButton(f"🔴 Sell {symbol}", callback_data=f"sell:{symbol}"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    return {"text": text, "markup": markup}


# ──────────────────────────────────────────────
# Handle plain text messages (contract address lookup)
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Basic Solana address check (32-44 chars, base58-ish)
    if 32 <= len(text) <= 44 and text.isalnum():
        await update.message.reply_text("🔍 Looking up token info...")
        pair = get_token_info(text)

        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            result = format_token_message_with_keyboard(pair, text, symbol)
            await update.message.reply_text(
                result["text"],
                parse_mode="Markdown",
                reply_markup=result["markup"],
                disable_web_page_preview=True,
            )
        else:
            await update.message.reply_text(
                "❌ Token not found on DexScreener.\n\n"
                "Make sure you pasted a valid Solana token contract address."
            )
    else:
        await update.message.reply_text(
            "👋 Paste a Solana token contract address to get started!\n"
            "Or type /help for instructions."
        )


# ──────────────────────────────────────────────
# Main — run the bot
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 SolBot is starting...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()
