from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.api import router as api_router

app = FastAPI(title='Northern Lakes Flag Football Scheduler API')


@app.get('/health')
def health_check(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}

app.include_router(api_router)
