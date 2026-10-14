from __future__ import annotations

import json

from ..engine.models import AnalysisResult
from .base import Reporter


class JsonReporter(Reporter):
    name = "json"
    extension = "json"

    def render(self, result: AnalysisResult) -> str:
        return json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"
