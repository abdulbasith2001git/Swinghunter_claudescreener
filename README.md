# Swing Hunter — Free Cloud Setup (GitHub Actions)
No laptop needed! Runs 3 scans daily for FREE.

## Daily Schedule
6:00 PM IST  — Full scan (Bhavcopy loaded) → Telegram
8:00 PM IST  — Recheck shortlist          → Telegram
9:15 AM IST  — Final BUY/WAIT/SKIP        → Telegram

## One-Time Setup (15 min)

1. github.com → Sign up free (no credit card)
2. New Repository → Name: swing-hunter → Private
3. Upload swing_hunter.py to repo
4. Create file: .github/workflows/scan.yml (paste scan.yml contents)
5. Settings → Secrets → Actions → Add:
   TELEGRAM_TOKEN = your bot token
   TELEGRAM_CHAT_ID = your chat ID
6. Actions tab → Enable workflows
7. Run workflow manually → select "test" → check Telegram

## Free Usage
2,000 min/month free. Our 3 scans use ~900 min/month. Well within limits!
