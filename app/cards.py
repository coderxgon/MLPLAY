"""
MLPlay canvas engine — HD, energetic card images powered by Pillow.
Every card (welcome, player profile, referrals, match lineups, fight
scenes, results, banners, hero portraits) is generated here. Admins can
restyle by uploading a custom logo / hero portraits.
"""
import io
import os
import random
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import FONTS_DIR, DATA_DIR

# ---------------------------------------------------------------- palette --
BG_TOP = (17, 12, 44)
BG_MID = (36, 20, 66)
BG_BOT = (10, 8, 28)
PURPLE = (124, 58, 237)
PINK = (236, 72, 153)
CYAN = (34, 211, 238)
GOLD = (251, 191, 36)
GREEN = (52, 211, 153)
RED = (244, 63, 94)
BLUE = (59, 88, 255)
WHITE = (255, 255, 255)
MUTED = (196, 181, 253)

# ---------------------------------------------------------------- fonts ----
_FONT_FILES = [
    ("Poppins-Bold.ttf", "https://raw.githubusercontent.com/googlefonts/poppins/main/fonts/ttf/Poppins-Bold.ttf"),
    ("Poppins-SemiBold.ttf", "https://raw.githubusercontent.com/googlefonts/poppins/main/fonts/ttf/Poppins-SemiBold.ttf"),
    ("Poppins-Medium.ttf", "https://raw.githubusercontent.com/googlefonts/poppins/main/fonts/ttf/Poppins-Medium.ttf"),
    ("Poppins-Regular.ttf", "https://raw.githubusercontent.com/googlefonts/poppins/main/fonts/ttf/Poppins-Regular.ttf"),
    ("Poppins-ExtraBold.ttf", "https://raw.githubusercontent.com/googlefonts/poppins/main/fonts/ttf/Poppins-ExtraBold.ttf"),
]

_font_fetched = False


def fetch_fonts(force: bool = False) -> None:
    global _font_fetched
    if _font_fetched and not force:
        return
    _font_fetched = True
    for fname, url in _FONT_FILES:
        path = os.path.join(FONTS_DIR, fname)
        if os.path.exists(path):
            continue
        try:
            urllib.request.urlretrieve(url, path, timeout=15)
        except Exception:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def _font_path(name: str) -> str:
    path = os.path.join(FONTS_DIR, name)
    return path if os.path.exists(path) else ""


