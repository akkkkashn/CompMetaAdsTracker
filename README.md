# LXRY Ad Tracker

Internal competitor ad tracking dashboard. Pulls ads from the Meta Ad Library API every 24 hours for tracked brands and surfaces them in a clean dashboard UI.

**Tracked brands:** Edblad, Mockberg

## Setup

### 1. Get a Meta Ad Library API Token

1. Go to [facebook.com/ads/library/api](https://www.facebook.com/ads/library/api)
2. Create or select an app
3. Generate a long-lived access token with the `ads_read` permission

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your META_TOKEN
```

### 3. Run with Docker Compose

```bash
docker compose up -d --build
```

The dashboard will be available at `http://localhost:8765`.

### 4. Run Locally (Development)

```bash
cd backend
pip install -r requirements.txt
META_TOKEN=your_token uvicorn main:app --reload --port 8765
```

Serve the frontend by setting `FRONTEND_PATH=../frontend`.

## Adding More Brands

Edit the `BRANDS` list in `backend/scraper.py`:

```python
BRANDS = ["Edblad", "Mockberg", "NewBrand"]
```

Rebuild and restart the container.

## Traefik Integration

Add labels to the `lxry-tracker` service in `docker-compose.yml`:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.lxry.rule=Host(`ads.yourdomain.com`)"
  - "traefik.http.services.lxry.loadbalancer.server.port=8765"
```

Remove the `ports` mapping if using Traefik's network.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ads` | List ads with filters |
| POST | `/ads/pull` | Manually trigger a pull |
| PATCH | `/ads/{id}/save` | Toggle saved/bookmarked |
| GET | `/stats` | Summary stats per brand |
| GET | `/schedule/next` | Next scheduled pull time |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `META_TOKEN` | Yes | — | Meta Ad Library API token |
| `META_COUNTRY` | No | `SE` | Country code for ad targeting |
