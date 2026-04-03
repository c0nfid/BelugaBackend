import random
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuthTGUser, UserEmail
from app.schemas import EmailRequestSchema, EmailVerifySchema, EmailConfirmUnlinkSchema
from app.auth_utils import get_current_user_orm
from app.email_utils import send_email, get_email_template
router = APIRouter(
    prefix="/api/email",
    tags=["Email Binding"]
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

    html = get_email_template(
        playername=playername,
        title="Привет",
        description="Твой код для привязки электронной почты:",
        code=code,
        warning="Код действителен 5 минут. Если ты не запрашивал привязку, просто проигнорируй это письмо."
    )

    try:
        await send_email(email, f"Код подтверждения BelugaEmpire {code}", html)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при отправке письма.")

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
    
    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Код не найден или истек.")
    if record["playername"] != playername:
        raise HTTPException(status_code=403, detail="Доступ запрещен.")
    if record["code"] != code:
        raise HTTPException(status_code=400, detail="Неверный код.")

    user_email_db = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    if user_email_db:
        user_email_db.email = email
        user_email_db.is_verified = True
    else:
        new_email = UserEmail(nickname=playername, email=email, is_verified=True)
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
    user_email = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    
    if not user_email:
        raise HTTPException(status_code=400, detail="Почта не привязана.")
        
    code = str(random.randint(100000, 999999))
    email_unlink_codes[playername] = {"code": code, "expires_at": time.time() + 300}

    html = get_email_template(
        playername=playername,
        title="Внимание",
        description="Поступил запрос на <b>отвязку</b> электронной почты от вашего аккаунта BelugaEmpire. Если это были вы, введите код ниже:",
        code=code,
        warning="Код действителен 5 минут. Если это были не вы, срочно измените пароль от аккаунта!"
    )

    try:
        await send_email(user_email.email, f"Отвязка почты BelugaEmpire {code}", html)
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при отправке письма.")

    return {"message": "Код отправлен."}

@router.post("/confirm-unlink")
async def confirm_unlink_email(
    payload: EmailConfirmUnlinkSchema,
    current_user: AuthTGUser = Depends(get_current_user_orm),
    db: Session = Depends(get_db)
):
    playername = current_user.playername
    record = email_unlink_codes.get(playername)
    
    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Код не найден или истек.")
    if record["code"] != payload.code:
        raise HTTPException(status_code=400, detail="Неверный код.")

    user_email = db.query(UserEmail).filter(UserEmail.nickname == playername).first()
    if user_email:
        db.delete(user_email)
        db.commit()

    del email_unlink_codes[playername]
    return {"message": "Почта успешно отвязана!"}