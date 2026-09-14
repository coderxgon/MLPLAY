"""Default hero roster — the full MLBB-style lineup (133 heroes, 6 roles).
Admins can edit every hero AND add new heroes in the panel.
"""
import hashlib
import re

from app.db import SessionLocal
from app.models import Hero

ROLES = {
    "tank": "Tank",
    "fighter": "Fighter",
    "assassin": "Assassin",
    "mage": "Mage",
    "support": "Support",
    "marksman": "Marksman",
}

ROLE_EMOJI = {
    "tank": "🛡️", "fighter": "⚔️", "assassin": "🗡️",
    "mage": "🔮", "support": "💠", "marksman": "🎯",
}

# accent pairs cycle through these per role so no two heroes look identical
ROLE_COLORS = {
    "tank": [("#2E86DE", "#1B4F8B"), ("#48C9B0", "#0B3D36"), ("#5DADE2", "#1C2833"), ("#2980B9", "#1B2A4A")],
    "fighter": [("#E67E22", "#5C2E0B"), ("#E74C3C", "#641E16"), ("#AF7AC5", "#4A235A"), ("#EB984E", "#6E2C00")],
    "assassin": [("#9B59B6", "#3B1A5C"), ("#8E44AD", "#2C0E44"), ("#C39BD3", "#512E5F"), ("#A569BD", "#4A235A")],
    "mage": [("#3498DB", "#0B3C5D"), ("#85C1E9", "#15445E"), ("#5DADE2", "#1A5276"), ("#F39C12", "#7E5109")],
    "support": [("#1ABC9C", "#0E6655"), ("#58D68D", "#145A32"), ("#76D7C4", "#0B5345"), ("#2ECC71", "#145A32")],
    "marksman": [("#E74C3C", "#641E16"), ("#EC7063", "#78281F"), ("#F1948A", "#7B241C"), ("#CD6155", "#641E16")],
}

ROLE_STATS = {
    "tank": {"hp": (850, 1100), "atk": (70, 100), "spd": (40, 58)},
    "fighter": {"hp": (700, 920), "atk": (110, 148), "spd": (55, 72)},
    "assassin": {"hp": (540, 680), "atk": (155, 195), "spd": (68, 92)},
    "mage": {"hp": (500, 630), "atk": (160, 205), "spd": (48, 66)},
    "support": {"hp": (600, 740), "atk": (60, 88), "spd": (54, 70)},
    "marksman": {"hp": (470, 570), "atk": (190, 235), "spd": (58, 82)},
}

ROLE_TITLES = {
    "tank": ["The Iron Guardian", "Bulwark of Dawn", "Unbreakable Wall", "Vanguard of Light", "Stoneheart Sentinel"],
    "fighter": ["Blade of the Arena", "Fury Incarnate", "Battle-Tested Legend", "Storm of the Plains", "Duel Champion"],
    "assassin": ["Shadow Stalker", "Silent Death", "Night's Edge", "Phantom Blade", "Swift Reaper"],
    "mage": ["Master of Arcana", "Weaver of Spells", "Storm Caller", "Aether Scholar", "Mystic Oracle"],
    "support": ["Light of the Team", "Guardian Spirit", "Heart of the Battle", "Aura Keeper", "Divine Blessing"],
    "marksman": ["Deadshot Marksman", "Precision Incarnate", "Golden Crossbow", "Relentless Hunter", "Silver Bullet"],
}

