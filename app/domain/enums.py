from enum import Enum


class Game(str, Enum):
    LOL = "lol"
    WILD_RIFT = "wild_rift"


class RunType(str, Enum):
    EVALUATE_BUILD = "evaluate_build"
    RECOMMEND_FULL_BUILD = "recommend_full_build"
    RECOMMEND_SLOT = "recommend_slot"
    EXPLAIN_SLOT = "explain_slot"
    COMPARE_BUILDS = "compare_builds"
    CHAT_FOLLOWUP = "chat_followup"


class Language(str, Enum):
    EN = "en"
    ZH_CN = "zh-CN"


class TerminologyStyle(str, Enum):
    OFFICIAL = "official"
    SLANG_ZH = "slang_zh"


class RunStatus(str, Enum):
    ACCEPTED = "accepted"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
