import os
import uuid
import time
import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from . import models, schemas, database, auth_utils, bot_auth

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

def get_token_from_cookie(access_token: Optional[str] = Cookie(None)):
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return access_token

def get_current_user_orm(token: str = Depends(get_token_from_cookie), db: Session = Depends(database.get_db)):
    try:
        payload = jwt.decode(token, auth_utils.SECRET_KEY, algorithms=[auth_utils.ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

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
def read_users_me(user: models.AuthTGUser = Depends(get_current_user_orm), db: Session = Depends(database.get_db)):
    player_data = db.query(models.PlayerData).filter(models.PlayerData.player_name == user.playername).first()
    playtime_data = db.query(models.PlayerPlaytime).filter(models.PlayerPlaytime.player_name == user.playername).first()
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
        "playtime_seconds": playtime_data.total_seconds if playtime_data else 0
    }

@app.post("/auth/change-password")
async def change_password(
    body: schemas.ChangePasswordRequest,
    user: models.AuthTGUser = Depends(get_current_user_orm),
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
async def request_unlink(user: models.AuthTGUser = Depends(get_current_user_orm)):
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

# --- TELEGRAM LOGIN (DEEP LINK) ---

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