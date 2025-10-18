from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import SQLModel, create_engine, Session, select
from models import Kid, LogEntry, AdminConfig
from contextlib import contextmanager
from datetime import datetime, date
import os
import time
from typing import Optional
import asyncio

# Global variable to track the last time deduction was calculated for display purposes
last_display_calc_time = datetime.utcnow()

# Add session middleware
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="your-super-secret-key-change-this-in-production")

# Database setup
DATABASE_URL = "sqlite:///./familiytime.db"
engine = create_engine(DATABASE_URL, echo=False)

# Create tables
def create_db_and_tables():
    SQLModel.metadata.create_all(bind=engine)

# Initialize database
create_db_and_tables()

# Templates
templates = Jinja2Templates(directory="templates")

# In-memory storage for active kid (for simplicity in this example)
active_kid_id = None
app.state.active_kid_id = None



def get_session():
    with Session(engine) as session:
        yield session

def verify_password(plain_password: str, session: Session) -> bool:
    # Get the admin config from the database
    admin_config = session.get(AdminConfig, 1)  # Assuming single admin config record
    if not admin_config:
        return False  # No admin config exists
    return admin_config.admin_password == plain_password

def admin_required(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return True

@app.on_event("startup")
def startup_event():
    create_db_and_tables()
    
    # Create a default admin config if none exists
    with Session(engine) as session:
        existing_admin = session.get(AdminConfig, 1)
        if not existing_admin:
            default_admin = AdminConfig(admin_password="admin")  # Default password
            session.add(default_admin)
            session.commit()
    
    # Create a default kid if none exist
    with Session(engine) as session:
        existing_kids = session.exec(select(Kid)).all()
        if not existing_kids:
            default_kid = Kid(name="Child1", current_minutes=30, last_reset_date=str(date.today()))
            session.add(default_kid)
            session.commit()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, session: Session = Depends(get_session)):
    kids = session.exec(select(Kid)).all()
    for kid in kids:
        kid.reset_daily_bonus_if_needed()
    session.commit()
    return templates.TemplateResponse("kids.html", {"request": request, "kids": kids})

@app.post("/api/session/start/{kid_id}")
def start_session(kid_id: int, request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    global active_kid_id
    app.state.active_kid_id = kid_id
    return {"message": f"Session started for kid {kid_id}"}

@app.get("/api/session/status")
def session_status():
    global last_deduction_state
    kid_id = app.state.active_kid_id
    
    if not kid_id:
        return {"is_active": False, "time_remaining_seconds": 0}
    
    # Get the kid from database
    with Session(engine) as db_session:
        kid = db_session.get(Kid, kid_id)
        if not kid:
            return {"is_active": False, "time_remaining_seconds": 0}
        
        # Reset daily bonus if needed
        kid.reset_daily_bonus_if_needed()
        
        # Calculate total available time
        main_time = max(0, kid.current_minutes)
        bonus_available = max(0, 15 - kid.daily_bonus_used)
        total_seconds = (main_time + bonus_available) * 60
        
        # If no time left, return status but don't deduct
        if total_seconds <= 0:
            return {"is_active": True, "time_remaining_seconds": 0, "kid_id": kid_id, "kid_name": kid.name}
        
        # Deduct 10 seconds
        if kid.current_minutes > 0:
            # Deduct from current minutes if available
            kid.current_minutes = max(-5, kid.current_minutes - 10/60)  # 10 seconds = 10/60 minutes
        else:
            # Deduct from daily bonus if main time is exhausted
            kid.daily_bonus_used = min(15, kid.daily_bonus_used + 10/60)
        
        db_session.add(kid)
        db_session.commit()
        
        # Update our tracking state with the new values after deduction
        last_deduction_state = {
            'kid_id': kid_id,
            'current_minutes': kid.current_minutes,
            'daily_bonus_used': kid.daily_bonus_used,
            'timestamp': datetime.utcnow()
        }
        
        # Calculate remaining time after deduction (for return value)
        # Recalculate after deduction
        updated_main_time = max(0, kid.current_minutes)
        updated_bonus_available = max(0, 15 - kid.daily_bonus_used)
        remaining_seconds = (updated_main_time + updated_bonus_available) * 60 - 10
        remaining_seconds = max(0, remaining_seconds)  # Ensure non-negative
        
        return {"is_active": True, "time_remaining_seconds": remaining_seconds, "kid_id": kid_id, "kid_name": kid.name}

@app.get("/api/kids")
def get_kids(session: Session = Depends(get_session)):
    kids = session.exec(select(Kid)).all()
    return [{"id": kid.id, "name": kid.name, "minutes": kid.current_minutes} for kid in kids]

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, session: Session = Depends(get_session)):
    if request.session.get("admin_authenticated"):
        kids = session.exec(select(Kid)).all()
        return templates.TemplateResponse("admin.html", {"request": request, "kids": kids})
    else:
        return templates.TemplateResponse("admin.html", {"request": request})

@app.post("/admin/login")
def login(request: Request, password: str = Form(...), session: Session = Depends(get_session)):
    if verify_password(password, session):
        request.session["admin_authenticated"] = True
        kids = session.exec(select(Kid)).all()
        return templates.TemplateResponse("admin.html", {"request": request, "kids": kids})
    else:
        return templates.TemplateResponse("admin.html", {
            "request": request, 
            "error": "Invalid password"
        })

