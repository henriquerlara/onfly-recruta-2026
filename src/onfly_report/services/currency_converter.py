"""Conversão de valores para BRL."""

from __future__ import annotations

from decimal import Decimal, localcontext

from ..exceptions import InputFileError


def convert_to_brl(amount: Decimal, currency: str, rates: dict[str, Decimal]) -> Decimal:
    """Converte um valor na moeda informada para BRL usando a taxa da tabela."""
    try:
        rate = rates[currency]
    except KeyError as err:
        raise InputFileError(f"moeda sem taxa de câmbio: {currency}") from err
    with localcontext() as context:
        context.prec = max(context.prec, len(amount.as_tuple().digits) + len(rate.as_tuple().digits))
        return amount * rate
