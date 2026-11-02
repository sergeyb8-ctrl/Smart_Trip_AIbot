#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Установите Python 3.10 или новее с python.org."
    exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Нужен Python 3.10+"'
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Создан .env. Откройте его, заполните BOT_TOKEN и повторите запуск."
    echo "При желании добавьте ключи Groq и Gemini. Анкета работает без них."
    open -t .env
    exit 0
fi
.venv/bin/python -m smarttrip