@app.post("/admin/time")
def update_time(
    request: Request,
    kid_id: int = Form(...),
    minutes: int = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session)
):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid
    kid = session.get(Kid, kid_id)
    if not kid:
        return HTMLResponse(content="Kid not found", status_code=404)
    
    # Update the kid's time
    kid.current_minutes = max(-5, kid.current_minutes + minutes)
    session.add(kid)
    
    # Create log entry
    log_entry = LogEntry(
        kid_id=kid_id,
        minutes_changed=minutes,
        reason=reason
    )
    session.add(log_entry)
    session.commit()
    
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/add_kid")
def add_kid(
    request: Request,
    name: str = Form(...),
    initial_minutes: int = Form(30),
    session: Session = Depends(get_session)
):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Create new kid
    new_kid = Kid(name=name, current_minutes=initial_minutes, last_reset_date=str(date.today()))
    session.add(new_kid)
    session.commit()
    
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/edit_kid")
def edit_kid(
    request: Request,
    kid_id: int = Form(...),
    name: str = Form(...),
    session: Session = Depends(get_session)
):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid
    kid = session.get(Kid, kid_id)
    if not kid:
        return HTMLResponse(content="Kid not found", status_code=404)
    
    # Update the kid's name
    kid.name = name
    session.add(kid)
    session.commit()
    
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/delete_kid")
def delete_kid(
    request: Request,
    kid_id: int = Form(...),
    session: Session = Depends(get_session)
):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid
    kid = session.get(Kid, kid_id)
    if not kid:
        return HTMLResponse(content="Kid not found", status_code=404)
    
    # Delete the kid
    session.delete(kid)
    session.commit()
    
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/start_session/{kid_id}")
def admin_start_session(kid_id: int, request: Request):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    app.state.active_kid_id = kid_id
    return {"message": f"Session started for kid {kid_id}"}


@app.get("/admin/logs")
def get_logs(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all log entries, ordered by timestamp (newest first)
    logs = session.exec(select(LogEntry).order_by(LogEntry.timestamp.desc())).all()
    return {"logs": logs}


# Track the last actual deduction time and state to calculate effective time
last_deduction_state = {
    'kid_id': None,
    'current_minutes': 0,
    'daily_bonus_used': 0,
    'timestamp': datetime.utcnow()
}

@app.get("/api/active-session")
def active_session():
    global last_deduction_state
    kid_id = app.state.active_kid_id
    
    if not kid_id:
        # Reset the state tracking when no active session
        last_deduction_state = {
            'kid_id': None,
            'current_minutes': 0,
            'daily_bonus_used': 0,
            'timestamp': datetime.utcnow()
        }
        return {"is_active": False, "active_kid": None}
    
    # Get the kid from database to get name
    with Session(engine) as db_session:
        kid = db_session.get(Kid, kid_id)
        if not kid:
            return {"is_active": False, "active_kid": None}
        
        # Reset daily bonus if needed (for consistency)
        kid.reset_daily_bonus_if_needed()
        
        # Check if this is the same kid as last time or a new session
        if last_deduction_state['kid_id'] != kid_id:
            # New session, update tracking state
            last_deduction_state = {
                'kid_id': kid_id,
                'current_minutes': kid.current_minutes,
                'daily_bonus_used': kid.daily_bonus_used,
                'timestamp': datetime.utcnow()
            }
        
        # Calculate time elapsed since the last known state
        time_elapsed = (datetime.utcnow() - last_deduction_state['timestamp']).total_seconds()
        
        # Estimate the effective time based on elapsed time
        # Deductions happen every 10 seconds, so 10 seconds of time is deducted per 10 seconds
        # For smooth display, we'll proportionally calculate the deduction
        effective_minutes = last_deduction_state['current_minutes']
        effective_bonus_used = last_deduction_state['daily_bonus_used']
        
        # Calculate how much time should have been deducted
        minutes_elapsed_since_known = time_elapsed / 60.0
        
        # Apply deduction logic similar to the session status endpoint
        if effective_minutes > 0:
            # Deduct from main minutes first
            effective_minutes = max(-5, effective_minutes - minutes_elapsed_since_known)
            # If main time goes below zero, the remainder goes to bonus
            if effective_minutes < 0:
                # Calculate how much bonus time would be used from remaining negative time
                remaining_to_deduct = abs(effective_minutes)
                effective_bonus_used = min(15, effective_bonus_used + remaining_to_deduct)
                # Set effective minutes to 0 (negative time is represented by bonus used)
                effective_minutes = effective_minutes  # Keep the negative value to show bonus time in use
        else:
            # If main time is already exhausted, deduct from bonus
            effective_bonus_used = min(15, effective_bonus_used + minutes_elapsed_since_known)
        
        # Calculate remaining effective time in seconds
        effective_seconds = effective_minutes * 60
        
        return {
            "is_active": True,
            "active_kid": {
                "id": kid.id,
                "name": kid.name,
                "time_remaining_seconds": effective_seconds
            }
        }


@app.get("/api/logs")
def get_logs_api(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all log entries, ordered by timestamp (newest first)
    logs = session.exec(select(LogEntry).order_by(LogEntry.timestamp.desc())).all()
    
    # Convert logs to JSON-serializable format
    logs_data = []
    for log in logs:
        # Find the kid's name using a separate query
        kid = session.get(Kid, log.kid_id)
        kid_name = kid.name if kid else "Unknown"
        
        logs_data.append({
            "id": log.id,
            "kid_name": kid_name,
            "minutes_changed": log.minutes_changed,
            "reason": log.reason,
            "timestamp": log.timestamp.isoformat()
        })
    
    return {"logs": logs_data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)