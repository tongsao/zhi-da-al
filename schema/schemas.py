import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# class Chunk(BaseModel):
#     id: int
#     document_id: int
#     chunk_index: int
#     content: str
#     char_count: int
#     vector_id: Optional[str] = None
#     created_at: Optional[datetime.datetime] = None
#
#     model_config = ConfigDict(from_attributes=True)
#
#
# class Conversation(BaseModel):
#     id: int
#     title: str
#     created_at: Optional[datetime.datetime] = None
#     updated_at: Optional[datetime.datetime] = None
#
#     model_config = ConfigDict(from_attributes=True)
#
#
# class Document(BaseModel):
#     id: int
#     title: str
#     file_name: str
#     file_type: str
#     file_path: str
#     chunk_size: int
#     chunk_overlap: int
#     chunk_count: Optional[int] = None
#     total_chars: Optional[int] = None
#     status: Optional[str] = None
#     error_msg: Optional[str] = None
#     created_at: Optional[datetime.datetime] = None
#     updated_at: Optional[datetime.datetime] = None
#
#     model_config = ConfigDict(from_attributes=True)
#
#
# class Message(BaseModel):
#     id: int
#     conversation_id: int
#     role: str
#     content: str
#     question: Optional[str] = None
#     sources: Optional[List[dict]] = None
#     feedback: Optional[str] = None
#     feedback_comment: Optional[str] = None
#     created_at: Optional[datetime.datetime] = None
#
#     model_config = ConfigDict(from_attributes=True)

class ZdFileInfo(BaseModel):
    ID: str
    FILE_NAME: Optional[str] = None
    FILE_PATH: Optional[str] = None
    FILE_TYPE: Optional[str] = None
    CREATE_DATE: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)

class FileInfo(BaseModel):
    ID: str
    FILE_NAME: Optional[str] = None
    FILE_PATH: Optional[str] = None
    FILE_TYPE: Optional[str] = None
    FILE_TITLE: Optional[str] = None
    CHUNK_COUNT: Optional[int] = None
    CREATE_DATE: Optional[datetime.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class QaFeedback(BaseModel):
    conversation_id: Optional[str] = None
    question: str
    answer: str
    action: str  # copy / usable / need_fix / unusable


class Response(BaseModel):
    code: str = "0"
    message: str = "ok"
    data: Optional[dict] = None
