"""Deutsche Datumsangaben unabhängig von der System-Locale."""

from datetime import datetime

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
MONTHS_SHORT = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]


def long_date(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}"


def short_date(now: datetime) -> str:
    return f"{WEEKDAYS_SHORT[now.weekday()]} {now.day}. {MONTHS_SHORT[now.month - 1]}"
