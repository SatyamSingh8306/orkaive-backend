from fastapi import Header, HTTPException, status, Depends
from app import SECRET_KEY

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not found in environment variables!")

def verify_secret(x_secret_key: str = Header(...)):
    """
    Dependency to verify that the incoming request contains the correct secret key
    in the headers (for example: X-Secret-Key: <your_secret_key>).
    """
    if x_secret_key != SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing secret key."
        )
    return True
