import json

from fastapi import APIRouter

from app.config import INPUT_SCHEMA_PATH

router = APIRouter(prefix="/api/schema", tags=["schema"])


@router.get("")
def get_input_schema():
    with open(INPUT_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
