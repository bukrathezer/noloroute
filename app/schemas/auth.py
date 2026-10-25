from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

MIN_PASSWORD_LENGTH = 8
Lang = Literal["tr", "en"]
Code = Field(pattern=r"^\d{6}$", description="The six-digit code from the email.")


class EmailForm(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        # One account per address regardless of letter case.
        return value.strip().lower()


class RegisterRequest(EmailForm):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    lang: Lang = Field(default="en", description="The language of the code email.")


class VerifyEmailRequest(EmailForm):
    code: str = Code
    password: str = Field(max_length=128, description="The password the code was asked for with.")


class ResendCodeRequest(EmailForm):
    purpose: Literal["verify", "reset"] = "verify"
    lang: Lang = "en"


class ForgotPasswordRequest(EmailForm):
    lang: Lang = "en"


class ResetPasswordRequest(EmailForm):
    code: str = Code
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class CodeSentResponse(BaseModel):
    status: Literal["code_sent"] = "code_sent"
    email: str


class UserOut(BaseModel):
    id: str
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DeleteAccountRequest(BaseModel):
    password: str = Field(max_length=128)
