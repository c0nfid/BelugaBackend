import os
import uuid
import time
import asyncio
import secrets
import requests
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Integer, or_

from . import models, schemas, database, auth_utils, bot_auth
from routers import wiki, email_auth

models.Base.metadata.create_all(bind=database.engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_token = os.getenv("TG_BOT_TOKEN")
    if bot_token:
        print("Запуск Telegram бота...")
        asyncio.create_task(bot_auth.start_bot_polling(bot_token))
    else:
        print("TG_BOT_TOKEN не найден, бот не запущен.")
    print("Запуск очистки старых сессий...")
    asyncio.create_task(bot_auth.cleanup_task())
    yield

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

security = HTTPBasic()

app.include_router(wiki.router)
app.include_router(email_auth.router)

def get_current_username_docs(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, os.getenv("SWAGGER_USER", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("SWAGGER_PASSWORD", "admin"))
    if not (correct_user and correct_password):
        raise HTTPException(status_code=401, detail="Incorrect auth", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(username: str = Depends(get_current_username_docs)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Beluga API Docs")

@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(username: str = Depends(get_current_username_docs)):
    return get_openapi(title="BelugaEmpire API", version="1.0.0", routes=app.routes)

cors_origins_str = os.getenv("CORS_ORIGINS", "")
origins = [origin.strip() for origin in cors_origins_str.split(",") if origin]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

online_cache = {
    "count": 0,
    "last_updated": 0
}

CACHE_TTL = 300  # 5 минут в секундах

PH_HOST = os.getenv("PLACEHOLDER_API_HOST")
PH_PORT = os.getenv("PLACEHOLDER_API_PORT")

@app.post("/login")
def login_with_password(creds: schemas.LoginRequest, response: Response, db: Session = Depends(database.get_db)):
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == creds.username).first()
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    if not auth_utils.verify_password(creds.password, user.password):
        raise HTTPException(status_code=400, detail="Неверный пароль")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=3600, samesite="lax", secure=False)
    return {"message": "Login successful"}

@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Logged out"}

@app.get("/me", response_model=schemas.UserResponse)
def read_users_me(user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm), db: Session = Depends(database.get_db)):
    player_data = db.query(models.PlayerData).filter(models.PlayerData.player_name == user.playername).first()
    playtime_data = db.query(models.PlayerPlaytime).filter(models.PlayerPlaytime.player_name == user.playername).first()
    
    kda_data = db.query(models.KDAData).filter(models.KDAData.player_name == user.playername).first()
    
    legit_stats = db.query(
        func.sum(models.PlayerPvpDaily.valid_kills).label("total_valid_kills"),
        func.sum(models.PlayerPvpDaily.valid_deaths).label("total_valid_deaths")
    ).filter(models.PlayerPvpDaily.player_name == user.playername).first()

    user_email_data = db.query(models.UserEmail).filter(models.UserEmail.nickname == user.playername).first()

    current_time_ms = int(time.time() * 1000)
    login_ts = player_data.login_timestamp if (player_data and player_data.login_timestamp) else 0
    logout_ts = player_data.logout_timestamp if (player_data and player_data.logout_timestamp) else 0

    session_duration = 0
    
    if login_ts > 0:
        if login_ts > logout_ts:
            session_duration = (current_time_ms - login_ts) // 1000
        else:
            session_duration = (logout_ts - login_ts) // 1000
    
    if session_duration < 0: session_duration = 0

    return {
        "playername": user.playername,
        "uuid": user.uuid,
        "activeTG": user.activeTG,
        "tg_username": user.username,
        "admin": user.admin,
        "clan_name": player_data.clan_name if player_data else None,
        "last_seen": player_data.logout_timestamp if player_data else None,
        "primary_group": player_data.primary_group if (player_data and player_data.primary_group) else "default",
        
        "donation_balance": player_data.donation_balance if player_data else 0,
        "balance": float(player_data.balance) if (player_data and player_data.balance) else 0.0,
                
        "kills": kda_data.player_kill if kda_data else 0,
        "deaths": kda_data.player_death if kda_data else 0,
        "legit_kills": legit_stats.total_valid_kills if legit_stats.total_valid_kills else 0,
        "legit_deaths": legit_stats.total_valid_deaths if legit_stats.total_valid_deaths else 0,

        "playtime_seconds": playtime_data.total_seconds if playtime_data else 0,
        "last_login_timestamp": login_ts,
        "last_ip": player_data.ip_address if (player_data and player_data.ip_address) else "Неизвестно",
        "session_duration": session_duration,
        
        "email": user_email_data.email if user_email_data else None,
        "is_email_verified": user_email_data.is_verified if user_email_data else False
    }

@app.get("/server/online")
def get_server_online():
    global online_cache
    current_time = time.time()
    
    ph_host = os.getenv("PLACEHOLDER_API_HOST")
    ph_port = os.getenv("PLACEHOLDER_API_PORT")

    if current_time - online_cache["last_updated"] > CACHE_TTL:
        try:
            placeholder_online = "server_online"
            url = f"http://{ph_host}:{ph_port}/--null/{placeholder_online}"
            
            response = requests.get(url, timeout=2.0)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    val_str = data.get("value", "0")
                    online_cache["count"] = int(float(val_str))
                    online_cache["last_updated"] = current_time
        except Exception as e:
            print(f"Failed to fetch online: {e}")
    
    return {"online": online_cache["count"]}

@app.post("/auth/change-password")
async def change_password(
    body: schemas.ChangePasswordRequest,
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    db.add(user)

    if user.activeTG and user.chatid:
        from aiogram import Bot
        bot = Bot(token=os.getenv("TG_BOT_TOKEN"))
        
        request_id = await bot_auth.send_confirmation_request(
            bot, user.chatid, "change_password", data={"new_password": body.new_password}
        )
        await bot.session.close()

        if not request_id:
            raise HTTPException(status_code=500, detail="Ошибка бота")
            
        return {"status": "confirmation_required", "request_id": request_id}

    else:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="Введите текущий пароль")
        
        if not auth_utils.verify_password(body.current_password, user.password):
            raise HTTPException(status_code=400, detail="Неверный текущий пароль")

        user.password = auth_utils.get_password_hash(body.new_password)
        db.commit()
        return {"status": "success", "message": "Пароль изменен"}

@app.post("/auth/request-unlink")
async def request_unlink(user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm)):
    if not user.activeTG or not user.chatid:
        raise HTTPException(status_code=400, detail="Telegram не привязан")

    from aiogram import Bot
    bot = Bot(token=os.getenv("TG_BOT_TOKEN"))
    
    request_id = await bot_auth.send_confirmation_request(bot, user.chatid, "unlink")
    await bot.session.close()
    
    if not request_id:
        raise HTTPException(status_code=500, detail="Ошибка бота")
        
    return {"request_id": request_id, "message": "Подтвердите действие в боте"}

