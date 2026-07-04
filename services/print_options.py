from __future__ import annotations

from typing import Final


DEFAULT_PAPER_SIZE = "A4"

PAPER_SPECS: Final[dict[str, dict[str, object]]] = {
    "A4": {
        "code": "A4",
        "label": "A4",
        "width_mm": 210,
        "height_mm": 297,
        "sumatra_paperkind": 9,
    },
    "A5": {
        "code": "A5",
        "label": "A5",
        "width_mm": 148,
        "height_mm": 210,
        "sumatra_paperkind": 11,
    },
}


def normalize_paper_size(paper_size: str | None) -> str:
    value = (paper_size or DEFAULT_PAPER_SIZE).strip().upper()
    if value not in PAPER_SPECS:
        raise ValueError("Invalid paper size")
    return value


def get_paper_size_options() -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for code, spec in PAPER_SPECS.items():
        options.append(
            {
                "code": code,
                "label": str(spec["label"]),
                "width_mm": int(spec["width_mm"]),
                "height_mm": int(spec["height_mm"]),
            }
        )
    return options


def get_sumatra_paper_setting(paper_size: str | None) -> str | None:
    code = normalize_paper_size(paper_size)
    paperkind = PAPER_SPECS[code].get("sumatra_paperkind")
    return f"paperkind={paperkind}" if paperkind else None
