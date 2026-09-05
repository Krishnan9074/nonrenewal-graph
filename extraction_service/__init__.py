import os
from pathlib import Path

STORE = Path(os.environ.get("EXTRACTION_STORE", "data/extractions"))
SCHEMA_DIR = Path(__file__).parent / "schema"
PROMPT_DIR = Path(__file__).parent / "prompts"
