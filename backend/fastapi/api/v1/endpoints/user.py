from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.fastapi.crud import UserService
from backend.fastapi.schemas import UserBase, UserCreate, UserSchema

router_sync = APIRouter()
router_async = APIRouter()

# Synchronous Endpoints
@router_sync.post("/users/", response_model=UserSchema)
def create_user(user_data: UserCreate, service: UserService = Depends()):
    return service.create_user(user_data)

@router_sync.get("/users/", response_model=list[UserSchema])
def get_users(skip: int = 0, limit: int = 30, service: UserService = Depends()):
    return service.get_users(skip, limit)

@router_sync.get("/user/", response_model=UserSchema)
def get_user(
    user_id: UUID = None, 
    discord_id: str = Query(None), 
    service: UserService = Depends()
):
    if user_id:
        return service.get_user(user_id)
    if discord_id:
        return service.get_user_by_discord_id(discord_id)
    raise HTTPException(status_code=400, detail="Either user_id or discord_id must be provided.")

@router_sync.put("/users/{user_id}", response_model=UserSchema)
def update_user(user_id: UUID, user_data: UserBase, service: UserService = Depends()):
    return service.update_user(user_id, user_data)

@router_sync.delete("/users/{user_id}", response_model=UserSchema)
def delete_user(user_id: UUID, service: UserService = Depends()):
    return service.delete_user(user_id)

# Asynchronous Endpoints
@router_async.post("/users/", response_model=UserSchema)
async def create_user_async(user_data: UserCreate, service: UserService = Depends()):
    return await service.create_user_async(user_data)

@router_async.get("/user/", response_model=UserSchema)
async def get_user_async(
    user_id: UUID | None = None, 
    discord_id: str | None = Query(None), 
    service: UserService = Depends()
):
    if user_id:
        return await service.get_user_async(user_id)
    if discord_id:
        return await service.get_user_by_discord_id_async(discord_id)
    raise HTTPException(status_code=400, detail="Either user_id or discord_id must be provided.")

@router_async.delete("/users/{user_id}", response_model=UserSchema)
async def delete_user_async(user_id: UUID, service: UserService = Depends()):
    return service.delete_user_async(user_id)