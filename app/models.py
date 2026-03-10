from sqlalchemy import Column, Integer, String, Boolean, BigInteger, Float, Numeric, Text, ForeignKey, or_, Date, func, DateTime
from datetime import datetime
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

class PlayerData(Base):
    __tablename__ = "player_data"
    
    __table_args__ = {"schema": "essential"} 

    player_name = Column(String(120), primary_key=True)
    login_timestamp = Column(BigInteger, nullable=True)
    logout_timestamp = Column(BigInteger, nullable=True)
    ip_address = Column(String(45), nullable=True)
    clan_name = Column(String(36), nullable=True)
    primary_group = Column(String(64), nullable=True, default="default")
    donation_balance = Column(BigInteger, nullable=True, default=0)
    balance = Column(Numeric(18, 2), default=0)

class PlayerPlaytime(Base):
    __tablename__ = "player_playtime"
    __table_args__ = {"schema": "essential"}

    player_name = Column(String(120), primary_key=True) 
    total_seconds = Column(BigInteger, default=0)

class ClanData(Base):
    __tablename__ = "clan_data"
    __table_args__ = {"schema": "essential"}

    clan_name = Column(String(12), primary_key=True)
    leader = Column(String(36))
    member_count = Column(Integer, default=1)

    balance = Column(Numeric(18, 2), default=0)
    clan_description = Column(Text, nullable=True)
    clan_rank = Column(String(16), default="Новичок")

class ClanRating(Base):
    __tablename__ = "clan_rating"
    __table_args__ = {"schema": "essential"}

    clan_name = Column(String(12), primary_key=True)
    final_rating = Column(Float, default=0.0)
    activity_score = Column(Integer, default=0)

class ClanWars(Base):
    __tablename__ = "clan_wars"
    __table_args__ = {"schema": "essential"}

    war_id = Column(String(36), primary_key=True)
    clan_a = Column(String(12)) # Атакующий
    clan_b = Column(String(12)) # Защищающийся
    winner_clan = Column(String(12))

class ClanHeads(Base):
    __tablename__ = "clan_heads"
    __table_args__ = {"schema": "essential"}

    player_name = Column(String(36), primary_key=True) 
    clan_name = Column(String(12), index=True)
    role = Column(Integer, default=0) # 0=Member, 1=Admin, 2=Leader

class KDAData(Base):
    __tablename__ = "KDA_data"
    __table_args__ = {"schema": "essential"}

    player_name = Column(String(36), primary_key=True)
    player_kill = Column(Integer, default=0)
    player_death = Column(Integer, default=0)

class PlayerPvpDaily(Base):
    __tablename__ = "player_pvp_daily"
    __table_args__ = {"schema": "essential"}

    day = Column(Date, primary_key=True)
    player_name = Column(String(36), primary_key=True)
    
    valid_kills = Column(Integer, default=0)
    valid_deaths = Column(Integer, default=0)

class Enchantment(Base):
    __tablename__ = "enchantments"
    __table_args__ = {"schema": "belugadb"}

    name = Column(String(100), primary_key=True)
    display = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    ench_group = Column(String(100), nullable=True)
    max_level = Column(Integer, nullable=True)

class EnchantmentItem(Base):
    __tablename__ = "enchantment_items"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    ench_name = Column(String(100), ForeignKey("belugadb.enchantments.name", ondelete="CASCADE"))
    item = Column(String(100), nullable=True)

class UserEmail(Base):
    __tablename__ = "user_emails"
    __table_args__ = {'schema': 'belugadb'}

    id = Column(Integer, primary_key=True, index=True)
    nickname = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)