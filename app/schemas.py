from pydantic import BaseModel
from typing import Optional

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
    last_login: Optional[int] = None
    primary_group: Optional[str] = "default"
    donation_balance: Optional[int] = 0
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class ChangePasswordRequest(BaseModel):
    new_password: str
    current_password: Optional[str] = None