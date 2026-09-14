# ⚡ MLPlay — Telegram Gaming Bot + Mini App + Admin Panel

A complete, deploy-ready esports betting platform:

- **🤖 Telegram Bot** (aiogram 3) — welcome card & registration, Menu pages (Profile / Referral / Games / Contact Services / Promotions), wallet binding with ₱30 bonus, daily reward, 3 games
- **🎮 Real-time Rank Game** — a new live match every 2 minutes, 5v5 lineups from 133 heroes, channel posts with bet deep-links, shared match IDs
- **🏆 Who's The MVP?** — guess the MVP hero, ×71 payout
- **🎭 HeRole** — guess the role, ×3 payout
- **📱 Mini App** (Telegram WebApp) — Deposit with QR + receipt upload, Withdraw with dynamic per-channel forms, Promo Codes, Transaction History, Promotions, Leaderboard
- **🖥 Admin Panel** — dashboard, user management (ban/suspend/freeze/add/remove balance with notifications), deposit & withdrawal approvals (also approvable from the transaction group), promotions & promo codes, win-rate settings per game + per user, rank-up bonuses, payment methods, broadcast, hero roster editor + add hero, logo/card customization, action logs
- **🖼 Canvas engine** (Pillow) — HD generated cards: welcome, player profile, referral, lineups, fight scenes, results, banners

---

## 🚀 Quick start (local)

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # fill BOT_TOKEN, ADMIN_PASSWORD, WEBAPP_URL
python run.py
```

Open `http://localhost:8000/admin` — default password `MLPlay-Admin-2026` (change it!).
In the **Customize → General** tab set your bot token (or leave the env `BOT_TOKEN`) — the bot hot-reloads within ~15 s, no restart needed.

> 💡 Mini App links need your app reachable over **HTTPS**. Locally, Telegram WebApps only open from a bot whose WebApp domain is `localhost` *and* the `t.me` link is opened inside Telegram (or use `DEBUG_WEBAPP_DEV=1` + a dev UID header to test the pages in a normal browser). On Render it just works.

---

## 📦 Deploy on Render (24/7)

1. Create your bot in **@BotFather** → copy its token.
2. Push this folder to a GitHub repo.
3. In Render: **New → Web Service → connect the repo**.
   - Build: `pip install -r requirements.txt`
   - Start: `python run.py`
4. Environment variables:
   - `BOT_TOKEN` → your token (can also be left empty and set from the admin panel)
   - `ADMIN_PASSWORD` → a strong admin password
   - `WEBAPP_URL` → `https://<your-app>.onrender.com`
   - `DATABASE_URL` → leave empty for the local SQLite file; for persistent data across deploys use a managed PostgreSQL (recommended: Neon/Supabase free tiers) as `postgresql+psycopg2://user:pass@host/db` (the SQLAlchemy driver is bundled with the standard install; if you get a driver error, run `pip install psycopg2-binary` and redeploy).
5. After first boot:
   - `/admin` → **Customize → General**: set Bot token (if not in env), logo, welcome card, referral %, daily bonus, bind bonus.
   - **Customize → Channels**: paste your game channel (`@name` or numeric ID), transaction group and actions group (the bot must be admin there).
   - **Customize → Admins**: add up to 10 Telegram admin IDs.
   - **Payment Methods**: add a deposit method (QR text auto-renders as QR) and a withdrawal channel with its form fields (JSON `[{"key":"account_number","label":"Account Number","placeholder":"…","type":"text"}]`).
6. Done — open the bot with `/start`, register, bind a wallet (₱30 bonus), deposit, and play!

`render.yaml` is included (free tier + optional 1 GB disk); you can also use the Render Blueprint "New + → Blueprint" with this file.

---

## 🎮 Games & ranks

| Rank | Tier | Max bet | Daily bets | Games | Reach conditions |
|---|---|---|---|---|---|
| Warrior | Beginner | ₱10 | 5 | Rank | — |
| Elite | Level 1 | ₱50 | 10 | Rank | 100 valid bets |
| Master | Level 2 | ₱70 | 50 | Rank | 300 valid bets |
| Grandmaster | Level 3 | ₱100 | 70 | Rank | 500 valid bets |
| Epic | Level 4 | ₱150 | ∞ | Rank + HeRole | ₱100 deposits + 1,000 bets |
| Legend | Level 5 | ₱300 | ∞ | Rank + HeRole | ₱300 + 1,000 bets |
| Mythic | VIP 1 | ₱500 | ∞ | All | ₱500 + 3,000 bets |
| Honor | VIP 2 | ₱1,000 | ∞ | All | ₱1,000 + 3,000 bets |
| Glory | VIP 3 | ₱5,000 | ∞ | All | ₱5,000 + 5,000 bets |
| Immortal | SVIP | ₱50,000 | ∞ | All | ₱50,000 + 10,000 bets |

