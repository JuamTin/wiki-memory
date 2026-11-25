import json
import sys
from importlib.metadata import distribution
from pathlib import Path

import pytest
from pydantic import ValidationError

from wiki_memoria.domain import ConsolidationPlan


def test_schema_and_installation():
    schema = json.loads(json.dumps(ConsolidationPlan.model_json_schema()))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["page_updates"]["maxItems"] == 4
    assert schema["$defs"]["PageUpdate"]["properties"]["citations"]["minItems"] == 1
    assert Path(sys.prefix).name == ".venv"
    scripts = {e.name for e in distribution("wiki-memoria").entry_points}
    assert scripts == {"wiki-memoria", "wiki-memoria-hook"}


def test_validation():
    plan = dict(session_summary="", durable_worth_saving=False, page_updates=[], initiatives=[], corrections=[])
    assert ConsolidationPlan.model_validate(plan).model_dump() == plan
    for changes in ({"invented": 1}, {"session_summary": "a" * 601}, {"durable_worth_saving": "true"}):
        with pytest.raises(ValidationError):
            ConsolidationPlan.model_validate(plan | changes)
