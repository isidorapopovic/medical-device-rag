"""Public errors contain fixed safe messages, never provider response bodies."""


class FoundationError(RuntimeError):
    code = "execution_error"

    def __init__(self):
        super().__init__(self.code)


class ValidationError(FoundationError):
    code = "validation_error"


class ParsingError(FoundationError):
    code = "parsing_error"


class MissingModel(FoundationError, ConnectionError):
    code = "missing_model"


class TransientModelError(FoundationError):
    code = "transient_model_error"


class BudgetExceeded(FoundationError):
    code = "budget_exceeded"


class CitationError(FoundationError):
    code = "citation_error"


class MissingEvidence(FoundationError):
    code = "missing_evidence"


class Cancelled(FoundationError):
    code = "cancelled"


class CircuitOpen(FoundationError):
    code = "circuit_open"


class StorageError(FoundationError):
    code = "storage_error"
