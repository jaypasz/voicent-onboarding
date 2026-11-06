from __future__ import annotations

from .approval import Approval
from .base import StepType
from .book_call import BookCall
from .connect import Connect
from .form import Form
from .internal_task import InternalTask
from .placeholders import CredentialShare, InfoVideo, PaymentLink
from .upload import Upload

_TYPES: dict[str, StepType] = {t.type: t for t in (Form(), Upload(), Connect(), BookCall(), Approval(), InternalTask(), CredentialShare(), InfoVideo(), PaymentLink())}


def get(type_: str) -> StepType | None:
    return _TYPES.get(type_)


def all_types() -> list[StepType]:
    return list(_TYPES.values())
