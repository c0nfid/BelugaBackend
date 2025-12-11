import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from . import models, schemas, database, auth_utils

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()

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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- ENDPOINTS ---

@app.post("/login", response_model=schemas.Token)
def login_with_password(creds: schemas.LoginRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == creds.username).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    
    if not auth_utils.verify_password(creds.password, user.password):
        raise HTTPException(status_code=400, detail="Неверный пароль")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/telegram", response_model=schemas.Token)
def login_telegram(tg_data: schemas.TelegramLoginRequest, db: Session = Depends(database.get_db)):
    data_dict = tg_data.model_dump(exclude_none=True)
    
    if not auth_utils.verify_telegram_data(data_dict):
        raise HTTPException(status_code=403, detail="Invalid Telegram signature")

    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.chatid == tg_data.id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Аккаунт не привязан к этому Telegram")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me", response_model=schemas.UserResponse)
def read_users_me(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
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
        
    return user
