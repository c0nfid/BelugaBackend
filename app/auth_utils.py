import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

# 1. Хеширование пароля (как в Java коде)
def get_password_hash(password: str) -> str:
    """SHA-256 hash returned as hex string"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    # Сравниваем хеш введенного пароля с тем, что в базе
    return get_password_hash(plain_password).lower() == hashed_password.lower()

# 2. JWT Токены
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# 3. Валидация Telegram Login Widget
def verify_telegram_data(data: dict) -> bool:
    """
    Проверка подписи данных от Telegram Login Widget.
    """
    if not TG_BOT_TOKEN:
        return False
        
    check_hash = data.get('hash')
    if not check_hash:
        return False

    # Формируем строку проверки данных
    data_check_arr = []
    for key, value in data.items():
        if key != 'hash':
            data_check_arr.append(f'{key}={value}')
    
    data_check_arr.sort()
    data_check_string = '\n'.join(data_check_arr)
    
    # Создаем секретный ключ из токена бота
    secret_key = hashlib.sha256(TG_BOT_TOKEN.encode()).digest()
    
    # Хешируем строку данных
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    return hmac_hash == check_hash
