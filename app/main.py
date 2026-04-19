import os
import re
import uuid
import time
import asyncio
import secrets
import requests
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Integer, or_

from collections import defaultdict

from app.security_challenges import password_recovery_challenges
from . import models, schemas, database, auth_utils, bot_auth
from routers import wiki, email_auth, shop

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
app.include_router(shop.router)


def get_current_username_docs(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, os.getenv("SWAGGER_USER", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("SWAGGER_PASSWORD", "admin"))
    if not (correct_user and correct_password):
        raise HTTPException(status_code=401, detail="Incorrect auth", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def check_group_permission(db: Session, group_name: str, target_perm: str) -> bool:
    if not group_name:
        return False

    visited = set()
    queue = [group_name.lower()]

    while queue:
        current_group = queue.pop(0)
        if current_group in visited:
            continue
        visited.add(current_group)

        perms = db.query(
            models.LuckpermsGroupPermission.permission,
            models.LuckpermsGroupPermission.value
        ).filter(
            models.LuckpermsGroupPermission.name == current_group
        ).all()

        for perm, val in perms:
            if perm == target_perm and val == 1:
                return True
            if perm.startswith("group.") and val == 1:
                parent_group = perm[6:]
                if parent_group not in visited:
                    queue.append(parent_group)
    return False


def mask_email(email: str) -> str:
    email_parts = email.split('@')
    if len(email_parts) != 2:
        return "***"
    local, domain = email_parts
    if len(local) > 2:
        return local[:2] + "***@" + domain
    return "***@" + domain

def mask_telegram_username(username: Optional[str]) -> str:
    if not username:
        return "Привязанный Telegram"

    clean = username.lstrip("@")
    if len(clean) <= 2:
        return f"@{clean}***"

    return f"@{clean[:2]}***"

def get_user_security_methods(db: Session, user: models.AuthTGUser) -> list[dict]:
    methods = []

    if user.activeTG and user.chatid:
        tg_label = "Telegram"
        tg_mask = f"@{user.username}" if user.username else "Привязанный Telegram"
        methods.append({
            "method": "telegram",
            "label": "Telegram",
            "masked_destination": mask_telegram_username(user.username),
        })

    user_email = db.query(models.UserEmail).filter(
        models.UserEmail.nickname == user.playername,
        models.UserEmail.is_verified == True
    ).first()

    if user_email:
        methods.append({
            "method": "email",
            "label": "Email",
            "masked_destination": mask_email(user_email.email),
        })

    return methods


@app.get("/api/docs", include_in_schema=False)
async def get_swagger_documentation(username: str = Depends(get_current_username_docs)):
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Beluga API Docs")


@app.get("/api/openapi.json", include_in_schema=False)
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

CACHE_TTL = 300

password_change_codes = {}
login_email_codes = {}

PH_HOST = os.getenv("PLACEHOLDER_API_HOST")
PH_PORT = os.getenv("PLACEHOLDER_API_PORT")


@app.post("/api/login")
async def login_with_password(creds: schemas.LoginRequest, response: Response, db: Session = Depends(database.get_db)):
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == creds.username).first()
    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    if not auth_utils.verify_password(creds.password, user.password):
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    user_email = db.query(models.UserEmail).filter(models.UserEmail.nickname == user.playername).first()

    if user_email and user_email.is_verified:
        code = str(secrets.randbelow(900000) + 100000)

        login_email_codes[user.playername] = {
            "code": code,
            "expires_at": time.time() + 300
        }

        from app.email_utils import send_email, get_email_template

        html = get_email_template(
            playername=user.playername,
            title="Вход в аккаунт",
            description="Поступил запрос на вход в ваш личный кабинет BelugaEmpire. Для завершения авторизации введите код:",
            code=code,
            warning="Код действителен 5 минут. Если вы не пытались войти на сайт, немедленно смените пароль!"
        )

        try:
            await send_email(user_email.email, f"Код для входа BelugaEmpire {code}", html)
        except Exception as e:
            print(f"SMTP Error: {e}")
            raise HTTPException(status_code=500, detail="Ошибка при отправке письма с кодом")

        return {
            "status": "confirmation_required",
            "method": "email",
            "masked_email": mask_email(user_email.email),
            "message": "Требуется код из письма"
        }

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=3600, samesite="lax", secure=False)
    return {"status": "success", "message": "Login successful"}


