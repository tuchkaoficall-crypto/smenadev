import asyncio
from database import async_session
from services import UserService, WorkerService

async def check():
    async with async_session() as s:
        user = await UserService.get_user(s, 6630976350)
        worker = await WorkerService.get_worker(s, 6630976350)
        print(f'User: {user}')
        print(f'User role: {user.role if user else None}')
        print(f'Worker: {worker}')
        print(f'Worker ID: {worker.id if worker else None}')
        print(f'Worker categories: {worker.categories if worker else None}')

asyncio.run(check())
