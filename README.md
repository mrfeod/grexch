# Greek Results Bot

Telegram-бот для проверки результатов экзамена на сайте `greek-language.gr`.

Бот умеет:
- проверять результат вручную
- запускать периодическую проверку каждые `n` минут
- присылать сообщение, когда результат найден
- хранить несколько кодов для одного пользователя


## Код активации

Пользователь отправляет боту код в формате:
```text
CENTER-CANDIDATE-SURNAME-SECRET
```

Пример:
```text
54321-1234-ANDREOU-the-secret-key
```

Где:
```text
54321          — код экзаменационного центра
1234           — код кандидата
ANDREOU        — фамилия кандидата
the-secret-key — значение GREEK_BOT_SECRET
```

Перед сохранением бот делает тестовый запрос на `greek-language.gr`.
Если сайт возвращает сообщение о неверных данных, код не сохраняется.

## Простой запуск

Этот вариант без Python: скачиваем готовый бинарник из GitHub и запускаем.

### 1. Создайте Telegram-бота

1. Откройте [BotFather](https://t.me/BotFather).
2. Отправьте команду:
```text
/newbot
```
3. BotFather выдаст токен вида:
```text
1234567890:AA...
```
4. Сохраните токен, он нужен в `settings.ini`.

### 2. Скачайте бинарник из GitHub

1. Cкачайте архив под вашу ОС:
- [Ubuntu Linux](https://github.com/mrfeod/grexch/releases/download/main-latest/greek-bot-ubuntu-latest.zip)
- [macOS](https://github.com/mrfeod/grexch/releases/download/main-latest/greek-bot-macos-latest.zip)
- [Windows](https://github.com/mrfeod/grexch/releases/download/main-latest/greek-bot-windows-latest.zip)
2. Распакуйте архив в отдельную папку.

После распаковки будут:
- исполняемый файл (`dist/greek-bot` или `dist/greek-bot.exe`)
- `settings.ini.example`
- README.md

### 3. Настройте `settings.ini`

Скопируйте шаблон `settings.ini.example` в `dist/settings.ini` (рядом с исполняемым файлом), откройте `settings.ini` и заполните:
```ini
[bot]
TELEGRAM_BOT_TOKEN=1234567890:AA...
GREEK_BOT_SECRET=the-secret-key
GREEK_BOT_DB=greek_results_bot.sqlite3
```

Пояснения:
- `TELEGRAM_BOT_TOKEN` — токен из BotFather
- `GREEK_BOT_SECRET` — ваш секрет для кода активации
- `GREEK_BOT_DB` — путь к SQLite-файлу (можно оставить как есть)

### 4. Запустите бота

Linux/macOS:

```bash
chmod +x ./greek-bot
./greek-bot
```

Windows:
Двойной клик по `greek-bot.exe` или через терминал PowerShell:
```powershell
.\greek-bot.exe
```

Бот работает, пока открыт этот процесс. Остановка: `Ctrl+C`.

## Запуск для опытных пользователей

Этот вариант для запуска из исходников или своей сборки.

### Требования

- Python 3.10+
- Bash (для `start.sh`/`stop.sh`)

### 1. Клонирование и установка

```bash
git clone https://github.com/mrfeod/grexch.git
cd grexch
```

### 2. Конфигурация

```bash
cp .env.example .env
```

Откройте `.env` и заполните переменные:
```env
TELEGRAM_BOT_TOKEN=1234567890:AA...
GREEK_BOT_SECRET=the-secret-key
GREEK_BOT_DB=greek_results_bot.sqlite3
```

### 3. Запуск из исходников
Запуск:
```bash
bash ./start.sh
```

Остановка:
```bash
bash ./stop.sh
```

Или напрямую (нужно создать venv и установить requirements):
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python greek.py
```

## Команды бота

После команды `/start` бот просит ввести код активации.

### `/check`

Проверить все сохраненные коды вручную.

### `/run n`

Запустить периодическую проверку раз в `n` минут.
Проверки выполняются только в окне `08:00–20:00` по времени Афин.
После `1 сентября` (по времени Афин) автопроверка останавливается.

Пример:

```text
/run 30
```

### `/stop`

Остановить периодическую проверку.

### `/list`

Показать все добавленные коды пользователя.

### `/remove CODE`

Удалить один код.

Пример:

```text
/remove 54321-1234-ANDREOU
```

### `/remove all`

Удалить все коды пользователя и остановить периодическую проверку.

## Если сайт greek-language.gr недоступен

- При команде `/check` бот покажет ошибку запроса.
- При фоновой проверке через `/run n` бот продолжит попытки и отправит результат, когда сайт снова ответит.

# Бонус
Однострочный bash-скрипт для получения результата в человекочитаемом виде:
```bash
CODE=КОД_КАНДИДАТА; SURNAME=ФАМИЛИЯ; curl -sS 'https://www.greek-language.gr/certification/results/index.html' -X POST --data-raw "inputCenterCode=35703&inputCandidateCode=${CODE}&inputCandidateSurname=${SURNAME}" | LC_ALL=C.UTF-8 perl -Mutf8 -CSDA -0777 -pe 's#<img[^>]*checkon\.png[^>]*># ✓#g;s#<img[^>]*>##g;s#</th><td><table[^>]*>#\n#g;s#</(?:h4|p|tr)>#\n#g;s#</b># #g;s#</td><td[^>]*># #g;s#<[^>]+>##g;s#^\s+|\s+$##gm;s#[ \t]{2,}# #g;s#\n+#\n#g;s#\z#\n#'
```

Нужно поменять `CODE` и `SURNAME` на свои.
`inputCenterCode=35703` - по умолчанию введен код экзаменационного центра на Кипре, если вы сдавали экзамен в другом центре, этот код тоже нужно поменять.
