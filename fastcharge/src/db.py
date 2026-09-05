from typing import List, Self
import aiosqlite
from datetime import datetime, timezone
from pydantic import BaseModel

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_utc(iso_str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class UserModel(BaseModel):
    user_id: str
    config_id: str
    cancel_date: str

class DBClient:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    @classmethod
    async def Create(cls, db_path: str = "users.db") -> Self:
        conn = await aiosqlite.connect(db_path)
        # Enable dictionary-like row mapping for UserModel (**dict(row))
        conn.row_factory = aiosqlite.Row
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT NOT NULL PRIMARY KEY, -- Telegram user_id
                config_id TEXT NOT NULL,           -- XRAY user_id
                cancel_date TEXT                   -- ISO-8601
            );
        """)
        await conn.commit()
        return cls(conn)

    async def add_user(self, user_id: str, config_id: str) -> UserModel:
        """Register a new user."""
        cancel_iso = utc_now().isoformat()
        user = UserModel(
            user_id=user_id,
            config_id=config_id,
            cancel_date=cancel_iso)
        await self.conn.execute(
            """
            INSERT INTO users (user_id, config_id, cancel_date)
            VALUES (?, ?, ?);
            """,
            (user_id, config_id, cancel_iso),
        )
        await self.conn.commit()
        return user

    async def get_user(self, user_id: str) -> UserModel | None:
        """Fetch user by Telegram ID."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?;", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return UserModel(**dict(row)) if row else None
    
    async def get_users(self) -> List[UserModel]:
        """Return all users"""
        users = []
        async with self.conn.execute(
            "SELECT * FROM users ;"
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                users.append(UserModel(**dict(row)))
        return users
    
    async def get_active_users(self) -> List[UserModel]:
        """Return all users"""
        users = await self.get_users()
        now = utc_now()
        return [u for u in users if parse_utc(u.cancel_date) > now]

    async def upd_user_cancel_date(self, user_id: str, cancel_date: str) -> None:
        """Update subscription cancellation date."""
        await self.conn.execute(
            "UPDATE users SET cancel_date = ? WHERE user_id = ?;",
            (cancel_date, user_id),
        )
        await self.conn.commit()

    async def close(self) -> None:
        """Close connection gracefully."""
        await self.conn.close()