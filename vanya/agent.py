"""Агент: цикл «модель → инструменты → модель», поток событий."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

from . import prompts, tools
from .llm import LLM, LLMError


@dataclass
class Event:
    kind: str  # "status" | "tool_call" | "tool_result" | "token" | "final" | "error"
    data: dict


class Agent:
    def __init__(self, llm=None, max_steps: int = 6, system: str | None = None) -> None:
        self.llm = llm if llm is not None else LLM()
        self.max_steps = max_steps
        self.system = system if system is not None else prompts.SYSTEM_PROMPT

    def run(self, user_message: str, history: list[dict] | None = None) -> Iterator[Event]:
        yield Event("status", {"message": "Ваня приступил к работе"})

        messages: list[dict] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        for _step in range(self.max_steps):
            try:
                result = self.llm.chat(messages, tools=tools.tool_schemas())
            except LLMError as exc:
                yield Event("error", {"message": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001 — приложение не должно падать
                yield Event("error", {"message": f"Ошибка модели: {exc}"})
                return

            assistant_msg: dict = {"role": "assistant", "content": result.content}
            if result.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in result.tool_calls
                ]
            messages.append(assistant_msg)

            if result.tool_calls:
                for tc in result.tool_calls:
                    yield Event(
                        "tool_call", {"name": tc.name, "arguments": tc.arguments}
                    )
                    disp = tools.dispatch(tc.name, tc.arguments)
                    if disp.get("ok"):
                        yield Event(
                            "tool_result",
                            {"name": tc.name, "ok": True, "result": disp.get("result")},
                        )
                    else:
                        yield Event(
                            "tool_result",
                            {"name": tc.name, "ok": False, "error": disp.get("error")},
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(disp, ensure_ascii=False),
                            "name": tc.name,
                        }
                    )
                continue

            yield Event("final", {"answer": result.content})
            return

        yield Event("final", {"answer": "Превышено число шагов, останавливаюсь."})

    def run_sync(self, user_message: str, history: list[dict] | None = None) -> Event:
        last = Event("status", {"message": ""})
        for event in self.run(user_message, history):
            last = event
        return last
