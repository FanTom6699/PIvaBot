from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

from openai import AsyncOpenAI, OpenAIError


logger = logging.getLogger(__name__)
ActionType = Literal["click", "wait", "open", "message", "noop"]
VALID_ACTIONS = {"click", "wait", "open", "message", "noop"}


class LLMClient(ABC):
    @abstractmethod
    async def decide(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


def load_json_file(path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ValueError("AI response must be a JSON object")
    kind = action.get("action")
    if kind not in VALID_ACTIONS:
        raise ValueError(f"Unsupported action: {kind}")

    if kind == "click" and not action.get("button"):
        raise ValueError("click action requires button")
    if kind == "open" and not action.get("menu"):
        raise ValueError("open action requires menu")
    if kind == "message" and not action.get("text"):
        raise ValueError("message action requires text")
    if kind == "wait":
        action["seconds"] = max(1, int(action.get("seconds", 60)))
    return action


class OpenAILLMClient(LLMClient):
    def __init__(self, api_key: str, model: str, recipes: dict[str, Any], rules: dict[str, Any]):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.recipes = recipes
        self.rules = rules
        self.fallback = HeuristicLLMClient(rules)

    async def decide(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = {
            "game": "Mafiozi Bot Telegram game assistant",
            "contract": {
                "allowed_actions": [
                    {"action": "click", "button": "точный текст inline-кнопки"},
                    {"action": "open", "menu": "название меню или кнопки"},
                    {"action": "wait", "seconds": 600},
                    {"action": "message", "text": "текст команды в чат с ботом"},
                    {"action": "noop"},
                ],
                "important": [
                    "Верни только JSON-объект без Markdown.",
                    "Не выдумывай кнопки: для click используй только текст из current_message.buttons.",
                    "Не трать предметы из rules.protected_items.",
                    "Сначала собирай готовые награды и закрывай срочные таймеры.",
                ],
            },
            "recipes": self.recipes,
            "rules": self.rules,
            "state": context,
        }
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=json.dumps(prompt, ensure_ascii=False),
            )
        except OpenAIError as error:
            logger.error("OpenAI API error, using heuristic fallback: %s", error)
            return await self.fallback.decide(context)

        text = response.output_text.strip()
        try:
            return validate_action(json.loads(text))
        except Exception:
            logger.exception("Bad AI response: %s", text)
            return {"action": "wait", "seconds": 60}


class HeuristicLLMClient(LLMClient):
    """Offline fallback used when OPENAI_API_KEY is not configured."""

    def __init__(self, rules: dict[str, Any]):
        self.rules = rules

    async def decide(self, context: dict[str, Any]) -> dict[str, Any]:
        current = context.get("current_message") or {}
        buttons = [button["text"] for button in current.get("buttons", [])]
        priorities = self.rules.get("button_priorities", [])

        for wanted in priorities:
            for button in buttons:
                if wanted.lower() in button.lower():
                    return {"action": "click", "button": button}

        next_timer = context.get("next_timer")
        if next_timer:
            return {"action": "wait", "seconds": 60}

        for menu in self.rules.get("default_menus", []):
            for button in buttons:
                if menu.lower() in button.lower():
                    return {"action": "click", "button": button}

        return {"action": "wait", "seconds": 120}


def build_llm(api_key: str | None, model: str, recipes: dict[str, Any], rules: dict[str, Any]) -> LLMClient:
    if api_key:
        return OpenAILLMClient(api_key, model, recipes, rules)
    logger.warning("OPENAI_API_KEY is not set. Using heuristic fallback.")
    return HeuristicLLMClient(rules)
