# Deploying LodgeOS (VPS + Docker)

Runs the **bot** (Telegram, outbound only) and the **dashboard** (public HTTPS via Caddy)
on one always-on box, sharing a persistent SQLite database.

## 1. Get a server + domain

- **VPS**: Oracle Cloud "Always Free" (ARM, generous, $0) or Hetzner / DigitalOcean (~$5/mo).
  Pick at least **1 GB RAM** for local Whisper (or use `WHISPER_MODE=cloud` to need less).
- **Domain**: point an **A record** to the VPS public IP (e.g. `lodgeos.example.com → 1.2.3.4`).
  Need a free one? DuckDNS works. The dashboard needs a real domain for automatic HTTPS.

## 2. Install Docker on the VPS

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # then log out/in
```

## 3. Get the code + configure

```bash
git clone https://github.com/<you>/lodgeos.git
cd lodgeos
cp .env.example .env
nano .env          # fill in TELEGRAM_TOKEN, OPENROUTER_API_KEY, DASHBOARD_BASE_URL, etc.
nano Caddyfile     # replace lodgeos.example.com with YOUR domain
```

Key `.env` values:
- `TELEGRAM_TOKEN` — from @BotFather (use a **fresh** one, not any you've shared)
- `OPENROUTER_API_KEY` — for text + vision
- `DASHBOARD_BASE_URL=https://your-domain` — so `/dashboard` links are reachable
- `DASHBOARD_ROOT=0` — multi-user safe (no single-user root page)

## 4. Launch

```bash
docker compose up -d --build
```

That starts three containers: `bot`, `dashboard`, `caddy`. Caddy auto-issues a
Let's Encrypt TLS cert for your domain (ports 80/443 must be open on the VPS firewall).

Check it:
```bash
docker compose logs -f bot        # should show "Application started"
curl -I https://your-domain       # dashboard reachable over HTTPS
```

In Telegram, send `/menu` → `/dashboard` → the link is now `https://your-domain/d/<token>`.

## 5. Operations

- **Update**: `git pull && docker compose up -d --build`
- **Backup the ledger**: `docker compose cp bot:/data/openclaw.db ./backup-$(date +%F).db`
- **Logs**: `docker compose logs -f`
- **Stop**: `docker compose down` (data is kept in the `appdata` volume)

## Notes & trade-offs

- **One writer**: the bot writes, the dashboard reads — SQLite WAL handles this. Don't run
  multiple bot replicas against the same DB.
- **First voice note** downloads the Whisper model (~150 MB) into the persisted `hf-cache`
  volume; subsequent ones are fast.
- **RAM tight?** Set `WHISPER_MODE=cloud` + a Groq key to offload transcription.
- **Firewall**: open inbound 80 and 443 only. The bot needs no inbound ports; the dashboard
  is reached only through Caddy (never exposed directly).
- **Secrets** live in `.env` on the server (gitignored), never in the image or repo.
