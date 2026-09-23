#!/usr/bin/env bash
# Первичная установка «Вани» — интернет нужен один раз (ставятся зависимости и модель).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
MODEL="qwen2.5:3b"
SKIP_MODEL=0

usage() {
    echo "Использование: ./install.sh [--skip-model] [--model ИМЯ]"
    echo "  --skip-model   не скачивать модель Ollama"
    echo "  --model ИМЯ    модель Ollama (по умолчанию qwen2.5:3b)"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-model) SKIP_MODEL=1; shift ;;
        --model) MODEL="${2:?--model требует имя модели}"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Неизвестный флаг: $1" >&2; usage ;;
    esac
done

echo "==> Проверка окружения"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Ошибка: python3 не найден. Установите Python 3.12." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "Ошибка: uv не найден. Установите: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

echo "==> Проверка ресурсов (предупреждение не останавливает установку)"
if ! python3 "$ROOT/scripts/check_ram.py" --model "$MODEL"; then
    echo "    Внимание: свободной ОЗУ мало — модель может работать медленно или уйти в своп."
fi

echo "==> Создание виртуального окружения"
if [ ! -x "$VENV/bin/python" ]; then
    uv venv --python 3.12 "$VENV"
fi

echo "==> Установка зависимостей"
uv pip install --python "$VENV/bin/python" -e "$ROOT"

if [ "$SKIP_MODEL" -eq 1 ]; then
    echo "==> Модель Ollama пропущена (--skip-model)"
else
    if ! command -v ollama >/dev/null 2>&1; then
        echo "Внимание: ollama не найден — модель не будет скачана." >&2
        echo "Установите Ollama (https://ollama.com/download) и повторите ./install.sh" >&2
    else
        echo "==> Проверка Ollama"
        if ! curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            echo "    Запускаю ollama serve в фоне..."
            nohup ollama serve >/dev/null 2>&1 &
            for _ in $(seq 1 30); do
                if curl -s --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
        fi
        echo "==> Скачивание модели $MODEL (может занять время)"
        ollama pull "$MODEL"
    fi
fi

echo "==> Генерация шаблона и тестовых данных"
"$VENV/bin/python" "$ROOT/scripts/make_template.py"
"$VENV/bin/python" "$ROOT/scripts/demo_data.py"

echo
echo "Готово. Запусти ./run.sh"
