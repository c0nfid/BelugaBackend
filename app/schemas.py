from pydantic import BaseModel, EmailStr
from typing import List, Optional

class LoginRequest(BaseModel):
    username: str
    password: str

class TelegramLoginRequest(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str

class UserResponse(BaseModel):
    playername: str
    uuid: str
    activeTG: bool
    tg_username: Optional[str] = None
    admin: bool
    clan_name: Optional[str] = None
    last_seen: Optional[int] = None
    playtime_seconds: Optional[int] = 0
    primary_group: Optional[str] = "default"

    donation_balance: Optional[int] = 0
    balance: Optional[float] = 0

    kills: Optional[int] = 0
    deaths: Optional[int] = 0
    legit_kills: Optional[int] = 0
    legit_deaths: Optional[int] = 0

    last_login_timestamp: Optional[int] = 0
    last_ip: Optional[str] = "Неизвестно"
    session_duration: Optional[int] = 0
    
    email: Optional[str] = None
    is_email_verified: Optional[bool] = False

    fake_player_name: Optional[str] = None
    can_edit_nickname: Optional[bool] = False
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class ChangePasswordRequest(BaseModel):
    new_password: str
    current_password: Optional[str] = None

class ClanRankingItem(BaseModel):
    rank: int
    name: str
    leader: str
    members: int
    rating: int
    wins: int

    class Config:
        from_attributes = True

class ClanMemberSchema(BaseModel):
    name: str
    role: str # LEADER, ELDER, MEMBER
    joined_date: str = "N/A" # В базе нет даты вступления, ставим заглушку

class ClanStatsSchema(BaseModel):
    wins: int
    losses: int

class ClanDetailsResponse(BaseModel):
    name: str
    description: Optional[str]
    leader: str
    rank_position: int
    rating: int
    rank_title: str
    balance: int
    activity_points: int
    stats: ClanStatsSchema
    members: List[ClanMemberSchema]

class EmailRequestSchema(BaseModel):
    email: EmailStr

class EmailVerifySchema(BaseModel):
    email: EmailStr
    code: str

class EmailConfirmUnlinkSchema(BaseModel):
    code: str

class EmailConfirmPasswordSchema(BaseModel):
    code: str

class EmailConfirmLoginSchema(BaseModel):
    username: str
    code: str

class InternalEmailSchema(BaseModel):
    nickname: str
    email: str
    code: str

class UpdateNicknameRequest(BaseModel):
    new_nickname: Optional[str] = None

