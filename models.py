from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
import hashlib
from datetime import date


class Kid(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    current_minutes: int = Field(default=0)  # Min: -5
    daily_bonus_used: int = Field(default=0)  # Max: 15 per day
    last_reset_date: str = Field(default="")  # Format: "YYYY-MM-DD"
    
    def reset_daily_bonus_if_needed(self):
        """Reset daily bonus if the last reset date is not today"""
        today = str(date.today())
        if self.last_reset_date != today:
            self.daily_bonus_used = 0
            self.last_reset_date = today
    
    def deduct_time(self, seconds_to_deduct: int = 10):
        """Deduct time from kid's balance, using main time first, then daily bonus if needed"""
        minutes_to_deduct = seconds_to_deduct / 60
        
        # First, try to deduct from main time if available
        if self.current_minutes > 0:
            self.current_minutes = max(-5, self.current_minutes - minutes_to_deduct)
        else:
            # If main time is exhausted, deduct from daily bonus
            self.daily_bonus_used = min(15, self.daily_bonus_used + minutes_to_deduct)


class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kid_id: int
    minutes_changed: int  # Positive = reward, negative = penalty
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AdminConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    admin_password: str = Field(default="admin")  # Default password