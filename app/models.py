from sqlalchemy import Column, Integer, String, Boolean, BigInteger
from .database import Base

class AuthTGUser(Base):
    __tablename__ = "AuthTGUsers"

    priKey = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), nullable=False)
    playername = Column(String(120), nullable=False)
    password = Column(String(64), nullable=True)
    active = Column(Boolean, default=False)
    twofactor = Column(Boolean, default=False)
    activeTG = Column(Boolean, default=False) # Привязан ли ТГ
    chatid = Column(BigInteger, nullable=True)
    username = Column(String(32), nullable=True) # ТГ юзернейм
    firstname = Column(String(120), nullable=True)
    lastname = Column(String(120), nullable=True)
    currentUUID = Column(Boolean, default=False)
    admin = Column(Boolean, default=False)
