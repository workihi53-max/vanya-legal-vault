#!/usr/bin/env bash
# Запуск «Вани» — работает без интернета.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
OFFLINE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --no-offline) OFFLINE=0; shift ;;
        *) echo "Неизвестный флаг: $1 (доступен --no-offline)" >&2; exit 2 ;;
    esac
done

if [ ! -x "$VENV/bin/python" ]; then
    echo "Ошибка: виртуальное окружение не найдено." >&2
    echo "Сначала выполните: ./install.sh" >&2
    exit 1
fi

# Ollama: если не отвечает — поднять в фоне (нужна только LLM-сценариям,
# детерминированное заполнение договора работает и без неё).
if command -v ollama >/dev/null 2>&1 && command -v curl >/dev/null 2>&1 \
   && ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Запускаю Ollama..."
    nohup ollama serve >/dev/null 2>&1 &
    for _ in $(seq 1 20); do
        curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
        sleep 1
    done
fi

# Предупреждение о ресурсах (не блокирует запуск).
if ! "$VENV/bin/python" "$ROOT/scripts/check_ram.py" --model "${VANYA_MODEL:-qwen2.5:3b}" >/dev/null 2>&1; then
    echo "Внимание: свободной ОЗУ мало — модель может работать медленно или уйти в своп." >&2
fi

export VANYA_OFFLINE="$OFFLINE"
export VANYA_MODEL="${VANYA_MODEL:-qwen2.5:3b}"

PORT="${VANYA_PORT:-8765}"
echo "Открой http://127.0.0.1:${PORT}"

cd "$ROOT"
exec "$VENV/bin/python" -m app.server
