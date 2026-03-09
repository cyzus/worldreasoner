"""Pydantic schema helper for smolagents tool output_schema.

This module provides utilities to convert Pydantic models to JSON schemas
that can be used as `output_schema` in smolagents Tool classes.

Usage:
    from pydantic import BaseModel
    from src.utils.schema_helper import pydantic_to_output_schema

    class MyToolOutput(BaseModel):
        status: str
        data: List[str]

    class MyTool(Tool):
        output_type = "object"
        output_schema = pydantic_to_output_schema(MyToolOutput)
"""

from typing import Type, Dict, Any
from pydantic import BaseModel


def pydantic_to_output_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model to a JSON schema for smolagents output_schema.

    Args:
        model: A Pydantic BaseModel class

    Returns:
        JSON schema dict compatible with smolagents output_schema

    Example:
        >>> class ArticleOutput(BaseModel):
        ...     id: str
        ...     title: str
        ...     status: str
        ...
        >>> schema = pydantic_to_output_schema(ArticleOutput)
        >>> schema['properties']['id']
        {'type': 'string'}
    """
    # Use Pydantic's built-in JSON schema generation
    schema = model.model_json_schema()

    # Clean up schema for smolagents compatibility
    # Remove Pydantic-specific keys that aren't needed
    keys_to_remove = ["title", "$defs", "definitions"]
    for key in keys_to_remove:
        schema.pop(key, None)

    # Recursively clean nested schemas
    _clean_schema(schema)

    return schema


def _clean_schema(schema: Dict[str, Any]) -> None:
    """Recursively clean a JSON schema for smolagents compatibility.

    Args:
        schema: JSON schema dict to clean in-place
    """
    if not isinstance(schema, dict):
        return

    # Remove title from nested properties
    schema.pop("title", None)

    # Clean properties
    if "properties" in schema:
        for prop_schema in schema["properties"].values():
            _clean_schema(prop_schema)

    # Clean array items
    if "items" in schema:
        _clean_schema(schema["items"])

    # Clean anyOf/oneOf/allOf
    for key in ["anyOf", "oneOf", "allOf"]:
        if key in schema:
            for sub_schema in schema[key]:
                _clean_schema(sub_schema)


def get_output_type_from_model(model: Type[BaseModel]) -> str:
    """Get the smolagents output_type string from a Pydantic model.

    Always returns "object" for Pydantic models since they represent
    structured data.

    Args:
        model: A Pydantic BaseModel class

    Returns:
        "object" for Pydantic models
    """
    return "object"


# Convenience class for defining tool outputs
class ToolOutputSchema:
    """Convenience class to define tool output schema from Pydantic model.

    Usage:
        class MyToolOutput(BaseModel):
            status: str
            data: List[str]

        class MyTool(Tool):
            _output_model = MyToolOutput
            output_type = "object"
            output_schema = ToolOutputSchema.from_model(MyToolOutput)
    """

    @staticmethod
    def from_model(model: Type[BaseModel]) -> Dict[str, Any]:
        """Create output_schema from a Pydantic model."""
        return pydantic_to_output_schema(model)


def model_to_json(model_instance: BaseModel, indent: int = 2) -> str:
    """Serialize a Pydantic model instance to JSON string.

    Use this in tool forward() methods to return validated Pydantic output.

    Args:
        model_instance: Instance of a Pydantic BaseModel
        indent: JSON indentation level (default: 2)

    Returns:
        JSON string representation of the model

    Example:
        >>> output = ArticleOutput(id="art_123", title="Test", url="...", status="created")
        >>> return model_to_json(output)
    """
    return model_instance.model_dump_json(indent=indent)
