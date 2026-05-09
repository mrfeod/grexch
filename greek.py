#!/usr/bin/env python3

import asyncio
import configparser
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

import aiohttp
import aiosqlite
import html2text
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, BotCommandScopeChat, Message
from dotenv import load_dotenv


RESULTS_URL = "https://www.greek-language.gr/certification/results/index.html"

NO_RESULT_MESSAGES = (
    "Τα αποτελέσματα δεν είναι ακόμη διαθέσιμα.",
)

INVALID_DATA_MESSAGES = (
    "Ο υποψήφιος δεν βρέθηκε.",
)

ATHENS_TIMEZONE = ZoneInfo("Europe/Athens")
AUTOCHECK_WINDOW_START = time(hour=8, minute=0)
AUTOCHECK_WINDOW_END = time(hour=20, minute=0)
AUTOCHECK_STOP_MONTH = 9
AUTOCHECK_STOP_DAY = 1


@dataclass(frozen=True)
class GreekCheck:
    chat_id: int
    center_code: str
    candidate_code: str
    candidate_surname: str

    @property
    def key(self) -> str:
        return f"{self.center_code}-{self.candidate_code}-{self.candidate_surname}"


@dataclass(frozen=True)
class RunTask:
    task: asyncio.Task
    interval_minutes: int


run_tasks: dict[int, RunTask] = {}
settings: dict[str, str] = {}
logger = logging.getLogger(__name__)

SETTINGS_INI_PATH = "settings.ini"
SETTINGS_SECTION = "bot"


def load_settings_ini(path: str = SETTINGS_INI_PATH) -> dict[str, str]:
    if not os.path.exists(path):
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as settings_file:
            parser.read_file(settings_file)
    except configparser.Error as exc:
        raise RuntimeError(f"Invalid settings file {path}: {exc}") from exc

    loaded: dict[str, str] = {}

    for key, value in parser.defaults().items():
        stripped = value.strip()
        if stripped:
            loaded[key.upper()] = stripped

    for section_name in parser.sections():
        if section_name.lower() != SETTINGS_SECTION:
            continue

        for key, value in parser.items(section_name):
            stripped = value.strip()
            if stripped:
                loaded[key.upper()] = stripped

    return loaded


def get_setting(name: str, default: str | None = None) -> str | None:
    value = settings.get(name)
    if value:
        return value

    env_value = os.getenv(name)
    if env_value:
        return env_value

    return default


def get_required_env(name: str) -> str:
    value = get_setting(name)
    if not value:
        raise RuntimeError(
            f"Missing required setting: {name}. "
            "Set it in settings.ini or in environment variables."
        )
    return value


def get_db_path() -> str:
    return get_setting("GREEK_BOT_DB", "greek_results_bot.sqlite3") or "greek_results_bot.sqlite3"


async def init_db() -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                chat_id INTEGER NOT NULL,
                center_code TEXT NOT NULL,
                candidate_code TEXT NOT NULL,
                candidate_surname TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    chat_id,
                    center_code,
                    candidate_code,
                    candidate_surname
                )
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                chat_id INTEGER PRIMARY KEY,
                interval_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        await db.commit()


