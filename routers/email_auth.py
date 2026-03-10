import random
import time
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.database import get_db
from app.models import AuthTGUser, UserEmail
from app.schemas import EmailRequestSchema, EmailVerifySchema, EmailConfirmUnlinkSchema
from app.auth_utils import get_current_user_orm

load_dotenv()

router = APIRouter(
    prefix="/api/email",
    tags=["Email Binding"]
)

conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "noreply@example.com"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "password"),
    MAIL_FROM = os.getenv("MAIL_FROM", "noreply@example.com"),
    MAIL_PORT = int(os.getenv("MAIL_PORT", 465)),
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.example.com"),
    MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "False") == "True",
    MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "True") == "True",
    USE_CREDENTIALS = os.getenv("USE_CREDENTIALS", "True") == "True",
    VALIDATE_CERTS = os.getenv("VALIDATE_CERTS", "True") == "True"
)

email_verification_codes = {}

email_unlink_codes = {}

@router.post("/send-code")
async def send_verification_code(
    payload: EmailRequestSchema, 
    current_user: AuthTGUser = Depends(get_current_user_orm),
    db: Session = Depends(get_db)
):
    email = payload.email
    playername = current_user.playername

    existing_email = db.query(UserEmail).filter(UserEmail.email == email).first()
    if existing_email and existing_email.nickname != playername:
        raise HTTPException(status_code=400, detail="Эта почта уже привязана к другому аккаунту.")

    code = str(random.randint(100000, 999999))
    
    email_verification_codes[email] = {
        "code": code,
        "expires_at": time.time() + 300,
        "playername": playername
    }

    html_content = f"""
    <div style="font-family: Arial, sans-serif; background-color: #0f172a; color: #fff; padding: 20px; border-radius: 10px;">
        <h2 style="color: #06b6d4;">BelugaEmpire</h2>
        <p>Привет, {playername}!</p>
        <p>Твой код для привязки почты:</p>
        <h1 style="color: #fbbf24; letter-spacing: 5px;">{code}</h1>
        <p style="color: #94a3b8; font-size: 12px;">Код действителен 5 минут. Если ты не запрашивал привязку, просто проигнорируй это письмо.</p>
    </div>
    """

    message = MessageSchema(
        subject="Код подтверждения BelugaEmpire",
        recipients=[email],
        body=html_content,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
    except Exception as e:
        print(f"SMTP Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при отправке письма. Проверьте настройки SMTP.")

    return {"message": "Код успешно отправлен"}


@router.post("/verify")
async def verify_email_code(
    payload: EmailVerifySchema, 
    current_user: AuthTGUser = Depends(get_current_user_orm),
    db: Session = Depends(get_db)
):
    email = payload.email
    code = payload.code
    playername = current_user.playername

    record = email_verification_codes.get(email)
    
    if not record:
        raise HTTPException(status_code=400, detail="Код не найден или вы не запрашивали привязку.")
    
    if time.time() > record["expires_at"]:
        del email_verification_codes[email]
        raise HTTPException(status_code=400, detail="Срок действия кода истек. Запросите новый.")
        
    if record["playername"] != playername:
        raise HTTPException(status_code=403, detail="Этот код запрошен для другого пользователя.")

    if record["code"] != code:
        raise HTTPException(status_code=400, detail="Неверный код.")

    user_email_db = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    
    if user_email_db:
        user_email_db.email = email
        user_email_db.is_verified = True
    else:
        new_email = UserEmail(
            nickname=playername,
            email=email,
            is_verified=True
        )
        db.add(new_email)
    
    db.commit()

    del email_verification_codes[email]

    return {"message": "Почта успешно привязана!"}

@router.post("/request-unlink")
async def request_unlink_email(
    current_user: AuthTGUser = Depends(get_current_user_orm),
    db: Session = Depends(get_db)
):
    playername = current_user.playername
    user_email_db = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    
    if not user_email_db:
        raise HTTPException(status_code=400, detail="Почта не привязана.")
        
    email = user_email_db.email
    code = str(random.randint(100000, 999999))
    
    email_unlink_codes[playername] = {
        "code": code,
        "expires_at": time.time() + 300
    }

    html_content = f"""
    <div style="font-family: Arial, sans-serif; background-color: #0f172a; color: #fff; padding: 20px; border-radius: 10px;">
        <h2 style="color: #ef4444;">Внимание, {playername}!</h2>
        <p>Поступил запрос на <b>отвязку</b> электронной почты от вашего аккаунта BelugaEmpire.</p>
        <p>Код для подтверждения отвязки:</p>
        <h1 style="color: #fbbf24; letter-spacing: 5px;">{code}</h1>
        <p style="color: #94a3b8; font-size: 12px;">Код действителен 5 минут. Если это были не вы, срочно измените пароль от аккаунта!</p>
    </div>
    """

    message = MessageSchema(
        subject="Отвязка почты BelugaEmpire",
        recipients=[email],
        body=html_content,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
    except Exception as e:
        print(f"SMTP Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при отправке письма.")

    return {"message": "Код для отвязки отправлен."}


@router.post("/confirm-unlink")
async def confirm_unlink_email(
    payload: EmailConfirmUnlinkSchema,
    current_user: AuthTGUser = Depends(get_current_user_orm),
    db: Session = Depends(get_db)
):
    playername = current_user.playername
    code = payload.code

    record = email_unlink_codes.get(playername)
    
    if not record:
        raise HTTPException(status_code=400, detail="Код не найден или срок действия истек.")
    
    if time.time() > record["expires_at"]:
        del email_unlink_codes[playername]
        raise HTTPException(status_code=400, detail="Срок действия кода истек.")

    if record["code"] != code:
        raise HTTPException(status_code=400, detail="Неверный код.")

    user_email_db = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    if user_email_db:
        db.delete(user_email_db)
        db.commit()

    del email_unlink_codes[playername]

    return {"message": "Почта успешно отвязана!"}