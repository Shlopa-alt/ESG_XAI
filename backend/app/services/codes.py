"""Следующий свободный человекочитаемый код: H-001, EXP-008, CR-02…"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session


def next_code(db: Session, column, prefix: str, width: int) -> str:  # type: ignore[no-untyped-def]
    nums = [int(m.group(1)) for c in db.scalars(select(column).where(column.like(f"{prefix}-%")))
            if (m := re.fullmatch(rf"{prefix}-(\d+)", c))]
    return f"{prefix}-{max(nums, default=0) + 1:0{width}d}"
