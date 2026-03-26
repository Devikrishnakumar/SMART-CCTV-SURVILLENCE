"""
Creates a default admin user if none exists.
Credentials come from environment variables or safe defaults (dev only).
"""
import os
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, UserRole
from app.auth.security import hash_password

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@12345!")


async def seed_admin(db: AsyncSession):
    result = await db.execute(select(User).where(User.role == UserRole.admin))
    if result.scalar_one_or_none():
        return  # admin already exists

    admin = User(
        username=DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        role=UserRole.admin,
    )
    db.add(admin)
    await db.commit()
    logger.warning(
        f"[SEED] Default admin created: username='{DEFAULT_ADMIN_USERNAME}'. "
        "Change password immediately in production!"
    )
