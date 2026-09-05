from typing import List
import uuid

from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from argparse import ArgumentParser
from fastapi import FastAPI, HTTPException, Request, Security,status,Response,Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader


from db import utc_now,parse_utc,DBClient,UserModel
from xray_controller import XRAYController, fprint

controller: XRAYController  = None
database: DBClient  = None

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key_header:str = Security(api_key_header)):
    if api_key_header != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return api_key_header

@asynccontextmanager
async def lifespan(app: FastAPI):
    global controller, database,API_KEY
    database = await DBClient.Create()
    load_dotenv()
    server_ip:str   = os.getenv("server_ip","")
    server_port     = os.getenv("server_port","8080")
    print('fastcharge started')

    API_KEY = os.getenv("API_KEY")
    SERVER_CONF = os.getenv('server_config_path')
    if not API_KEY or not SERVER_CONF:
        raise Exception("Error API_KEY not found")

    controller = XRAYController(ip=server_ip,server_config_path=SERVER_CONF)

    task = asyncio.create_task(purge_task())
    yield
    task.cancel()
    await database.close()

app = FastAPI(
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
    docs_url=None,
    redoc_url=None,
    )

@app.post(
    "/user/add/{user_id}",
    summary="Register new user by their id (str)",
    tags=["User"],
    status_code=status.HTTP_201_CREATED)
async def add_user(user_id: str):
    user = await database.get_user(user_id)
    if user:
        raise HTTPException(detail="User already exists", status_code=400)
    
    config_id = str(uuid.uuid4())
    try:
        await database.add_user(user_id, config_id)
    except Exception:
        raise HTTPException(detail="Error adding new user", status_code=500)
    return {"msg": "success"}
        

@app.get(
    "/user/get/{user_id}",
    summary="Gather user info by user_id",
    tags=["User"],)
async def get_user(user_id:str):
    user = await database.get_user(user_id)
    if user is  None:
        raise HTTPException(detail="User not found",status_code=404)
    return {"user":user.model_dump()}


@app.get(
    "/users/get",
    summary="Gather all users",
    tags=["User"],)
async def get_users():
    users:List[UserModel] = await database.get_users()
    res = []

    for u in users:
        res.append(u.model_dump())
    return {"users":res}

@app.get(
    "/sub/get/{user_id}",
    summary="Get subscription link by user_id",
    tags=["Subscription"]
    )
async def get_sub(user_id: str):
    user = await database.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    
    if parse_utc(user.cancel_date) < utc_now():
        raise HTTPException(status_code=403, detail="Subscription expired")

    link  =  await controller.export_vless("vless", user.config_id)
    if not link:
        raise HTTPException(status_code=500, detail="Failed to generate link")

    return {"link": link}

@app.post(
    "/sub/add/{user_id}",
    summary="Update user subscription cancel_date and " \
    "add user into xray configuration",
    tags=["Subscription"]
    )
async def add_sub(user_id:str,request:Request):
    user = await database.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    body:dict = await request.json()
    cancel_date = body.get('cancel_date')

    if not cancel_date:
        raise HTTPException(status_code=400, detail="Missing cancel_date field")
    
    try:
        normalized_iso = parse_utc(cancel_date).isoformat()
    except ValueError:
        raise HTTPException(detail="Invalid ISO-8601 date format",status_code=400)
    
    await database.upd_user_cancel_date(user_id,normalized_iso)
    active_users = await database.get_active_users()
    await controller.merge_vless_clients(active_users,'vless')
    return {"msg":"success"}

async def setup(block_torrents:bool = True):
    global controller
    

    load_dotenv()
    server_ip:str   = os.getenv("server_ip","")
    server_port     = os.getenv("server_port","8080")

    SERVER_CONF = os.getenv('server_config_path')
    if not SERVER_CONF:
        raise Exception("Error API_KEY not found")

    controller = XRAYController(server_ip,SERVER_CONF)
    routing = "socks+tun"
    tag = "vless"
    sni = "www.wikipedia.org"

    controller.generate_reality_keys(save=True, mlken=False)
    await controller.update_reality_key(tag, sni, server_port, "tcp", 
                                        block_torrents=block_torrents,
                                        routing=routing)

    fprint(
        ("address", f"{server_ip}:{server_port}"), 
        ("routing", routing), 
        ("SNI", sni)
    )

async def purge_task():
    global database,controller
    while True:
        # start purge task immediately, to update users ( purge inactive )
        if database and controller:
            active_users = await database.get_active_users()
            await controller.merge_vless_clients(active_users,'vless')
        await asyncio.sleep(7200) # 2H
                    

# dev ENV
# start from ./fastcharge
# uvicorn  main:app --app-dir src --host 0.0.0.0 --port 8000 
# --ssl-keyfile key.pem --ssl-certfile cert.pem --no-server-header
def main():
    parser = ArgumentParser()
    parser.add_argument('-s','--setup',action='store_true')
    parser.add_argument('-bt','--block-torrents',action='store_true')

    args = parser.parse_args()
    if args.setup:
        asyncio.run(setup(args.block_torrents))

if __name__ == "__main__":
    main()