def F(size: int, weight: str = "medium"):
    fetch_fonts()
    mapping = {
        "bold": _font_path("Poppins-Bold.ttf"),
        "ebold": _font_path("Poppins-ExtraBold.ttf") or _font_path("Poppins-Bold.ttf"),
        "semibold": _font_path("Poppins-SemiBold.ttf") or _font_path("Poppins-Bold.ttf"),
        "medium": _font_path("Poppins-Medium.ttf") or _font_path("Poppins-SemiBold.ttf") or _font_path("Poppins-Bold.ttf"),
        "regular": _font_path("Poppins-Regular.ttf") or _font_path("Poppins-Medium.ttf"),
    }
    path = mapping.get(weight, "")
    fallback_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    if not path:
        for c in fallback_candidates:
            if os.path.exists(c):
                path = c
                break
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# ---------------------------------------------------------------- helpers --
def _hex(c) -> tuple:
    c = str(c).lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _canvas(w, h, top=BG_TOP, mid=BG_MID, bot=BG_BOT):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        if t < 0.5:
            c = _lerp(top, mid, t * 2)
        else:
            c = _lerp(mid, bot, (t - 0.5) * 2)
        for x in range(w):
            px[x, y] = c
    vign = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vign)
    vd.ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    vign = vign.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGB", (w, h), (4, 2, 14))
    img = Image.composite(dark, img, vign.point(lambda p: 255 - p // 2))
    return img


def _glow(img, cx, cy, radius, color, alpha=120):
    layer = Image.new("RGB", img.size, color)
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=alpha)
    mask = mask.filter(ImageFilter.GaussianBlur(max(8, radius // 2)))
    img.paste(Image.composite(layer, img, mask), (0, 0), mask)


def _banner_line(img, y, color=PINK):
    """Glowing horizontal divider (brightest in the middle)."""
    w, h = img.size
    line = Image.new("RGB", (w, 10))
    ld = ImageDraw.Draw(line)
    for x in range(w):
        t = abs(x / max(1, w - 1) - 0.5) * 2  # 1 at edges -> 0 at center
        c = _lerp(color, BG_TOP, t * 0.55)
        ld.line([(x, 0), (x, 9)], fill=c)
    line = line.filter(ImageFilter.GaussianBlur(2))
    img.paste(line, (0, y - 5))


def _rounded(draw, box, radius, fill=None, outline=None, width=0):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _sparkles(draw, w, h, n=26, seed=7):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        s = rnd.choice([2, 3, 4])
        color = rnd.choice([GOLD, CYAN, PINK, WHITE])
        draw.line([(x, y - s), (x, y + s)], fill=color, width=1)
        draw.line([(x - s, y), (x + s, y)], fill=color, width=1)
    for _ in range(n // 2):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        r = rnd.randint(1, 2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)


def _text(draw, xy, text, size, weight="medium", fill=WHITE, anchor="mm", max_w=None):
    f = None
    if max_w:
        s = size
        while s > 16:
            f = F(s, weight)
            if draw.textlength(str(text), font=f) <= max_w:
                break
            s -= 2
    if f is None:
        f = F(size, weight)
    draw.text(xy, str(text), font=f, fill=fill, anchor=anchor)


def _avatar(draw, cx, cy, r, initials, c1=(124, 58, 237), c2=(236, 72, 153)):
    for i in range(r, 0, -3):
        t = i / r
        draw.ellipse([cx - i, cy - i, cx + i, cy + i], fill=_lerp(c1, c2, t))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD, width=4)
    _text(draw, (cx, cy), (initials or "?")[0].upper(), int(r * 0.66), "ebold", WHITE)


def _logo(draw, cx, cy, r=52):
    for i in range(r, 0, -3):
        t = i / r
        draw.ellipse([cx - i, cy - i, cx + i, cy + i], fill=_lerp(PURPLE, PINK, t))
    bolt = [(cx - 12, cy - r + 12), (cx + 8, cy - 16), (cx - 1, cy - 2), (cx + 15, cy - 2),
            (cx + 12, cy + 5), (cx - 4, cy + 28), (cx + 2, cy + 8), (cx - 12, cy + 8)]
    draw.polygon(bolt, fill=GOLD)


def _footer(img, h, text="⚡ PLAY HARD • WIN BIGGER ⚡"):
    w = img.size[0]
    _banner_line(img, h - 64)
    _text(ImageDraw.Draw(img), (w / 2, h - 32), text, 22, "semibold", MUTED,
          max_w=w - 80)


def _stat_tile(draw, x, y, wdt, hgt, label, value, accent):
    _rounded(draw, [x, y, x + wdt, y + hgt], 22, (28, 22, 60))
    _rounded(draw, [x, y, x + wdt, y + 6], 3, accent)
    _text(draw, (x + wdt / 2, y + 30), str(label).upper(), 17, "medium", MUTED, max_w=wdt - 24)
    _text(draw, (x + wdt / 2, y + 66), str(value), 28, "ebold", WHITE, max_w=wdt - 24)


def _paste_logo(img, w, top=96, size=64):
    logo_path = os.path.join(DATA_DIR, "uploads", "logo", "logo.png")
    if os.path.exists(logo_path):
        try:
            lg = Image.open(logo_path).convert("RGBA")
            lg.thumbnail((size * 2, size * 2), Image.LANCZOS)
            img.paste(lg, (w // 2 - lg.width // 2, top - lg.height // 2), lg)
            return
        except Exception:
            pass
    d = ImageDraw.Draw(img)
    _logo(d, w / 2, top, size)


# ---------------------------------------------------------------- cards ----
def welcome_card(fullname: str = "", username: str = "", rank_name: str = "Warrior",
                 is_new: bool = True) -> bytes:
    w, h = 1080, 1350
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    _glow(img, w * 0.5, h * 0.16, 380, PURPLE, 110)
    _glow(img, w * 0.12, h * 0.75, 300, PINK, 70)
    _glow(img, w * 0.92, h * 0.9, 320, CYAN, 55)
    _sparkles(d, w, h)

    _paste_logo(img, w, top=150, size=86)
    _text(d, (w / 2, 340), "MLPLAY", 96, "ebold", WHITE)
    _text(d, (w / 2, 406), "ENTER THE ARENA", 30, "semibold", GOLD)

    _banner_line(img, 460)
    _text(d, (w / 2, 550), "3 EPIC GAMES", 32, "ebold", WHITE)
    _text(d, (w / 2, 602), "RANK MATCH   •   WHO'S THE MVP?   •   HEROL", 24, "medium", MUTED)

    chips = [("BETS UP TO ₱50,000", PURPLE), ("LIVE MATCH EVERY 2 MIN", CYAN), ("DAILY & PROMO REWARDS", GOLD)]
    cx = 190
    for label, acc in chips:
        _rounded(d, [cx - 165, 668, cx + 165, 744], 38, (32, 26, 66))
        _rounded(d, [cx - 165, 668, cx + 165, 744], 38, None, outline=acc, width=2)
        _text(d, (cx, 706), label, 20, "semibold", WHITE, max_w=310)
        cx += 350

    _text(d, (w / 2, 862), "READY TO CLAIM YOUR GLORY?" if is_new
          else ("WELCOME BACK, " + fullname.upper() if fullname else "WELCOME BACK!"),
          28, "semibold", MUTED, max_w=980)

    _rounded(d, [w / 2 - 280, 946, w / 2 + 280, 1064], 59, PURPLE)
    _rounded(d, [w / 2 - 280, 946, w / 2 + 280, 1064], 59, None, outline=GOLD, width=4)
    _text(d, (w / 2, 1005), "REGISTER TO MLPLAY" if is_new else "OPEN YOUR MENU",
          32, "ebold", WHITE)

    _text(d, (w / 2, 1166), "YOUR CURRENT RANK", 20, "medium", MUTED)
    _rounded(d, [w / 2 - 180, 1192, w / 2 + 180, 1262], 35, (36, 26, 70))
    _text(d, (w / 2, 1227), f"★ {rank_name.upper()} ★", 28, "ebold", GOLD)

    _footer(img, h)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def profile_card(fullname: str, username: str, rank: dict, balance: float, turnover: float,
                 rewards: float, deposited: float, withdrawn: float, valid_bets: int,
                 joined: str, type_label: str, inviter: str, ref_link: str,
                 frozen: bool = False, bind_label: str = "") -> bytes:
    w, h = 1080, 1620
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    _glow(img, w * 0.5, 170, 360, PURPLE, 120)
    _glow(img, w * 0.9, h * 0.85, 300, PINK, 60)
    _sparkles(d, w, h)

    _paste_logo(img, w, top=80, size=50)
    _text(d, (w / 2, 180), "YOUR PLAYER CARD", 30, "ebold", GOLD)
    _banner_line(img, 212)

    initials = "".join(x[0] for x in str(fullname).split()[:2]).upper() or "P"
    _avatar(d, w / 2, 332, 92, initials, _hex("#7C3AED"), _hex("#EC4899"))
    _text(d, (w / 2, 470), fullname or "Player", 42, "ebold", WHITE, max_w=940)
    _text(d, (w / 2, 526), f"@{username}" if username else f"TG ID {0}", 25, "medium", MUTED)

    _rounded(d, [w / 2 - 260, 564, w / 2 - 12, 636], 36, (44, 30, 80))
    _text(d, (w / 2 - 136, 600), f"{rank['tier']}  {rank['name']}", 25, "ebold", GOLD)
    _rounded(d, [w / 2 + 12, 564, w / 2 + 260, 636], 36, (46, 26, 34) if type_label == "ADMIN" else (30, 26, 60))
    _text(d, (w / 2 + 136, 600), "ADMIN" if type_label == "ADMIN" else "PLAYER", 22, "semibold", WHITE)

    stats = [
        ("BALANCE", f"₱{balance:,.2f}", GREEN),
        ("TURNOVER", f"₱{turnover:,.2f}", CYAN),
        ("REWARDS", f"₱{rewards:,.2f}", GOLD),
        ("DEPOSITS", f"₱{deposited:,.2f}", PURPLE),
        ("WITHDRAWN", f"₱{withdrawn:,.2f}", PINK),
        ("JOINED", joined, MUTED),
    ]
    y0 = 706
    for i, (lab, val, acc) in enumerate(stats):
        x = 60 + (i % 2) * 510
        y = y0 + (i // 2) * 148
        _stat_tile(d, x, y, 460, 118, lab, val, acc)

    rows = [
        ("WALLET", bind_label if bind_label else "NOT BOUND — BIND FOR ₱30"),
        ("VALID BETS", str(valid_bets)),
        ("INVITER", inviter if inviter else "—"),
        ("REFERRAL LINK", ref_link[:50] + ("…" if len(ref_link) > 50 else "")),
    ]
    ry = 1140
    for lab, val in rows:
        _rounded(d, [60, ry, 1020, ry + 74], 20, (24, 20, 54))
        _text(d, (130, ry + 37), lab.upper(), 18, "semibold", MUTED, anchor="lm")
        _text(d, (620, ry + 37), val, 19, "semibold", WHITE, anchor="lm", max_w=385)
        ry += 88

    if frozen:
        _rounded(d, [60, h - 216, 1020, h - 142], 20, (60, 24, 34))
        _text(d, (w / 2, h - 179), "BALANCE FROZEN — CONTACT SUPPORT", 21, "ebold", RED)

    _footer(img, h, f"★ {rank['name'].upper()} • MLPLAY PLAYER CARD ★")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def referral_card(rank_name: str, rewards: float, invites: int, valid_invites: int,
                  ref_link: str, top5: list) -> bytes:
    w, h = 1080, 1500
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    _glow(img, w * 0.5, 160, 340, PINK, 100)
    _glow(img, w * 0.15, h * 0.8, 280, PURPLE, 70)
    _sparkles(d, w, h)

    _paste_logo(img, w, top=80, size=48)
    _text(d, (w / 2, 176), "REFERRAL REWARDS", 30, "ebold", GOLD)
    _banner_line(img, 206)

    _rounded(d, [80, 248, 1000, 420], 30, (70, 26, 90))
    _rounded(d, [80, 248, 1000, 420], 30, None, outline=GOLD, width=3)
    _text(d, (w / 2, 300), "REFERRAL REWARDS BALANCE", 20, "semibold", MUTED)
    _text(d, (w / 2, 368), f"₱{rewards:,.2f}", 54, "ebold", GOLD)

    _stat_tile(d, 80, 464, 440, 130, "TOTAL INVITES", str(invites), CYAN)
    _stat_tile(d, 560, 464, 440, 130, "VALID INVITES", str(valid_invites), GREEN)

    _text(d, (w / 2, 688), "YOUR INVITE LINK", 20, "semibold", MUTED)
    _rounded(d, [80, 712, 1000, 796], 24, (24, 20, 54))
    _text(d, (w / 2, 754), ref_link, 22, "semibold", WHITE, max_w=880)

    _text(d, (w / 2, 900), "TOP 5 REFERRERS", 28, "ebold", WHITE)
    y = 950
    medals = ["1st", "2nd", "3rd", "4th", "5th"]
    for i, item in enumerate(top5):
        name, income = (list(item or ("—", 0)) + ["—", 0.0])[:2]
        _rounded(d, [80, y, 1000, y + 88], 26, (28, 22, 58))
        _text(d, (130, y + 44), f"{medals[i]}  {name}", 23, "semibold", WHITE, anchor="lm", max_w=640)
        _text(d, (950, y + 44), f"₱{float(income or 0):,.2f}", 23, "ebold", GOLD, anchor="rm")
        y += 104

    _footer(img, h, f"★ INVITE • EARN • RISE — {rank_name.upper()} ★")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def lineup_card(match_no: int, blue: list, red: list, closes_in: int = 0) -> bytes:
    w, h = 1080, 1000
    img = _canvas(w, h, top=(14, 16, 46), bot=(8, 8, 26))
    d = ImageDraw.Draw(img)
    _glow(img, 250, 320, 300, BLUE, 90)
    _glow(img, 830, 320, 300, RED, 90)
    _sparkles(d, w, h, n=18)

    _text(d, (w / 2, 70), f"MATCH #{match_no}  —  5 vs 5", 40, "ebold", WHITE)
    if closes_in:
        _text(d, (w / 2, 128), f"Betting closes in {closes_in}s • Pick your side", 22, "semibold", GOLD)
    else:
        _text(d, (w / 2, 128), "Pick your side", 22, "semibold", GOLD)

    col_w = 470
    for side, heroes, cx, accent in (("BLUE", blue, 60, BLUE), ("RED", red, 550, RED)):
        _rounded(d, [cx, 190, cx + col_w, 930], 28, (28, 24, 60))
        _rounded(d, [cx, 190, cx + col_w, 264], 28, accent)
        _text(d, (cx + col_w / 2, 227), f"{side} TEAM", 28, "ebold", WHITE)
        y = 296
        for he in heroes:
            c1 = _hex(he.get("color1", "#7C3AED"))
            _avatar(d, cx + 52, y + 38, 30, he.get("name", "?")[0], c1, c1)
            _text(d, (cx + 102, y + 20), he.get("name", "-"), 23, "ebold", WHITE, anchor="lm", max_w=330)
            _text(d, (cx + 102, y + 54), he.get("title", ""), 16, "medium", MUTED, anchor="lm", max_w=330)
            y += 88

    vs = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vs)
    vd.ellipse([6, 6, 144, 144], fill=(20, 16, 48))
    vd.ellipse([6, 6, 144, 144], outline=GOLD, width=5)
    _text(vd, (75, 75), "VS", 42, "ebold", GOLD)
    img.paste(vs, (w // 2 - 75, 465), vs)

    _footer(img, h, "THE WINNING TEAM TAKES ALL")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _hero_bust(d, cx, cy, r, hero):
    c1 = _hex(hero.get("color1", "#7C3AED"))
    c2 = _hex(hero.get("color2", "#1E1B4B"))
    for i in range(r, 0, -3):
        t = i / r
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=_lerp(c1, c2, t))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD, width=4)
    _text(d, (cx, cy), hero.get("name", "?")[0].upper(), int(r * 0.7), "ebold", WHITE)


def fight_card(game: str, match_no=None, blue=None, red=None, hero=None, picked_role=None) -> bytes:
    w, h = 1080, 900
    if game == "rank":
        img = _canvas(w, h, top=(10, 14, 42), bot=(6, 6, 22))
        d = ImageDraw.Draw(img)
        _glow(img, 250, h / 2, 340, BLUE, 110)
        _glow(img, 830, h / 2, 340, RED, 110)
        _sparkles(d, w, h, n=16)
        _hero_bust(d, 220, h // 2, 130, blue[0] if blue else {"name": "?", "color1": "#3B58FF", "color2": "#1B2A6A"})
        _hero_bust(d, 860, h // 2, 130, red[0] if red else {"name": "?", "color1": "#F43F5E", "color2": "#701A2B"})
        _text(d, (w / 2, 120), f"MATCH #{match_no or '???'}", 30, "ebold", GOLD)
        _text(d, (w / 2, 300), "VS", 76, "ebold", WHITE)
        _text(d, (w / 2, h - 150), "THE BATTLE RAGES ON...", 30, "ebold", WHITE)
        _text(d, (w / 2, h - 92), "FIGHTING", 40, "ebold", PINK)
    elif game == "mvp":
        img = _canvas(w, h)
        d = ImageDraw.Draw(img)
        _glow(img, w / 2, h / 2, 380, GOLD, 110)
        _sparkles(d, w, h, n=24)
        _text(d, (w / 2, 120), "WHO'S THE MVP?", 46, "ebold", GOLD)
        _text(d, (w / 2, 196), f"Your pick: {hero.get('name', '?') if hero else '?'}", 26, "semibold", WHITE)
        _avatar(d, w / 2, 470, 165, (hero.get("name", "?")[0] if hero else "?"),
                _hex(hero.get("color1", "#FBBF24")), _hex(hero.get("color2", "#7A4A0B")))
        _text(d, (w / 2, 716), "THE CLASH OF LEGENDS", 30, "ebold", WHITE)
        _text(d, (w / 2, 778), "ONE HERO. ONE MVP. x71 PAYOUT!", 26, "semibold", GOLD)
    else:  # herole
        img = _canvas(w, h)
        d = ImageDraw.Draw(img)
        _glow(img, w / 2, h / 2, 360, CYAN, 100)
        _sparkles(d, w, h, n=22)
        _text(d, (w / 2, 110), "HEROLE UNLOCKED", 42, "ebold", CYAN)
        _text(d, (w / 2, 180), f"Your role: {picked_role.upper() if picked_role else '?'}", 27, "semibold", WHITE)
        roles = ["Tank", "Fighter", "Assassin", "Mage", "Support", "Marksman"]
        cols = [BLUE, (230, 126, 34), PURPLE, (52, 152, 219), GREEN, RED]
        for i, rname in enumerate(roles):
            cx = 190 + (i % 3) * 350
            cy = 400 + (i // 3) * 240
            _rounded(d, [cx - 140, cy - 64, cx + 140, cy + 64], 34, (28, 22, 60))
            picked = rname.upper() == str(picked_role).upper()
            _rounded(d, [cx - 140, cy - 64, cx + 140, cy + 64], 34, None,
                     outline=(GOLD if picked else None), width=3)
            _text(d, (cx, cy - 14), rname.upper(), 25, "ebold", GOLD if picked else cols[i])
            _text(d, (cx, cy + 26), "★ PICKED" if picked else "•", 16, "medium", MUTED)
        _text(d, (w / 2, 838), "THE ROLE REVEAL APPROACHES...", 24, "semibold", WHITE)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def result_card(headline: str, sub: str, payout: str, hero=None, win: bool = True) -> bytes:
    w, h = 1080, 820
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    accent = GREEN if win else RED
    _glow(img, w / 2, 200, 340, accent, 120)
    _glow(img, w / 2, h - 120, 280, GOLD if win else RED, 70)
    _sparkles(d, w, h)

    if hero:
        _avatar(d, 300, h // 2, 115, hero.get("name", "?")[0],
                _hex(hero.get("color1", "#7C3AED")), _hex(hero.get("color2", "#1E1B4B")))

    _text(d, (w / 2, 130), "MATCH RESULT", 26, "semibold", MUTED)
    _text(d, (w / 2, 226), headline, 50, "ebold", WHITE, max_w=1000)
    _text(d, (w / 2, 316), sub, 27, "semibold", GOLD, max_w=1000)

    _rounded(d, [w / 2 - 260, 420, w / 2 + 260, 550], 44, accent)
    _rounded(d, [w / 2 - 260, 420, w / 2 + 260, 550], 44, None, outline=GOLD, width=3)
    _text(d, (w / 2, 485), payout, 36, "ebold", WHITE)

    _text(d, (w / 2, 648), "KEEP GRINDING LEGEND!" if win else "NEXT MATCH IN YOUR FAVOR!", 25, "semibold", MUTED)
    _footer(img, h, "MLPLAY • EVERY BATTLE COUNTS")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def banner_card(title: str, subtitle: str = "", accent: tuple = PURPLE, glyph: str = "★") -> bytes:
    w, h = 1080, 380
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    _glow(img, w / 2, h / 2, 300, accent, 110)
    _sparkles(d, w, h, n=16)
    _text(d, (w / 2, h / 2 - 56), f"{glyph} {title} {glyph}", 52, "ebold", WHITE, max_w=1020)
    _text(d, (w / 2, h / 2 + 44), subtitle, 24, "semibold", GOLD, max_w=980)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def hero_portrait(hero) -> bytes:
    w, h = 540, 720
    c1 = _hex(hero.color1)
    img = _canvas(w, h, top=c1, mid=(14, 12, 40), bot=BG_BOT)
    d = ImageDraw.Draw(img)
    _glow(img, w / 2, 260, 210, c1, 150)
    _sparkles(d, w, h, n=12)
    _avatar(d, w / 2, 260, 140, hero.name[0].upper(), c1, _hex(hero.color2))
    _text(d, (w / 2, 452), hero.name.upper(), 38, "ebold", WHITE)
    _text(d, (w / 2, 504), hero.title, 20, "medium", MUTED, max_w=480)
    _rounded(d, [w / 2 - 105, 540, w / 2 + 105, 602], 30, (36, 26, 70))
    _text(d, (w / 2, 571), hero.role.upper(), 21, "semibold", GOLD)
    _text(d, (w / 2, 662), f"HP {hero.hp}   ATK {hero.atk}   SPD {hero.spd}", 18, "medium", MUTED)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def hero_bust_bytes(hero) -> bytes:
    """Square portrait used inside lineups / admin uploads previews."""
    w = h = 400
    c1 = _hex(hero.color1)
    img = _canvas(w, h, top=c1, mid=(14, 12, 40), bot=BG_BOT)
    d = ImageDraw.Draw(img)
    _glow(img, w / 2, h / 2, 170, c1, 120)
    _avatar(d, w / 2, h / 2, 130, hero.name[0].upper(), c1, _hex(hero.color2))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()