from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

REFERRAL_REWARD_POINTS = 10


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
    referral_code: Mapped[str | None] = mapped_column(String(24), unique=True, nullable=True)
    referred_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    referral_count: Mapped[int] = mapped_column(Integer, default=0)
    group_approved: Mapped[bool] = mapped_column(Boolean, default=False)
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


class PendingJoin(Base):
    __tablename__ = "pending_joins"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger)
    user_chat_id: Mapped[int] = mapped_column(BigInteger)
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
            await conn.run_sync(self._migrate_users_table)

        # Backfill referral codes for users that existed before this version.
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.referral_code.is_(None)))
            users = result.scalars().all()
            for user in users:
                user.referral_code = f"KZH-R{user.id:06d}"
            if users:
                await session.commit()

    @staticmethod
    def _migrate_users_table(sync_conn) -> None:
        """Small, idempotent migration that preserves the existing Railway data."""
        inspector = inspect(sync_conn)
        if "users" not in inspector.get_table_names():
            return

        existing = {column["name"] for column in inspector.get_columns("users")}
        dialect = sync_conn.dialect.name

        additions = {
            "referral_code": "VARCHAR(24)",
            "referred_by_telegram_id": "BIGINT",
            "referral_count": "INTEGER DEFAULT 0 NOT NULL",
            "group_approved": "BOOLEAN DEFAULT FALSE NOT NULL",
        }
        for name, sql_type in additions.items():
            if name not in existing:
                sync_conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {sql_type}")

        # Unique index keeps referral codes safe without rebuilding the existing table.
        sync_conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users (referral_code)"
        )
        sync_conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_users_referred_by_telegram_id "
            "ON users (referred_by_telegram_id)"
        )

    async def save_pending_join(
        self, telegram_id: int, group_chat_id: int, user_chat_id: int
    ) -> None:
        async with self.sessions() as session:
            pending = await session.get(PendingJoin, telegram_id)
            if pending:
                pending.group_chat_id = group_chat_id
                pending.user_chat_id = user_chat_id
                pending.created_at = datetime.now(timezone.utc)
            else:
                session.add(
                    PendingJoin(
                        telegram_id=telegram_id,
                        group_chat_id=group_chat_id,
                        user_chat_id=user_chat_id,
                    )
                )
            await session.commit()

    async def get_pending_join(self, telegram_id: int) -> PendingJoin | None:
        async with self.sessions() as session:
            return await session.get(PendingJoin, telegram_id)

    async def delete_pending_join(self, telegram_id: int) -> None:
        async with self.sessions() as session:
            pending = await session.get(PendingJoin, telegram_id)
            if pending:
                await session.delete(pending)
                await session.commit()

    async def get_user(self, telegram_id: int) -> User | None:
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            return result.scalar_one_or_none()

    async def get_user_by_referral_code(self, referral_code: str) -> User | None:
        code = referral_code.strip().upper().replace(" ", "")
        async with self.sessions() as session:
            result = await session.execute(
                select(User).where(func.upper(User.referral_code) == code)
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
        referred_by_telegram_id: int | None = None,
    ) -> User:
        async with self.sessions() as session:
            user = User(
                telegram_id=telegram_id,
                telegram_username=telegram_username,
                full_name=full_name,
                phone=phone,
                city=city,
                discovery_source=discovery_source,
                referred_by_telegram_id=referred_by_telegram_id,
                rules_accepted=True,
                channel_verified=True,
                group_approved=False,
            )
            session.add(user)
            await session.flush()
            user.member_code = f"KZH-{user.id:06d}"
            user.referral_code = f"KZH-R{user.id:06d}"
            session.add(
                Activity(
                    telegram_id=telegram_id,
                    activity_type="membership",
                    title="ثبت پروفایل کژوان",
                    details=f"شناسه عضویت: {user.member_code}",
                )
            )
            await session.commit()
            await session.refresh(user)
            return user

    async def mark_group_approved_and_reward_referrer(self, telegram_id: int) -> User | None:
        """Mark approval and award the referral exactly once."""
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()
            if not user:
                return None
            if user.group_approved:
                return user

            user.group_approved = True
            session.add(
                Activity(
                    telegram_id=user.telegram_id,
                    activity_type="group_join",
                    title="عضویت در گروه تأیید شد",
                    details=None,
                )
            )

            if user.referred_by_telegram_id:
                ref_result = await session.execute(
                    select(User).where(User.telegram_id == user.referred_by_telegram_id)
                )
                referrer = ref_result.scalar_one_or_none()
                if referrer and referrer.telegram_id != user.telegram_id:
                    referrer.points += REFERRAL_REWARD_POINTS
                    referrer.referral_count += 1
                    session.add(
                        Activity(
                            telegram_id=referrer.telegram_id,
                            activity_type="referral",
                            title="معرفی عضو جدید",
                            details=(
                                f"{user.full_name} عضو گروه شد. "
                                f"+{REFERRAL_REWARD_POINTS} امتیاز"
                            ),
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
