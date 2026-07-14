from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32))
    city: Mapped[str] = mapped_column(String(100))
    discovery_source: Mapped[str] = mapped_column(String(100))
    rules_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    member_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    activity_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, future=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_user(self, telegram_id: int) -> User | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def create_user(
        self,
        telegram_id: int,
        telegram_username: str | None,
        full_name: str,
        phone: str,
        city: str,
        discovery_source: str,
    ) -> User:
        async with self.sessions() as session:
            user = User(
                telegram_id=telegram_id,
                telegram_username=telegram_username,
                full_name=full_name,
                phone=phone,
                city=city,
                discovery_source=discovery_source,
                rules_accepted=True,
                channel_verified=True,
            )
            session.add(user)
            await session.flush()
            user.member_code = f"KZH-{user.id:06d}"
            session.add(
                Activity(
                    telegram_id=telegram_id,
                    activity_type="membership",
                    title="عضویت در کژوان",
                    details=f"شناسه عضویت: {user.member_code}",
                )
            )
            await session.commit()
            await session.refresh(user)
            return user

    async def list_activities(self, telegram_id: int, limit: int = 15) -> list[Activity]:
        async with self.sessions() as session:
            result = await session.execute(
                select(Activity)
                .where(Activity.telegram_id == telegram_id)
                .order_by(Activity.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def count_users(self) -> int:
        async with self.sessions() as session:
            result = await session.execute(select(func.count(User.id)))
            return int(result.scalar_one())
