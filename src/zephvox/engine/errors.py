class ZephvoxError(Exception):
    """Base class for all engine errors."""


class ConfigError(ZephvoxError):
    pass


class PluginNotFound(ZephvoxError):
    def __init__(self, kind: str, name: str, known: list[str]):
        self.kind, self.name = kind, name
        hint = f" (known: {', '.join(known)})" if known else ""
        super().__init__(f"No {kind} plugin named {name!r}{hint}")


class ProviderUnavailable(ZephvoxError):
    def __init__(self, kind: str, reasons: list[str]):
        self.kind, self.reasons = kind, reasons
        detail = "; ".join(reasons) if reasons else "none configured"
        super().__init__(f"No usable {kind} provider: {detail}")


class PlanError(ZephvoxError):
    pass


class RecordingError(ZephvoxError):
    pass


class AudioError(ZephvoxError):
    pass


class LLMError(ZephvoxError):
    pass
