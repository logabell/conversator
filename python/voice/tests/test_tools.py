"""Tests for tool definitions - validates Gemini Live tool schemas."""

import pytest

from conversator_voice.tools import CONVERSATOR_TOOLS, get_tool_by_name


class TestToolDefinitions:
    """Tests for CONVERSATOR_TOOLS list."""

    def test_tools_is_list(self):
        """CONVERSATOR_TOOLS is a list."""
        assert isinstance(CONVERSATOR_TOOLS, list)

    def test_correct_number_of_tools(self):
        """Expected number of tools defined."""
        # Original 10 + 4 new (run_command, engage_brainstormer, get_builder_plan, approve_builder_plan)
        assert len(CONVERSATOR_TOOLS) == 14

    def test_all_tools_have_required_fields(self):
        """Each tool has name, description, and parameters."""
        for tool in CONVERSATOR_TOOLS:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool.get('name')}"
            assert "parameters" in tool, f"Tool missing 'parameters': {tool.get('name')}"

    def test_all_tool_names_are_unique(self):
        """No duplicate tool names."""
        names = [tool["name"] for tool in CONVERSATOR_TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names found"

    def test_expected_tools_present(self):
        """All expected tools are defined."""
        expected = [
            "engage_planner",
            "lookup_context",
            "check_status",
            "dispatch_to_builder",
            "add_to_memory",
            "cancel_task",
            "check_inbox",
            "acknowledge_inbox",
            "update_working_prompt",
            "freeze_prompt",
            # Quick dispatch for simple operations (replaces run_command)
            "quick_dispatch",
            "engage_brainstormer",
            "get_builder_plan",
            "approve_builder_plan",
        ]

        actual = [tool["name"] for tool in CONVERSATOR_TOOLS]

        for name in expected:
            assert name in actual, f"Expected tool '{name}' not found"


class TestToolSchemas:
    """Tests for tool parameter schemas."""

    def test_parameters_have_type_object(self):
        """All tool parameters are type: object."""
        for tool in CONVERSATOR_TOOLS:
            params = tool["parameters"]
            assert params.get("type") == "object", f"Tool {tool['name']} params not object type"

    def test_parameters_have_properties(self):
        """All tool parameters have properties field."""
        for tool in CONVERSATOR_TOOLS:
            params = tool["parameters"]
            assert "properties" in params, f"Tool {tool['name']} missing properties"

    def test_required_fields_are_valid(self):
        """Required fields exist in properties."""
        for tool in CONVERSATOR_TOOLS:
            params = tool["parameters"]
            required = params.get("required", [])
            properties = params.get("properties", {})

            for field in required:
                assert field in properties, (
                    f"Tool {tool['name']}: required field '{field}' not in properties"
                )

    def test_property_types_are_valid(self):
        """All property types are valid JSON Schema types."""
        valid_types = {"string", "number", "integer", "boolean", "array", "object", "null"}

        for tool in CONVERSATOR_TOOLS:
            properties = tool["parameters"].get("properties", {})
            for prop_name, prop_schema in properties.items():
                prop_type = prop_schema.get("type")
                if prop_type:
                    assert prop_type in valid_types, (
                        f"Tool {tool['name']}.{prop_name}: invalid type '{prop_type}'"
                    )

    def test_enum_properties_have_valid_values(self):
        """Enum properties have non-empty value lists."""
        for tool in CONVERSATOR_TOOLS:
            properties = tool["parameters"].get("properties", {})
            for prop_name, prop_schema in properties.items():
                if "enum" in prop_schema:
                    enum_values = prop_schema["enum"]
                    assert isinstance(enum_values, list), (
                        f"Tool {tool['name']}.{prop_name}: enum must be list"
                    )
                    assert len(enum_values) > 0, (
                        f"Tool {tool['name']}.{prop_name}: enum cannot be empty"
                    )

    def test_array_properties_have_items(self):
        """Array properties have items schema."""
        for tool in CONVERSATOR_TOOLS:
            properties = tool["parameters"].get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_schema.get("type") == "array":
                    assert "items" in prop_schema, (
                        f"Tool {tool['name']}.{prop_name}: array missing items schema"
                    )


class TestSpecificTools:
    """Tests for specific tool configurations."""

    def test_engage_planner_has_task_description_required(self):
        """engage_planner requires task_description."""
        tool = get_tool_by_name("engage_planner")
        assert tool is not None
        assert "task_description" in tool["parameters"].get("required", [])

    def test_engage_planner_urgency_enum(self):
        """engage_planner urgency has correct enum values."""
        tool = get_tool_by_name("engage_planner")
        urgency = tool["parameters"]["properties"]["urgency"]
        assert urgency["enum"] == ["low", "normal", "high"]

    def test_dispatch_to_builder_agent_enum(self):
        """dispatch_to_builder has correct agent options."""
        tool = get_tool_by_name("dispatch_to_builder")
        agent = tool["parameters"]["properties"]["agent"]
        assert "auto" in agent["enum"]
        assert "claude-code" in agent["enum"]
        assert "opencode-fast" in agent["enum"]
        assert "opencode-pro" in agent["enum"]

    def test_dispatch_to_builder_mode_enum(self):
        """dispatch_to_builder has plan/build modes."""
        tool = get_tool_by_name("dispatch_to_builder")
        mode = tool["parameters"]["properties"]["mode"]
        assert mode["enum"] == ["plan", "build"]

    def test_lookup_context_scope_enum(self):
        """lookup_context has correct scope options."""
        tool = get_tool_by_name("lookup_context")
        scope = tool["parameters"]["properties"]["scope"]
        assert scope["enum"] == ["memory", "codebase", "both"]

    def test_add_to_memory_keywords_is_array(self):
        """add_to_memory keywords is array of strings."""
        tool = get_tool_by_name("add_to_memory")
        keywords = tool["parameters"]["properties"]["keywords"]
        assert keywords["type"] == "array"
        assert keywords["items"]["type"] == "string"

    def test_acknowledge_inbox_has_array_ids(self):
        """acknowledge_inbox inbox_ids is array."""
        tool = get_tool_by_name("acknowledge_inbox")
        inbox_ids = tool["parameters"]["properties"]["inbox_ids"]
        assert inbox_ids["type"] == "array"

    def test_update_working_prompt_requires_title_and_intent(self):
        """update_working_prompt requires title and intent."""
        tool = get_tool_by_name("update_working_prompt")
        required = tool["parameters"].get("required", [])
        assert "title" in required
        assert "intent" in required

    def test_check_status_has_verbose_boolean(self):
        """check_status has verbose boolean parameter."""
        tool = get_tool_by_name("check_status")
        verbose = tool["parameters"]["properties"]["verbose"]
        assert verbose["type"] == "boolean"


class TestGetToolByName:
    """Tests for get_tool_by_name function."""

    def test_returns_tool_by_name(self):
        """get_tool_by_name returns correct tool."""
        tool = get_tool_by_name("engage_planner")
        assert tool is not None
        assert tool["name"] == "engage_planner"

    def test_returns_none_for_unknown(self):
        """get_tool_by_name returns None for unknown tools."""
        tool = get_tool_by_name("nonexistent_tool")
        assert tool is None

    def test_case_sensitive(self):
        """get_tool_by_name is case sensitive."""
        tool = get_tool_by_name("ENGAGE_PLANNER")
        assert tool is None

    def test_all_tools_retrievable(self):
        """All defined tools are retrievable by name."""
        for defined_tool in CONVERSATOR_TOOLS:
            name = defined_tool["name"]
            retrieved = get_tool_by_name(name)
            assert retrieved is not None, f"Could not retrieve tool '{name}'"
            assert retrieved["name"] == name


class TestToolDescriptions:
    """Tests for tool descriptions quality."""

    def test_descriptions_not_empty(self):
        """All tools have non-empty descriptions."""
        for tool in CONVERSATOR_TOOLS:
            desc = tool["description"]
            assert desc and len(desc.strip()) > 0, (
                f"Tool {tool['name']} has empty description"
            )

    def test_descriptions_are_actionable(self):
        """Tool descriptions explain when to use the tool."""
        # Key phrases that indicate actionable guidance
        trigger_phrases = ["use when", "use this", "call when", "engage", "get", "check", "send", "save", "cancel", "mark", "update", "freeze", "execute", "approve"]

        for tool in CONVERSATOR_TOOLS:
            desc = tool["description"].lower()
            has_trigger = any(phrase in desc for phrase in trigger_phrases)
            assert has_trigger, (
                f"Tool {tool['name']} description lacks actionable guidance"
            )

    def test_property_descriptions_present(self):
        """Tool properties have descriptions."""
        for tool in CONVERSATOR_TOOLS:
            properties = tool["parameters"].get("properties", {})
            for prop_name, prop_schema in properties.items():
                assert "description" in prop_schema, (
                    f"Tool {tool['name']}.{prop_name} missing description"
                )
