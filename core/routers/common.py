from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.texts import HELP, WELCOME

router = Router(name="common")


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)
