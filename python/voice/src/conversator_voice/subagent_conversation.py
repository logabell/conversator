"""State machine for multi-question conversations with subagents.

This module tracks the back-and-forth question/answer flow between Gemini Live
and OpenCode subagents (planner, brainstormer). It enables:
- Parsing questions from subagent responses
- Iterating through questions one at a time
- Collecting answers and formatting as XML for the subagent
- Tracking sent context to avoid duplication
"""

import re
from dataclasses import dataclass, field


@dataclass
class SubagentQuestion:
    """A single question from a subagent response."""

    index: int  # 1-based question number
    text: str  # Canonical question text (for sending back)
    spoken_text: str | None = None  # Voice-friendly rewrite (optional)
    answered: bool = False
    answer: str | None = None

    def __str__(self) -> str:
        status = f"[answered: {self.answer}]" if self.answered else "[pending]"
        return f"Q{self.index}: {self.text} {status}"


@dataclass
class SubagentConversationState:
    """Tracks multi-question conversation with a subagent.

    This state machine manages the flow of:
    1. Receiving questions from subagent
    2. Presenting them one at a time to user via Gemini
    3. Collecting user answers
    4. Formatting answers as XML when ready to send
    """

    subagent_name: str  # "planner" or "brainstormer"
    session_id: str  # OpenCode session ID for continue_session
    questions: list[SubagentQuestion] = field(default_factory=list)
    current_question_index: int = 0  # 0-based index into questions list
    all_answers_collected: bool = False
    user_confirmed_send: bool = False
    sent_context_hashes: set[str] = field(default_factory=set)  # Track what was sent

    # Relay UX: staged answer confirmation per question
    pending_answer: str | None = None
    awaiting_answer_confirmation: bool = False

    # Relay UX: confirmation before sending all answers
    awaiting_send_confirmation: bool = False
    pending_send_context: str | None = None

    # Final review/edit flow before sending
    awaiting_edit_question_number: bool = False
    awaiting_edit_answer: bool = False
    pending_edit_question_number: int | None = None

    # Auto-confirm: set True after we inject "send it" once
    auto_confirm_sent: bool = False

    @property
    def total_questions(self) -> int:
        """Get the total number of questions."""
        return len(self.questions)

    @property
    def current_question_number(self) -> int:
        """Get the current question number (1-based for user display)."""
        return self.current_question_index + 1

    @property
    def questions_remaining(self) -> int:
        """Get the number of unanswered questions remaining."""
        return sum(1 for q in self.questions if not q.answered)

    def get_current_question(self) -> SubagentQuestion | None:
        """Get the current unanswered question, or None if all answered."""
        if self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None

    def record_answer(self, answer: str) -> bool:
        """Record answer to current question and advance.

        Args:
            answer: The user's answer to the current question

        Returns:
            True if there are more questions, False if all answered
        """
        current = self.get_current_question()
        if current:
            current.answered = True
            current.answer = answer
            self.current_question_index += 1

        # Check if we've answered all questions
        if self.current_question_index >= len(self.questions):
            self.all_answers_collected = True
            return False

        return True  # More questions remain

    def replace_answer(self, question_number: int, answer: str) -> bool:
        """Replace the answer for a specific question (1-based)."""
        if question_number < 1 or question_number > len(self.questions):
            return False
        question = self.questions[question_number - 1]
        question.answered = True
        question.answer = answer
        return True

    def stage_answer(self, answer: str) -> None:
        """Stage an answer but do not commit it yet.

        This supports the relay UX where Gemini asks: "Anything else to add?" and
        only commits on user acknowledgement (or auto-confirm silence).
        """
        self.pending_answer = answer
        self.awaiting_answer_confirmation = True
        self.auto_confirm_sent = False

    def append_pending(self, extra: str) -> None:
        """Append additional text to the staged answer."""
        extra_clean = extra.strip()
        if not extra_clean:
            return
        if self.pending_answer:
            self.pending_answer = f"{self.pending_answer}\n{extra_clean}".strip()
        else:
            self.pending_answer = extra_clean
        self.awaiting_answer_confirmation = True
        self.auto_confirm_sent = False

    def commit_pending_answer(self) -> bool:
        """Commit the staged answer to the current question and advance."""
        answer = (self.pending_answer or "").strip()
        self.pending_answer = None
        self.awaiting_answer_confirmation = False
        self.auto_confirm_sent = False
        return self.record_answer(answer)

    def start_send_confirmation(self) -> None:
        """Enter the final send-confirmation stage."""
        self.awaiting_send_confirmation = True
        self.pending_send_context = None
        self.awaiting_edit_question_number = False
        self.awaiting_edit_answer = False
        self.pending_edit_question_number = None
        self.auto_confirm_sent = False

    def append_send_context(self, extra: str) -> None:
        """Stage additional context before sending answers to the subagent."""
        extra_clean = extra.strip()
        if not extra_clean:
            return
        if self.pending_send_context:
            self.pending_send_context = f"{self.pending_send_context}\n{extra_clean}".strip()
        else:
            self.pending_send_context = extra_clean
        self.awaiting_send_confirmation = True
        self.auto_confirm_sent = False

    def consume_send_context(self) -> str:
        """Consume staged send-context and clear it."""
        value = (self.pending_send_context or "").strip()
        self.pending_send_context = None
        return value

    def clear_confirmations(self) -> None:
        """Clear any pending confirmation states."""
        self.pending_answer = None
        self.awaiting_answer_confirmation = False
        self.awaiting_send_confirmation = False
        self.pending_send_context = None
        self.auto_confirm_sent = False

    def get_intro_message(self) -> str:
        """Generate intro message announcing question count."""
        count = self.total_questions
        if count == 1:
            return "They have one question."
        return f"They have {count} questions."

    def get_current_question_message(self) -> str:
        """Get the current question text for voice delivery.

        Note: numbering/ordinals are handled by the caller so we can produce
        natural prompts like "First question:" and "Second question:".
        """
        current = self.get_current_question()
        if not current:
            return "All questions have been answered."

        return current.spoken_text or current.text

    def get_progress_message(self) -> str:
        """Get a progress message like 'Question 2 of 5'."""
        return f"Question {self.current_question_number} of {self.total_questions}"

    def format_answers_xml(self, additional_context: str = "") -> str:
        """Format all collected answers as XML for sending to subagent.

        This is "XML-like" but kept as valid single-root XML to make it easier for
        LLMs to parse deterministically.

        Args:
            additional_context: Optional additional context from user

        Returns:
            XML-formatted string with all Q&A pairs
        """
        lines = [f'<user_responses session_id="{self.session_id}" subagent="{self.subagent_name}">']

        for q in self.questions:
            if q.answered:
                lines.append(f'  <response question_number="{q.index}">')
                lines.append(f"    <original_question>{_escape_xml(q.text)}</original_question>")
                lines.append(f"    <user_answer>{_escape_xml(q.answer or '')}</user_answer>")
                lines.append("  </response>")

        if additional_context:
            lines.append(
                f"  <additional_context>{_escape_xml(additional_context)}</additional_context>"
            )
        else:
            lines.append("  <additional_context>None provided</additional_context>")

        lines.append("</user_responses>")
        return "\n".join(lines)

    def reset_for_new_questions(self, questions: list["SubagentQuestion"]) -> None:
        """Reset state for a new round of questions from subagent."""
        self.questions = questions
        self.current_question_index = 0
        self.all_answers_collected = False
        self.user_confirmed_send = False
        self.clear_confirmations()


