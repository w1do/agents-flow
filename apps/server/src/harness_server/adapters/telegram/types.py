"""Типы и ошибки адаптера Telegram. Внутренние: MCP, API и консоль их не видят (D-29)."""

from dataclasses import dataclass

# Описание ошибки Telegram короткое; длинный текст в исключении не нужен и может нести лишнее.
_DESCRIPTION_LIMIT = 200


@dataclass(frozen=True, slots=True)
class InlineButton:
    """Кнопка под сообщением. callback_data приходит обратно в callback_query."""

    text: str
    callback_data: str


@dataclass(frozen=True, slots=True)
class InlineKeyboard:
    """Инлайн-клавиатура: ряды кнопок."""

    rows: tuple[tuple[InlineButton, ...], ...]

    def to_api(self) -> dict[str, list[list[dict[str, str]]]]:
        """Форма reply_markup, которую принимает Bot API."""
        return {
            "inline_keyboard": [
                [{"text": button.text, "callback_data": button.callback_data} for button in row]
                for row in self.rows
            ]
        }


@dataclass(frozen=True, slots=True)
class TelegramFile:
    """Метаданные файла из getFile. file_path нужен для скачивания."""

    file_id: str
    file_path: str | None
    file_size: int | None


class TelegramError(Exception):
    """Ошибка Bot API или сети. Сообщение без URL и токена: только метод, код и описание."""

    def __init__(self, method: str, error_code: int | None, description: str) -> None:
        short = description[:_DESCRIPTION_LIMIT]
        super().__init__(f"telegram {method} failed: {error_code} {short}")
        self.method = method
        self.error_code = error_code
        self.description = short


class MessageNotEditable(TelegramError):
    """Сообщение нельзя отредактировать (удалено, старое, чужое) — нужно отправить новое."""


class FileTooLarge(TelegramError):
    """Файл больше разрешённого лимита."""
