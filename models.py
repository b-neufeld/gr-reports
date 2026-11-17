from dataclasses import dataclass
from datetime import date


@dataclass
class Book:
    review_id: str
    book_id: str
    title: str
    author: str
    rating: float
    review: str
    tags: list[str]
    cover_url: str
    read_date: date | None = None