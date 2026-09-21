"""Pydantic contract for the model's structured reply.

Everything the LLM returns goes through `parse_ai_reply` first, so the rest of
the pipeline only ever sees a validated, normalised `AIReply`.
"""
import json
import re
from typing import Literal, get_args

from ai.question_detector import is_question
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ReplyStyle = Literal["question", "share", "tease", "flirt", "compliment", "react", "clarify"]
REPLY_STYLES: tuple[str, ...] = get_args(ReplyStyle)

MAX_MESSAGES = 2

_STYLE_ALIASES = {
    "reaction": "react",
    "comment": "react",
    "reply": "react",
    "ask": "question",
    "asking": "question",
    "hỏi": "question",
    "chia sẻ": "share",
    "trêu": "tease",
    "khen": "compliment",
    "praise": "compliment",
    "flirting": "flirt",
    "clarification": "clarify",
    "làm rõ": "clarify",
}


def _clean_str(value) -> str:
    return "" if value is None else str(value).strip()


class AIReply(BaseModel):
    """One validated model reply."""

    model_config = ConfigDict(extra="ignore")

    context_analysis: str = ""
    action: Literal["REPLY", "WAIT"] = "REPLY"
    messages: list[str] = Field(default_factory=list)
    intent: str = ""
    topic: str = ""
    pattern_used: str = ""
    reply_style: ReplyStyle = "react"
    question_key: str = ""

    @field_validator("action", mode="before")
    @classmethod
    def _norm_action(cls, v):
        v = _clean_str(v).upper()
        return v or "REPLY"

    @field_validator("messages", mode="before")
    @classmethod
    def _norm_messages(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, (list, tuple)):
            raise ValueError("messages phải là danh sách chuỗi")
        return [s for s in (_clean_str(x) for x in v) if s]

    @field_validator("reply_style", mode="before")
    @classmethod
    def _norm_style(cls, v):
        v = _clean_str(v).lower()
        v = _STYLE_ALIASES.get(v, v)
        return v if v in REPLY_STYLES else "react"

    @field_validator("context_analysis", "intent", "topic", "pattern_used", "question_key", mode="before")
    @classmethod
    def _norm_text(cls, v):
        return _clean_str(v)

    @model_validator(mode="after")
    def _finalize(self):
        if len(self.messages) > MAX_MESSAGES:
            self.messages = self.messages[:MAX_MESSAGES]
        if not self.messages:
            self.action = "WAIT"
        if self.action == "WAIT":
            self.messages = []
        # `intent` doubles as the question key in the existing contract.
        if not self.question_key and self.intent and any(is_question(m) for m in self.messages):
            self.question_key = self.intent
        return self

    @property
    def asks_question(self) -> bool:
        if not self.messages:
            return False
        return (
            any(is_question(m) for m in self.messages)
            or bool(self.question_key)
            or self.reply_style == "question"
        )

    @property
    def question_texts(self) -> list[str]:
        """Messages that ask something, with or without `?` (the last one if only question_key says so)."""
        qs = [m for m in self.messages if is_question(m)]
        if not qs and self.question_key and self.messages:
            qs = [self.messages[-1]]
        return qs

    @property
    def stored_style(self) -> str:
        """Style to persist: an actual question always counts as `question`."""
        return "question" if self.asks_question and self.reply_style in ("react", "share") else self.reply_style


def _extract_json_text(raw: str) -> str | None:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    if text.startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return None


def parse_ai_reply(raw: str) -> tuple[AIReply | None, str | None]:
    """Validate raw model text. Returns (reply, None) or (None, error_reason)."""
    text = (raw or "").strip()
    if not text:
        return None, "output rỗng"
    if text.strip("\"'` ").upper() == "WAIT":
        return AIReply(action="WAIT"), None

    blob = _extract_json_text(text)
    if blob is None:
        return None, "output không phải JSON (phải trả đúng JSON theo OUTPUT CONTRACT)"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return None, f"JSON không hợp lệ: {e.msg}"
    if not isinstance(data, dict):
        return None, "JSON phải là một object"
    try:
        return AIReply.model_validate(data), None
    except ValidationError as e:
        fields = ", ".join(sorted({".".join(map(str, err["loc"])) or "?" for err in e.errors()}))
        return None, f"JSON sai schema ở trường: {fields}"
