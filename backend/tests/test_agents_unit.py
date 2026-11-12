import copy

import pytest

from app.agents import registry
from app.agents.registry import AgentSpec
from app.agents.runner import MAX_TOOL_OUTPUT_CHARS, extract_tool_calls, run_agent
from app.agents.tools import TOOLS, Tool, ToolContext, ToolError, ToolResult, _calculator, safe_eval
from app.services.errors import LLMUnavailable


# ---------- calculator ----------
def test_safe_eval_basic_arithmetic():
    assert safe_eval("2+3*4") == 14
    assert safe_eval("(40*0.25)+3") == 13.0
    assert safe_eval("2**3") == 8
    assert safe_eval("-5 + 10 // 3") == -2
    assert safe_eval("7 % 4") == 3


@pytest.mark.parametrize(
    "bad",
    ["__import__('os').system('dir')", "abs(3)", "x + 1", "1 +", "2**1000", "1/0", "'a' * 3", "9" * 120],
)
def test_safe_eval_rejects_anything_unsafe(bad):
    with pytest.raises(ToolError):
        safe_eval(bad)


def test_calculator_tool_formats_whole_numbers():
    assert _calculator(None, {"expression": "(40*0.25)+3"}).text == "(40*0.25)+3 = 13"
    with pytest.raises(ToolError):
        _calculator(None, {"expression": ""})


# ---------- reading tool calls from the model ----------
KNOWN = {"search_documents", "calculator"}


