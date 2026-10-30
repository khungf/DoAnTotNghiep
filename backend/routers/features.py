from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Rating, SOSRequest
from pydantic import BaseModel

router = APIRouter(prefix="/api/features", tags=["Features"])

class RatingCreate(BaseModel):
    sos_id: int
    rater_id: int
    target_id: int
    score: int
    comment: str

@router.post("/rate")
def rate_user(data: RatingCreate, db: Session = Depends(get_db)):
    r = Rating(
        sos_id=data.sos_id,
        rater_id=data.rater_id,
        target_id=data.target_id,
        score=data.score,
        comment=data.comment
    )
    db.add(r)
    db.commit()
    return {"status": "success", "message": "Đã gửi đánh giá thành công"}

@router.get("/dashboard/{user_id}")
def get_dashboard(user_id: int, db: Session = Depends(get_db)):
    completed_count = db.query(SOSRequest).filter(
        SOSRequest.user_id == user_id, SOSRequest.status == "Completed"
    ).count()
    ratings = db.query(Rating).filter(Rating.target_id == user_id).all()
    avg_score = sum([r.score for r in ratings]) / len(ratings) if ratings else 5.0
    return {
        "completed_tasks": completed_count,
        "average_rating": round(avg_score, 1),
        "total_ratings": len(ratings)
    }