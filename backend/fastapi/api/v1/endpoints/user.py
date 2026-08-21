from uuid import UUID

from fastapi import APIRouter, Depends

from backend.fastapi.crud import UserService
from backend.fastapi.schemas import UserBase, UserCreate, UserSchema

router = APIRouter()


@router.post("/users/", response_model=UserSchema)
async def create_user(user_data: UserCreate, service: UserService = Depends()):
    return await service.create(user_data)


@router.get("/users/", response_model=list[UserSchema])
async def list_users(skip: int = 0, limit: int = 30, service: UserService = Depends()):
    return await service.list(skip, limit)


@router.get("/users/{user_id}", response_model=UserSchema)
async def get_user(user_id: UUID, service: UserService = Depends()):
    return await service.get(user_id)


@router.put("/users/{user_id}", response_model=UserSchema)
async def update_user(user_id: UUID, user_data: UserBase, service: UserService = Depends()):
    return await service.update(user_id, user_data)


@router.delete("/users/{user_id}", response_model=UserSchema)
async def delete_user(user_id: UUID, service: UserService = Depends()):
    return await service.delete(user_id)


@router.get("/user/", response_model=UserSchema | None)
async def get_user_by_discord_id(discord_id: str, service: UserService = Depends()):
    return await service.get_by_discord_id(discord_id)
