from sqlalchemy import text


async def ensure_profile_extra_schema(db) -> None:
    """Create the extra profile table without changing the existing users table."""
    async with db.sessions() as session:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profile_extra (
                telegram_id BIGINT PRIMARY KEY,
                neighborhood VARCHAR(160)
            )
        """))
        await session.commit()


async def save_neighborhood(db, telegram_id: int, neighborhood: str) -> None:
    await ensure_profile_extra_schema(db)
    clean = (neighborhood or "").strip()
    async with db.sessions() as session:
        result = await session.execute(
            text("UPDATE user_profile_extra SET neighborhood=:n WHERE telegram_id=:tid"),
            {"n": clean, "tid": int(telegram_id)},
        )
        if not result.rowcount:
            await session.execute(
                text("INSERT INTO user_profile_extra (telegram_id, neighborhood) VALUES (:tid, :n)"),
                {"tid": int(telegram_id), "n": clean},
            )
        await session.commit()


async def get_neighborhood(db, telegram_id: int) -> str | None:
    await ensure_profile_extra_schema(db)
    async with db.sessions() as session:
        result = await session.execute(
            text("SELECT neighborhood FROM user_profile_extra WHERE telegram_id=:tid"),
            {"tid": int(telegram_id)},
        )
        row = result.first()
        return row[0] if row else None


async def update_basic_profile(db, telegram_id: int, field: str, value: str) -> bool:
    allowed = {"full_name", "city", "discovery_source"}
    if field not in allowed:
        return False
    clean = (value or "").strip()
    if not clean:
        return False
    async with db.sessions() as session:
        result = await session.execute(
            text(f"UPDATE users SET {field}=:value WHERE telegram_id=:tid"),
            {"value": clean, "tid": int(telegram_id)},
        )
        await session.commit()
        return bool(result.rowcount)


async def update_phone(db, telegram_id: int, phone: str) -> bool:
    clean = (phone or "").strip()
    if not clean:
        return False
    async with db.sessions() as session:
        result = await session.execute(
            text("UPDATE users SET phone=:value WHERE telegram_id=:tid"),
            {"value": clean, "tid": int(telegram_id)},
        )
        await session.commit()
        return bool(result.rowcount)