ROSTER = [
    ("tank", ["Akai", "Alice", "Atlas", "Barats", "Baxia", "Belerick", "Chip", "Edith",
              "Esmeralda", "Franco", "Fredrinn", "Gatotkaca", "Gloo", "Grock", "Hylos",
              "Johnson", "Khufra", "Lolita", "Masha", "Minotaur", "Tigreal", "Uranus"]),
    ("fighter", ["Aldous", "Alpha", "Alucard", "Argus", "Arlott", "Aulus", "Badang", "Balmond",
                 "Bane", "Chou", "Cici", "Dyrroth", "Freya", "Guinevere", "Hilda", "Jawhead",
                 "Julian", "Kaja", "Khaleed", "Lapu-Lapu", "Leomord", "Lukas", "Martis",
                 "Minsitthar", "Paquito", "Phoveus", "Roger", "Ruby", "Silvanna", "Sora",
                 "Sun", "Suyou", "Terizla", "Thamuz", "X.Borg", "Yin", "Yu Zhong", "Zilong"]),
    ("assassin", ["Aamon", "Benedetta", "Fanny", "Gusion", "Hanzo", "Harley", "Hayabusa",
                  "Helcurt", "Hirara", "Joy", "Karina", "Lancelot", "Lesley", "Ling",
                  "Mathilda", "Natalia", "Nolan", "Saber", "Selena", "Yi Sun-shin"]),
    ("mage", ["Aurora", "Cecilion", "Chang'e", "Cyclops", "Eudora", "Faramis", "Gord",
              "Harith", "Kadita", "Kagura", "Kimmy", "Lunox", "Luo Yi", "Lylia", "Nana",
              "Novaria", "Odette", "Pharsa", "Vale", "Valentina", "Valir", "Vexana",
              "Xavier", "Yve", "Zetian", "Zhask", "Zhuxin"]),
    ("marksman", ["Beatrix", "Brody", "Bruno", "Claude", "Clint", "Granger", "Hanabi",
                  "Irithel", "Ixia", "Karrie", "Layla", "Melissa", "Miya", "Moskov",
                  "Natan", "Obsidia", "Popol and Kupa", "Wanwan"]),
    ("support", ["Angela", "Carmilla", "Diggie", "Estes", "Floryn", "Kalea", "Marcel", "Rafaela"]),
]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "hero"


def build_default_heroes():
    heroes = []
    for role, names in ROSTER:
        for idx, name in enumerate(names):
            key = slugify(name)
            digest = hashlib.md5(key.encode()).hexdigest()
            seed = int(digest[:8], 16)
            stats = ROLE_STATS[role]
            hp = stats["hp"][0] + seed % (stats["hp"][1] - stats["hp"][0])
            atk = stats["atk"][0] + (seed >> 8) % (stats["atk"][1] - stats["atk"][0])
            spd = stats["spd"][0] + (seed >> 16) % (stats["spd"][1] - stats["spd"][0])
            c1, c2 = ROLE_COLORS[role][idx % len(ROLE_COLORS[role])]
            title = ROLE_TITLES[role][seed % len(ROLE_TITLES[role])]
            heroes.append({
                "key": key, "name": name, "title": title, "role": role,
                "emoji": ROLE_EMOJI[role], "color1": c1, "color2": c2,
                "hp": hp, "atk": atk, "spd": spd, "active": True,
            })
    return heroes


def ensure_heroes() -> None:
    """Seed the full roster. If the real roster is absent (fresh DB or old
    fictional roster), wipe and reseed."""
    s = SessionLocal()
    try:
        if s.query(Hero).filter(Hero.key == "akai").first():
            return
        s.query(Hero).delete()
        for h in build_default_heroes():
            s.add(Hero(**h))
        s.commit()
    finally:
        s.close()


def get_hero_pool(session, role: str | None = None):
    q = session.query(Hero).filter(Hero.active.is_(True))
    if role:
        q = q.filter(Hero.role == role)
    return q.all()


def hero_by_key(session, key: str):
    return session.query(Hero).filter(Hero.key == key, Hero.active.is_(True)).first()


def hero_by_name(session, name: str):
    low = slugify(name)
    q = session.query(Hero).filter(Hero.active.is_(True))
    for h in q:
        if slugify(h.name) == low or h.key == low:
            return h
    return None


LINEUP_ROLES = ["tank_support", "fighter", "assassin", "mage", "marksman"]

ROLE_LABEL = {
    "tank": "Tank", "support": "Support",
    "fighter": "Fighter", "assassin": "Assassin",
    "mage": "Mage", "marksman": "Marksman",
    "tank_support": "Tank / Support",
}

GAME_MULTIPLIERS = {"rank": 2.0, "mvp": 71.0, "herole": 3.0}