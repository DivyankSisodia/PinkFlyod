"""The project document contract: JSON Schema (schema/project.v1.schema.json) plus semantic checks.

The JSON Schema file is the single definition of the format. Python validates against it; the frontend's
TypeScript types are generated from it (frontend/src/model/project.gen.ts).
"""
from .issues import Issue, errors_only
from .migrate import CURRENT_VERSION, MigrationError, migrate
from .semantic import semantic_issues
from .validate import schema_issues, validate_document

__all__ = ["Issue", "errors_only", "CURRENT_VERSION", "MigrationError", "migrate", "semantic_issues",
           "schema_issues", "validate_document"]
