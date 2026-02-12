import os
import uuid
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
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

app = FastAPI(lifespan=lifespan)

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return access_token

@app.post("/login")
def login_with_password(
    creds: schemas.LoginRequest, 
    response: Response, 
    db: Session = Depends(database.get_db)
):
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == creds.username).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    
    if not auth_utils.verify_password(creds.password, user.password):
        raise HTTPException(status_code=400, detail="Неверный пароль")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=3600,
        samesite="lax",
        secure=False
    )
    return {"message": "Login successful"}

@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Logged out"}

@app.get("/me", response_model=schemas.UserResponse)
def read_users_me(
    token: str = Depends(get_token_from_cookie), 
    db: Session = Depends(database.get_db)
):
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

    player_data = db.query(models.PlayerData).filter(models.PlayerData.player_name == user.playername).first()

    return {
        "playername": user.playername,
        "uuid": user.uuid,
        "activeTG": user.activeTG,
        "tg_username": user.username,
        "admin": user.admin,
        "clan_name": player_data.clan_name if player_data else None,
        "last_login": player_data.login_timestamp if player_data else None
    }

# ================= TELEGRAM DEEP LINK AUTH =================
@app.get("/auth/generate-link")
def generate_tg_link():
    code = str(uuid.uuid4())

    bot_auth.login_attempts[code] = {
        "status": "pending",
        "created_at": time.time()
    }
    
    bot_name = os.getenv("TG_BOT_NAME", "BelugaEmpireBot")
    
    return {
        "link": f"https://t.me/{bot_name}?start={code}",
        "code": code
    }

@app.post("/auth/check-link")
def check_tg_link(
    body: dict, 
    response: Response,
    db: Session = Depends(database.get_db)
):
    code = body.get("code")
    
    if not code or code not in bot_auth.login_attempts:
        raise HTTPException(status_code=404, detail="Код устарел или не найден")
        
    attempt = bot_auth.login_attempts[code]
    
    if time.time() - attempt.get("created_at", 0) > bot_auth.CODE_TTL:
        del bot_auth.login_attempts[code]
        raise HTTPException(status_code=404, detail="Код истек")

    if attempt["status"] == "pending":
        return {"status": "pending"}

    if attempt["status"] == "ready":
        playername = attempt.get("playername")
        
        user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == playername).first()
        if not user:
            del bot_auth.login_attempts[code]
            raise HTTPException(status_code=404, detail="Пользователь не найден")
            
        access_token = auth_utils.create_access_token(data={"sub": user.playername})
        
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=3600,
            samesite="lax",
            secure=False
        )
        
        del bot_auth.login_attempts[code]
        
        return {"status": "success"}