class QuestionParser:
    """Parse questions from subagent responses.

    Handles various question formats:
    - Numbered: "1. Question" / "2) Question" (with or without '?')
    - Bulleted: "- Question" / "* Question" (with or without '?')
    - Labeled: "Question 1: text" (with or without '?')
    - Single lines ending with '?'

    Heuristic filtering is used so we don't treat ordinary bullet lists as questions.
    """

    # Patterns for different question formats
    NUMBERED_PATTERN = re.compile(r"^\s*(\d+)\s*[.)]\s*(.+?)\s*$", re.MULTILINE)
    BULLETED_PATTERN = re.compile(r"^\s*[-*]\s*(.+?)\s*$", re.MULTILINE)
    LABELED_PATTERN = re.compile(r"^\s*[Qq]uestion\s*(\d+)\s*[:.]\s*(.+?)\s*$", re.MULTILINE)
    # Single question - any line ending with ?
    SINGLE_QUESTION_PATTERN = re.compile(r"^(.+?\?)\s*$", re.MULTILINE)

    QUESTION_PREFIXES = (
        "what ",
        "which ",
        "how ",
        "why ",
        "when ",
        "where ",
        "who ",
        "can ",
        "could ",
        "would ",
        "should ",
        "do ",
        "does ",
        "did ",
        "is ",
        "are ",
        "will ",
        "tell me",
        "describe",
        "share",
        "confirm",
        "please",
    )

    @classmethod
    def _looks_like_question(cls, text: str) -> bool:
        candidate = text.strip()
        if len(candidate) < 8:
            return False
        if "?" in candidate:
            return True
        lowered = candidate.lower()
        return lowered.startswith(cls.QUESTION_PREFIXES)

    @classmethod
    def parse_questions(cls, response: str) -> list[SubagentQuestion]:
        """Parse questions from a subagent response.

        Tries multiple patterns in order of specificity:
        1. Labeled questions (Question 1:, Question 2:)
        2. Numbered questions (1., 2.)
        3. Bulleted questions (-, *)
        4. Single question lines ending with '?'

        For list-like formats (labeled/numbered/bulleted), a heuristic is applied so
        non-question bullet lists don't get treated as questions.

        Args:
            response: The subagent's response text

        Returns:
            List of SubagentQuestion objects, empty if no questions found
        """
        questions: list[SubagentQuestion] = []

        # Try labeled questions first (most explicit)
        labeled_matches = cls.LABELED_PATTERN.findall(response)
        if labeled_matches:
            for idx, (_num, text) in enumerate(labeled_matches, start=1):
                cleaned = text.strip()
                if cls._looks_like_question(cleaned):
                    questions.append(SubagentQuestion(index=idx, text=cleaned))
            return questions

        # Try numbered questions
        numbered_matches = cls.NUMBERED_PATTERN.findall(response)
        if numbered_matches:
            for idx, (_num, text) in enumerate(numbered_matches, start=1):
                cleaned = text.strip()
                if cls._looks_like_question(cleaned):
                    questions.append(SubagentQuestion(index=idx, text=cleaned))
            return questions

        # Try bulleted questions
        bulleted_matches = cls.BULLETED_PATTERN.findall(response)
        if bulleted_matches:
            for idx, text in enumerate(bulleted_matches, start=1):
                cleaned = text.strip()
                if cls._looks_like_question(cleaned):
                    questions.append(SubagentQuestion(index=idx, text=cleaned))
            return questions

        # Try to find any question sentences (lines ending with ?)
        single_matches = cls.SINGLE_QUESTION_PATTERN.findall(response)
        if single_matches:
            # Filter out very short matches (likely false positives like "?")
            valid_questions = [q.strip() for q in single_matches if len(q.strip()) > 10]
            for idx, text in enumerate(valid_questions, start=1):
                questions.append(SubagentQuestion(index=idx, text=text))

        return questions

    @classmethod
    def is_asking_questions(cls, response: str) -> bool:
        """Check if the response contains questions that need user input.

        Args:
            response: The subagent's response text

        Returns:
            True if the response contains questions
        """
        # Quick check for question marks
        if "?" not in response:
            return False

        # Check for question patterns
        questions = cls.parse_questions(response)
        return len(questions) > 0

    @classmethod
    def count_questions(cls, response: str) -> int:
        """Count the number of questions in a response.

        Args:
            response: The subagent's response text

        Returns:
            Number of questions found
        """
        return len(cls.parse_questions(response))


def _escape_xml(text: str) -> str:
    """Escape special XML characters in text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def create_conversation_state(
    subagent_name: str,
    session_id: str,
    response: str,
) -> SubagentConversationState | None:
    """Create a conversation state from a subagent response.

    Args:
        subagent_name: Name of the subagent (planner, brainstormer)
        session_id: OpenCode session ID
        response: The subagent's response containing questions

    Returns:
        SubagentConversationState if questions found, None otherwise
    """
    questions = QuestionParser.parse_questions(response)
    if not questions:
        return None

    return SubagentConversationState(
        subagent_name=subagent_name,
        session_id=session_id,
        questions=questions,
    )
