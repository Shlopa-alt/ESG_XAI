"""Переводчик runner/translate/translator.py — без Argos: модели перевода подменены функциями."""

import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "translator", Path(__file__).resolve().parents[2] / "runner" / "translate" / "translator.py"
)
T = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(T)  # type: ignore[union-attr]


def test_texts_become_pairs_and_one_failure_does_not_stop_the_rest() -> None:
    def fake(source: str, target: str) -> Callable[[str], str]:
        assert (source, target) == ("fr", "ru")

        def fn(text: str) -> str:
            if text == "[сломается]":
                raise RuntimeError("модель упала")
            return f"<{text}>"

        return fn

    job = {"payload": {"source": "fr", "texts": ["Taux", "[сломается]", "", "année"]}}
    out = T.job_translate(job, fake)
    assert out["pairs"] == {"Taux": "<Taux>", "année": "<année>"} and out["failed"] == 1
    assert out["engine"].startswith("Argos Translate")
    with pytest.raises(ValueError, match="не знает"):
        T.job_translate({"payload": {"source": "es", "texts": ["hola"]}}, fake)


def test_no_direct_model_goes_through_english(monkeypatch: pytest.MonkeyPatch) -> None:
    models = {("ar", "en"): lambda s: f"en({s})", ("en", "ru"): lambda s: f"ru({s})"}
    monkeypatch.setattr(T, "_direct", lambda f, t: models.get((f, t)))
    assert T.translator("ar")("[текст]") == "ru(en([текст]))"
    assert T.translator("en")("[text]") == "ru([text])"  # прямая модель — без посредника
    with pytest.raises(RuntimeError, match="--install"):
        T.translator("zh")


def test_needs_only_models_into_english_and_english_to_russian() -> None:
    assert T.NEEDED == [("en", "ru"), ("ar", "en"), ("zh", "en"), ("fr", "en"), ("de", "en")]
    assert T.KINDS == {"kinds": ["translate"]}
