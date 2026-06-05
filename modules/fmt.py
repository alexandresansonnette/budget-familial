"""Helpers de formatage."""

NBSP = "\u202f"


def fmt(n):
    if n is None:
        return "—"
    return f"{n:,.0f} €".replace(",", NBSP)


def fmt2(n):
    if n is None:
        return "—"
    return f"{n:,.2f} €".replace(",", NBSP)


def fmt_delta(n):
    if n is None:
        return "—"
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:,.0f} €".replace(",", NBSP)
