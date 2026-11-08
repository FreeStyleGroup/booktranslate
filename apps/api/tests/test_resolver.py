"""Решение замечаний моделью: строгий разбор ответа и состав запроса."""

import json

import pytest

from app.services.providers.base import Neighbourhood, ProviderError
from app.services.providers.resolver import (
    Problem,
    ResolveRequest,
    StubResolver,
    Verdict,
    build_user_message,
    parse_resolutions,
)


def request(key: str = "CH01-B0001", *problems: str) -> ResolveRequest:
    return ResolveRequest(
        key=key,
        source_text="1 Pumps",
        target_text="Насосы",
        source_language="en",
        target_language="ru",
        problems=[
            Problem(
                key=code,
                description="в переводе нет чисел: 1",
                category="number",
                severity="critical",
            )
            for code in (problems or ("BK01-CH01-ERR-0001",))
        ],
    )


def answer(*blocks: dict) -> str:
    return json.dumps({"blocks": list(blocks)}, ensure_ascii=False)


def block(key: str, text: str, *verdicts: tuple[str, str, str]) -> dict:
    return {
        "id": key,
        "text": text,
        "problems": [
            {"id": code, "verdict": verdict, "reason": reason} for code, verdict, reason in verdicts
        ],
    }


def test_fix_and_rejection_are_read_per_problem() -> None:
    wanted = request("CH01-B0001", "BK01-CH01-ERR-0001", "BK01-CH01-ERR-0002")
    raw = answer(
        block(
            "CH01-B0001",
            " 1 Насосы ",
            ("BK01-CH01-ERR-0001", "fix", "Номер раздела восстановлен"),
            ("BK01-CH01-ERR-0002", "not_an_error", "Термин склонён"),
        )
    )

    result = parse_resolutions(raw, [wanted])["CH01-B0001"]

    assert result.text == "1 Насосы"
    assert result.verdicts["BK01-CH01-ERR-0001"].verdict is Verdict.FIX
    assert result.verdicts["BK01-CH01-ERR-0002"].reason == "Термин склонён"


def test_text_without_a_fix_is_ignored() -> None:
    raw = answer(block("CH01-B0001", "что-то", ("BK01-CH01-ERR-0001", "unsure", "Нет данных")))

    assert parse_resolutions(raw, [request()])["CH01-B0001"].text is None


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("не json", "неверном виде"),
        (json.dumps({"other": []}), "нет списка блоков"),
        (answer(block("CH09-B0001", "", ("BK01-CH01-ERR-0001", "unsure", "?"))), "неизвестный"),
        (answer(), "не все блоки"),
        (answer(block("CH01-B0001", "", ("BK01-CH01-ERR-0099", "unsure", "?"))), "неизвестное"),
        (answer(block("CH01-B0001", "")), "не все замечания"),
        (answer(block("CH01-B0001", "", ("BK01-CH01-ERR-0001", "maybe", "?"))), "решение"),
        (answer(block("CH01-B0001", "", ("BK01-CH01-ERR-0001", "unsure", "  "))), "объяснила"),
        (answer(block("CH01-B0001", "  ", ("BK01-CH01-ERR-0001", "fix", "Исправлено"))), "текст"),
        (
            answer(
                block("CH01-B0001", "", ("BK01-CH01-ERR-0001", "unsure", "?")),
                block("CH01-B0001", "", ("BK01-CH01-ERR-0001", "unsure", "?")),
            ),
            "дважды",
        ),
    ],
)
def test_broken_answer_is_refused(raw: str, why: str) -> None:
    with pytest.raises(ProviderError, match=why):
        parse_resolutions(raw, [request()])


def test_request_carries_only_what_is_there() -> None:
    plain = json.loads(build_user_message([request()]))["blocks"][0]
    assert set(plain) == {"id", "kind", "source", "target", "problems"}
    assert "proposed_fix" not in plain["problems"][0]

    full = request()
    full.protected = ["r2"]
    full.previous_attempt = "Проверки не приняли исправление: в переводе нет чисел: 1"
    full.context = Neighbourhood(before=("Intro",), heading="Pumps")
    full.problems[0].proposed_fix = "1 Насосы"
    body = json.loads(build_user_message([full]))["blocks"][0]

    assert body["protected"] == ["r2"]
    assert body["previous_attempt"].startswith("Проверки не приняли")
    assert body["before"] == ["Intro"]
    assert body["heading"] == "Pumps"
    assert body["problems"][0]["proposed_fix"] == "1 Насосы"


async def test_stub_is_never_sure() -> None:
    result = await StubResolver().resolve([request()])

    verdict = result.items["CH01-B0001"].verdicts["BK01-CH01-ERR-0001"]
    assert verdict.verdict is Verdict.UNSURE
    assert result.items["CH01-B0001"].text is None
