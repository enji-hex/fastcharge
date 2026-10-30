from asyncio import Lock
from typing import List, Optional, Self
import aiofiles
import aiosqlite
from datetime import datetime, timezone
from pydantic import BaseModel
import os
import aiohttp

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

class KeysModel(BaseModel):
    private: str
    public: str
    short_id: str
    decryption: str
    encryption: str



class DBClient:
    def __init__(self, conn: aiosqlite.Connection,
                 db_path:str,
                 api_key:str,
                 dependent_nodes:list[str] = []) -> None:
        self.conn = conn
        self.db_path = db_path
        self.api_key = api_key
        self.dependent_nodes = dependent_nodes
        self.write_lock = Lock()

    @classmethod
    async def Create(cls, 
                     dependent_nodes:list[str],
                     api_key:str,
                     db_path: str = "./files/users.db"
                     ) -> Self:
        os.makedirs('./files',exist_ok=True)
        conn = await aiosqlite.connect(db_path)
        # Enable dictionary-like row mapping for UserModel (**dict(row))
        conn.row_factory = aiosqlite.Row
        
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT NOT NULL PRIMARY KEY, -- Telegram user_id
                config_id TEXT NOT NULL,           -- XRAY user_id
                cancel_date TEXT                   -- ISO-8601
            );
                           
            CREATE TABLE IF NOT EXISTS keys (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                private     TEXT NOT NULL,           
                public      TEXT NOT NULL,           
                short_id    TEXT NOT NULL,           
                decryption  TEXT NOT NULL,           
                encryption  TEXT NOT NULL       
            );
        """,)
        await conn.commit()
        return cls(conn,db_path,api_key,dependent_nodes)

    async def get_snaphot(self):
        async with self.write_lock:
            async with aiofiles.open(self.db_path,'rb') as f:
                return await f.read()

    async def reconnect(self,new_db_bytes:bytes) -> None:
        tmp_path = f'{self.db_path}.tmp'
        async with self.write_lock:
            async with aiofiles.open(tmp_path,'wb') as f:
                await f.write(new_db_bytes)
            
            async with aiosqlite.connect(tmp_path) as tmp_conn:
                cur = await tmp_conn.execute("PRAGMA quick_check;")
                res = await cur.fetchone()
                if not res or res[0] != "ok":
                    os.remove(tmp_path)
                    raise ValueError("Invalid SQLite snapshot")

            await self.conn.close()
            os.replace(tmp_path,self.db_path)

            self.conn = await aiosqlite.connect(self.db_path)
            self.conn.row_factory = aiosqlite.Row

    async def set_keys(self,keys:KeysModel):
        """
        Only one key instance allowed, 
        keys stored in sqlite db to provide one-file storage
        """
        await self.conn.execute("DELETE FROM keys;")
        await self.conn.execute(
            """
            INSERT INTO keys (private,public,short_id,decryption,encryption)
            VALUES (?, ?, ? ,? ,?);
            """,
            (keys.private,keys.public,keys.short_id,keys.decryption,keys.encryption)
        )
        await self.conn.commit()

    async def get_keys(self) -> Optional[KeysModel]:
        async with self.conn.execute(
            """
            SELECT private,public,short_id,decryption,encryption FROM keys;
            """) as curosr:
            row = await curosr.fetchone()
            return KeysModel(**dict(row)) if row else None

    async def add_user(self, user_id: str, config_id: str) -> UserModel:
        """[Mutating] Register a new user."""
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
        await self.update_nodes()
        return user

    async def upd_user_cancel_date(self, user_id: str, cancel_date: str) -> None:
            """[Mutating] Update subscription cancellation date."""
            await self.conn.execute(
                "UPDATE users SET cancel_date = ? WHERE user_id = ?;",
                (cancel_date, user_id),
            )
            await self.conn.commit()
            await self.update_nodes()

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

    

    async def close(self) -> None:
        """Close connection gracefully."""
        await self.conn.close()

    async def update_nodes(self):
        """
        Updates list of dependent nodes with port
        """
        db_snap = await self.get_snaphot()
        connector = aiohttp.TCPConnector(ssl=False)
        session = aiohttp.ClientSession(connector=connector,connector_owner=True)
        form = aiohttp.FormData()
        form.add_field(
            'file',
            db_snap,
            filename="users.db",
            content_type='application/octet-stream'
        )

        for s in self.dependent_nodes:
            await session.post(f"https://{s}/update",data=form,headers={"X-API-Key": self.api_key})

        await session.close()