@app.post("/api/auth/confirm-login")
def confirm_login(payload: schemas.EmailConfirmLoginSchema, response: Response, db: Session = Depends(database.get_db)):
    user = db.query(models.AuthTGUser).filter(models.AuthTGUser.playername == payload.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    record = login_email_codes.get(user.playername)

    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Код не найден или срок действия истек")

    if record["code"] != payload.code:
        raise HTTPException(status_code=400, detail="Неверный код")

    access_token = auth_utils.create_access_token(data={"sub": user.playername})
    response.set_cookie(key="access_token", value=access_token, httponly=True, max_age=3600, samesite="lax", secure=False)

    del login_email_codes[user.playername]

    return {"status": "success", "message": "Login successful"}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "Logged out"}


@app.get("/api/me", response_model=schemas.UserResponse)
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

    fake_nick_data = db.query(models.FakeNick).filter(models.FakeNick.player_name == user.playername).first()

    active_ban = db.query(models.BannedPlayer).filter(
        models.BannedPlayer.player_name == user.playername,
        models.BannedPlayer.isActive == 1
    ).order_by(desc(models.BannedPlayer.id)).first()

    total_bans = db.query(models.BannedPlayer).filter(
        models.BannedPlayer.player_name == user.playername
    ).count()

    is_banned = False
    if active_ban:
        if active_ban.ban_duration == -1:
            is_banned = True
        else:
            expires_at = active_ban.ban_timestamp + active_ban.ban_duration
            if current_time_ms < expires_at:
                is_banned = True

    session_duration = 0
    if login_ts > 0:
        if login_ts > logout_ts:
            session_duration = (current_time_ms - login_ts) // 1000
        else:
            session_duration = (logout_ts - login_ts) // 1000

    if session_duration < 0:
        session_duration = 0

    group = player_data.primary_group if (player_data and player_data.primary_group) else "default"
    can_edit = check_group_permission(db, group, "essentials.nick")

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
        "is_email_verified": user_email_data.is_verified if user_email_data else False,

        "fake_player_name": fake_nick_data.fake_player_name if fake_nick_data else None,
        "can_edit_nickname": can_edit,

        "is_banned": is_banned,
        "ban_reason": active_ban.reason if is_banned else None,
        "ban_timestamp": active_ban.ban_timestamp if is_banned else None,
        "ban_duration": active_ban.ban_duration if is_banned else None,
        "ban_by": active_ban.ban_by if is_banned else None,
        "total_bans": total_bans
    }


@app.get("/api/server/online")
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


