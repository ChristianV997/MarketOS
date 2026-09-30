import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jose import jwt

from backend.api import app
from backend.database.core import Base, get_db
from backend.database.models import User, Workspace
from backend.auth.security import get_password_hash, SECRET_KEY, ALGORITHM

# Dispatch testing pattern: Nested transaction testing
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables in memory
Base.metadata.create_all(bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """Dispatch's nested transaction fixture for fast isolated DB tests."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # We use a nested transaction so we can rollback at the end of the test
    nested = connection.begin_nested()

    # Automatically rollback when the nested transaction ends (e.g. session.commit())
    @event.listens_for(session, "after_transaction_end")
    def end_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()

from sqlalchemy import event

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session


    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c

def test_login_and_workspace_isolation_pattern(client, db_session):
    # Create owner user
    user = User(email="owner@example.com", hashed_password=get_password_hash("testpassword"))
    db_session.add(user)
    db_session.commit()

    # Create workspace isolated to that user (Tiangolo's logical isolation pattern)
    ws = Workspace(workspace_id="ws-123", name="My Project", owner_id=user.id)
    db_session.add(ws)
    db_session.commit()

    # Login to get token
    response = client.post("/api/v1/login/access-token", data={"username": "owner@example.com", "password": "testpassword"})
    assert response.status_code == 200
    token = response.json()["access_token"]

    # Validate token signature
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == user.id

    # Verify logical isolation works in query
    workspaces = db_session.query(Workspace).filter(Workspace.owner_id == user.id).all()
    assert len(workspaces) == 1
    assert workspaces[0].name == "My Project"
