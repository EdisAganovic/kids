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

# In-memory storage for active kid and session tracking
app.state.active_kid_id = None
app.state.session_start_time = None  # When the session started
app.state.time_remaining_at_start = 0  # Time remaining when session started
app.state.original_time_at_session_start = 0  # Original time at session start for accurate deduction



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
            default_admin = AdminConfig(
                admin_password="admin",  # Default password
                bonus_time_enabled=True  # Bonus time enabled by default
            )
            session.add(default_admin)
            session.commit()
    
    # Create a default kid if none exist
    with Session(engine) as session:
        existing_kids = session.exec(select(Kid)).all()
        if not existing_kids:
            default_kid = Kid(name="Child1", current_minutes=30, last_reset_date=str(date.today()))
            session.add(default_kid)
            # Add a log entry for the initial time allocation
            # Also add the same amount as initial points
            initial_log = LogEntry(
                kid_id=1,
                time_change=30,
                points_change=30,  # Add same amount as initial points
                reason="Initial time allocation"
            )
            session.add(initial_log)
            session.commit()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, session: Session = Depends(get_session)):
    # Get all kids
    kids = session.exec(select(Kid)).all()
    for kid in kids:
        kid.reset_daily_bonus_if_needed()
    session.commit()
    
    # For the leaderboard, we want to show the sum of points from log entries
    # rather than the current time balance
    all_logs = session.exec(select(LogEntry)).all()
    
    # Calculate total points for each kid (separate from time)
    kid_points = {}
    for log in all_logs:
        # Sum up the points changes (separate from time)
        if log.kid_id in kid_points:
            kid_points[log.kid_id] += log.points_change
        else:
            kid_points[log.kid_id] = log.points_change
    
    # Create a list of tuples (kid, points) and sort by points
    kid_point_pairs = [(kid, kid_points.get(kid.id, 0)) for kid in kids]
    sorted_kid_point_pairs = sorted(kid_point_pairs, key=lambda x: x[1], reverse=True)
    
    # Return the sorted list for the template
    return templates.TemplateResponse("kids.html", {
        "request": request, 
        "kids_with_points": sorted_kid_point_pairs
    })

