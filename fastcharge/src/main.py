from typing import List, Optional
import uuid

import aiofiles
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from argparse import ArgumentParser
from fastapi import FastAPI, HTTPException, Request, Security,status,Response,Depends,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi

from db import utc_now,parse_utc,DBClient,UserModel
from xray_controller import XRAYController, fprint


controller: XRAYController  = None
database: DBClient          = None
API_KEY:str                 = None
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
VERSION = "1.0.2"

async def verify_api_key(request: Request):
    # Header (X-API-Key) - for SDK
    api_key = request.headers.get("X-API-Key")
    
    # query/cookie mostly for developers 
    if not api_key:
        api_key = request.query_params.get("api_key")
        
    if not api_key:
        api_key = request.cookies.get("api_key")

    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    global controller, database,API_KEY
    load_dotenv()
    database = await DBClient.Create()
    server_ip:str   = os.getenv("server_ip","")

    try:
        server_port     = int(os.getenv("server_port","8080"))
    except Exception as err:
        raise Exception(f"Error get server port from .env {err}")

    API_KEY = os.getenv("API_KEY","")
    SERVER_CONF = os.getenv('server_config_path')
    if not API_KEY or not SERVER_CONF:
        raise Exception("Error API_KEY not found")

    # Idempotent generate new key pair if not exists
    keys = await database.get_keys()
    keys_model = None
    if not keys:
        keys_model = XRAYController.generate_reality_keys(mlken=False)
        await database.set_keys(keys_model)
    if keys_model is not None:
        keys = keys_model
        

    controller = XRAYController(ip=server_ip,
                                port=server_port,
                                sni=os.getenv('sni',''),
                                tag=os.getenv('tag',''),
                                server_config_path=SERVER_CONF,
                                keys=keys)
    
    await controller.update_reality_key(block_torrents=True)
    active_users = await database.get_active_users()
    await controller.merge_vless_clients(active_users)


    task = asyncio.create_task(purge_task())
    yield
    task.cancel()
    await database.close()

app = FastAPI(
    version=VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    )


# Secure docs
@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(api_key: str = Depends(verify_api_key)):
    # Crucial: pass the key into openapi_url so Swagger UI can fetch the JSON spec
    return get_swagger_ui_html(
        openapi_url=f"/openapi.json?api_key={api_key}", 
        title="Secure Docs"
    )

@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(verify_api_key)])
async def get_open_api_endpoint():
    return get_openapi(title="Secure API", version=VERSION, routes=app.routes)


@app.post(
    "/user/add/{user_id}",
    summary="Register new user by their id (str)",
    tags=["User"],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)])
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
    tags=["User"],
    dependencies=[Depends(verify_api_key)])
async def get_user(user_id:str):
    user = await database.get_user(user_id)
    if user is  None:
        raise HTTPException(detail="User not found",status_code=404)
    return {"user":user.model_dump()}


@app.get(
    "/users/get",
    summary="Gather all users",
    tags=["User"],
    dependencies=[Depends(verify_api_key)])
async def get_users():
    users:List[UserModel] = await database.get_users()
    res = []

    for u in users:
        res.append(u.model_dump())
    return {"users":res}

@app.post(
    "/update",
    summary="Update current database",
    tags=["Control"],
    dependencies=[Depends(verify_api_key)])
async def update_state(file:UploadFile):
    fcontent = await file.read()
    
    try:
        await database.reconnect(fcontent)
    except Exception as err:
        raise HTTPException(status_code=505,detail=str(err))
    
    active_users = await database.get_active_users()
    await controller.merge_vless_clients(active_users)
    return {"msg":"database was updates"}

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

    link  =  await controller.export_vless(user.config_id)
    if not link:
        raise HTTPException(status_code=500, detail="Failed to generate link")

    return {"link": link}

# @app.get(
#     "/sub/get/json/{user_id}",
#     summary="Get subscription json configuration",
#     tags=["Subscription"]
#     )
# async def get_json_sub(user_id: str,ru_bypass:bool = True):
#     user = await database.get_user(user_id)
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

    
#     if parse_utc(user.cancel_date) < utc_now():
#         raise HTTPException(status_code=403, detail="Subscription expired")

#     node = await controller.export_client_outbound(user.config_id)
#     config  =  await controller.export_full_client_config([node], ru_bypass)

#     return config

@app.post(
    "/sub/add/{user_id}",
    summary="Update user subscription cancel_date and " \
    "add user into xray configuration",
    tags=["Subscription"],
    dependencies=[Depends(verify_api_key)]
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
    await controller.merge_vless_clients(active_users)
    return {"msg":"success"}

async def purge_task():
    global database,controller
    while True:
        # start purge task immediately, to update users ( purge inactive )
        if database and controller:
            active_users = await database.get_active_users()
            await controller.merge_vless_clients(active_users)
        await asyncio.sleep(7200) # 2H