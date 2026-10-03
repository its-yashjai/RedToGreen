"""The whole agent with a scripted LLM: real MCP server subprocess, real graph, local sandbox."""

import asyncio

from redtogreen.llm.base import ToolCall, Turn
from redtogreen.llm.fake import ScriptedLLM
from redtogreen.pipeline import fix_local
from redtogreen.tracing import Tracer


def call(name, **args):
    return Turn("", [ToolCall(f"{name}-{len(args)}", name, args)], 10, 5, "tool_use")


def say(text):
    return Turn(text, [], 10, 5, "end_turn")


GOOD_FIX = [
    call("read_file", path="calc.py"),
    call("replace_in_file", path="calc.py", old_text="return a - b", new_text="return a + b"),
    say("Root cause: add() subtracted.\nFix: use +."),
]


def run(repo, settings, llm):
    tracer = Tracer()
    outcome = asyncio.run(fix_local(repo, settings, llm=llm, tracer=tracer))
    return outcome, tracer


def test_fixes_on_first_attempt(mini_repo, settings):
    outcome, tracer = run(mini_repo, settings, ScriptedLLM([GOOD_FIX]))
    assert outcome.status == "fixed"
    assert outcome.attempts == 1
    assert outcome.changed_files == ["calc.py"]
    assert "return a + b" in outcome.final_files["calc.py"]
    assert "Root cause" in outcome.explanation
    assert outcome.input_tokens == 30 and outcome.output_tokens == 15
    assert [s.node for s in tracer.steps][:2] == ["reproduce", "reproduce"]
    # the user's folder is untouched without --apply
    assert "return a - b" in (mini_repo / "calc.py").read_text()


def test_editing_tests_is_blocked_then_retry_succeeds(mini_repo, settings):
    cheat = [call("replace_in_file", path="tests/test_calc.py", old_text="== 5", new_text="== -1"),
             say("I changed the test.")]
    llm = ScriptedLLM([cheat, GOOD_FIX])
    outcome, tracer = run(mini_repo, settings, llm)
    assert outcome.status == "fixed" and outcome.attempts == 2
    blocked = [s for s in tracer.steps if s.tool == "replace_in_file" and not s.ok]
    assert blocked and "protected" in blocked[0].detail
    assert outcome.history[0]["violations"] == ["No code was changed."]
    assert "attempt 2" in llm.prompts[1] and "Rejected by safety rules" in llm.prompts[1]
    assert llm.conversations[0].user_messages  # it was nudged once to actually change code


def test_wrong_fix_then_right_fix(mini_repo, settings):
    wrong = [call("replace_in_file", path="calc.py", old_text="return x * 2", new_text="return x + x"),
             say("Fixed double.")]
    llm = ScriptedLLM([wrong, GOOD_FIX])
    outcome, _ = run(mini_repo, settings, llm)
    assert outcome.status == "fixed" and outcome.attempts == 2
    assert outcome.history[0]["passed"] is False
    assert "return x + x" in llm.prompts[1]  # the failed diff is fed back
    assert "return x + x" not in outcome.final_files["calc.py"]  # attempt 2 started from clean code


def test_gives_up_after_max_attempts(mini_repo, settings):
    wrong = [call("replace_in_file", path="calc.py", old_text="return x * 2", new_text="return 2 * x"),
             say("Done.")]
    outcome, _ = run(mini_repo, settings, ScriptedLLM([wrong, wrong, wrong]))
    assert outcome.status == "gave_up"
    assert outcome.attempts == settings.max_attempts
    assert outcome.diff == "" and outcome.final_files == {}


def test_not_reproducible_skips_the_llm(mini_repo, settings):
    (mini_repo / "calc.py").write_text((mini_repo / "calc.py").read_text().replace("a - b", "a + b"))
    llm = ScriptedLLM([GOOD_FIX])
    outcome, _ = run(mini_repo, settings, llm)
    assert outcome.status == "not_reproducible"
    assert llm.prompts == []  # no tokens spent
