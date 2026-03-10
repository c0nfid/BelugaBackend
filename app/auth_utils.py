import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Cookie
from sqlalchemy.orm import Session

from . import database, models

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

def get_password_hash(password: str) -> str:
    """SHA-256 hash returned as hex string"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return get_password_hash(plain_password).lower() == hashed_password.lower()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_telegram_data(data: dict) -> bool:
    """
    Проверка подписи данных от Telegram Login Widget.
    """
    if not TG_BOT_TOKEN:
        return False
        
    check_hash = data.get('hash')
    if not check_hash:
        return False

    data_check_arr = []
    for key, value in data.items():
        if key != 'hash':
            data_check_arr.append(f'{key}={value}')
    
    data_check_arr.sort()
    data_check_string = '\n'.join(data_check_arr)
    
    secret_key = hashlib.sha256(TG_BOT_TOKEN.encode()).digest()
    
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return hmac_hash == check_hash

def get_token_from_cookie(access_token: Optional[str] = Cookie(None)):
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return access_token

def get_current_user_orm(token: str = Depends(get_token_from_cookie), db: Session = Depends(database.get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user