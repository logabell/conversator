from conversator_voice.subagent_conversation import (
    QuestionParser,
    SubagentConversationState,
    SubagentQuestion,
)


def test_question_parser_handles_numbered_without_question_marks() -> None:
    text = """Here are a few things I need:

1. Tell me the target users
2. What platform are you shipping on?
3. Confirm your main success metric

Thanks!"""

    questions = QuestionParser.parse_questions(text)
    assert [q.index for q in questions] == [1, 2, 3]
    assert questions[0].text.lower().startswith("tell me")
    assert "platform" in questions[1].text.lower()


def test_question_parser_does_not_treat_idea_bullets_as_questions() -> None:
    text = """Some ideas:

- Add dark mode
- Offline support
- Reduce bundle size

No questions for now."""

    assert QuestionParser.parse_questions(text) == []


def test_format_answers_xml_is_single_root() -> None:
    conv = SubagentConversationState(subagent_name="planner", session_id="sess-123")
    conv.questions = [
        SubagentQuestion(index=1, text="What is the goal?"),
        SubagentQuestion(index=2, text="Any constraints?"),
    ]

    conv.record_answer("Ship a calculator app")
    conv.record_answer("No external APIs")

    xml = conv.format_answers_xml(additional_context="Use TypeScript")

    assert xml.count("<user_responses") == 1
    assert xml.count("</user_responses>") == 1
    assert "<additional_context>" in xml
    assert "calculator app" in xml


def test_stage_answer_requires_ack_commit() -> None:
    conv = SubagentConversationState(subagent_name="brainstormer", session_id="sess-1")
    conv.questions = [SubagentQuestion(index=1, text="What is the target audience?")]

    conv.stage_answer("Kids")
    assert conv.awaiting_answer_confirmation is True
    assert conv.questions[0].answered is False

    # Add extra detail before committing
    conv.append_pending("Ages 7 to 10")
    assert "Ages 7" in (conv.pending_answer or "")

    conv.commit_pending_answer()
    assert conv.awaiting_answer_confirmation is False
    assert conv.questions[0].answered is True
    assert conv.questions[0].answer and "Kids" in conv.questions[0].answer
