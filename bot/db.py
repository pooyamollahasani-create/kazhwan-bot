from datetime import datetime, timedelta, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, inspect, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

REFERRAL_REWARD_POINTS = 5


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


class MemberActivity(Base):
    __tablename__ = "member_activity"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(160))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class GroupModerationState(Base):
    __tablename__ = "group_moderation_state"

    group_chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    saved_permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_code: Mapped[str | None] = mapped_column(String(24), unique=True, nullable=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    start_date_text: Mapped[str] = mapped_column(String(80))
    end_date_text: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_by_telegram_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TripParticipant(Base):
    __tablename__ = "trip_participants"

    trip_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="declared", index=True)
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
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

    async def touch_member_activity(
        self, telegram_id: int, username: str | None, display_name: str
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            activity = await session.get(MemberActivity, telegram_id)
            if activity:
                activity.telegram_username = username
                activity.display_name = display_name
                activity.last_activity_at = now
            else:
                session.add(
                    MemberActivity(
                        telegram_id=telegram_id,
                        telegram_username=username,
                        display_name=display_name,
                        first_seen_at=now,
                        last_activity_at=now,
                    )
                )

            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.last_activity_at = now
            await session.commit()

    async def ensure_member_activity(
        self, telegram_id: int, username: str | None, display_name: str
    ) -> None:
        async with self.sessions() as session:
            activity = await session.get(MemberActivity, telegram_id)
            if not activity:
                now = datetime.now(timezone.utc)
                session.add(
                    MemberActivity(
                        telegram_id=telegram_id,
                        telegram_username=username,
                        display_name=display_name,
                        first_seen_at=now,
                        last_activity_at=now,
                    )
                )
                await session.commit()

    async def list_inactive_members(self, days: int, limit: int = 100) -> list[MemberActivity]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.sessions() as session:
            result = await session.execute(
                select(MemberActivity)
                .where(MemberActivity.last_activity_at <= cutoff)
                .order_by(MemberActivity.last_activity_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_existing_group_member(self, telegram_id: int) -> None:
        async with self.sessions() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user and not user.group_approved:
                user.group_approved = True
                await session.commit()

    async def get_saved_group_permissions(self, group_chat_id: int) -> str | None:
        async with self.sessions() as session:
            state = await session.get(GroupModerationState, group_chat_id)
            return state.saved_permissions_json if state else None

    async def save_group_permissions(self, group_chat_id: int, permissions_json: str) -> None:
        async with self.sessions() as session:
            state = await session.get(GroupModerationState, group_chat_id)
            if state:
                state.saved_permissions_json = permissions_json
            else:
                session.add(
                    GroupModerationState(
                        group_chat_id=group_chat_id,
                        saved_permissions_json=permissions_json,
                    )
                )
            await session.commit()

    async def clear_group_permissions(self, group_chat_id: int) -> None:
        async with self.sessions() as session:
            state = await session.get(GroupModerationState, group_chat_id)
            if state:
                state.saved_permissions_json = None
                await session.commit()

    async def list_users(self, limit: int = 5000) -> list[User]:
        async with self.sessions() as session:
            result = await session.execute(
                select(User).order_by(User.created_at.asc()).limit(limit)
            )
            return list(result.scalars().all())

    async def list_group_users(self, limit: int = 5000) -> list[User]:
        """Users whose membership in the main Kazhwan/BTC group was approved/confirmed."""
        async with self.sessions() as session:
            result = await session.execute(
                select(User)
                .where(User.group_approved.is_(True))
                .order_by(User.created_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def count_group_users(self) -> int:
        async with self.sessions() as session:
            result = await session.execute(
                select(func.count(User.id)).where(User.group_approved.is_(True))
            )
            return int(result.scalar_one())

    async def search_users(self, query: str, limit: int = 20) -> list[User]:
        value = query.strip()
        if not value:
            return []
        like = f"%{value}%"
        normalized = value.upper().replace(" ", "")
        async with self.sessions() as session:
            conditions = [
                User.full_name.ilike(like),
                User.phone.ilike(like),
                User.telegram_username.ilike(like),
                func.upper(User.member_code).ilike(f"%{normalized}%"),
                func.upper(User.referral_code).ilike(f"%{normalized}%"),
            ]
            if value.lstrip("-").isdigit():
                conditions.append(User.telegram_id == int(value))
            result = await session.execute(
                select(User).where(or_(*conditions)).order_by(User.full_name.asc()).limit(limit)
            )
            return list(result.scalars().all())

    async def list_unregistered_seen_members(self, limit: int = 500) -> list[MemberActivity]:
        async with self.sessions() as session:
            result = await session.execute(
                select(MemberActivity)
                .outerjoin(User, User.telegram_id == MemberActivity.telegram_id)
                .where(User.id.is_(None))
                .order_by(MemberActivity.last_activity_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def list_top_referrers(self, limit: int = 20) -> list[User]:
        async with self.sessions() as session:
            result = await session.execute(
                select(User)
                .where(User.referral_count > 0)
                .order_by(User.referral_count.desc(), User.points.desc(), User.full_name.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def create_or_update_trip(
        self,
        telegram_chat_id: int,
        title: str,
        start_date_text: str,
        end_date_text: str,
        created_by_telegram_id: int,
    ) -> Trip:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            result = await session.execute(
                select(Trip).where(Trip.telegram_chat_id == telegram_chat_id)
            )
            trip = result.scalar_one_or_none()
            if trip:
                trip.title = title
                trip.start_date_text = start_date_text
                trip.end_date_text = end_date_text
                trip.status = "open"
                trip.created_by_telegram_id = created_by_telegram_id
                trip.updated_at = now
            else:
                trip = Trip(
                    telegram_chat_id=telegram_chat_id,
                    title=title,
                    start_date_text=start_date_text,
                    end_date_text=end_date_text,
                    created_by_telegram_id=created_by_telegram_id,
                    status="open",
                    updated_at=now,
                )
                session.add(trip)
                await session.flush()
                trip.trip_code = f"TRIP-{trip.id:05d}"
            await session.commit()
            await session.refresh(trip)
            return trip

    async def get_trip_by_chat_id(self, telegram_chat_id: int) -> Trip | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(Trip).where(Trip.telegram_chat_id == telegram_chat_id)
            )
            return result.scalar_one_or_none()

    async def get_trip(self, trip_id: int) -> Trip | None:
        async with self.sessions() as session:
            return await session.get(Trip, trip_id)

    async def set_trip_status(self, trip_id: int, status: str) -> Trip | None:
        async with self.sessions() as session:
            trip = await session.get(Trip, trip_id)
            if not trip:
                return None
            trip.status = status
            trip.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(trip)
            return trip

    async def register_trip_participant(self, trip_id: int, telegram_id: int) -> TripParticipant:
        now = datetime.now(timezone.utc)
        async with self.sessions() as session:
            participant = await session.get(TripParticipant, (trip_id, telegram_id))
            if participant:
                participant.status = "declared"
                participant.updated_at = now
            else:
                participant = TripParticipant(
                    trip_id=trip_id, telegram_id=telegram_id, status="declared", updated_at=now
                )
                session.add(participant)
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            trip = await session.get(Trip, trip_id)
            if user and trip:
                existing_activity = await session.execute(
                    select(Activity).where(
                        Activity.telegram_id == telegram_id,
                        Activity.activity_type == "trip_declared",
                        Activity.details == trip.trip_code,
                    )
                )
                if existing_activity.scalar_one_or_none() is None:
                    session.add(
                        Activity(
                            telegram_id=telegram_id,
                            activity_type="trip_declared",
                            title=f"اعلام حضور در سفر {trip.title}",
                            details=trip.trip_code,
                        )
                    )
            await session.commit()
            return participant

    async def set_trip_participant_status(
        self, trip_id: int, telegram_id: int, status: str
    ) -> TripParticipant | None:
        async with self.sessions() as session:
            participant = await session.get(TripParticipant, (trip_id, telegram_id))
            if not participant:
                return None
            participant.status = status
            participant.updated_at = datetime.now(timezone.utc)
            trip = await session.get(Trip, trip_id)
            if trip and status == "attended":
                check = await session.execute(
                    select(Activity).where(
                        Activity.telegram_id == telegram_id,
                        Activity.activity_type == "trip_attended",
                        Activity.details == trip.trip_code,
                    )
                )
                if check.scalar_one_or_none() is None:
                    session.add(
                        Activity(
                            telegram_id=telegram_id,
                            activity_type="trip_attended",
                            title=f"شرکت در سفر {trip.title}",
                            details=trip.trip_code,
                        )
                    )
            await session.commit()
            return participant

    async def list_trip_participants(self, trip_id: int) -> list[tuple[TripParticipant, User | None]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(TripParticipant, User)
                .outerjoin(User, User.telegram_id == TripParticipant.telegram_id)
                .where(TripParticipant.trip_id == trip_id)
                .order_by(TripParticipant.declared_at.asc())
            )
            return list(result.all())

    async def count_trip_participants(self, trip_id: int) -> int:
        async with self.sessions() as session:
            result = await session.execute(
                select(func.count()).select_from(TripParticipant).where(TripParticipant.trip_id == trip_id)
            )
            return int(result.scalar_one())

    async def list_user_trips(self, telegram_id: int) -> list[tuple[TripParticipant, Trip]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(TripParticipant, Trip)
                .join(Trip, Trip.id == TripParticipant.trip_id)
                .where(TripParticipant.telegram_id == telegram_id)
                .order_by(Trip.created_at.desc())
            )
            return list(result.all())

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
