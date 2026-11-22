"""入力の生成と、JSON としての比較。"""

import json

from hypothesis import strategies as st

# XML 1.0 の文書に書ける文字 (Char)。SOAP の XML を通る値の生成に使う。
xml_text = st.text(
    alphabet=st.sampled_from("\t\n\r")
    | st.characters(
        min_codepoint=0x20, exclude_categories=["Cs"], exclude_characters="\ufffe\uffff"
    )
)


def as_json(value: object) -> str:
    """
    JSON の値として比べるための表現。

    Python の == は True と 1、False と 0 を等しいとみなし、JSON の型の違いを見逃す。
    """
    return json.dumps(value, sort_keys=True)
