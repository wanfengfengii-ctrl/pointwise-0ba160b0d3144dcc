from fractions import Fraction

from energy.storage import decode_integer, encode_integer


def convert_reading(reading: int | None, coefficient: Fraction) -> Fraction | None:
    if reading is None:
        return None
    return reading * coefficient


def encode_quantity(value: Fraction | None) -> str | None:
    if value is None:
        return None
    return f'{encode_integer(value.numerator)}/{encode_integer(value.denominator)}'


def decode_fraction(value: str) -> Fraction:
    numerator, denominator = value.split('/')
    return Fraction(decode_integer(numerator), decode_integer(denominator))


def decode_quantity(value: str | None) -> Fraction | None:
    if value is None:
        return None
    return decode_fraction(value)
