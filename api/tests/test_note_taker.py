from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.note_taker.agent import build_note_taker
from app.note_taker.prompts import note_taker_prompt

COURSE_ID = "00000000-0000-0000-0000-000000000001"
MOODLE_COURSE_ID = 42


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs) -> "ScriptedModel":
        return self


def test_prompt_sets_the_role() -> None:
    prompt = note_taker_prompt()
    assert "{{" not in prompt
    assert "turn a Moodle course into a prepared course" in prompt


def test_main_agent_has_built_ins_and_no_own_tools() -> None:
    agent = build_note_taker(COURSE_ID, MOODLE_COURSE_ID, model=ScriptedModel(messages=iter([])))
    tool_names = set(agent.get_graph().nodes["tools"].data.tools_by_name)
    assert {"write_todos", "read_file", "write_file", "ls", "task"} <= tool_names
    assert not tool_names & {"list_course_contents", "preview_module", "fetch_materials"}


def test_main_agent_plans_with_write_todos() -> None:
    todos = [
        {"content": "Gather course materials", "status": "in_progress"},
        {"content": "Write the notes", "status": "pending"},
    ]
    model = ScriptedModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_todos", "args": {"todos": todos}, "id": "1"}],
                ),
                AIMessage(content="Report: note generation is not wired yet."),
            ]
        )
    )
    agent = build_note_taker(COURSE_ID, MOODLE_COURSE_ID, model=model)
    result = agent.invoke(
        {"messages": [HumanMessage(content=f"Make notes for course {COURSE_ID} (Moodle 42)")]}
    )
    assert result["todos"] == todos
    assert result["messages"][-1].text == "Report: note generation is not wired yet."


def test_approval_adds_a_checkpointer() -> None:
    model = ScriptedModel(messages=iter([]))
    assert build_note_taker(COURSE_ID, MOODLE_COURSE_ID, model=model).checkpointer is None
    approved = build_note_taker(COURSE_ID, MOODLE_COURSE_ID, model=model, approval=True)
    assert approved.checkpointer is not None
