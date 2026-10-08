from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from bot.db import User

def jalali_date(value):
    if not value:return '-'
    if isinstance(value,str):
        import re
        match=re.search(r'(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)',value)
        if not match:return value
        try:
            jy,jm,jd=_g2j(*map(int,match.groups()))
            return value[:match.start()]+f'{jy:04d}/{jm:02d}/{jd:02d}'+value[match.end():]
        except (ValueError,IndexError):return value
    if isinstance(value,datetime):
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
        value=value.astimezone(ZoneInfo('Asia/Tehran'))
    jy,jm,jd=_g2j(value.year,value.month,value.day)
    suffix=f' {value:%H:%M}' if isinstance(value,datetime) else ''
    return f'{jy:04d}/{jm:02d}/{jd:02d}'+suffix

def _g2j(gy,gm,gd):
    gdm=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400+gd+gdm[gm-1]
    jy=-1595+33*(days//12053);days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:jy+=(days-1)//365;days=(days-1)%365
    if days<186:jm=1+days//31;jd=1+days%31
    else:jm=7+(days-186)//30;jd=1+(days-186)%30
    return jy,jm,jd

async def referrer_name(db,user):
    rid=getattr(user,'referred_by_telegram_id',None)
    if not rid:return 'بدون معرف'
    async with db.sessions() as session:
        name=await session.scalar(select(User.full_name).where(User.telegram_id==rid))
    return name or 'معرف یافت نشد'
