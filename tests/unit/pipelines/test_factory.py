"""Unit tests for PipelineFactory."""

import pytest
from unittest.mock import Mock, patch

from src.pipelines.factory import PipelineFactory
from src.pipelines.types import PipelineType
from src.config import Config
from src.config.app import LLMConfig


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock(spec=Config)
    config.llm = Mock(spec=LLMConfig)
    config.llm.model = "test-model"
    return config


@pytest.fixture
def test_db_path(tmp_path):
    """Create temporary database path."""
    return str(tmp_path / "test.db")


class TestCreateEvidencePipeline:
    """Test evidence pipeline creation."""

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_create_basic_evidence_pipeline(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Create basic evidence pipeline with default config."""
        PipelineFactory.create_evidence_pipeline(
            mock_config, test_db_path, adaptive=False
        )

        # Verify pipeline was created
        assert mock_pipeline_class.called
        call_kwargs = mock_pipeline_class.call_args[1]

        # Should not have agent parameters
        assert "agent_max_steps" not in call_kwargs
        assert "min_graph_depth" not in call_kwargs
        assert call_kwargs["enable_persistence"] is True

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_create_adaptive_evidence_pipeline(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Create adaptive evidence pipeline with agent parameters."""
        PipelineFactory.create_evidence_pipeline(
            mock_config,
            test_db_path,
            adaptive=True,
            agent_max_steps=50,
            min_graph_depth=5,
        )

        # Verify pipeline was created with agent parameters
        assert mock_pipeline_class.called
        call_kwargs = mock_pipeline_class.call_args[1]

        assert call_kwargs["agent_max_steps"] == 50
        assert call_kwargs["min_graph_depth"] == 5
        assert call_kwargs["enable_persistence"] is True

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_create_with_custom_config(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Create pipeline with custom configuration overrides."""
        PipelineFactory.create_evidence_pipeline(
            mock_config,
            test_db_path,
            adaptive=False,
            evidence_window_days=180,
            min_evidence_articles=10,
        )

        # Verify evidence config was customized
        assert mock_pipeline_class.called
        call_kwargs = mock_pipeline_class.call_args[1]

        evidence_config = call_kwargs["evidence_config"]
        assert evidence_config.evidence_window_days == 180
        assert evidence_config.min_evidence_articles == 10


class TestCreateByType:
    """Test generic create method with pipeline types."""

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_create_evidence_type(self, mock_pipeline_class, mock_config, test_db_path):
        """Create pipeline by EVIDENCE type."""
        PipelineFactory.create(PipelineType.EVIDENCE, mock_config, test_db_path)

        assert mock_pipeline_class.called

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_create_adaptive_evidence_type(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Create pipeline by ADAPTIVE_EVIDENCE type."""
        PipelineFactory.create(
            PipelineType.ADAPTIVE_EVIDENCE,
            mock_config,
            test_db_path,
            agent_max_steps=40,
        )

        assert mock_pipeline_class.called
        call_kwargs = mock_pipeline_class.call_args[1]
        assert call_kwargs["agent_max_steps"] == 40

    def test_create_unsupported_type(self, mock_config, test_db_path):
        """Creating unsupported pipeline type raises NotImplementedError."""
        with pytest.raises(NotImplementedError) as exc_info:
            PipelineFactory.create(PipelineType.FORECAST, mock_config, test_db_path)

        assert "FORECAST" in str(exc_info.value)
        assert "not yet in factory" in str(exc_info.value)


class TestConfigurationConsistency:
    """Test that factory creates consistent configurations."""

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_database_config_passed(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Database path is correctly passed to pipeline."""
        PipelineFactory.create_evidence_pipeline(
            mock_config, test_db_path, adaptive=False
        )

        call_kwargs = mock_pipeline_class.call_args[1]
        database_config = call_kwargs["database_config"]

        assert database_config.db_path == test_db_path

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_persistence_enabled_by_default(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Persistence is enabled by default."""
        PipelineFactory.create_evidence_pipeline(
            mock_config, test_db_path, adaptive=False
        )

        call_kwargs = mock_pipeline_class.call_args[1]
        assert call_kwargs["enable_persistence"] is True

    @patch("src.pipelines.evidence.EvidencePipeline")
    def test_expert_analysis_enabled(
        self, mock_pipeline_class, mock_config, test_db_path
    ):
        """Expert analysis is enabled in evidence config."""
        PipelineFactory.create_evidence_pipeline(
            mock_config, test_db_path, adaptive=False
        )

        call_kwargs = mock_pipeline_class.call_args[1]
        evidence_config = call_kwargs["evidence_config"]
        assert evidence_config.include_expert_analysis is True
