"""
Market Event Calendar — Risk-Level Detection for NSE Trading Days
================================================================
Detects high-risk market events to suppress or reduce bot activity:
1. NSE Trading Holidays (no trading)
2. RBI MPC Meeting Dates (high volatility days)
3. Union Budget / Economic Survey dates
4. F&O Expiry Weeks (last Thursday of each month + Wednesday before)
5. Quarterly Earnings Season peaks (Jan, Apr, Jul, Oct)
"""

import datetime
from datetime import timezone, timedelta

# NSE Holidays 2025-2026
NSE_HOLIDAYS_2025 = [
    "2025-01-14",  # Makar Sankranti
    "2025-02-19",  # Chhatrapati Shivaji Maharaj Jayanti
    "2025-03-25",  # Holi
    "2025-04-10",  # Id-Ul-Fitr (Ramadan Eid)
    "2025-04-14",  # Dr. Baba Saheb Ambedkar Jayanti / Good Friday
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Gandhi Jayanti / Dussehra
    "2025-10-20",  # Diwali Laxmi Puja
    "2025-10-21",  # Diwali Balipratipada
    "2025-11-05",  # Prakash Gurpurb
    "2025-12-25",  # Christmas
]

NSE_HOLIDAYS_2026 = [
    "2026-01-26",  # Republic Day
    "2026-03-02",  # Holi
    "2026-03-20",  # Gudi Padwa
    "2026-04-02",  # Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    "2026-11-14",  # Diwali
    "2026-12-25",  # Christmas
]

# RBI MPC Meeting dates (announce policy decisions — high volatility)
RBI_MPC_DATES_2025 = [
    "2025-02-07", "2025-04-09", "2025-06-06",
    "2025-08-08", "2025-10-08", "2025-12-05",
]

RBI_MPC_DATES_2026 = [
    "2026-02-06", "2026-04-03", "2026-06-05",
    "2026-08-07", "2026-10-02", "2026-12-04",
]

# Union Budget dates
BUDGET_DATES = [
    "2025-02-01",  # Union Budget 2025-26
    "2026-02-01",  # Union Budget 2026-27 (expected)
]


def get_ist_now():
    return datetime.datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)


def _get_fno_expiry_thursdays(year, month):
    """Returns the last Thursday of the given month (F&O expiry day)."""
    # Start at the last day of the month
    if month == 12:
        last_day = datetime.date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime.date(year, month + 1, 1) - timedelta(days=1)
        
    # Walk back to find Thursday (weekday 3 in python, Mon=0, Sun=6)
    offset = (last_day.weekday() - 3) % 7
    expiry_day = last_day - timedelta(days=offset)
    return expiry_day


def is_nse_holiday(date_str=None):
    """Returns True if date is NSE trading holiday."""
    if date_str is None:
        date_str = get_ist_now().date().isoformat()
        
    # Check weekends
    try:
        dt = datetime.date.fromisoformat(date_str)
        if dt.weekday() in (5, 6):  # Saturday or Sunday
            return True
    except Exception:
        pass
        
    return (date_str in NSE_HOLIDAYS_2025) or (date_str in NSE_HOLIDAYS_2026)


def is_fno_expiry_day(date_str=None):
    """Returns True if date is F&O expiry (last Thursday of month)."""
    if date_str is None:
        date_str = get_ist_now().date().isoformat()
    try:
        dt = datetime.date.fromisoformat(date_str)
        expiry_thurs = _get_fno_expiry_thursdays(dt.year, dt.month)
        return dt == expiry_thurs
    except Exception:
        return False


def is_fno_expiry_week(date_str=None):
    """Returns True if date is in the F&O expiry week (Wednesday to Thursday)."""
    if date_str is None:
        date_str = get_ist_now().date().isoformat()
    try:
        dt = datetime.date.fromisoformat(date_str)
        expiry_thurs = _get_fno_expiry_thursdays(dt.year, dt.month)
        
        # Expiry week is Wednesday & Thursday of that week
        expiry_wed = expiry_thurs - timedelta(days=1)
        return dt in (expiry_wed, expiry_thurs)
    except Exception:
        return False


def get_event_risk(date_str=None):
    """
    Returns risk level for the given date.
    
    Returns dict:
    {
      'level': 'HOLIDAY' | 'VERY_HIGH' | 'HIGH' | 'MEDIUM' | 'LOW',
      'events': ['RBI MPC Meeting', 'F&O Expiry Week', ...],
      'recommended_action': 'NO_TRADING' | 'HALF_SIZE' | 'REDUCE_ENTRIES' | 'NORMAL'
    }
    """
    if date_str is None:
        date_str = get_ist_now().date().isoformat()
        
    events = []
    level = 'LOW'
    action = 'NORMAL'
    
    if is_nse_holiday(date_str):
        events.append("NSE Holiday/Weekend")
        level = 'HOLIDAY'
        action = 'NO_TRADING'
        return {
            'level': level,
            'events': events,
            'recommended_action': action
        }
        
    # Check RBI MPC Meeting
    if (date_str in RBI_MPC_DATES_2025) or (date_str in RBI_MPC_DATES_2026):
        events.append("RBI MPC Policy Meeting")
        level = 'VERY_HIGH'
        action = 'HALF_SIZE'
        
    # Check Budget
    if date_str in BUDGET_DATES:
        events.append("Union Budget Day")
        level = 'VERY_HIGH'
        action = 'NO_TRADING'
        
    # Check F&O Expiry Day / Week
    if is_fno_expiry_day(date_str):
        events.append("Monthly F&O Expiry Day")
        if level != 'VERY_HIGH':
            level = 'HIGH'
            action = 'REDUCE_ENTRIES'
    elif is_fno_expiry_week(date_str):
        events.append("F&O Expiry Week Pressure")
        if level not in ('VERY_HIGH', 'HIGH'):
            level = 'MEDIUM'
            action = 'REDUCE_ENTRIES'
            
    # Check earnings season peaks
    # Jan 15-30, Apr 15-30, Jul 15-30, Oct 15-30
    try:
        dt = datetime.date.fromisoformat(date_str)
        if dt.month in (1, 4, 7, 10) and 15 <= dt.day <= 30:
            events.append("Earnings Season Peak")
            if level not in ('VERY_HIGH', 'HIGH'):
                level = 'MEDIUM'
                action = 'NORMAL'
    except Exception:
        pass
        
    return {
        'level': level,
        'events': events,
        'recommended_action': action
    }
