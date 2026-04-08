import uuid
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, Float, Numeric, Text, ForeignKey, or_, Date, func, DateTime
from datetime import datetime
from .database import Base
from sqlalchemy.orm import relationship

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

class Boss(Base):
    __tablename__ = "bosses"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    base_health = Column(BigInteger, nullable=False)
    base_damage = Column(Integer, nullable=False)
    damage_modifier = Column(Numeric(10, 2), default=1.00)
    health_modifier = Column(Numeric(10, 2), default=1.00)
    max_players = Column(Integer, default=1)
    dungeon_name = Column(String(100), nullable=True)

    difficulties = relationship("BossDifficulty", back_populates="boss", cascade="all, delete-orphan")
    drops = relationship("BossDrop", back_populates="boss", cascade="all, delete-orphan")

class BossDifficulty(Base):
    __tablename__ = "boss_difficulties"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(Integer, ForeignKey("belugadb.bosses.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    level = Column(Integer, nullable=False)

    boss = relationship("Boss", back_populates="difficulties")
    drops = relationship("BossDrop", back_populates="difficulty")

class BossDrop(Base):
    __tablename__ = "boss_drops"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(Integer, ForeignKey("belugadb.bosses.id", ondelete="CASCADE"), nullable=False)
    difficulty_id = Column(Integer, ForeignKey("belugadb.boss_difficulties.id", ondelete="CASCADE"), nullable=True)
    item_name = Column(String(100), nullable=False)
    min_amount = Column(Integer, default=1)
    max_amount = Column(Integer, default=1)

    boss = relationship("Boss", back_populates="drops")
    difficulty = relationship("BossDifficulty", back_populates="drops")

class FakeNick(Base):
    __tablename__ = "fake_nicks"
    __table_args__ = {"schema": "essential"}

    player_name = Column(String(36), primary_key=True)
    uuid = Column(String(36), index=True, nullable=True)
    fake_player_name = Column(String(36), unique=True, nullable=True)
    updated_at = Column(BigInteger, default=0)

class LuckpermsGroupPermission(Base):
    __tablename__ = "luckperms_group_permissions"
    __table_args__ = {"schema": "LuckPerms"}
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(36), index=True, nullable=False)
    permission = Column(String(200), nullable=False)
    value = Column(Integer, nullable=False)
    server = Column(String(36), nullable=False)
    world = Column(String(64), nullable=False)
    expiry = Column(BigInteger, nullable=False)
    contexts = Column(String(200), nullable=False)


class ShopCategory(Base):
    __tablename__ = "shop_categories"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)

class ShopProduct(Base):
    __tablename__ = "shop_products"
    __table_args__ = {"schema": "belugadb"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("belugadb.shop_categories.id"))
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    currency_type = Column(String(20), default="donate") # 'donate' (Fish-баксы) или 'soft' (Монеты)
    
    command_template = Column(String(255), nullable=False) 
    item_id = Column(String(100), nullable=False)        
    amount = Column(String(50), nullable=False)          
    require_online = Column(Boolean, default=True)       
    required_free_slots = Column(Integer, default=0)     

    image_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)

    allow_quantity = Column(Boolean, default=False)
    variants = Column(Text, nullable=True)

class ShopPurchaseLog(Base):
    __tablename__ = "shop_purchase_logs"
    __table_args__ = {"schema": "belugadb"}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_name = Column(String(120), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("belugadb.shop_products.id"))
    price_paid = Column(Integer, nullable=False)
    currency_type = Column(String(20), nullable=False)
    
    status = Column(String(20), default="completed")
    
    created_at = Column(DateTime, default=datetime.utcnow)

class WebstoreQueue(Base):
    __tablename__ = "webstore_queue"
    __table_args__ = {"schema": "shop_msqlc"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    external_order_id = Column(String(100), nullable=True)
    player_uuid = Column(String(36), nullable=True)
    player_name = Column(String(16), nullable=True)
    command_text = Column(Text, nullable=False)
    require_online = Column(Boolean, default=False)
    required_free_slots = Column(Integer, default=0)
    success_message = Column(Text, nullable=True)
    failure_message = Column(Text, nullable=True)
    status = Column(String(16), default='PENDING')
    attempt_count = Column(Integer, default=0)
    retry_delay_seconds = Column(Integer, nullable=True, default=30)
    max_attempts = Column(Integer, nullable=True, default=50)
    next_attempt_at = Column(DateTime, server_default=func.now())
    locked_by = Column(String(64), nullable=True)
    lock_until = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)