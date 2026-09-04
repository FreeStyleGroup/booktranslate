"""Короткие имена для адресов.

Вынесено отдельно, потому что нужно и организациям, и проектам: две копии
транслитерации разъехались бы на первой же правке таблицы соответствий.
"""

_TRANSLITERATION = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def slugify(value: str, *, fallback: str = "item", limit: int = 60) -> str:
    """Короткое имя из названия.

    Транслитерация намеренно простая: короткое имя не обязано быть
    красивым, оно обязано быть предсказуемым и уникальным. Владелец
    сможет его изменить.
    """
    lowered = value.strip().lower().translate(_TRANSLITERATION)
    cleaned = "".join(char if char.isalnum() else "-" for char in lowered)
    slug = "-".join(part for part in cleaned.split("-") if part)[:limit]

    return slug.strip("-") or fallback
