"""Unit tests for litdb.extract module.

Focus on testing the schema DSL parser which was recently fixed for security.
"""

import pytest
from pydantic import BaseModel

from litdb.extract import parse_schema_dsl


class TestParseSchemaDSL:
    """Test the schema DSL parser."""

    @pytest.mark.unit
    def test_simple_schema(self):
        """Test parsing a simple schema with required fields."""
        schema = parse_schema_dsl("name:str, age:int")

        # Should create a Pydantic model
        assert issubclass(schema, BaseModel)

        # Test creating an instance
        instance = schema(name="John", age=30)
        assert instance.name == "John"
        assert instance.age == 30

    @pytest.mark.unit
    def test_optional_fields(self):
        """Test parsing schemas with optional fields."""
        schema = parse_schema_dsl("name:str, email?:str")

        # Required field must be provided
        instance1 = schema(name="Jane")
        assert instance1.name == "Jane"
        assert instance1.email is None

        # Optional field can be provided
        instance2 = schema(name="John", email="john@example.com")
        assert instance2.email == "john@example.com"

    @pytest.mark.unit
    def test_default_values(self):
        """Test parsing schemas with default values."""
        schema = parse_schema_dsl("name:str, city:str=Unknown")

        # Use default
        instance1 = schema(name="Alice")
        assert instance1.city == "Unknown"

        # Override default
        instance2 = schema(name="Bob", city="NYC")
        assert instance2.city == "NYC"

    @pytest.mark.unit
    def test_optional_with_default(self):
        """Test optional field with explicit default value."""
        schema = parse_schema_dsl("name:str, status?:str=pending")

        instance = schema(name="Test")
        assert instance.status == "pending"

    @pytest.mark.unit
    def test_all_types(self):
        """Test all supported types in schema DSL."""
        schema = parse_schema_dsl(
            "name:str, age:int, score:float, active:bool, tags:list, meta:dict"
        )

        instance = schema(
            name="Test",
            age=25,
            score=95.5,
            active=True,
            tags=["a", "b"],
            meta={"key": "value"},
        )

        assert isinstance(instance.name, str)
        assert isinstance(instance.age, int)
        assert isinstance(instance.score, float)
        assert isinstance(instance.active, bool)
        assert isinstance(instance.tags, list)
        assert isinstance(instance.meta, dict)

    @pytest.mark.unit
    def test_numeric_default(self):
        """Test default values for numeric types."""
        schema = parse_schema_dsl("name:str, count:int=0, score:float=0.0")

        instance = schema(name="Test")
        assert instance.count == 0
        assert instance.score == 0.0

    @pytest.mark.unit
    def test_list_default(self):
        """Test default value for list type."""
        schema = parse_schema_dsl("name:str, tags:list=[]")

        instance = schema(name="Test")
        assert instance.tags == []

    @pytest.mark.unit
    def test_security_literal_eval_only(self):
        """Test that only safe literals are evaluated, not arbitrary code.

        This is a regression test for the eval() security vulnerability.
        """
        # These should work (safe literals)
        safe_schemas = [
            "x:str=hello",  # String
            "x:int=42",  # Integer
            "x:float=3.14",  # Float
            "x:list=[1,2,3]",  # List
            "x:dict={'a':1}",  # Dict (with quoted keys)
        ]

        for schema_str in safe_schemas:
            schema = parse_schema_dsl(schema_str)
            instance = schema()  # Should use default
            assert instance is not None

    @pytest.mark.unit
    def test_dangerous_input_rejected(self):
        """Test that dangerous input is safely handled.

        Dangerous code should be treated as a string, not executed.
        """
        # This would execute code with eval(), but should fail with literal_eval
        schema = parse_schema_dsl("x:str=__import__('os').system('echo hacked')")

        # Should treat the whole thing as a string, not execute it
        instance = schema()
        # The dangerous string becomes the default value (as a string)
        assert isinstance(instance.x, str)
        assert "import" in instance.x  # Stored as string, not executed

    @pytest.mark.unit
    def test_whitespace_handling(self):
        """Test that whitespace in schema is handled correctly."""
        schema = parse_schema_dsl("  name : str  ,  age : int  ")

        instance = schema(name="Test", age=25)
        assert instance.name == "Test"
        assert instance.age == 25

    @pytest.mark.unit
    def test_unknown_type_defaults_to_str(self):
        """Test that unknown types default to str."""
        schema = parse_schema_dsl("name:str, custom:unknown_type")

        instance = schema(name="Test", custom="value")
        assert isinstance(instance.custom, str)

    @pytest.mark.unit
    def test_complex_schema(self, sample_schema_inputs):
        """Test a complex schema with multiple features."""
        schema = parse_schema_dsl(sample_schema_inputs["complex"])

        # Create with all fields
        instance = schema(
            title="Paper Title", authors=["A", "B"], year=2024, doi="10.1234", cited=10
        )

        assert instance.title == "Paper Title"
        assert instance.authors == ["A", "B"]
        assert instance.year == 2024
        assert instance.doi == "10.1234"
        assert instance.cited == 10

        # Create with minimal fields (optional and defaults)
        instance2 = schema(title="Another Paper", authors=[], year=2023)
        assert instance2.doi is None  # Optional
        assert instance2.cited == 0  # Default

    @pytest.mark.unit
    def test_empty_schema(self):
        """Test parsing an empty schema string."""
        schema = parse_schema_dsl("")

        # Should create a model with no fields
        instance = schema()
        assert instance is not None

    @pytest.mark.unit
    def test_single_field(self):
        """Test schema with a single field."""
        schema = parse_schema_dsl("name:str")

        instance = schema(name="Single")
        assert instance.name == "Single"

    @pytest.mark.unit
    def test_case_sensitivity(self):
        """Test that field names are case-sensitive."""
        schema = parse_schema_dsl("Name:str, name:str")

        # Should have two different fields
        instance = schema(Name="Upper", name="lower")
        assert instance.Name == "Upper"
        assert instance.name == "lower"


class TestExtractTablesPlaceholder:
    """Placeholder tests for extract_tables function.

    TODO: These tests require PDF fixtures and are marked as integration tests.
    """

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires PDF fixture files")
    def test_extract_tables_basic(self):
        """Test basic table extraction from PDF."""
        # TODO: Implement when PDF fixtures are available
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires PDF fixture files")
    def test_extract_specific_tables(self):
        """Test extracting specific tables by index."""
        # TODO: Implement when PDF fixtures are available
        pass
