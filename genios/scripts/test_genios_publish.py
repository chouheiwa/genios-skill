"""genios_publish 的离线测试：python3 <skill>/scripts/test_genios_publish.py"""
import argparse
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genios_publish as gp  # noqa: E402

DRAFT = {"ModelID": "m", "UpdateTime": "t", "ModelName": "x", "PrePrompt": "旧",
         "QADatasetConfig": {"TopK": 1, "MatchType": "force", "Similarity": 0.5},
         "ModelConfig": {"MaxTokens": 512, "RoundsReserved": 3, "ReasoningSwitchType": "disabled", "ReasoningMode": 0}}


def args(**kw):
    base = dict(prompt_file=None, prompt_marker=None, max_tokens=None, reasoning=None, history_rounds=None,
                qa_match=None, qa_similarity=None)
    return argparse.Namespace(**{**base, **kw})


class BuildConfigTest(unittest.TestCase):
    def test_only_overrides_given_fields_and_drops_readonly(self):
        cfg = gp.build_config(DRAFT, args(max_tokens=2048, history_rounds=100, qa_match="auto", qa_similarity=0.92))
        self.assertNotIn("UpdateTime", cfg)
        self.assertEqual(cfg["PrePrompt"], "旧")
        self.assertEqual((cfg["ModelConfig"]["MaxTokens"], cfg["ModelConfig"]["RoundsReserved"]), (2048, 100))
        self.assertEqual(cfg["QADatasetConfig"], {"TopK": 1, "MatchType": "auto", "Similarity": 0.92})
        self.assertIs(cfg["ModelConfig"]["ReasoningMode"], False)  # 必须是布尔值

    def test_refuses_draft_with_reasoning_unless_explicit(self):
        draft = dict(DRAFT, ModelConfig=dict(DRAFT["ModelConfig"], ReasoningSwitchType="auto", ReasoningMode=True))
        with self.assertRaises(SystemExit):
            gp.build_config(draft, args())
        cfg = gp.build_config(draft, args(reasoning="disabled"))
        self.assertEqual((cfg["ModelConfig"]["ReasoningSwitchType"], cfg["ModelConfig"]["ReasoningMode"]), ("disabled", False))
        cfg = gp.build_config(draft, args(reasoning="auto"))  # 明确指定时允许
        self.assertTrue(cfg["ModelConfig"]["ReasoningMode"])

    def test_prompt_marker_extracts_text_block(self):
        fd, path = tempfile.mkstemp(suffix=".md")
        os.write(fd, "# 文档\n## 2. 系统提示词\n说明\n```text\n你是助手。\n第二行\n```\n".encode())
        os.close(fd)
        self.addCleanup(os.remove, path)
        cfg = gp.build_config(DRAFT, args(prompt_file=path, prompt_marker="## 2. 系统提示词"))
        self.assertEqual(cfg["PrePrompt"], "你是助手。\n第二行")


if __name__ == "__main__":
    unittest.main()