@app.get("/auth/check-status/{request_id}")
def check_action_status(request_id: str):
    if request_id not in bot_auth.pending_confirmations:
         return {"status": "expired"}
    
    status = bot_auth.pending_confirmations[request_id]["status"]
    if status == "approved":
        del bot_auth.pending_confirmations[request_id]
        
    return {"status": status}

@app.get("/auth/generate-link")
def generate_tg_link():
    code = str(uuid.uuid4())
    bot_auth.login_attempts[code] = {"status": "pending", "created_at": time.time()}
    bot_name = os.getenv("TG_BOT_NAME", "BelugaEmpireBot")
    return {"link": f"https://t.me/{bot_name}?start={code}", "code": code}

@app.post("/auth/check-link")
def check_tg_link(body: dict, response: Response, db: Session = Depends(database.get_db)):
    code = body.get("code")
    if not code or code not in bot_auth.login_attempts:
        raise HTTPException(status_code=404, detail="Код устарел")
    
    attempt = bot_auth.login_attempts[code]
    if attempt["status"] == "ready":
        playername = attempt.get("playername")
        user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == playername).first()
        if not user:
            del bot_auth.login_attempts[code]
            raise HTTPException(status_code=404, detail="User not found")
            
        access_token = auth_utils.create_access_token(data={"sub": user.playername})
        response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=3600, samesite="lax", secure=False)
        del bot_auth.login_attempts[code]
        return {"status": "success"}

    return {"status": "pending"}