async def add_check(check: GreekCheck) -> bool:
    async with aiosqlite.connect(get_db_path()) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO checks (
                chat_id,
                center_code,
                candidate_code,
                candidate_surname
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                check.chat_id,
                check.center_code,
                check.candidate_code,
                check.candidate_surname,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_checks(chat_id: int) -> list[GreekCheck]:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT chat_id, center_code, candidate_code, candidate_surname
            FROM checks
            WHERE chat_id = ?
            ORDER BY created_at
            """,
            (chat_id,),
        )

        rows = await cursor.fetchall()

    return [
        GreekCheck(
            chat_id=row["chat_id"],
            center_code=row["center_code"],
            candidate_code=row["candidate_code"],
            candidate_surname=row["candidate_surname"],
        )
        for row in rows
    ]


async def remove_check(chat_id: int, key: str) -> bool:
    parts = key.strip().split("-", maxsplit=2)

    if len(parts) != 3:
        return False

    center_code, candidate_code, candidate_surname = parts

    async with aiosqlite.connect(get_db_path()) as db:
        cursor = await db.execute(
            """
            DELETE FROM checks
            WHERE chat_id = ?
              AND center_code = ?
              AND candidate_code = ?
              AND candidate_surname = ?
            """,
            (
                chat_id,
                center_code.strip(),
                candidate_code.strip(),
                candidate_surname.strip().upper(),
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


async def remove_all_checks(chat_id: int) -> int:
    async with aiosqlite.connect(get_db_path()) as db:
        cursor = await db.execute(
            "DELETE FROM checks WHERE chat_id = ?",
            (chat_id,),
        )
        await db.commit()
        return cursor.rowcount


async def save_run(chat_id: int, interval_minutes: int) -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute(
            """
            INSERT INTO runs (chat_id, interval_minutes)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                interval_minutes = excluded.interval_minutes,
                created_at = CURRENT_TIMESTAMP
            """,
            (chat_id, interval_minutes),
        )
        await db.commit()


async def delete_run(chat_id: int) -> None:
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("DELETE FROM runs WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def get_runs() -> list[tuple[int, int]]:
    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT chat_id, interval_minutes
            FROM runs
            ORDER BY created_at
            """
        )

        rows = await cursor.fetchall()

    return [(row["chat_id"], row["interval_minutes"]) for row in rows]


def cleanup_markdown(markdown: str) -> str:
    processed_lines: list[str] = []

    for line in markdown.splitlines():
        line = line.rstrip()
        line = line.replace("|", "")
        line = re.sub(r" {2,}", "\n", line)

        for subline in line.splitlines():
            subline = subline.strip()

            if not subline:
                continue

            if re.fullmatch(r"[-\s]{2,}", subline):
                continue

            processed_lines.append(subline)

    return "\n".join(processed_lines).strip()


def format_result_html(html: str) -> str:
    html = html.replace('<img src="/certification/img/checkon.png">', "✓")
    html = html.replace('<img src="/certification/img/check.png">', "")

    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.ignore_links = True
    converter.ignore_images = True
    converter.unicode_snob = True

    markdown = converter.handle(html)
    return cleanup_markdown(markdown)


def now_in_athens() -> datetime:
    return datetime.now(ATHENS_TIMEZONE)


def to_athens_datetime(dt: datetime | None) -> datetime:
    if dt is None:
        return now_in_athens()

    if dt.tzinfo is None:
        return dt.replace(tzinfo=ATHENS_TIMEZONE)

    return dt.astimezone(ATHENS_TIMEZONE)


def is_within_autocheck_window(dt: datetime | None = None) -> bool:
    local_dt = to_athens_datetime(dt)
    local_time = local_dt.time()
    return AUTOCHECK_WINDOW_START <= local_time < AUTOCHECK_WINDOW_END


def is_autocheck_stopped_by_date(dt: datetime | None = None) -> bool:
    local_dt = to_athens_datetime(dt)
    stop_dt = datetime(
        year=local_dt.year,
        month=AUTOCHECK_STOP_MONTH,
        day=AUTOCHECK_STOP_DAY,
        tzinfo=ATHENS_TIMEZONE,
    )
    return local_dt >= stop_dt