def test_extract_proper_tool_calls_and_json_string_arguments():
    message = {
        "tool_calls": [
            {"function": {"name": "search_documents", "arguments": {"query": "pump"}}},
            {"function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}},
        ]
    }
    calls = extract_tool_calls(message, KNOWN)
    assert [c.name for c in calls] == ["search_documents", "calculator"]
    assert calls[1].arguments == {"expression": "1+1"}


def test_extract_limits_calls_per_turn():
    message = {"tool_calls": [{"function": {"name": "calculator", "arguments": {}}}] * 10}
    assert len(extract_tool_calls(message, KNOWN)) == 3


def test_extract_accepts_json_written_as_text_for_known_tools_only():
    ok = extract_tool_calls({"content": '{"name": "calculator", "parameters": {"expression": "2+2"}}'}, KNOWN)
    assert ok[0].name == "calculator" and ok[0].arguments == {"expression": "2+2"}
    assert extract_tool_calls({"content": '{"name": "rm_rf", "parameters": {}}'}, KNOWN) == []
    assert extract_tool_calls({"content": "Just a normal answer."}, KNOWN) == []
    assert extract_tool_calls({"content": "{not json}"}, KNOWN) == []


# ---------- the agent loop (with dummy tools, no database) ----------
class ScriptedChat:
    model_name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((copy.deepcopy(messages), tools))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def call(name, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def final(text):
    return {"role": "assistant", "content": text}


def make_tools(handler=None):
    def default(ctx, args):
        return ToolResult(f"result for {args.get('q')}", [{"filename": "a.pdf", "page": 2}])

    echo = Tool("echo", "echo tool", {"type": "object", "properties": {}}, handler or default)
    secret = Tool("secret", "secret tool", {"type": "object", "properties": {}}, default)
    return {"echo": echo, "secret": secret}


def make_spec(max_steps=3):
    return AgentSpec("tester", "Tester", "test agent", "SYSTEM", ("echo",), max_steps)


CTX = ToolContext(db=None, embedder=None)


def test_agent_uses_tool_then_answers():
    chat = ScriptedChat([call("echo", q="pump"), final("Answer [a.pdf, p.2].")])
    result = run_agent(make_spec(), "task", chat, CTX, make_tools())
    assert result.status == "completed" and result.answer == "Answer [a.pdf, p.2]."
    assert result.steps[0]["tool"] == "echo" and result.steps[0]["status"] == "ok"
    assert result.sources == [{"filename": "a.pdf", "page": 2}]
    second_call_messages = chat.calls[1][0]
    assert second_call_messages[-1]["role"] == "tool" and "result for pump" in second_call_messages[-1]["content"]
    assert [t["function"]["name"] for t in chat.calls[0][1]] == ["echo"]  # only allowed tools are offered


def test_agent_cannot_use_a_tool_it_was_not_given():
    chat = ScriptedChat([call("secret", q="x"), final("ok")])
    result = run_agent(make_spec(), "task", chat, CTX, make_tools())
    assert result.steps[0]["status"] == "denied"
    assert "Permission denied" in chat.calls[1][0][-1]["content"]
    assert result.sources == []  # a denied call never returns data


def test_tool_errors_are_reported_to_the_model_not_raised():
    def bad(ctx, args):
        raise ToolError("bad input")

    result = run_agent(make_spec(), "task", ScriptedChat([call("echo"), final("done")]), CTX, make_tools(bad))
    assert result.status == "completed" and result.steps[0]["status"] == "error"
    assert "bad input" in result.steps[0]["output_preview"]


def test_crashing_tool_does_not_crash_the_run():
    def crash(ctx, args):
        raise RuntimeError("boom")

    result = run_agent(make_spec(), "task", ScriptedChat([call("echo"), final("done")]), CTX, make_tools(crash))
    assert result.steps[0]["status"] == "error" and "unexpectedly" in result.steps[0]["output_preview"]


def test_step_limit_forces_a_final_answer_without_tools():
    chat = ScriptedChat([call("echo"), call("echo"), final("Best effort answer")])
    result = run_agent(make_spec(max_steps=2), "task", chat, CTX, make_tools())
    assert result.status == "step_limit" and result.answer == "Best effort answer"
    assert len(result.steps) == 2
    assert chat.calls[-1][1] == []  # no tools offered for the forced final answer


def test_llm_failure_keeps_partial_steps():
    chat = ScriptedChat([call("echo"), LLMUnavailable("Ollama is down")])
    result = run_agent(make_spec(), "task", chat, CTX, make_tools())
    assert result.status == "failed" and result.answer is None
    assert "Ollama is down" in result.error and len(result.steps) == 1


def test_tool_output_is_truncated_before_going_back_to_the_model():
    def huge(ctx, args):
        return ToolResult("x" * 10000)

    chat = ScriptedChat([call("echo"), final("ok")])
    run_agent(make_spec(), "task", chat, CTX, make_tools(huge))
    assert len(chat.calls[1][0][-1]["content"]) <= MAX_TOOL_OUTPUT_CHARS


def test_empty_final_answer_gets_a_message():
    result = run_agent(make_spec(), "task", ScriptedChat([final("   ")]), CTX, make_tools())
    assert result.status == "completed" and "no answer" in result.answer


# ---------- registry ----------
def test_every_agent_only_lists_tools_that_exist():
    for agent in registry.AGENTS.values():
        assert agent.max_steps > 0
        assert set(agent.allowed_tools) <= set(TOOLS)


def test_least_privilege_librarian_cannot_search_or_calculate():
    librarian = registry.get_agent("librarian")
    assert librarian.allowed_tools == ("list_documents",)
    assert registry.get_agent("nope") is None


def test_tool_specs_have_the_shape_ollama_expects():
    for tool in TOOLS.values():
        spec = tool.spec()
        assert spec["type"] == "function" and spec["function"]["name"] == tool.name
        assert spec["function"]["parameters"]["type"] == "object"


def test_token_usage_is_added_up_across_model_calls():
    turns = [
        {**call("echo"), "usage": {"prompt_tokens": 40, "completion_tokens": 5}},
        {**final("done"), "usage": {"prompt_tokens": 60, "completion_tokens": 15}},
    ]
    result = run_agent(make_spec(), "task", ScriptedChat(turns), CTX, make_tools())
    assert (result.prompt_tokens, result.completion_tokens) == (100, 20)


def test_citation_notice_only_when_sources_were_used_but_not_cited():
    from app.agents.runner import citation_notice
    src = [{"filename": "manual.pdf", "page": 3}]
    assert citation_notice("Close valve A [manual.pdf, p.3].", src) is None
    assert citation_notice("See manual.pdf for details.", src) is None
    assert "does not cite" in citation_notice("Close valve A first.", src)
    assert citation_notice("I could not find this in the uploaded documents.", src) is None
    assert citation_notice("Close valve A first.", []) is None
    assert citation_notice(None, src) is None


def test_agent_that_wrongly_says_not_found_is_re_answered_from_its_own_passages():
    from app.services.rag import NOT_FOUND_TEXT
    chat = ScriptedChat([call("echo", q="x"), final(NOT_FOUND_TEXT), final("The trainee maintained SQL databases [a.pdf, p.2].")])
    result = run_agent(make_spec(), "What did the trainee do?", chat, CTX, make_tools())
    assert result.answer.startswith("The trainee maintained")
    assert result.steps[-1]["tool"] == "answer_check"
    assert chat.calls[-1][1] == [] and "PASSAGES:" in chat.calls[-1][0][1]["content"]


def test_a_genuine_not_found_is_kept_when_the_second_look_agrees():
    from app.services.rag import NOT_FOUND_TEXT
    chat = ScriptedChat([call("echo", q="x"), final(NOT_FOUND_TEXT), final(NOT_FOUND_TEXT)])
    result = run_agent(make_spec(), "unrelated question", chat, CTX, make_tools())
    assert result.answer == NOT_FOUND_TEXT and all(s["tool"] != "answer_check" for s in result.steps)


def test_no_second_look_when_nothing_was_retrieved():
    from app.services.rag import NOT_FOUND_TEXT
    chat = ScriptedChat([final(NOT_FOUND_TEXT)])
    assert run_agent(make_spec(), "q", chat, CTX, make_tools()).answer == NOT_FOUND_TEXT
    assert len(chat.calls) == 1
