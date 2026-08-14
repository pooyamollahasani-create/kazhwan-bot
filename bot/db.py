from datetime import datetime, timedelta, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, inspect, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

REFERRAL_REWARD_POINTS = 5
TRIP_POINTS = {
    "domestic_day": 5,
    "domestic_multi": 15,
    "international": 100,
}


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
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    group_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="active")
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class BtcMembership(Base):
    __tablename__ = "btc_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    btc_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    rules_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(
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
    trip_type: Mapped[str] = mapped_column(String(24), default="domestic_multi", index=True)
    points_value: Mapped[int] = mapped_column(Integer, default=15)
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
    points_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    awarded_points: Mapped[int] = mapped_column(Integer, default=0)


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, future=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._migrate_users_table)
            await conn.run_sync(self._migrate_trips_table)

        # Backfill referral codes for users that existed before this version.
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.referral_code.is_(None)))
            users = result.scalars().all()
            for user in users:
                user.referral_code = f"KZH-R{user.id:06d}"

            # Existing successful referrals were already rewarded in older versions.
            rewarded_result = await session.execute(
                select(User).where(
                    User.referred_by_telegram_id.is_not(None),
                    User.group_approved.is_(True),
                    User.referral_rewarded.is_(False),
                )
            )
            for user in rewarded_result.scalars().all():
                user.referral_rewarded = True

            # Legacy Kazhwan profiles that had a referrer but were never BTC-approved
            # did not receive the old BTC-tied reward. Award them once now.
            pending_reward_result = await session.execute(
                select(User).where(
                    User.referred_by_telegram_id.is_not(None),
                    User.referral_rewarded.is_(False),
                )
            )
            for user in pending_reward_result.scalars().all():
                ref_result = await session.execute(
                    select(User).where(User.telegram_id == user.referred_by_telegram_id)
                )
                referrer = ref_result.scalar_one_or_none()
                if referrer and referrer.telegram_id != user.telegram_id:
                    referrer.points += REFERRAL_REWARD_POINTS
                    referrer.referral_count += 1
                    user.referral_rewarded = True
                    session.add(
                        Activity(
                            telegram_id=referrer.telegram_id,
                            activity_type="referral",
                            title="معرفی عضو جدید کژوان",
                            details=(
                                f"{user.full_name} پروفایل کژوان را تکمیل کرد. "
                                f"+{REFERRAL_REWARD_POINTS} امتیاز (مهاجرت)"
                            ),
                        )
                    )

            # Existing BTC members keep their KZH code and receive a separate BTC code.
            btc_result = await session.execute(
                select(User).where(User.group_approved.is_(True)).order_by(User.id.asc())
            )
            for user in btc_result.scalars().all():
                existing_btc = await session.execute(
                    select(BtcMembership).where(BtcMembership.telegram_id == user.telegram_id)
                )
                if existing_btc.scalar_one_or_none() is None:
                    membership = BtcMembership(telegram_id=user.telegram_id, status="active", rules_accepted=True)
                    session.add(membership)
                    await session.flush()
                    membership.btc_code = f"BTC-{membership.id:06d}"

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
            "referral_rewarded": "BOOLEAN DEFAULT FALSE NOT NULL",
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


    @staticmethod
    def _migrate_trips_table(sync_conn) -> None:
        """Idempotent migration for trip categories and point awarding."""
        inspector = inspect(sync_conn)
        tables = inspector.get_table_names()
        if "trips" in tables:
            existing = {column["name"] for column in inspector.get_columns("trips")}
            if "trip_type" not in existing:
                sync_conn.exec_driver_sql(
                    "ALTER TABLE trips ADD COLUMN trip_type VARCHAR(24) DEFAULT 'domestic_multi' NOT NULL"
                )
            if "points_value" not in existing:
                sync_conn.exec_driver_sql(
                    "ALTER TABLE trips ADD COLUMN points_value INTEGER DEFAULT 15 NOT NULL"
                )
            # Convert the old two-category model to the new one. Existing domestic trips
            # are treated as multi-day until an admin redefines them with /settrip.
            sync_conn.exec_driver_sql(
                "UPDATE trips SET trip_type='domestic_multi' WHERE trip_type='domestic'"
            )
            sync_conn.exec_driver_sql(
                "UPDATE trips SET points_value=100 WHERE trip_type='international'"
            )
            sync_conn.exec_driver_sql(
                "UPDATE trips SET points_value=5 WHERE trip_type='domestic_day'"
            )
            sync_conn.exec_driver_sql(
                "UPDATE trips SET points_value=15 WHERE trip_type='domestic_multi'"
            )
            sync_conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_trips_trip_type ON trips (trip_type)"
            )

        if "trip_participants" in tables:
            existing_participant = {
                column["name"] for column in inspector.get_columns("trip_participants")
            }
            if "points_awarded" not in existing_participant:
                sync_conn.exec_driver_sql(
                    "ALTER TABLE trip_participants ADD COLUMN points_awarded BOOLEAN DEFAULT FALSE NOT NULL"
                )
            if "awarded_points" not in existing_participant:
                sync_conn.exec_driver_sql(
                    "ALTER TABLE trip_participants ADD COLUMN awarded_points INTEGER DEFAULT 0 NOT NULL"
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

    async def reward_referrer_if_needed(self, telegram_id: int) -> User | None:
        """Award the Kazhwan referral reward exactly once after profile completion."""
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()
            if not user or user.referral_rewarded or not user.referred_by_telegram_id:
                return user

            ref_result = await session.execute(
                select(User).where(User.telegram_id == user.referred_by_telegram_id)
            )
            referrer = ref_result.scalar_one_or_none()
            if referrer and referrer.telegram_id != user.telegram_id:
                referrer.points += REFERRAL_REWARD_POINTS
                referrer.referral_count += 1
                user.referral_rewarded = True
                session.add(
                    Activity(
                        telegram_id=referrer.telegram_id,
                        activity_type="referral",
                        title="معرفی عضو جدید کژوان",
                        details=(
                            f"{user.full_name} پروفایل کژوان را تکمیل کرد. "
                            f"+{REFERRAL_REWARD_POINTS} امتیاز"
                        ),
                    )
                )
                await session.commit()
                await session.refresh(user)
            return user

    async def ensure_btc_membership(self, telegram_id: int) -> BtcMembership | None:
        async with self.sessions() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                return None
            result = await session.execute(
                select(BtcMembership).where(BtcMembership.telegram_id == telegram_id)
            )
            membership = result.scalar_one_or_none()
            if membership:
                return membership
            membership = BtcMembership(telegram_id=telegram_id, status="active")
            session.add(membership)
            await session.flush()
            membership.btc_code = f"BTC-{membership.id:06d}"
            await session.commit()
            await session.refresh(membership)
            return membership

    async def get_btc_membership(self, telegram_id: int) -> BtcMembership | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(BtcMembership).where(BtcMembership.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def mark_group_approved_and_reward_referrer(self, telegram_id: int) -> User | None:
        """Mark BTC approval and ensure a separate BTC membership code.

        The legacy method name is retained so deployed handlers remain compatible.
        Referral points are now Kazhwan-wide and awarded on profile completion.
        """
        async with self.sessions() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()
            if not user:
                return None
            if not user.group_approved:
                user.group_approved = True
                session.add(
                    Activity(
                        telegram_id=user.telegram_id,
                        activity_type="btc_join",
                        title="عضویت Beyond The Clouds تأیید شد",
                        details=None,
                    )
                )
            btc_result = await session.execute(
                select(BtcMembership).where(BtcMembership.telegram_id == telegram_id)
            )
            membership = btc_result.scalar_one_or_none()
            if membership is None:
                membership = BtcMembership(
                    telegram_id=telegram_id, status="active", rules_accepted=True
                )
                session.add(membership)
                await session.flush()
                membership.btc_code = f"BTC-{membership.id:06d}"
            else:
                membership.rules_accepted = True
                membership.status = "active"
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
            if not user:
                return
            user.group_approved = True
            btc_result = await session.execute(
                select(BtcMembership).where(BtcMembership.telegram_id == telegram_id)
            )
            membership = btc_result.scalar_one_or_none()
            if membership is None:
                membership = BtcMembership(
                    telegram_id=telegram_id, status="active", rules_accepted=True
                )
                session.add(membership)
                await session.flush()
                membership.btc_code = f"BTC-{membership.id:06d}"
            else:
                membership.rules_accepted = True
                membership.status = "active"
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
            if normalized.startswith("BTC-"):
                btc_result = await session.execute(
                    select(User)
                    .join(BtcMembership, BtcMembership.telegram_id == User.telegram_id)
                    .where(func.upper(BtcMembership.btc_code).ilike(f"%{normalized}%"))
                    .order_by(User.full_name.asc())
                    .limit(limit)
                )
                btc_users = list(btc_result.scalars().all())
                if btc_users:
                    return btc_users
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
        trip_type: str,
        created_by_telegram_id: int,
    ) -> Trip:
        now = datetime.now(timezone.utc)
        points_value = TRIP_POINTS.get(trip_type, 0)
        async with self.sessions() as session:
            result = await session.execute(
                select(Trip).where(Trip.telegram_chat_id == telegram_chat_id)
            )
            trip = result.scalar_one_or_none()
            if trip:
                trip.title = title
                trip.start_date_text = start_date_text
                trip.end_date_text = end_date_text
                trip.trip_type = trip_type
                trip.points_value = points_value
                trip.status = "open"
                trip.created_by_telegram_id = created_by_telegram_id
                trip.updated_at = now
            else:
                trip = Trip(
                    telegram_chat_id=telegram_chat_id,
                    title=title,
                    trip_type=trip_type,
                    points_value=points_value,
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

    async def list_trips(self, limit: int = 100) -> list[Trip]:
        async with self.sessions() as session:
            result = await session.execute(
                select(Trip).order_by(Trip.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

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

            trip = await session.get(Trip, trip_id)
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()

            # Reversible and idempotent points: only attended earns points.
            if status == "attended":
                if trip and user and not participant.points_awarded:
                    points = int(trip.points_value or TRIP_POINTS.get(trip.trip_type, 0))
                    user.points += points
                    participant.points_awarded = True
                    participant.awarded_points = points
                    session.add(
                        Activity(
                            telegram_id=telegram_id,
                            activity_type="trip_attended",
                            title=f"شرکت در سفر {trip.title}",
                            details=f"{trip.trip_code} | +{points} امتیاز",
                        )
                    )
            elif participant.points_awarded:
                # If an admin corrects an attended status, remove the previously-awarded trip points.
                if user:
                    user.points = max(0, user.points - int(participant.awarded_points or 0))
                participant.points_awarded = False
                participant.awarded_points = 0

            participant.status = status
            participant.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(participant)
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


    async def list_all_trip_history(self) -> list[tuple[TripParticipant, Trip]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(TripParticipant, Trip)
                .join(Trip, Trip.id == TripParticipant.trip_id)
                .order_by(TripParticipant.telegram_id.asc(), Trip.created_at.asc())
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