async def fetch_result_page_html(
    session: aiohttp.ClientSession,
    center_code: str,
    candidate_code: str,
    candidate_surname: str,
) -> str:
    data = {
        "inputCenterCode": center_code,
        "inputCandidateCode": candidate_code,
        "inputCandidateSurname": candidate_surname,
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    timeout = aiohttp.ClientTimeout(total=20)

    async with session.post(RESULTS_URL, data=data, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        return await response.text()


def has_invalid_data_message(text: str) -> bool:
    return any(message in text for message in INVALID_DATA_MESSAGES)


async def fetch_greek_exam_result(
    session: aiohttp.ClientSession,
    center_code: str,
    candidate_code: str,
    candidate_surname: str,
) -> str:
    html = await fetch_result_page_html(
        session=session,
        center_code=center_code,
        candidate_code=candidate_code,
        candidate_surname=candidate_surname,
    )

    for message in NO_RESULT_MESSAGES:
        if message in html:
            return ""

    return format_result_html(html)


def parse_activation_message(chat_id: int, text: str) -> GreekCheck | None:
    secret = get_required_env("GREEK_BOT_SECRET")
    suffix = f"-{secret}"

    if not text.endswith(suffix):
        return None

    payload = text[: -len(suffix)]
    parts = payload.split("-", maxsplit=2)

    if len(parts) != 3:
        return None

    center_code, candidate_code, candidate_surname = parts

    center_code = center_code.strip()
    candidate_code = candidate_code.strip()
    candidate_surname = candidate_surname.strip().upper()

    if not center_code or not candidate_code or not candidate_surname:
        return None

    return GreekCheck(
        chat_id=chat_id,
        center_code=center_code,
        candidate_code=candidate_code,
        candidate_surname=candidate_surname,
    )


def format_check_result(check: GreekCheck, result: str) -> str:
    return f"Проверка: {check.key}\n\n{result}"


async def set_user_commands(bot: Bot, chat_id: int) -> None:
    commands = [
        BotCommand(command="check", description="Проверить результаты"),
        BotCommand(command="run", description="Проверять каждые n минут"),
        BotCommand(command="stop", description="Остановить проверку"),
        BotCommand(command="list", description="Показать мои коды"),
        BotCommand(command="remove", description="Удалить код или все коды"),
    ]

    await bot.set_my_commands(
        commands=commands,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def delete_user_commands(bot: Bot, chat_id: int) -> None:
    await bot.delete_my_commands(
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def check_all_for_chat(chat_id: int) -> list[tuple[GreekCheck, str | Exception]]:
    checks = await get_checks(chat_id)

    if not checks:
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_greek_exam_result(
                session=session,
                center_code=check.center_code,
                candidate_code=check.candidate_code,
                candidate_surname=check.candidate_surname,
            )
            for check in checks
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

    return list(zip(checks, results))


async def send_check_results(
    bot: Bot,
    chat_id: int,
    say_no_results: bool,
    say_errors: bool,
) -> bool:
    results = await check_all_for_chat(chat_id)

    if not results:
        if say_no_results:
            await bot.send_message(chat_id, "Сначала введите код активации")
        return False

    found_any = False

    for check, result in results:
        if isinstance(result, Exception):
            if say_errors:
                await bot.send_message(
                    chat_id,
                    f"Ошибка запроса для {check.key}: {result}",
                )
            else:
                print(f"Ошибка запроса для {check.key}: {result}")
            continue

        if result:
            found_any = True
            await bot.send_message(chat_id, format_check_result(check, result))

    if not found_any and say_no_results:
        await bot.send_message(chat_id, "Результатов пока нет")

    return found_any


async def run_loop(bot: Bot, chat_id: int, interval_minutes: int) -> None:
    try:
        while True:
            await asyncio.sleep(interval_minutes * 60)
            local_dt = now_in_athens()

            if is_autocheck_stopped_by_date(local_dt):
                await delete_run(chat_id)
                run_tasks.pop(chat_id, None)
                return

            if not is_within_autocheck_window(local_dt):
                continue

            found_any = await send_check_results(
                bot=bot,
                chat_id=chat_id,
                say_no_results=False,
                say_errors=False,
            )

            if found_any:
                await delete_run(chat_id)
                run_tasks.pop(chat_id, None)
                return

    except asyncio.CancelledError:
        raise


def stop_run_task(chat_id: int) -> bool:
    run_task = run_tasks.pop(chat_id, None)

    if not run_task:
        return False

    run_task.task.cancel()
    return True


async def restore_run_tasks(bot: Bot) -> None:
    for chat_id, interval_minutes in await get_runs():
        stop_run_task(chat_id)

        task = asyncio.create_task(
            run_loop(
                bot=bot,
                chat_id=chat_id,
                interval_minutes=interval_minutes,
            )
        )

        run_tasks[chat_id] = RunTask(
            task=task,
            interval_minutes=interval_minutes,
        )


dp = Dispatcher()


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer("Введите код активации")


@dp.message(Command("check"))
async def check_handler(message: Message, bot: Bot) -> None:
    await send_check_results(
        bot=bot,
        chat_id=message.chat.id,
        say_no_results=True,
        say_errors=True,
    )


@dp.message(Command("run"))
async def run_handler(
    message: Message,
    command: CommandObject,
    bot: Bot,
) -> None:
    checks = await get_checks(message.chat.id)

    if not checks:
        await message.answer("Сначала введите код активации")
        return

    if not command.args:
        await message.answer("Использование: /run n")
        return

    try:
        minutes = int(command.args.strip())
    except ValueError:
        await message.answer("n должно быть числом минут")
        return

    if minutes <= 0:
        await message.answer("n должно быть больше 0")
        return

    stop_run_task(message.chat.id)

    task = asyncio.create_task(
        run_loop(
            bot=bot,
            chat_id=message.chat.id,
            interval_minutes=minutes,
        )
    )

    run_tasks[message.chat.id] = RunTask(
        task=task,
        interval_minutes=minutes,
    )

    await save_run(message.chat.id, minutes)

    await message.answer(f"Проверка запущена: раз в {minutes} мин.")


@dp.message(Command("stop"))
async def stop_handler(message: Message) -> None:
    stopped = stop_run_task(message.chat.id)
    await delete_run(message.chat.id)

    if stopped:
        await message.answer("Проверка остановлена")
    else:
        await message.answer("Проверка не была запущена")


@dp.message(Command("list"))
async def list_handler(message: Message) -> None:
    checks = await get_checks(message.chat.id)

    if not checks:
        await message.answer("У вас нет добавленных кодов")
        return

    text = "Ваши коды:\n\n" + "\n".join(
        f"{index}. {check.key}"
        for index, check in enumerate(checks, start=1)
    )

    await message.answer(text)


@dp.message(Command("remove"))
async def remove_handler(
    message: Message,
    command: CommandObject,
    bot: Bot,
) -> None:
    if not command.args:
        await message.answer(
            "Использование:\n"
            "/remove CENTER-CANDIDATE-SURNAME\n"
            "/remove all"
        )
        return

    arg = command.args.strip()

    if arg.lower() == "all":
        removed_count = await remove_all_checks(message.chat.id)

        stop_run_task(message.chat.id)
        await delete_run(message.chat.id)
        await delete_user_commands(bot, message.chat.id)

        if removed_count:
            await message.answer("Все коды удалены")
        else:
            await message.answer("У вас не было добавленных кодов")

        return

    removed = await remove_check(message.chat.id, arg)

    if not removed:
        await message.answer("Такой код не найден")
        return

    checks_left = await get_checks(message.chat.id)

    if not checks_left:
        stop_run_task(message.chat.id)
        await delete_run(message.chat.id)
        await delete_user_commands(bot, message.chat.id)

    await message.answer(f"Код удалён: {arg}")


@dp.message(F.text)
async def activation_handler(message: Message, bot: Bot) -> None:
    if not message.text:
        return

    check = parse_activation_message(
        chat_id=message.chat.id,
        text=message.text.strip(),
    )

    if check is None:
        # На неправильные сообщения молчим.
        return

    try:
        async with aiohttp.ClientSession() as session:
            html = await fetch_result_page_html(
                session=session,
                center_code=check.center_code,
                candidate_code=check.candidate_code,
                candidate_surname=check.candidate_surname,
            )
    except Exception as exc:
        logger.exception("Ошибка проверки кода активации")
        await message.answer("Не удалось проверить код. Попробуйте позже.")
        return

    if has_invalid_data_message(html):
        await message.answer("Данные неверны, код не сохранён")
        return

    inserted = await add_check(check)
    await set_user_commands(bot, message.chat.id)

    if inserted:
        await message.answer(f"Код добавлен: {check.key}")
    else:
        await message.answer(f"Код уже был добавлен: {check.key}")


async def main() -> None:
    load_dotenv()
    global settings
    settings = load_settings_ini()

    token = get_required_env("TELEGRAM_BOT_TOKEN")
    get_required_env("GREEK_BOT_SECRET")

    await init_db()

    bot = Bot(token=token)

    await restore_run_tasks(bot)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
