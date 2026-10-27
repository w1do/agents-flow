from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)


class Chat(StrictModel):
    id: StrictInt
    type: StrictStr | None = None
    title: StrictStr | None = None
    username: StrictStr | None = None


class User(StrictModel):
    id: StrictInt
    is_bot: bool = False
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    username: StrictStr | None = None


class Media(StrictModel):
    file_id: StrictStr = Field(min_length=1, max_length=256)
    file_size: StrictInt = Field(default=0, ge=0)
    file_name: StrictStr = Field(default="", max_length=256)
    caption: StrictStr | None = Field(default=None, max_length=4096)
    duration: StrictInt | None = Field(default=None, ge=0)
    mime_type: StrictStr | None = Field(default=None, max_length=256)
    title: StrictStr | None = Field(default=None, max_length=256)
    performer: StrictStr | None = Field(default=None, max_length=256)


class Reply(StrictModel):
    message_id: StrictInt
    sender: User | None = Field(None, alias="from")
    text: StrictStr | None = Field(default=None, max_length=4096)


class Message(StrictModel):
    message_id: StrictInt
    date: StrictInt | None = None
    chat: Chat
    sender: User | None = Field(None, alias="from")
    text: StrictStr | None = Field(default=None, max_length=4096)
    caption: StrictStr | None = Field(default=None, max_length=4096)
    voice: Media | None = None
    audio: Media | None = None
    reply_to_message: Reply | None = None


class Callback(StrictModel):
    id: StrictStr = Field(min_length=1, max_length=256)
    sender: User = Field(alias="from")
    message: Message | None = None
    data: StrictStr = Field(default="", max_length=256)


class Update(StrictModel):
    update_id: StrictInt = Field(ge=0)
    message: Message | None = None
    callback_query: Callback | None = None
