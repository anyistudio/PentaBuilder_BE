from pydantic import BaseModel, ConfigDict

from app.domain.enums import Language, TerminologyStyle


class UserSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    auth_provider: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None
    username: str | None = None
    icon_url: str | None = None
    preferred_language: Language = Language.ZH_CN
    preferred_terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL


class AuthExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    provider_token: str


class AuthExchangePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserSchema


class PatchMePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str | None = None
    preferred_language: Language | None = None
    preferred_terminology_style: TerminologyStyle | None = None
