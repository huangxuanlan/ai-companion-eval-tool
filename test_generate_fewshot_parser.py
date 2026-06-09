from pathlib import Path

from generate import get_fewshot_messages, parse_fewshot_library


def test_parse_default_fewshot_library_routes_personal_types() -> None:
    library = parse_fewshot_library(
        Path(__file__).parent / "few_shot" / "长文模式_Few-shot示例库.md"
    )

    expected_types = {"霸道腹黑", "理性沉稳", "温暖陪伴", "可爱活泼"}
    assert expected_types.issubset(library.keys())
    assert all(len(library[type_name]) >= 5 for type_name in expected_types)

    messages = get_fewshot_messages("霸道腹黑型", library)
    assert len(messages) == 6
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


if __name__ == "__main__":
    test_parse_default_fewshot_library_routes_personal_types()
    print("OK: default few-shot library parses and routes")
