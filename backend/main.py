import os
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, SQLModel, create_engine, select, func

from models import Ad
from scraper import pull_all_brands, BRANDS

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/lxry.db")
engine = create_engine(DATABASE_URL, echo=False)

scheduler = AsyncIOScheduler()
last_pull_time: datetime | None = None


def get_session():
    return Session(engine)


async def scheduled_pull():
    global last_pull_time
    print(f"[scheduler] Running scheduled pull at {datetime.utcnow()}")
    with get_session() as session:
        result = await pull_all_brands(session)
        last_pull_time = datetime.utcnow()
        print(f"[scheduler] Pull complete: {result}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    SQLModel.metadata.create_all(engine)

    # Schedule daily pull at 06:00 UTC
    scheduler.add_job(scheduled_pull, CronTrigger(hour=6, minute=0), id="daily_pull")
    scheduler.start()

    # If database is empty, run initial pull
    with get_session() as session:
        count = session.exec(select(func.count()).select_from(Ad)).one()
        if count == 0:
            print("[startup] Database empty, running initial pull...")
            await scheduled_pull()

    yield

    scheduler.shutdown()


app = FastAPI(title="LXRY Ad Tracker", lifespan=lifespan)

# Serve frontend
FRONTEND_PATH = os.environ.get("FRONTEND_PATH", "/app/frontend")
if os.path.isdir(FRONTEND_PATH):
    app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")


@app.get("/")
async def serve_index():
    index_path = os.path.join(FRONTEND_PATH, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "LXRY Ad Tracker API", "docs": "/docs"}


@app.get("/ads")
async def get_ads(
    brand: str | None = Query(None),
    status: str | None = Query(None),
    format: str | None = Query(None),
    saved: bool | None = Query(None),
    sort_by: str | None = Query(None),
    min_run_days: int | None = Query(None),
):
    with get_session() as session:
        query = select(Ad)

        if brand:
            query = query.where(Ad.brand == brand)
        if status:
            query = query.where(Ad.status == status)
        if format:
            query = query.where(Ad.format == format)
        if saved is not None:
            query = query.where(Ad.saved == saved)
        if min_run_days is not None:
            query = query.where(Ad.run_days >= min_run_days)

        if sort_by == "run_days":
            query = query.order_by(Ad.run_days.desc())
        elif sort_by == "impressions_est":
            query = query.order_by(Ad.impressions_est.desc())
        else:
            query = query.order_by(Ad.last_seen.desc())

        ads = session.exec(query).all()
        return [ad.model_dump() for ad in ads]


@app.post("/ads/pull")
async def manual_pull():
    global last_pull_time
    with get_session() as session:
        result = await pull_all_brands(session)
        last_pull_time = datetime.utcnow()
        return {"status": "complete", "result": result, "pulled_at": last_pull_time.isoformat()}


@app.patch("/ads/{ad_id}/save")
async def toggle_save(ad_id: str):
    with get_session() as session:
        ad = session.get(Ad, ad_id)
        if not ad:
            return {"error": "Ad not found"}, 404
        ad.saved = not ad.saved
        session.add(ad)
        session.commit()
        session.refresh(ad)
        return {"id": ad.id, "saved": ad.saved}


@app.get("/stats")
async def get_stats():
    with get_session() as session:
        stats = {}
        for brand in BRANDS:
            brand_ads = session.exec(select(Ad).where(Ad.brand == brand)).all()
            active = [a for a in brand_ads if a.status == "Active"]
            run_days_list = [a.run_days for a in brand_ads if a.run_days > 0]
            avg_run = round(sum(run_days_list) / len(run_days_list), 1) if run_days_list else 0

            # Top format
            format_counts: dict[str, int] = {}
            for a in brand_ads:
                format_counts[a.format] = format_counts.get(a.format, 0) + 1
            top_format = max(format_counts, key=format_counts.get) if format_counts else "N/A"

            stats[brand] = {
                "total": len(brand_ads),
                "active": len(active),
                "avg_run_days": avg_run,
                "top_format": top_format,
            }

        # Totals
        all_ads = session.exec(select(Ad)).all()
        new_today = [a for a in all_ads if a.is_new]
        all_run_days = [a.run_days for a in all_ads if a.run_days > 0]

        stats["_totals"] = {
            "total": len(all_ads),
            "active": len([a for a in all_ads if a.status == "Active"]),
            "new_today": len(new_today),
            "avg_run_days": round(sum(all_run_days) / len(all_run_days), 1) if all_run_days else 0,
            "longest_run_days": max(all_run_days) if all_run_days else 0,
        }

        return stats


@app.get("/schedule/next")
async def next_schedule():
    job = scheduler.get_job("daily_pull")
    next_run = job.next_run_time if job else None
    return {
        "next_pull": next_run.isoformat() if next_run else None,
        "last_pull": last_pull_time.isoformat() if last_pull_time else None,
    }
