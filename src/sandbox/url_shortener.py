import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

DATABASE_URL = "sqlite:///./links.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Link(Base):
    __tablename__ = "links"
    alias = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    clicks = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class LinkCreate(BaseModel):
    url: HttpUrl
    alias: str | None = None


class LinkStats(BaseModel):
    alias: str
    url: str
    clicks: int
    expires_at: datetime

    model_config = {"from_attributes": True}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    with Session(engine) as db:
        yield db


def _increment_clicks(alias: str) -> None:
    with Session(engine) as db:
        link = db.get(Link, alias)
        if link:
            link.clicks += 1
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/links", response_model=LinkStats, status_code=201)
def create_link(payload: LinkCreate, db: Session = Depends(get_db)):
    alias = payload.alias or secrets.token_urlsafe(6)
    if db.get(Link, alias):
        raise HTTPException(status_code=409, detail="Alias already exists")
    link = Link(
        alias=alias,
        url=str(payload.url),
        clicks=0,
        expires_at=_now() + timedelta(hours=24),
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@app.get("/links/{alias}/stats", response_model=LinkStats)
def get_stats(alias: str, db: Session = Depends(get_db)):
    link = db.get(Link, alias)
    if not link or link.expires_at < _now():
        raise HTTPException(status_code=404, detail="Link not found or expired")
    return link


@app.get("/{alias}")
def redirect_link(alias: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    link = db.get(Link, alias)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    if link.expires_at < _now():
        db.delete(link)
        db.commit()
        raise HTTPException(status_code=404, detail="Link expired")
    background_tasks.add_task(_increment_clicks, alias)
    return RedirectResponse(url=link.url, status_code=302)
