import enum


class PlanCycleStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class SolarRequestPurpose(str, enum.Enum):
    NEW_CYCLE = "NEW_CYCLE"
    ACTIVE_CYCLE = "ACTIVE_CYCLE"


class SolarRequestStatus(str, enum.Enum):
    COLLECTING = "COLLECTING"
    CHANGE_CONFIRMATION = "CHANGE_CONFIRMATION"
    CHANGE_INPUT = "CHANGE_INPUT"
    FINAL_REVIEW = "FINAL_REVIEW"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SolarAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class SolarEntityType(str, enum.Enum):
    TASK = "TASK"
    FIXED_SCHEDULE = "FIXED_SCHEDULE"


class SolarItemStatus(str, enum.Enum):
    INFO_MISSING = "INFO_MISSING"
    READY = "READY"
    EXECUTED = "EXECUTED"


class SolarMessageRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class SolarMessageKind(str, enum.Enum):
    TEXT = "TEXT"
    QUESTION = "QUESTION"
    ERROR = "ERROR"
    DECISION = "DECISION"


class PlanPeriod(str, enum.Enum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"


class TaskStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PlanBlockStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    CHECKED = "CHECKED"
    COMPLETED = "COMPLETED"
    NOT_DONE = "NOT_DONE"


class EstimateSource(str, enum.Enum):
    USER = "USER"
    AI_ESTIMATED = "AI_ESTIMATED"


class AmountSource(str, enum.Enum):
    USER = "USER"
    AI_ESTIMATED = "AI_ESTIMATED"
    UNKNOWN = "UNKNOWN"
