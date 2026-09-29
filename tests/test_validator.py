"""TC-AGT-02~06: 검증기."""
from pm_agent.agents.summarizer import validate
from pm_agent.graph import build_graph
from pm_agent.llm import FakeLLM
from pm_agent.models import Diagnosis, MemberSection


def final_state(cfg, raw):
    app = build_graph(cfg, FakeLLM(display=cfg.display), lambda: raw, log=lambda *_: None)
    return app.invoke({}, {"recursion_limit": 50})


def with_members(state, fn):
    rep = state["report"]
    return {**state, "report": rep.model_copy(update={"members": fn(rep.members)})}


def test_agt02_unknown_ref_detected(cfg, fixture):
    s = final_state(cfg, fixture("normal_day"))
    bad = with_members(s, lambda ms: [ms[0].model_copy(update={"yesterday": ms[0].yesterday + ["가짜 [pr:999]"]}), *ms[1:]])
    report, errors, _ = validate(bad, cfg)
    assert any("pr:999" in e for e in errors)
    assert all("pr:999" not in l for l in report.members[0].yesterday)


def test_agt02b_other_members_ref_rejected(cfg, fixture):
    s = final_state(cfg, fixture("normal_day"))
    # 지우의 커밋을 민수 어제 한 일로 적으면 거부
    swap = lambda ms: [m.model_copy(update={"yesterday": ["무한 스크롤 [commit:e5f6a7b]"]}) if m.member == "minsu" else m
                       for m in ms]
    _, errors, _ = validate(with_members(s, swap), cfg)
    assert any("minsu" in e for e in errors)


def test_agt02c_line_without_ref(cfg, fixture):
    s = final_state(cfg, fixture("normal_day"))
    _, errors, _ = validate(with_members(s, lambda ms: [ms[0].model_copy(update={"yesterday": ["열심히 일함"]}), *ms[1:]]), cfg)
    assert any("근거 ref 없음" in e for e in errors)


def test_agt03_missing_risk_detected(cfg, fixture):
    s = final_state(cfg, fixture("risky_day"))
    s = {**s, "report": s["report"].model_copy(update={"risks": s["report"].risks[1:]})}
    _, errors, _ = validate(s, cfg)
    assert any("위험 요소" in e for e in errors)


def test_v4_missing_member(cfg, fixture):
    s = final_state(cfg, fixture("normal_day"))
    _, errors, _ = validate(with_members(s, lambda ms: ms[1:]), cfg)
    assert any("팀원 섹션 누락" in e for e in errors)


def test_agt05_diagnosis_with_fabricated_line_dropped(cfg, fixture):
    s = final_state(cfg, fixture("ci_flaky"))
    fake = Diagnosis(test="t", pattern="flaky", hypothesis="h", evidence_lines=["로그에 없는 줄"], next_step="n")
    s = {**s, "report": s["report"].model_copy(update={"diagnosis": fake})}
    report, errors, warnings = validate(s, cfg)
    assert report.diagnosis is None and not errors and warnings


def test_agt06_email_masked(cfg, fixture):
    s = final_state(cfg, fixture("normal_day"))
    s = {**s, "report": s["report"].model_copy(update={"headline": "문의: minsu@example.com"})}
    report, _, warnings = validate(s, cfg)
    assert "@example.com" not in report.headline and warnings
