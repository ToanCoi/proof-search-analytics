from src.common.schema import EVENT_SCHEMA, SCHEMA_VERSION, domain_of, to_table, validate


def _row(**kw):
    base = dict(schema_version=SCHEMA_VERSION, source="search", run_id="r", theorem_id="t",
                step_idx=0, state_before="⊢ True", tactic="trivial", outcome="finished",
                budget_id="M", policy="none")
    return {**base, **kw}


def test_valid_table():
    t = to_table([_row()])
    assert t.schema == EVENT_SCHEMA
    assert validate(t) == []


def test_rejects_bad_outcome_and_nulls():
    errs = validate(to_table([_row(outcome="weird", tactic=None)]))
    assert any("outcome" in e for e in errs)
    assert any("tactic has nulls" in e for e in errs)


def test_rejects_wrong_version():
    assert any("schema_version" in e for e in validate(to_table([_row(schema_version="9.9.9")])))


def test_domain_of():
    assert domain_of("Mathlib/Algebra/Group/Basic.lean") == "Algebra"
    assert domain_of("Other/File.lean") == "Other"
    assert domain_of(None) == "Other"
