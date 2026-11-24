from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import TypeAlias


CommitHook: TypeAlias = Callable[[str], None]


class DomainError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require_text(value: str, field: str, *, code: str = 'invalid_input') -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(code, f'{field} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise DomainError(code, f'{field} must be valid Unicode') from error
    return value


def encode_integer(value: int) -> str:
    return format(value, 'x')


def decode_integer(value: str) -> int:
    return int(value, 16)


def open_database(path: str | Path, *, create: bool = True) -> sqlite3.Connection:
    destination = path if create else Path(path).resolve().as_uri() + '?mode=rw'
    connection = sqlite3.connect(destination, uri=not create, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection, *, write: bool = False) -> Iterator[None]:
    connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