**Rank-up bonuses (auto-credited, editable in admin → Games):**
Warrior ₱0 • Elite ₱1 • Master ₱3 • Grandmaster ₱10 • Epic ₱15 • Legend ₱30 • Mythic ₱50 • Honor ₱100 • Glory ₱200 • Immortal ₱5,000

**Payouts:** Rank Game ×2 (correct team) • Who's The MVP? ×71 • HeRole ×3. Min bet ₱1 everywhere.

**Win rate:** per game, global default 30%, per-user overrides (100% = always wins). Bet outcomes are rolled server-side at placement; the result is revealed after the 10-second fight.

> 🎲 **How Rank Game works:** a match is created every 120 s, all players bet on the same match ID, bets close ~105 s, results are posted to the game channel with a "Place Bet" button that deep-links into the bot. Each player's result follows the platform win-rate config so the house economics stay consistent.

---

## 🧾 Repository layout

```
mlplay/
├── run.py                  # entry point: FastAPI + bot + game loop in one process
├── render.yaml             # Render blueprint
├── requirements.txt
├── .env.example
└── app/
    ├── config.py           # env config
    ├── db.py               # SQLAlchemy engine (SQLite/Postgres) + migrations
    ├── models.py           # users/orders/bets/matches/heroes/promos/settings...
    ├── settings_svc.py     # key-value settings, win rates, admins
    ├── heroes.py           # 133-hero roster + helpers
    ├── ranks.py            # rank table, limits, progress
    ├── cards.py            # Pillow canvas engine (all images)
    ├── wallet.py           # money engine: bets, deposits, withdrawals, promos, rewards, binds, rank-ups
    ├── notifier.py         # async bridge bot ↔ sync services
    ├── games_svc.py        # 2-minute match loop, channel posts, bet sweeper
    ├── bot_controller.py   # bot lifecycle, token hot-reload, broadcasts
    ├── bot_core.py         # /start, register, menu, profile, referral, contact, bind
    ├── bot_games.py        # Rank Game / MVP / HeRole flows
    ├── bot_admin.py        # TG-group approve/reject/ban with remarks
    └── web/
        ├── app.py          # FastAPI factory (+optional webhook endpoint)
        ├── auth.py         # admin sessions
        ├── admin_routes.py # panel API
        ├── mini_routes.py  # mini app API (initData-verified)
        ├── templates/      # admin Jinja2 pages
        └── static/
            ├── admin.css / admin.js
            └── mini/       # Mini App SPA (index.html, mini.js, mini.css)
```

---

## 👤 Key user flows

- **/start** → welcome card → **Register to MLPlay** → Menu
- **Profile** → player card image (name, @username, balance, rank, turnover, rewards, deposits, withdrawals, join date, user type, inviter, referral link, wallet binding) + Deposit / Withdraw / Promo Code / History buttons (open the mini app)
- **Referral** → rewards balance, total/valid invites, link, top-5 referrers, Copy Link, Copy Link w/ Text (unique promo copy + link), Convert rewards to balance
- **Contact Services** → Group / Channel / CSR1–3 redirect buttons (admin-configurable)
- **Bind Wallet/Bank** → one-time binding (GCash / Maya / Bank…) → **₱30 bonus**; after binding, **all withdrawals are paid ONLY to that permanently bound wallet** — players cannot change or bypass it, only admins can (panel → Users → 🏦 Bind). Unbound users are blocked from withdrawing until they bind.
- **Daily Reward** → daily ₱ bonus
- **Games** → rank limits apply automatically; fight animations + 10 s reveal

## 🔎 Admin extras ("betterness" features baked in)

- Maintenance mode (blocks betting/deposits instantly)
- Broadcast with image/text/button, filterable by rank, cancellable, per-user progress
- Transaction group approvals with remark requirement + Reject-with-Ban
- User action log (audit trail), rank-up & binding events posted to the actions group
- Hero stats (HP/ATK/SPD) and portraits editable, add your own heroes, per-hero activation
- Weekly deposit chart, per-game house stats, leaderboards (balance/referral/bets/deposits)
- Mini-app leaderboard + promotions feed
- Optional Telegram webhook mode (set `WEBHOOK_URL`-style deployment yourself; polling is default and simplest on Render)

---

## ⚠️ Notes

- The platform uses fictional-game hero names & emojis in-game; the hero roster is fully yours to edit/rename.
- **Responsibility:** operating a real-money betting product requires compliance with the laws of every jurisdiction you serve (KYC, anti-money-laundering, responsible gambling, operator licensing). Configure admin review for all deposits/withdrawals and set win rates responsibly.
- SQLite file lives in `./data` — on Render free tier storage is ephemeral; use the persistent disk or a managed Postgres for real money. The server boots fine with neither (best-effort).
- All Telegram amounts are in **₱ (PHP)**; change `MIN_BET`/`MAX_BET_GLOBAL`/payment limits in config/panel as needed.