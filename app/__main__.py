import uvicorn
from app.main import app
from app.config.settings import get_settings

if __name__=="__main__":
    settings = get_settings()
    uvicorn.run(app=app, host=settings.host, port=settings.port, log_level=settings.log_level)