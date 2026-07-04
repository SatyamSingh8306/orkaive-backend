from typing import Optional
from datetime import datetime
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException, status
from app.db.mongodb import get_database
from app.schemas.user import UserCreate, UserInDB, UserResponse
from app.utils.auth import get_password_hash, verify_password

class UserService:
    def __init__(self):
        self.db = None
        self.users_collection = None

    async def get_db(self):
        """Get database connection."""
        if self.db is None:
            self.db = get_database()
            self.users_collection = self.db.users
        return self.db

    async def create_user(self, user_data: UserCreate) -> UserResponse:
        """Create a new user in the database."""
        try:
            await self.get_db()
            # Check if user already exists
            existing_user = await self.users_collection.find_one({"email": user_data.email})
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            # Hash password
            hashed_password = get_password_hash(user_data.password)

            # Create user document
            user_doc = {
                "email": user_data.email,
                "name": user_data.name,
                "hashed_password": hashed_password,
                "created_at": datetime.utcnow(),
                "is_active": True,
                "updated_at": datetime.utcnow()
            }

            # Insert user
            result = await self.users_collection.insert_one(user_doc)
            user_doc["_id"] = result.inserted_id

            # Return user response (without password)
            return UserResponse.from_mongo_doc(user_doc)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create user: {str(e)}"
            )

    async def get_user_by_email(self, email: str) -> Optional[UserInDB]:
        """Get user by email from database."""
        try:
            await self.get_db()
            user_doc = await self.users_collection.find_one({"email": email})
            if not user_doc:
                return None

            return UserInDB.from_mongo_doc(user_doc)

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get user: {str(e)}"
            )

    async def get_user_by_id(self, user_id: str) -> Optional[UserResponse]:
        """Get user by ID from database."""
        try:
            await self.get_db()
            from bson import ObjectId
            user_doc = await self.users_collection.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                return None

            return UserResponse.from_mongo_doc(user_doc)

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get user: {str(e)}"
            )

    async def authenticate_user(self, email: str, password: str) -> Optional[UserInDB]:
        """Authenticate user with email and password."""
        user = await self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account is inactive"
            )
        return user

    async def update_password(self, email: str, new_password: str) -> bool:
        """Update user password."""
        try:
            await self.get_db()
            hashed_password = get_password_hash(new_password)
            result = await self.users_collection.update_one(
                {"email": email},
                {
                    "$set": {
                        "hashed_password": hashed_password,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return result.modified_count > 0

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update password: {str(e)}"
            )

    async def deactivate_user(self, email: str) -> bool:
        """Deactivate user account."""
        try:
            await self.get_db()
            result = await self.users_collection.update_one(
                {"email": email},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return result.modified_count > 0

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deactivate user: {str(e)}"
            )

# Global user service instance
user_service = UserService()
