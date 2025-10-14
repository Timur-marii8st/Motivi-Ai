import pytest
from app.services.profile_completeness_service import ProfileCompletenessService
from app.models.users import User
from app.models.core_memory import CoreMemory

@pytest.mark.asyncio
async def test_completeness_score(db_session):
    # Create minimal user
    user = User(tg_user_id=12345, tg_chat_id=12345, name="Test")
    db_session.add(user)
    await db_session.flush()
    
    score = await ProfileCompletenessService.calculate_score(db_session, user.id)
    assert 0.0 <= score <= 1.0
    assert score < 0.5  # Minimal user should have low score
    
    # Add more fields
    user.age = 30
    user.timezone = "UTC"
    core = CoreMemory(user_id=user.id, goals_json={"goals": ["test"]})
    db_session.add(core)
    await db_session.flush()
    
    score2 = await ProfileCompletenessService.calculate_score(db_session, user.id)
    assert score2 > score  # Should increase