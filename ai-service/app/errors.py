"""Typed errors with a stable code the backend and UI can show and branch on."""


class IngestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ServiceUnavailable(Exception):
    """A dependency (store, model, LLM) is down. Maps to HTTP 503."""

    def __init__(self, component: str, message: str):
        super().__init__(message)
        self.component = component
        self.message = message