@app.post("/api/session/start/{kid_id}")
def start_session(kid_id: int, request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid to record the original time
    kid = session.get(Kid, kid_id)
    if kid:
        # Get admin config to check if bonus time is enabled
        admin_config = session.get(AdminConfig, 1)
        bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
        
        # Reset daily bonus if needed (only if bonus is enabled)
        if bonus_time_enabled:
            kid.reset_daily_bonus_if_needed()
        
        # Calculate total available time
        main_time = max(0, kid.current_minutes)
        bonus_available = 0  # Don't include bonus if disabled
        if bonus_time_enabled:
            bonus_available = max(0, 15 - kid.daily_bonus_used)
        total_available_seconds = (main_time + bonus_available) * 60
        
        app.state.original_time_at_session_start = kid.current_minutes  # Record original time for accurate deduction
        app.state.time_remaining_at_start = total_available_seconds  # Record initial time
    
    global active_kid_id
    app.state.active_kid_id = kid_id
    return {"message": f"Session started for kid {kid_id}"}

@app.get("/api/session/status")
def session_status():
    kid_id = app.state.active_kid_id
    
    if not kid_id:
        return {"is_active": False, "time_remaining_seconds": 0}
    
    with Session(engine) as db_session:
        kid = db_session.get(Kid, kid_id)
        if not kid:
            return {"is_active": False, "time_remaining_seconds": 0}
        
        # Get admin config to check if bonus time is enabled
        admin_config = db_session.get(AdminConfig, 1)
        bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
        
        # Reset daily bonus if needed (only if bonus time is enabled)
        if bonus_time_enabled:
            kid.reset_daily_bonus_if_needed()
        
        # Calculate initial total time available at session start
        # Use the original time at session start to maintain consistency
        main_time = max(0, app.state.original_time_at_session_start)
        bonus_available = 0  # Don't include bonus if disabled
        if bonus_time_enabled:
            bonus_available = max(0, 15 - kid.daily_bonus_used)  # Use current bonus used at session start
        initial_total_seconds = (main_time + bonus_available) * 60
        
        # If session just started, record the start time and initial time
        if app.state.session_start_time is None:
            app.state.session_start_time = datetime.utcnow()
            app.state.time_remaining_at_start = initial_total_seconds
            app.state.original_time_at_session_start = kid.current_minutes  # Record original time for accurate deduction
        
        # Calculate elapsed time since session started
        current_time = datetime.utcnow()
        total_elapsed = (current_time - app.state.session_start_time).total_seconds()
        
        # Calculate remaining time
        time_remaining = max(0, app.state.time_remaining_at_start - total_elapsed)
        
        # If time is up, return 0
        if time_remaining <= 0:
            return {
                "is_active": True,
                "time_remaining_seconds": 0,
                "kid_id": kid_id,
                "kid_name": kid.name
            }
        
        return {
            "is_active": True,
            "time_remaining_seconds": time_remaining,
            "kid_id": kid_id,
            "kid_name": kid.name
        }

@app.get("/api/kids")
def get_kids(session: Session = Depends(get_session)):
    kids = session.exec(select(Kid)).all()
    return [{"id": kid.id, "name": kid.name, "minutes": kid.current_minutes} for kid in kids]

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, session: Session = Depends(get_session)):
    if request.session.get("admin_authenticated"):
        kids = session.exec(select(Kid)).all()
        # Get admin config to check bonus time status
        admin_config = session.get(AdminConfig, 1)
        bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
        return templates.TemplateResponse("admin.html", {
            "request": request, 
            "kids": kids, 
            "bonus_time_enabled": bonus_time_enabled
        })
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
    
    # Create log entry - time change and also add same amount as points
    log_entry = LogEntry(
        kid_id=kid_id,
        time_change=minutes,
        points_change=minutes,  # Add same amount as points
        reason=reason
    )
    session.add(log_entry)
    session.commit()
    
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/points")
def update_points(
    request: Request,
    kid_id: int = Form(...),
    points: int = Form(...),
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
    
    # Create log entry - points change only, no time change
    log_entry = LogEntry(
        kid_id=kid_id,
        time_change=0,  # No time change when updating points
        points_change=points,
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
    
    # Create log entry for initial time allocation
    # Also add the same amount as initial points
    initial_log = LogEntry(
        kid_id=new_kid.id,
        time_change=initial_minutes,
        points_change=initial_minutes,  # Add same amount as initial points
        reason="Initial time allocation"
    )
    session.add(initial_log)
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
def admin_start_session(kid_id: int, request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid to check available time
    kid = session.get(Kid, kid_id)
    if not kid:
        raise HTTPException(status_code=404, detail="Kid not found")
    
    # Get admin config to check if bonus time is enabled
    admin_config = session.get(AdminConfig, 1)
    bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
    
    # Reset daily bonus if needed (only if bonus is enabled)
    if bonus_time_enabled:
        kid.reset_daily_bonus_if_needed()
    
    # Calculate total available time
    main_time = max(0, kid.current_minutes)
    bonus_available = 0  # Don't include bonus if disabled
    if bonus_time_enabled:
        bonus_available = max(0, 15 - kid.daily_bonus_used)
    total_available_seconds = (main_time + bonus_available) * 60
    
    # If no time available, don't start session
    if total_available_seconds <= 0:
        raise HTTPException(status_code=400, detail="No time available for this kid")
    
    app.state.active_kid_id = kid_id
    app.state.session_start_time = datetime.utcnow()  # Record when session started
    app.state.time_remaining_at_start = total_available_seconds  # Record initial time
    app.state.original_time_at_session_start = kid.current_minutes  # Record original time for accurate deduction
    
    return {"message": f"Session started for kid {kid_id}"}


@app.post("/admin/start_session_with_time")
def admin_start_session_with_time(
    request: Request,
    kid_id: int = Form(...),
    session_time: int = Form(...),
    session: Session = Depends(get_session)
):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the kid to check available time
    kid = session.get(Kid, kid_id)
    if not kid:
        raise HTTPException(status_code=404, detail="Kid not found")
    
    # Validate that requested session time is positive
    if session_time <= 0:
        raise HTTPException(status_code=400, detail="Session time must be greater than 0")
    
    # Get admin config to check if bonus time is enabled
    admin_config = session.get(AdminConfig, 1)
    bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
    
    # Reset daily bonus if needed (only if bonus is enabled)
    if bonus_time_enabled:
        kid.reset_daily_bonus_if_needed()
    
    # Calculate total available time
    main_time = max(0, kid.current_minutes)
    bonus_available = 0  # Don't include bonus if disabled
    if bonus_time_enabled:
        bonus_available = max(0, 15 - kid.daily_bonus_used)
    total_available_seconds = (main_time + bonus_available) * 60
    
    # If no time available, don't start session
    if total_available_seconds <= 0:
        raise HTTPException(status_code=400, detail="No time available for this kid")
    
    # Use the custom session time (convert to seconds), but don't exceed available time
    requested_seconds = session_time * 60
    actual_session_seconds = min(requested_seconds, total_available_seconds)
    
    app.state.active_kid_id = kid_id
    app.state.session_start_time = datetime.utcnow()  # Record when session started
    app.state.time_remaining_at_start = actual_session_seconds  # Record initial time
    app.state.original_time_at_session_start = kid.current_minutes  # Record original time for accurate deduction
    
    return {"message": f"Session started for kid {kid_id} with {session_time} minutes"}


import subprocess
import platform

def lock_screen():
    """Function to lock the computer screen"""
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif system == "Darwin":  # macOS
            subprocess.run(["pmset", "displaysleepnow"])
        elif system == "Linux":
            subprocess.run(["xdg-screensaver", "lock"])
    except Exception as e:
        print(f"Error locking screen: {e}")

@app.post("/admin/stop_session")
def admin_stop_session(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    kid_id = app.state.active_kid_id
    if kid_id:
        # Get the kid from database
        kid = session.get(Kid, kid_id)
        if kid:
            # Get admin config to check if bonus time is enabled
            admin_config = session.get(AdminConfig, 1)
            bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
            
            # Reset daily bonus if needed (only if bonus is enabled)
            if bonus_time_enabled:
                kid.reset_daily_bonus_if_needed()
            
            # Calculate total elapsed time at the moment of stopping
            current_time = datetime.utcnow()
            if app.state.session_start_time:
                # Calculate from start to now
                total_elapsed = (current_time - app.state.session_start_time).total_seconds()
            else:
                total_elapsed = 0
            
            # Calculate total time that should be deducted based on original time at session start
            original_main_time = max(0, app.state.original_time_at_session_start)
            original_bonus_available = 0  # Don't include bonus if disabled
            if bonus_time_enabled:
                original_bonus_available = max(0, 15 - kid.daily_bonus_used)  # Use current bonus used at session start
            initial_total_seconds = (original_main_time + original_bonus_available) * 60
            
            # Use the minimum of elapsed time and initial available time
            total_elapsed = min(total_elapsed, initial_total_seconds)
            
            # Deduct the elapsed time from the kid's time
            total_elapsed_minutes = round(total_elapsed / 60.0, 1)  # Round to 1 decimal place to avoid floating point issues
            
            # Store the original time to calculate the change
            original_time = kid.current_minutes
            
            # First, try to deduct from main time
            if kid.current_minutes > 0:
                kid.current_minutes = max(-5, round(kid.current_minutes - total_elapsed_minutes, 1))
                
                # If main time went negative and bonus is enabled, use bonus time for the remainder
                if bonus_time_enabled and kid.current_minutes < 0:
                    remaining_to_deduct = abs(kid.current_minutes)  # How much more to deduct
                    kid.daily_bonus_used = min(15, round(kid.daily_bonus_used + remaining_to_deduct, 1))
                    kid.current_minutes = -5  # Cap at -5
            elif bonus_time_enabled and kid.daily_bonus_used < 15:
                # If main time was already exhausted, deduct from bonus time
                kid.daily_bonus_used = min(15, round(kid.daily_bonus_used + total_elapsed_minutes, 1))
            
            # Calculate the actual time change for the log entry
            # Since we're deducting time, the change should be negative
            actual_time_change = -total_elapsed_minutes
            
            # Create a log entry for the time deduction (points not affected)
            log_entry = LogEntry(
                kid_id=kid_id,
                time_change=actual_time_change,  # Negative value since time was deducted
                points_change=0,  # Points are not affected during session stop
                reason="Session manually stopped by admin"
            )
            session.add(log_entry)
            session.add(kid)
            session.commit()
    
    # Reset all session tracking
    app.state.active_kid_id = None
    app.state.session_start_time = None
    app.state.time_remaining_at_start = 0
    app.state.original_time_at_session_start = 0
    
    # Lock the screen after stopping the session
    lock_screen()
    
    return {"message": "Session stopped and time deducted"}





@app.post("/admin/toggle_bonus_time")
def admin_toggle_bonus_time(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the admin config
    admin_config = session.get(AdminConfig, 1)
    if not admin_config:
        raise HTTPException(status_code=404, detail="Admin config not found")
    
    # Toggle the bonus time setting
    admin_config.bonus_time_enabled = not admin_config.bonus_time_enabled
    session.add(admin_config)
    session.commit()
    
    status = "enabled" if admin_config.bonus_time_enabled else "disabled"
    return {"message": f"Bonus time {status}"}


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
    kid_id = app.state.active_kid_id
    
    if not kid_id:
        # Reset all session tracking when no active session
        app.state.session_start_time = None
        app.state.time_remaining_at_start = 0
        return {"is_active": False, "active_kid": None}
    
    # Get the kid from database to get name
    with Session(engine) as db_session:
        kid = db_session.get(Kid, kid_id)
        if not kid:
            return {"is_active": False, "active_kid": None}
        
        # Get admin config to check if bonus time is enabled
        admin_config = db_session.get(AdminConfig, 1)
        bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
        
        # Reset daily bonus if needed (for consistency, only if bonus is enabled)
        if bonus_time_enabled:
            kid.reset_daily_bonus_if_needed()
        
        # Calculate initial total time available at session start
        # Use the original time at session start to maintain consistency
        main_time = max(0, app.state.original_time_at_session_start)
        bonus_available = 0  # Don't include bonus if disabled
        if bonus_time_enabled:
            bonus_available = max(0, 15 - kid.daily_bonus_used)  # Use current bonus used at session start
        initial_total_seconds = (main_time + bonus_available) * 60
        
        # If session just started, initialize tracking
        if app.state.session_start_time is None:
            app.state.session_start_time = datetime.utcnow()
            app.state.time_remaining_at_start = initial_total_seconds
            app.state.original_time_at_session_start = kid.current_minutes  # Record original time for accurate deduction
        
        # Calculate elapsed time since session started
        current_time = datetime.utcnow()
        total_elapsed = (current_time - app.state.session_start_time).total_seconds()
        
        # Calculate remaining time
        time_remaining = max(0, app.state.time_remaining_at_start - total_elapsed)
        
        return {
            "is_active": True,
            "active_kid": {
                "id": kid.id,
                "name": kid.name,
                "time_remaining_seconds": time_remaining
            }
        }


@app.post("/admin/recalculate_points")
def recalculate_points(request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all log entries
    all_logs = session.exec(select(LogEntry)).all()
    
    # Calculate total points for each kid from logs
    kid_points = {}
    for log in all_logs:
        if log.kid_id in kid_points:
            kid_points[log.kid_id] += log.points_change
        else:
            kid_points[log.kid_id] = log.points_change
    
    # Return the recalculated points for verification
    return {"message": "Points recalculated successfully", "kid_points": kid_points}


@app.post("/admin/delete_log/{log_id}")
def delete_log(log_id: int, request: Request, session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the log entry
    log = session.get(LogEntry, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")
    
    # Delete the log entry
    session.delete(log)
    session.commit()
    
    return {"message": "Log entry deleted successfully"}


@app.post("/admin/update_log_reason/{log_id}")
def update_log_reason(log_id: int, request: Request, reason: str = Form(...), session: Session = Depends(get_session)):
    # Check if admin is authenticated by checking session cookie
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the log entry
    log = session.get(LogEntry, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")
    
    # Update the reason
    log.reason = reason
    session.add(log)
    session.commit()
    
    return {"message": "Log reason updated successfully"}


@app.post("/api/active-session/time-expired")
def time_expired_endpoint(request: Request, session: Session = Depends(get_session)):
    # Note: This endpoint is called from the ESP32 which doesn't have admin session
    # We'll allow this without authentication for now
    
    # Get the currently active kid
    kid_id = app.state.active_kid_id
    if kid_id:
        # Get the kid from database
        kid = session.get(Kid, kid_id)
        if kid:
            # Get admin config to check if bonus time is enabled
            admin_config = session.get(AdminConfig, 1)
            bonus_time_enabled = admin_config.bonus_time_enabled if admin_config else True
            
            # Reset daily bonus if needed (only if bonus is enabled)
            if bonus_time_enabled:
                kid.reset_daily_bonus_if_needed()
            
            # Calculate total elapsed time based on original time at session start
            original_main_time = max(0, app.state.original_time_at_session_start)
            original_bonus_available = 0  # Don't include bonus if disabled
            if bonus_time_enabled:
                original_bonus_available = max(0, 15 - kid.daily_bonus_used)  # Use current bonus used at session start
            initial_total_seconds = (original_main_time + original_bonus_available) * 60
            
            # Calculate total elapsed time (which should be the full initial time since it expired)
            total_elapsed = initial_total_seconds
            
            # Deduct the elapsed time from the kid's time
            total_elapsed_minutes = round(total_elapsed / 60.0, 1)  # Round to 1 decimal place to avoid floating point issues
            
            # Store the original time to calculate the change
            original_time = kid.current_minutes
            
            # First, try to deduct from main time
            if kid.current_minutes > 0:
                kid.current_minutes = max(-5, round(kid.current_minutes - total_elapsed_minutes, 1))
                
                # If main time went negative and bonus is enabled, use bonus time for the remainder
                if bonus_time_enabled and kid.current_minutes < 0:
                    remaining_to_deduct = abs(kid.current_minutes)  # How much more to deduct
                    kid.daily_bonus_used = min(15, round(kid.daily_bonus_used + remaining_to_deduct, 1))
                    kid.current_minutes = -5  # Cap at -5
            elif bonus_time_enabled and kid.daily_bonus_used < 15:
                # If main time was already exhausted, deduct from bonus time
                kid.daily_bonus_used = min(15, round(kid.daily_bonus_used + total_elapsed_minutes, 1))
            
            # Calculate the actual time change for the log entry
            # Since we're deducting time, the change should be negative
            actual_time_change = -total_elapsed_minutes
            
            # Create a log entry for the time deduction (points not affected)
            log_entry = LogEntry(
                kid_id=kid_id,
                time_change=actual_time_change,  # Negative value since time was deducted
                points_change=0,  # Points are not affected during time expiration
                reason="Time expired - session ended"
            )
            session.add(log_entry)
            session.add(kid)
            session.commit()
    
    # Lock the screen when time expires
    lock_screen()
    
    # Reset all session tracking
    app.state.active_kid_id = None
    app.state.session_start_time = None
    app.state.time_remaining_at_start = 0
    app.state.original_time_at_session_start = 0
    
    return {"message": "Time expired and screen locked"}


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
            "time_change": log.time_change,
            "points_change": log.points_change,
            "reason": log.reason,
            "timestamp": log.timestamp.isoformat()
        })
    
    return {"logs": logs_data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)