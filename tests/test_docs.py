from agentmon import cardmodel, catalog, criteria, fraud_types, riskregister


def test_risk_register_is_consistent():
    ids = [r[0] for r in riskregister.R]
    assert len(ids) == len(set(ids)) >= 50
    assert all(r[1] in riskregister.GROUPS and r[6] in riskregister.STATUS_ORDER for r in riskregister.R)
    assert set(riskregister.summary()) == {"CÓ", "MỘT PHẦN", "CHƯA"}
    assert all(r[5] and r[3] and r[4] for r in riskregister.R)


def test_generated_docs_in_sync():
    import os
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    for name, gen in (("FEATURE_CATALOG.md", catalog.markdown), ("FRAUD_TAXONOMY.md", fraud_types.markdown),
                      ("CARD_TAXONOMY.md", cardmodel.markdown), ("RISK_REGISTER.md", riskregister.markdown), ("CRITERIA.md", criteria.markdown)):
        assert open(os.path.join(d, name), encoding="utf-8").read().strip() == gen().strip(), f"{name} lỗi thời – chạy: python -m tools.gen_docs"


def test_criteria_matrix_is_complete():
    ids = [c[0] for c in criteria.C]
    assert len(ids) == len(set(ids)) >= 20 and all(all(f for f in c) for c in criteria.C)
    assert {c[8] for c in criteria.C} <= {"T1", "T2", "T1+T2"}
    text = " ".join(c[7] for c in criteria.C)
    for kw in ("CARD_ENUMERATION", "PRESENTATION" if False else "ISO/IEC 30107-3", "ACTOR_UNVERIFIED", "AGENT_ECHO", "ATM_CARD_COLLECTION", "FRAUD_RING"):
        assert kw in text + " ".join(c[7] for c in criteria.C) or kw in " ".join(" ".join(c) for c in criteria.C)