@app.get("/api/auth/change-password/options", response_model=schemas.ChangePasswordOptionsResponse)
def get_change_password_options(
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    return {"methods": get_user_security_methods(db, user)}


@app.post("/api/auth/change-password")
async def change_password(
    body: schemas.ChangePasswordRequest,
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    is_valid, err_msg = auth_utils.validate_password(body.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)

    methods = get_user_security_methods(db, user)
    available_methods = {m["method"] for m in methods}

    if available_methods:
        selected_method = body.method

        if not selected_method:
            if len(methods) == 1:
                selected_method = methods[0]["method"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Выберите способ подтверждения."
                )

        if selected_method not in available_methods:
            raise HTTPException(
                status_code=400,
                detail="Выбранный способ подтверждения недоступен."
            )

        if selected_method == "telegram":
            from app.bot_auth import get_bot
            bot = get_bot()

            request_id = await bot_auth.send_confirmation_request(
                bot,
                user.chatid,
                "change_password",
                data={"new_password": body.new_password}
            )
            await bot.session.close()

            if not request_id:
                raise HTTPException(status_code=500, detail="Ошибка бота")

            return {
                "status": "confirmation_required",
                "method": "telegram",
                "request_id": request_id
            }

        if selected_method == "email":
            user_email = db.query(models.UserEmail).filter(
                models.UserEmail.nickname == user.playername,
                models.UserEmail.is_verified == True
            ).first()

            if not user_email:
                raise HTTPException(status_code=400, detail="Подтвержденная почта не найдена.")

            code = str(secrets.randbelow(900000) + 100000)

            password_change_codes[user.playername] = {
                "code": code,
                "new_password": body.new_password,
                "expires_at": time.time() + 300
            }

            from app.email_utils import send_email, get_email_template

            html = get_email_template(
                playername=user.playername,
                title="Смена пароля",
                description="Поступил запрос на изменение пароля от вашего аккаунта BelugaEmpire. Если это были вы, введите код ниже:",
                code=code,
                warning="Код действителен 5 минут. Если вы не запрашивали смену пароля, кто-то пытается получить доступ к вашему аккаунту!"
            )

            try:
                await send_email(user_email.email, "Смена пароля BelugaEmpire", html)
            except Exception as e:
                print(f"SMTP Error: {e}")
                raise HTTPException(status_code=500, detail="Ошибка при отправке письма")

            return {
                "status": "confirmation_required",
                "method": "email",
                "masked_email": mask_email(user_email.email)
            }

        raise HTTPException(status_code=400, detail="Неизвестный способ подтверждения.")

    if not body.current_password:
        raise HTTPException(
            status_code=400,
            detail="У вас не привязан Telegram или Email. Введите текущий пароль для подтверждения смены."
        )

    if not auth_utils.verify_password(body.current_password, user.password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")

    user.password = auth_utils.get_password_hash(body.new_password)
    db.commit()

    return {"status": "success", "message": "Пароль изменен"}


@app.post("/api/auth/confirm-change-password")
async def confirm_change_password(
    payload: schemas.EmailConfirmPasswordSchema,
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    record = password_change_codes.get(user.playername)

    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Код не найден или истек")

    if record["code"] != payload.code:
        raise HTTPException(status_code=400, detail="Неверный код")

    user.password = auth_utils.get_password_hash(record["new_password"])
    db.commit()

    del password_change_codes[user.playername]

    return {"status": "success", "message": "Пароль успешно изменен"}


@app.post("/api/auth/recovery/options", response_model=schemas.RecoveryOptionsResponse)
async def get_recovery_options(
    body: schemas.ForgotPasswordRequest,
    db: Session = Depends(database.get_db)
):
    user = db.query(models.AuthTGUser).filter(
        models.AuthTGUser.playername == body.username
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="Игрок с таким никнеймом не найден.")

    methods = get_user_security_methods(db, user)

    if not methods:
        raise HTTPException(
            status_code=400,
            detail="К аккаунту не привязаны способы подтверждения. Обратитесь в поддержку."
        )

    return {
        "status": "ok",
        "username": user.playername,
        "methods": methods,
    }


@app.post("/api/auth/recovery/start", response_model=schemas.RecoveryStartResponse)
async def start_password_recovery(
    body: schemas.RecoveryStartRequest,
    db: Session = Depends(database.get_db)
):
    user = db.query(models.AuthTGUser).filter(
        models.AuthTGUser.playername == body.username
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="Игрок с таким никнеймом не найден.")

    methods = get_user_security_methods(db, user)
    available_methods = {m["method"] for m in methods}

    if body.method not in available_methods:
        raise HTTPException(status_code=400, detail="Выбранный способ подтверждения недоступен.")

    challenge_id = str(uuid.uuid4())
    password_recovery_challenges[challenge_id] = {
        "username": user.playername,
        "method": body.method,
        "status": "pending",
        "expires_at": time.time() + 300,
    }

    if body.method == "email":
        user_email = db.query(models.UserEmail).filter(
            models.UserEmail.nickname == user.playername,
            models.UserEmail.is_verified == True
        ).first()

        if not user_email:
            raise HTTPException(status_code=400, detail="Подтвержденная почта не найдена.")

        code = str(secrets.randbelow(900000) + 100000)
        password_recovery_challenges[challenge_id]["code"] = code

        from app.email_utils import send_email, get_email_template

        html = get_email_template(
            playername=user.playername,
            title="Восстановление пароля",
            description="Поступил запрос на восстановление пароля от вашего аккаунта BelugaEmpire. Введите код ниже:",
            code=code,
            warning="Код действителен 5 минут. Если это были не вы, срочно проверьте безопасность аккаунта."
        )

        try:
            await send_email(
                user_email.email,
                f"Восстановление пароля BelugaEmpire {code}",
                html
            )
        except Exception as e:
            print(f"SMTP Error: {e}")
            raise HTTPException(status_code=500, detail="Ошибка при отправке письма.")

        return {
            "status": "confirmation_required",
            "method": "email",
            "challenge_id": challenge_id,
            "masked_destination": mask_email(user_email.email),
            "message": "Код отправлен на почту",
        }

    if body.method == "telegram":
        from app.bot_auth import get_bot
        bot = get_bot()

        request_id = await bot_auth.send_confirmation_request(
            bot,
            user.chatid,
            "reset_password",
            data={
                "challenge_id": challenge_id,
                "username": user.playername,
            }
        )
        await bot.session.close()

        if not request_id:
            raise HTTPException(status_code=500, detail="Ошибка Telegram-подтверждения.")

        password_recovery_challenges[challenge_id]["request_id"] = request_id

        return {
            "status": "confirmation_required",
            "method": "telegram",
            "challenge_id": challenge_id,
            "request_id": request_id,
            "message": "Подтвердите восстановление пароля в Telegram",
        }

    raise HTTPException(status_code=400, detail="Неизвестный способ подтверждения.")


@app.post("/api/auth/recovery/confirm-email")
async def confirm_recovery_email(
    body: schemas.RecoveryConfirmEmailRequest
):
    record = password_recovery_challenges.get(body.challenge_id)

    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Сессия восстановления истекла.")

    if record["method"] != "email":
        raise HTTPException(status_code=400, detail="Неверный тип подтверждения.")

    if record.get("code") != body.code:
        raise HTTPException(status_code=400, detail="Неверный код.")

    record["status"] = "approved"
    record.pop("code", None)

    return {
        "status": "approved",
        "challenge_id": body.challenge_id,
        "message": "Подтверждение прошло успешно",
    }


@app.post("/api/auth/recovery/reset")
async def recovery_reset_password(
    body: schemas.RecoveryResetRequest,
    db: Session = Depends(database.get_db)
):
    record = password_recovery_challenges.get(body.challenge_id)

    if not record or time.time() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Сессия восстановления истекла.")

    if record.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Подтверждение восстановления не завершено.")

    is_valid, err_msg = auth_utils.validate_password(body.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=err_msg)

    user = db.query(models.AuthTGUser).filter(
        models.AuthTGUser.playername == record["username"]
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    user.password = auth_utils.get_password_hash(body.new_password)
    db.commit()

    del password_recovery_challenges[body.challenge_id]

    return {
        "status": "success",
        "message": "Пароль успешно изменен."
    }


@app.post("/api/auth/request-unlink")
async def request_unlink(user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm)):
    if not user.activeTG or not user.chatid:
        raise HTTPException(status_code=400, detail="Telegram не привязан")

    from app.bot_auth import get_bot
    bot = get_bot()

    request_id = await bot_auth.send_confirmation_request(bot, user.chatid, "unlink")
    await bot.session.close()

    if not request_id:
        raise HTTPException(status_code=500, detail="Ошибка бота")

    return {"request_id": request_id, "message": "Подтвердите действие в боте"}


@app.get("/api/auth/check-status/{request_id}")
def check_action_status(request_id: str):
    if request_id not in bot_auth.pending_confirmations:
        return {"status": "expired"}

    status = bot_auth.pending_confirmations[request_id]["status"]
    if status == "approved":
        del bot_auth.pending_confirmations[request_id]

    return {"status": status}


@app.get("/api/auth/generate-link")
def generate_tg_link():
    code = str(uuid.uuid4())
    bot_auth.login_attempts[code] = {"status": "pending", "created_at": time.time()}
    bot_name = os.getenv("TG_BOT_NAME", "BelugaEmpireBot")
    return {"link": f"https://t.me/{bot_name}?start={code}", "code": code}


@app.post("/api/auth/check-link")
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


@app.get("/api/clans/top", response_model=list[schemas.ClanRankingItem])
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


@app.get("/api/clans/{clan_name}", response_model=schemas.ClanDetailsResponse)
def get_clan_details(clan_name: str, db: Session = Depends(database.get_db)):
    clan_data = db.query(models.ClanData).filter(models.ClanData.clan_name == clan_name).first()
    if not clan_data:
        raise HTTPException(status_code=404, detail="Клан не найден")

    rating_row = db.query(models.ClanRating).filter(models.ClanRating.clan_name == clan_name).first()
    current_rating = int(rating_row.final_rating) if rating_row else 0

    activity_row = db.query(models.ClanRating).filter(models.ClanRating.clan_name == clan_name).first()
    activity_points = activity_row.activity_score if activity_row else 0

    rank_position = db.query(models.ClanRating).filter(
        models.ClanRating.final_rating > (rating_row.final_rating if rating_row else 0)
    ).count() + 1

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


@app.get("/api/pvp/top", response_model=list[schemas.PvPRankingItem])
def get_top_pvp(db: Session = Depends(database.get_db)):
    results = db.query(
        models.PlayerPvpDaily.player_name.label("raw_name"),
        models.AuthTGUser.playername.label("real_name"),
        models.PlayerData.clan_name,
        func.sum(models.PlayerPvpDaily.valid_kills).label("total_kills"),
        func.sum(models.PlayerPvpDaily.valid_deaths).label("total_deaths")
    ).outerjoin(
        models.AuthTGUser,
        models.PlayerPvpDaily.player_name == models.AuthTGUser.playername
    ).outerjoin(
        models.PlayerData,
        models.PlayerPvpDaily.player_name == models.PlayerData.player_name
    ).group_by(
        models.PlayerPvpDaily.player_name,
        models.AuthTGUser.playername,
        models.PlayerData.clan_name
    ).having(
        func.sum(models.PlayerPvpDaily.valid_kills) > 0
    ).order_by(
        desc("total_kills"), "total_deaths"
    ).all()

    response = []
    for idx, row in enumerate(results):
        kills = int(row.total_kills or 0)
        deaths = int(row.total_deaths or 0)

        kd_ratio = round(kills / (deaths if deaths > 0 else 1), 2)

        final_name = row.real_name if row.real_name else row.raw_name

        response.append({
            "rank": idx + 1,
            "player_name": final_name,
            "clan_name": row.clan_name,
            "kills": kills,
            "deaths": deaths,
            "kd": kd_ratio
        })

    return response


@app.get("/api/economy/top", response_model=list[schemas.EconomyRankingItem])
def get_top_economy(db: Session = Depends(database.get_db)):
    results = db.query(
        models.PlayerData.player_name.label("raw_name"),
        models.AuthTGUser.playername.label("real_name"),
        models.PlayerData.clan_name,
        models.PlayerData.balance
    ).outerjoin(
        models.AuthTGUser,
        models.PlayerData.player_name == models.AuthTGUser.playername
    ).filter(
        models.PlayerData.balance > 0
    ).order_by(
        desc(models.PlayerData.balance)
    ).all()

    response = []
    for idx, row in enumerate(results):
        final_name = row.real_name if row.real_name else row.raw_name
        response.append({
            "rank": idx + 1,
            "player_name": final_name,
            "clan_name": row.clan_name,
            "balance": float(row.balance)
        })

    return response


def _get_active_bosses(db: Session) -> tuple[list[models.Boss], list[str], dict[str, models.Boss]]:
    bosses = db.query(models.Boss).filter(models.Boss.is_active == True).all()
    boss_names = [boss.name for boss in bosses]
    boss_map = {boss.name: boss for boss in bosses}
    return bosses, boss_names, boss_map


@app.get("/api/bosses/top-slayers", response_model=list[schemas.BossSlayerItem])
def get_top_boss_slayers(db: Session = Depends(database.get_db)):
    results = (
        db.query(
            models.MMKill.uuid.label("uuid"),
            models.MMPlayer.last_name.label("player_name"),
            func.sum(models.MMKill.kills).label("total_kills")
        )
        .join(models.Boss, models.Boss.name == models.MMKill.mob)
        .outerjoin(models.MMPlayer, models.MMPlayer.uuid == models.MMKill.uuid)
        .filter(
            models.Boss.is_active == True,
            models.MMKill.kills > 0
        )
        .group_by(models.MMKill.uuid, models.MMPlayer.last_name)
        .having(func.sum(models.MMKill.kills) > 0)
        .order_by(desc("total_kills"), models.MMPlayer.last_name)
        .all()
    )

    if not results:
        return []

    player_names = [row.player_name for row in results if row.player_name]
    clan_map = {}

    if player_names:
        clan_rows = (
            db.query(models.PlayerData.player_name, models.PlayerData.clan_name)
            .filter(models.PlayerData.player_name.in_(player_names))
            .all()
        )
        clan_map = {row.player_name: row.clan_name for row in clan_rows}

    response = []
    for idx, row in enumerate(results, start=1):
        final_name = row.player_name or row.uuid
        response.append({
            "rank": idx,
            "player_name": final_name,
            "clan_name": clan_map.get(final_name.lower()),
            "total_kills": int(row.total_kills or 0),
        })

    return response


@app.get("/api/bosses/stats", response_model=list[schemas.BossStatItem])
def get_bosses_stats(db: Session = Depends(database.get_db)):
    total_rows = (
        db.query(
            models.Boss.name.label("mob_id"),
            models.Boss.display_name.label("display_name"),
            models.Boss.dungeon_name.label("dungeon_name"),
            func.coalesce(func.sum(models.MMKill.kills), 0).label("total_kills")
        )
        .outerjoin(models.MMKill, models.MMKill.mob == models.Boss.name)
        .filter(models.Boss.is_active == True)
        .group_by(models.Boss.name, models.Boss.display_name, models.Boss.dungeon_name)
        .all()
    )

    per_player_rows = (
        db.query(
            models.MMKill.mob.label("mob_id"),
            models.MMKill.uuid.label("uuid"),
            models.MMPlayer.last_name.label("player_name"),
            func.sum(models.MMKill.kills).label("player_kills")
        )
        .join(models.Boss, models.Boss.name == models.MMKill.mob)
        .outerjoin(models.MMPlayer, models.MMPlayer.uuid == models.MMKill.uuid)
        .filter(
            models.Boss.is_active == True,
            models.MMKill.kills > 0
        )
        .group_by(models.MMKill.mob, models.MMKill.uuid, models.MMPlayer.last_name)
        .order_by(models.MMKill.mob, desc("player_kills"), models.MMPlayer.last_name)
        .all()
    )

    top_by_boss = {}
    for row in per_player_rows:
        if row.mob_id not in top_by_boss:
            top_by_boss[row.mob_id] = {
                "top_slayer_name": row.player_name or row.uuid,
                "top_slayer_kills": int(row.player_kills or 0),
            }

    response = []
    for row in total_rows:
        top = top_by_boss.get(row.mob_id, {})
        response.append({
            "mob_id": row.mob_id,
            "display_name": row.display_name,
            "dungeon_name": row.dungeon_name,
            "total_kills": int(row.total_kills or 0),
            "top_slayer_name": top.get("top_slayer_name"),
            "top_slayer_kills": top.get("top_slayer_kills", 0),
        })

    response.sort(key=lambda x: x["total_kills"], reverse=True)
    return response


def verify_internal_token(x_internal_token: str = Header(None)):
    secret = os.getenv("INTERNAL_API_SECRET", "super_secret_beluga_key_123")

    if not x_internal_token or x_internal_token != secret:
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещен. Неверный токен внутренней авторизации."
        )


@app.get("/api/bosses/my-kills", response_model=schemas.MyBossKillsResponse)
def get_my_boss_kills(
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    my_rows = (
        db.query(
            models.Boss.name.label("mob_id"),
            models.Boss.display_name.label("display_name"),
            models.Boss.dungeon_name.label("dungeon_name"),
            func.coalesce(func.sum(models.MMKill.kills), 0).label("kills")
        )
        .outerjoin(
            models.MMKill,
            (models.MMKill.mob == models.Boss.name) & (models.MMKill.uuid == user.uuid)
        )
        .filter(models.Boss.is_active == True)
        .group_by(models.Boss.name, models.Boss.display_name, models.Boss.dungeon_name)
        .all()
    )

    bosses = []
    total_kills = 0

    for row in my_rows:
        kills = int(row.kills or 0)
        total_kills += kills

        bosses.append({
            "mob_id": row.mob_id,
            "display_name": row.display_name,
            "dungeon_name": row.dungeon_name,
            "kills": kills,
        })

    bosses.sort(key=lambda x: x["kills"], reverse=True)

    totals = (
        db.query(
            models.MMKill.uuid.label("uuid"),
            func.sum(models.MMKill.kills).label("total_kills")
        )
        .join(models.Boss, models.Boss.name == models.MMKill.mob)
        .filter(
            models.Boss.is_active == True,
            models.MMKill.kills > 0
        )
        .group_by(models.MMKill.uuid)
        .order_by(desc("total_kills"), models.MMKill.uuid)
        .all()
    )

    rank = None
    for idx, row in enumerate(totals, start=1):
        if row.uuid == user.uuid:
            rank = idx
            break

    return {
        "player_name": user.playername,
        "total_kills": total_kills,
        "rank": rank,
        "bosses": bosses,
    }


@app.post("/api/internal/send-code", dependencies=[Depends(verify_internal_token)])
async def internal_send_code(payload: schemas.InternalEmailSchema):
    from app.email_utils import send_email, get_email_template

    html = get_email_template(
        playername=payload.nickname,
        title="Вход в игру",
        description="Поступил запрос на вход в игру. Для завершения авторизации введите код:",
        code=payload.code,
        warning="Код действителен 5 минут. Если вы не пытались войти в игру, немедленно смените пароль!"
    )

    try:
        await send_email(payload.email, f"Код подтверждения BelugaEmpire {payload.code}", html)
    except Exception as e:
        print(f"SMTP Error on internal route: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при отправке письма")

    return {"status": "success", "message": f"Письмо успешно отправлено на {payload.email}"}


@app.post("/api/profile/nickname")
def update_nickname(
    payload: schemas.UpdateNicknameRequest,
    user: models.AuthTGUser = Depends(auth_utils.get_current_user_orm),
    db: Session = Depends(database.get_db)
):
    player_data = db.query(models.PlayerData).filter(models.PlayerData.player_name == user.playername).first()
    group = player_data.primary_group if (player_data and player_data.primary_group) else "default"

    if not check_group_permission(db, group, "essentials.nick"):
        raise HTTPException(status_code=403, detail="У вашей привилегии нет доступа к смене псевдонима.")

    new_nick = payload.new_nickname.strip() if payload.new_nickname else None

    if new_nick:
        if len(new_nick) > 16 or len(new_nick) < 3:
            raise HTTPException(status_code=400, detail="Никнейм должен быть от 3 до 16 символов.")

        if not re.match(r"^[A-Za-z0-9_]+$", new_nick):
            raise HTTPException(status_code=400, detail="Разрешены только английские буквы, цифры и подчеркивание.")

        existing = db.query(models.FakeNick).filter(models.FakeNick.fake_player_name == new_nick).first()
        if existing and existing.player_name != user.playername:
            raise HTTPException(status_code=400, detail="Этот псевдоним уже занят другим игроком.")

    fake_record = db.query(models.FakeNick).filter(models.FakeNick.player_name == user.playername).first()

    if not fake_record:
        fake_record = models.FakeNick(
            player_name=user.playername,
            uuid=user.uuid,
            fake_player_name=new_nick,
            updated_at=int(time.time() * 1000)
        )
        db.add(fake_record)
    else:
        fake_record.fake_player_name = new_nick
        fake_record.updated_at = int(time.time() * 1000)

    db.commit()
    return {"status": "success", "message": "Псевдоним успешно обновлен"}