@app.get("/clans/top", response_model=list[schemas.ClanRankingItem])
def get_top_clans(all: bool = Query(False, description="Вернуть все кланы вместо ТОП-10"),
    db: Session = Depends(database.get_db)):
    
    rating_calc = cast(
        func.round(func.coalesce(models.ClanRating.final_rating, 0)), 
        Integer
    )

    results = db.query(
        models.ClanData.clan_name,
        models.ClanData.leader,
        models.ClanData.member_count,
        rating_calc.label("rating"),
        func.count(models.ClanWars.winner_clan).label("wins")
    ).outerjoin(
        models.ClanRating, models.ClanData.clan_name == models.ClanRating.clan_name
    ).outerjoin(
        models.ClanWars, models.ClanData.clan_name == models.ClanWars.winner_clan
    ).group_by(
        models.ClanData.clan_name
    ).order_by(
        desc("rating"), desc("wins")
    )

    if not all:
        results = results.limit(10)
    
    results = results.all()

    response = []
    for idx, row in enumerate(results):
        response.append({
            "rank": idx + 1,
            "name": row.clan_name,
            "leader": row.leader,
            "members": row.member_count,
            "rating": row.rating,
            "wins": row.wins
        })
        
    return response
    
@app.get("/clans/{clan_name}", response_model=schemas.ClanDetailsResponse)
def get_clan_details(clan_name: str, db: Session = Depends(database.get_db)):
    clan_data = db.query(models.ClanData).filter(models.ClanData.clan_name == clan_name).first()
    if not clan_data:
        raise HTTPException(status_code=404, detail="Клан не найден")

    rating_row = db.query(models.ClanRating).filter(models.ClanRating.clan_name == clan_name).first()
    current_rating = int(rating_row.final_rating) if rating_row else 0

    activity_row = db.query(models.ClanRating).filter(models.ClanRating.clan_name == clan_name).first()
    activity_points = activity_row.activity_score if activity_row else 0

    rank_position = db.query(models.ClanRating).filter(models.ClanRating.final_rating > (rating_row.final_rating if rating_row else 0)).count() + 1

    wins_count = db.query(models.ClanWars).filter(models.ClanWars.winner_clan == clan_name).count()

    losses_count = db.query(models.ClanWars).filter(
        or_(models.ClanWars.clan_a == clan_name, models.ClanWars.clan_b == clan_name),
        models.ClanWars.winner_clan != clan_name
    ).count()

    members_rows = db.query(models.ClanHeads).filter(models.ClanHeads.clan_name == clan_name).all()
    members_list = []
    
    role_map = {0: "MEMBER", 1: "ADMIN", 2: "LEADER"}

    for m in members_rows:
        role_str = role_map.get(m.role, "MEMBER") 
        members_list.append({
            "name": m.player_name,
            "role": role_str,
            "joined_date": "Давно"
        })

    members_list.sort(key=lambda x: {"LEADER": 0, "ADMIN": 1, "MEMBER": 2}[x["role"]])

    return {
        "name": clan_data.clan_name,
        "description": clan_data.clan_description or "Описание отсутствует",
        "leader": clan_data.leader,
        "rank_position": rank_position,
        "rating": current_rating,
        "rank_title": clan_data.clan_rank or "Новичок",
        "balance": int(clan_data.balance) if clan_data.balance else 0,
        "activity_points": activity_points,
        "stats": {
            "wins": wins_count,
            "losses": losses_count
        },
        "members": members_list
    }