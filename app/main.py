import os
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from . import models, schemas, database, auth_utils

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()

# --- CORS ---
cors_origins_str = os.getenv("CORS_ORIGINS", "")
origins = [origin.strip() for origin in cors_origins_str.split(",") if origin]
if not origins:
    origins = ["http://localhost:5173"]

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

# --- ENDPOINTS ---

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
        max_age=3600, # Время жизни токена
        samesite="lax",
        secure=False      # Важно: False для http (на локалке), True только для https
    )
    return {"message": "Login successful"}

@app.post("/auth/telegram")
def login_telegram(
    tg_data: schemas.TelegramLoginRequest, 
    response: Response,
    db: Session = Depends(database.get_db)
):
    data_dict = tg_data.model_dump(exclude_none=True)
    
    if not auth_utils.verify_telegram_data(data_dict):
        raise HTTPException(status_code=403, detail="Invalid Telegram signature")

    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == tg_data.id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Аккаунт не привязан к этому Telegram")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=3600, # Время жизни токена
        samesite="lax",
        secure=False      # Важно: False для http (на локалке), True только для https
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
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == username).first()
    if user is None:
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