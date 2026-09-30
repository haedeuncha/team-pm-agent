"""LLM 계층: 실제 모델 래퍼(가짜 chat 모델로), FakeLLM 분기."""
import pytest

from pm_agent.agents import dumps
from pm_agent.llm import LLM, FakeLLM, LangChainLLM, fake_diagnosis, fake_finding, make_llm
from pm_agent.models import SummaryDraft


class FakeRaw:
    usage_metadata = {"input_tokens": 120, "output_tokens": 30}


class FakeChat:
    def __init__(self, parsed=None, error=None):
        self.parsed, self.error, self.calls = parsed, error, []

    def with_structured_output(self, schema, include_raw, method):
        assert include_raw and method == "function_calling"
        chat = self

        class Runnable:
            def invoke(self, messages):
                chat.calls.append(messages)
                return {"raw": FakeRaw(), "parsed": chat.parsed, "parsing_error": chat.error}
        return Runnable()


def wrapper(chat):
    llm = LangChainLLM.__new__(LangChainLLM)
    LLM.__init__(llm)
    llm.chat = chat
    return llm


def test_langchain_llm_returns_parsed_and_tracks_usage():
    draft = SummaryDraft(members=[], headline="h")
    llm = wrapper(FakeChat(parsed=draft))
    assert llm.structured("summarizer", SummaryDraft, "sys", "user", {}) is draft
    assert llm.usage["summarizer"] == {"calls": 1, "input": 120, "output": 30}


def test_langchain_llm_raises_parsing_error():
    llm = wrapper(FakeChat(error=ValueError("bad json")))
    with pytest.raises(ValueError):
        llm.structured("summarizer", SummaryDraft, "sys", "user", {})


def test_make_llm_providers(monkeypatch):
    assert isinstance(make_llm("fake"), FakeLLM)
    with pytest.raises(ValueError):
        make_llm("unknown-provider")
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert type(make_llm("openai", "gpt-4o-mini").chat).__name__ == "ChatOpenAI"


def test_base_llm_is_abstract():
    with pytest.raises(NotImplementedError):
        LLM().structured("n", SummaryDraft, "", "", {})


def test_fake_finding_blocked_with_linked_pr_and_unknown_rule():
    c = {"id": "c1", "rule_id": "R-ISSUE-BLOCKED", "severity": "medium", "refs": ["issue:38", "pr:39"],
         "owner": "jiwoo", "facts": {"assigned_days": 4, "open_linked_prs": ["pr:39"]}}
    assert "리뷰 대기" in fake_finding(c, str).explanation
    c2 = {**c, "rule_id": "R-NEW"}
    assert fake_finding(c2, str).title == "R-NEW"


def test_fake_diagnosis_patterns():
    base = {"test": "t", "log": "FAILED t - AssertionError", "suspect_commit": "commit:abc"}
    assert "외부 의존성" in fake_diagnosis({**base, "flaky": True}).hypothesis
    reg = fake_diagnosis({**base, "flaky": False})
    assert reg.pattern == "regression" and reg.suspect_commit == "commit:abc"


def test_dumps_handles_models_and_rejects_unknown():
    assert '"headline": "h"' in dumps(SummaryDraft(members=[], headline="h"))
    with pytest.raises(TypeError):
        dumps(object())


def test_fake_finding_unowned_bug_wording():
    """실데이터 개선: 막 등록된 버그가 '0일 지났지만'으로 어색하게 나오던 문제."""
    c = {"id": "c1", "rule_id": "R-ISSUE-UNOWNED", "severity": "medium", "refs": ["issue:1"],
         "owner": None, "facts": {"age_days": 0.1}}
    assert "오늘 등록된" in fake_finding(c, str).explanation
    c["facts"]["age_days"] = 3
    assert "3일 지났지만" in fake_finding(c, str).explanation
