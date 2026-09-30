from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database.core import get_db
from backend.database.models import User
from backend.auth.security import verify_password, create_access_token

router = APIRouter(tags=["login"])

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/login/access-token", response_model=Token)
def login_access_token(
    session: Annotated[Session, Depends(get_db)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """OAuth2 compatible token login, get an access token for future requests."""
    user = session.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return Token(access_token=create_access_token(user.id))
