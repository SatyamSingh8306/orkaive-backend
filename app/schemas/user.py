"""User / auth schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class SignUpFormData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    confirm_password: str = Field(..., alias="confirmPassword")
    name: str = Field(..., min_length=1, max_length=200)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if v != info.data.get("password"):
            raise ValueError("passwords do not match")
        return v


class LoginFormData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str


class ForgotPasswordForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr


class ResetPasswordForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str
    new_password: str = Field(..., min_length=8, alias="new_password")
    confirm_password: str = Field(..., alias="confirm_password")

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if v != info.data.get("new_password"):
            raise ValueError("passwords do not match")
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    email: EmailStr
    name: str
    created_at: datetime
    is_active: bool = True

    @classmethod
    def from_mongo_doc(cls, doc: dict):
        return cls(
            id=str(doc["_id"]),
            email=doc["email"],
            name=doc["name"],
            created_at=doc["created_at"],
            is_active=doc.get("is_active", True),
        )
    
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str
    name: str


class UserInDB(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    email: EmailStr
    name: str
    created_at: datetime
    is_active: bool = True
    hashed_password: str

    @classmethod
    def from_mongo_doc(cls, doc: dict):
        return cls(
            id=str(doc["_id"]),
            email=doc["email"],
            name=doc["name"],
            created_at=doc["created_at"],
            is_active=doc.get("is_active", True),
            hashed_password=doc["hashed_password"],
        )
