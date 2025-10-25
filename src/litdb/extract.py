"""Extraction library for litdb.

Extract tables and structured data from a pdf.
"""

import json
from ast import literal_eval
from .utils import get_config
from docling.document_converter import DocumentConverter

from gmft.auto import AutoTableFormatter, AutoTableDetector
from gmft.pdf_bindings import PyPDFium2Document

import litellm

from typing import Any, Optional, Dict, Tuple
from pydantic import BaseModel, create_model


def extract_tables(pdf, extract=None):
    """Extract the tables from PDF.

    EXTRACT: list of integers for tables to return, starting at table 1
    """
    detector = AutoTableDetector()
    formatter = AutoTableFormatter()

    doc = PyPDFium2Document(pdf)
    tables = []
    for page in doc:
        tables += detector.extract(page)

    if extract:
        tables = [tables[i - 1] for i in extract]

    results = []
    for table in tables:
        ft = formatter.extract(table)
        df = ft.df()
        results += [df]

    doc.close()
    return results


def parse_schema_dsl(dsl: str) -> type[BaseModel]:
    """
    Parse a mini-DSL (e.g. "name:str, age:int, email?:str, city=Atlanta")
    into a dynamically created Pydantic model class.
    """
    # Each field definition is separated by commas
    field_defs = [f.strip() for f in dsl.split(",") if f.strip()]

    # We'll store field definitions in a dict: field_name -> (type, default)
    fields: Dict[str, Tuple[Any, Any]] = {}

    for field_def in field_defs:
        # e.g. "email?:str=foo"
        #  1) optional "fieldName" + "?"
        #  2) optional ":pythonType"
        #  3) optional "=defaultValue"

        # We'll parse it in steps using a small regex to capture:
        #   fieldName
        #   an optional question mark
        #   optional " : type "
        #   optional " = defaultValue"
        #
        # For simplicity, we'll do it manually instead of a single big pattern.

        # 1) Does field_def contain an '=' for a default?
        default_value = None
        if "=" in field_def:
            field_def, default_str = field_def.split("=", maxsplit=1)
            default_str = default_str.strip()
            # Use literal_eval for safe parsing of Python literals (str, int, float, list, dict, etc.)
            try:
                default_value = literal_eval(default_str)
            except (ValueError, SyntaxError):
                # If we can't parse as a literal, store it as a raw string
                default_value = default_str

        # 2) Does field_def contain ':type'?
        field_type = str  # default type if none specified
        if ":" in field_def:
            field_name_part, type_part = field_def.split(":", maxsplit=1)
            field_def = field_name_part.strip()  # what's left after removing :type
            type_part = type_part.strip()
            # We won't parse complicated types, just built-ins or known strings
            # E.g. int, float, str, list, dict
            # If needed, handle more thoroughly with a map:
            type_map = {
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "list": list,
                "dict": dict,
            }
            field_type = type_map.get(
                type_part, str
            )  # default to str if not recognized

        # 3) Check if the field is optional
        field_name = field_def
        is_optional = False
        if field_name.endswith("?"):
            is_optional = True
            field_name = field_name[:-1].strip()

        # 4) If optional, the type becomes Optional[field_type]
        if is_optional:
            field_type = Optional[field_type]

        # 5) If no default was specified and it's optional, default to None
        if default_value is None and is_optional:
            default_value = None

        # Put everything in the fields dict
        fields[field_name] = (field_type, default_value)

    # Dynamically create the model
    DynamicModel = create_model("DynamicCLIModel", **fields)
    return DynamicModel


def extract_schema(source, schema_string):
    """Extract a structured output from a SOURCE.

    SOURCE: string, url or path to file that Docling can convert to md.
    SCHEMA_STRING: string, shorthand schema, or literal json.

    The schema syntax: fieldName[:pythonType][?][=defaultValue]
    """

    if schema_string.startswith("{"):
        fields = json.loads(schema_string)
        Schema = create_model("Extractor", **fields)

    else:
        Schema = parse_schema_dsl(schema_string)

    # Now we need to convert the pdf to markdown
    converter = DocumentConverter()
    result = converter.convert(source)
    md = result.document.export_to_markdown()

    # Then pass the markdown and schema to the llm
    prompt = """Extract structured information from the following document
    using the provided schema. Return only a valid JSON object."""

    msgs = [{"role": "user", "content": prompt + "\n\n" + md}]

    config = get_config()

    gpt = config.get("llm")
    gpt_model = gpt["model"]

    response = litellm.completion(
        messages=msgs, model=gpt_model, response_format=Schema
    )

    return response["choices"][0]["message"]["content"]
