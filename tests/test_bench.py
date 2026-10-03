from redtogreen.bench import DEMO_REPO, apply_edits, load_attacks, load_bugs, make_case, oracle_fix


def test_thirty_unique_bugs_each_applies_once():
    bugs = load_bugs()
    assert len(bugs) == 30
    assert len({b.id for b in bugs}) == 30
    for bug in bugs:
        text = (DEMO_REPO / bug.file).read_text()
        assert text.count(bug.find) == 1, bug.id


def test_oracle_fix_restores_the_original(tmp_path):
    for bug in load_bugs():
        repo = make_case(bug.edits, tmp_path / bug.id)
        fix = oracle_fix(bug)
        broken = (repo / bug.file).read_text()
        assert broken.count(fix.old_text) == 1, bug.id
        assert broken.replace(fix.old_text, fix.new_text) == (DEMO_REPO / bug.file).read_text(), bug.id


def test_attacks_load_and_apply(tmp_path):
    bugs = {b.id: b for b in load_bugs()}
    for attack in load_attacks():
        edits = (bugs[attack.base_bug].edits if attack.base_bug else []) + attack.edits
        make_case(edits, tmp_path / attack.id)


def test_apply_edits_rejects_ambiguous_text(tmp_path):
    repo = make_case([], tmp_path / "r")
    from redtogreen.bench import Edit

    try:
        apply_edits(repo, [Edit("shopkit/pricing.py", "return", "x")])
    except ValueError as exc:
        assert "expected the text to appear once" in str(exc)
    else:
        raise AssertionError("should have failed")
