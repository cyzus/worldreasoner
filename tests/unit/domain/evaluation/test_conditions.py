"""Tests for experiment condition definitions."""

import pytest
from src.domain.evaluation.conditions import (
    ConditionName,
    ExperimentCondition,
    EXPERIMENT_CONDITIONS,
    get_conditions,
)


class TestConditionRegistry:
    """Tests for EXPERIMENT_CONDITIONS registry."""

    def test_all_five_conditions_defined(self):
        assert len(EXPERIMENT_CONDITIONS) == len(ConditionName)

    def test_all_condition_names_present(self):
        for name in ConditionName:
            assert name in EXPERIMENT_CONDITIONS

    def test_conditions_have_correct_types(self):
        for name, condition in EXPERIMENT_CONDITIONS.items():
            assert isinstance(condition, ExperimentCondition)
            assert condition.name == name
            assert isinstance(condition.display_name, str)
            assert isinstance(condition.mode, str) and len(condition.mode) > 0
            assert isinstance(condition.enable_causal_tools, bool)
            assert isinstance(condition.is_oracle, bool)
            assert isinstance(condition.max_steps, int)
            assert condition.max_steps > 0

    def test_oracle_flag_only_on_oracle(self):
        for name, condition in EXPERIMENT_CONDITIONS.items():
            if name == ConditionName.ORACLE:
                assert condition.is_oracle is True
            else:
                assert condition.is_oracle is False

    def test_vanilla_llm_config(self):
        c = EXPERIMENT_CONDITIONS[ConditionName.VANILLA_LLM]
        assert c.mode == "knowledge_only"
        assert c.enable_causal_tools is False
        assert c.max_steps == 10

    def test_structured_scenario_config(self):
        c = EXPERIMENT_CONDITIONS[ConditionName.STRUCTURED_SCENARIO]
        assert c.mode == "knowledge_only"
        assert c.enable_causal_tools is True
        assert c.max_steps == 25

    def test_search_enabled_config(self):
        c = EXPERIMENT_CONDITIONS[ConditionName.SEARCH_ENABLED]
        assert c.mode == "container"
        assert c.enable_causal_tools is False
        assert c.max_steps == 15

    def test_worldreasoner_config(self):
        c = EXPERIMENT_CONDITIONS[ConditionName.WORLDREASONER]
        assert c.mode == "container"
        assert c.enable_causal_tools is True
        assert c.max_steps == 25

    def test_oracle_config(self):
        c = EXPERIMENT_CONDITIONS[ConditionName.ORACLE]
        assert c.mode == "container"
        assert c.enable_causal_tools is True
        assert c.is_oracle is True
        assert c.max_steps == 25


class TestGetConditions:
    """Tests for get_conditions helper."""

    def test_returns_all_when_no_filter(self):
        conditions = get_conditions()
        assert len(conditions) == len(ConditionName)

    def test_filter_single(self):
        conditions = get_conditions(["vanilla_llm"])
        assert len(conditions) == 1
        assert conditions[0].name == ConditionName.VANILLA_LLM

    def test_filter_multiple(self):
        conditions = get_conditions(["vanilla_llm", "oracle"])
        assert len(conditions) == 2
        names = {c.name for c in conditions}
        assert names == {ConditionName.VANILLA_LLM, ConditionName.ORACLE}

    def test_filter_preserves_order(self):
        conditions = get_conditions(["oracle", "vanilla_llm"])
        assert conditions[0].name == ConditionName.ORACLE
        assert conditions[1].name == ConditionName.VANILLA_LLM

    def test_invalid_filter_raises(self):
        with pytest.raises(ValueError, match="Unknown condition"):
            get_conditions(["nonexistent"])

    def test_empty_filter_returns_empty(self):
        conditions = get_conditions([])
        assert conditions == []

    def test_condition_name_enum_values(self):
        """Ensure enum values match expected strings."""
        assert ConditionName.VANILLA_LLM.value == "vanilla_llm"
        assert ConditionName.STRUCTURED_SCENARIO.value == "structured_scenario"
        assert ConditionName.SEARCH_ENABLED.value == "search_enabled"
        assert ConditionName.WORLDREASONER.value == "worldreasoner"
        assert ConditionName.ORACLE.value == "oracle"
