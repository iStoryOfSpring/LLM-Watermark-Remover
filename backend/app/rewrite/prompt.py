from __future__ import annotations

import json

from backend.app.core.models import LayoutSensitivity, SentenceContext


LEXICAL_SYSTEM_PROMPT = """你是一个受约束的中文词汇替换引擎，不是文章重写模型。

你的任务只能是判断给定候选文本是否可以被完全等义替换，并在允许时给出最小范围的替换结果。

你不得：
1. 修改候选范围以外的任何文字；
2. 修改数字、日期、专有名词、专业术语、URL、代码或公式；
3. 改变否定关系、因果关系、数量、程度、概率或事实强度；
4. 添加或删除事实；
5. 重写整个句子或改变句子结构；
6. 使用候选允许替换集合之外的替换词。

如果不能确认完全等义，必须 KEEP。
只返回一个 JSON 对象，不要 Markdown，不要解释，不要输出完整句子。
JSON schema:
{"schema_version":"1.0","decisions":[{"id":"candidate id","action":"keep|replace","replacement":null|string,"reason":"short reason"}]}
"""


SENTENCE_SYSTEM_PROMPT = """你是一个受约束的中文局部句子改写引擎。

只有在明确给出 sentence_rewrite 任务时，你才可以提出整句替换。
你不得：
1. 拆分或合并句子；
2. 修改候选句之外的任何文字；
3. 修改 protected spans、数字、日期、金额、单位、实体、专业术语、URL、代码或公式；
4. 改变否定、因果、数量、程度、概率、义务关系或事实强度；
5. 添加、删除或臆造事实；
6. 输出超过长度限制的句子；
7. 输出完整文档。

如果不能确认完全等义，必须 KEEP。只返回规定 JSON，不要 Markdown，不要解释。
JSON schema:
{"schema_version":"1.1","task":"sentence_rewrite","decisions":[{"id":"sentence id","action":"keep|replace","replacement":null|string,"reason":"short reason"}]}
"""


class PromptBuilder:
    def build(self, context: SentenceContext) -> list[dict[str, str]]:
        payload = {
            "schema_version": "1.0",
            "task": "lexical_substitution",
            "context": {
                "previous_sentence": context.previous_sentence,
                "target_sentence": context.text,
                "next_sentence": context.next_sentence,
            },
            "protected": [span.model_dump(mode="json") for span in context.protected],
            "candidates": [candidate.model_dump(mode="json") for candidate in context.candidates],
        }
        return [
            {"role": "system", "content": LEXICAL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]

    def build_sentence(
        self,
        context: SentenceContext,
        layout_sensitivity: LayoutSensitivity = LayoutSensitivity.STRICT,
    ) -> list[dict[str, str]]:
        if isinstance(layout_sensitivity, str):
            layout_sensitivity = LayoutSensitivity(layout_sensitivity)
        length_limit = {
            LayoutSensitivity.STRICT: 10,
            LayoutSensitivity.NORMAL: 20,
            LayoutSensitivity.LOOSE: 30,
        }[layout_sensitivity]
        payload = {
            "schema_version": "1.1",
            "task": "sentence_rewrite",
            "context": {
                "previous_sentence": context.previous_sentence,
                "target_sentence": context.text,
                "next_sentence": context.next_sentence,
            },
            "protected": [span.model_dump(mode="json") for span in context.protected],
            "constraints": {
                "one_input_sentence_to_one_output_sentence": True,
                "max_length_change_percent": length_limit,
                "no_new_facts": True,
            },
            "candidate": {
                "id": context.sentence_id,
                "text": context.text,
            },
        }
        return [
            {"role": "system", "content": SENTENCE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]
