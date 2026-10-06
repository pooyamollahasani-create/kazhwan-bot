import asyncio, logging, html, io, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from bot.db import Base, Activity, Trip, User, BtcMembership, TripParticipant

log=logging.getLogger(__name__)
IR=ZoneInfo("Asia/Tehran")
CAP,PRICE,DISC,DEADLINE,EXECUTE,CANCEL_HOURS,CANCEL_POINTS,PAY_ACCOUNT,PAY_NAME=range(700,709)

class PrebookingSettings(Base):
    __tablename__="prebooking_settings"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    capacity:Mapped[int]=mapped_column(Integer,default=0)
    regular_price:Mapped[int]=mapped_column(BigInteger,default=0)
    early_discount:Mapped[int]=mapped_column(BigInteger,default=0)
    deadline_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    execution_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    cancel_hours:Mapped[int]=mapped_column(Integer,default=0)
    cancel_from_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    payment_recipient:Mapped[str]=mapped_column(String(255),default="")
    payment_account:Mapped[str]=mapped_column(String(255),default="")
    cancel_points:Mapped[int]=mapped_column(Integer,default=0)
    waitlist:Mapped[bool]=mapped_column(Boolean,default=True)
    show_names:Mapped[bool]=mapped_column(Boolean,default=True)
    chat_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    message_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)

class PrebookingGroup(Base):
    __tablename__="prebooking_groups"
    chat_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    title:Mapped[str]=mapped_column(String(255),default="")
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class PrebookingPublication(Base):
    __tablename__="prebooking_publications"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    chat_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    message_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class Prebooking(Base):
    __tablename__="prebookings"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    telegram_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    status:Mapped[str]=mapped_column(String(20),default="prebooked")
    price_snapshot:Mapped[int]=mapped_column(BigInteger,default=0)
    discount_snapshot:Mapped[int]=mapped_column(BigInteger,default=0)
    penalty_points:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class PrebookingReceipt(Base):
    __tablename__="prebooking_receipts"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    trip_id:Mapped[int]=mapped_column(Integer,index=True)
    telegram_id:Mapped[int]=mapped_column(BigInteger,index=True)
    file_id:Mapped[str]=mapped_column(String(255))
    status:Mapped[str]=mapped_column(String(20),default="pending",index=True)
    submitted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    reviewed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    reviewed_by:Mapped[int|None]=mapped_column(BigInteger,nullable=True)

def admin(uid,c): return uid in c.application.bot_data["settings"].admin_ids
def money(n): return f"{int(n or 0):,} تومان"
def aware(d): return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d
def fdt(d):
    if not d:return "تعیین نشده"
    z=aware(d).astimezone(IR)
    jy,jm,jd=gregorian_to_jalali(z.year,z.month,z.day)
    return f"{jd} {JMONTHS[jm-1]} {jy} - {z:%H:%M}"

def jalali_trip_date(value):
    v=(value or "").strip()
    m=re.search(r"(20\\d{2})[-/](\\d{1,2})[-/](\\d{1,2})",v)
    if not m:return v
    gy,gm,gd=map(int,m.groups());jy,jm,jd=gregorian_to_jalali(gy,gm,gd)
    return f"{jd} {JMONTHS[jm-1]} {jy}"
def remain(d):
    if not d:return "تعیین نشده"
    sec=int((aware(d)-datetime.now(timezone.utc)).total_seconds())
    if sec<=0:return "پایان یافته"
    days,sec=divmod(sec,86400); hours=sec//3600
    return f"{days} روز و {hours} ساعت"

async def cfg(db,tid,create=False):
    async with db.sessions() as s:
        x=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one_or_none()
        if not x and create:
            x=PrebookingSettings(trip_id=tid);s.add(x);await s.commit();await s.refresh(x)
        return x

async def trip(db,tid):
    async with db.sessions() as s:return (await s.execute(select(Trip).where(Trip.id==tid))).scalar_one_or_none()

async def counts(db,tid):
    async with db.sessions() as s:
        a=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status.in_(["prebooked","confirmed"])))
        w=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status=="waitlist"))
        return int(a or 0),int(w or 0)

async def text(db,t,c):
    a,w=await counts(db,t.id); left=max(0,c.capacity-a)
    lines=[f"🧳 {t.title}",f"📅 تاریخ سفر: {jalali_trip_date(t.start_date_text)} تا {jalali_trip_date(t.end_date_text)}","",
           f"💰 قیمت اصلی: {money(c.regular_price)}"]
    if c.early_discount:
        lines += [f"🎁 تخفیف ثبت‌نام زودهنگام: {money(c.early_discount)}",
                  f"💳 قیمت پیش‌رزرو: {money(max(0,c.regular_price-c.early_discount))}"]
    lines += ["",f"⏳ مهلت پیش‌رزرو: {fdt(c.deadline_at)}",f"⏱ فرصت باقی‌مانده: {remain(c.deadline_at)}","",
              f"👥 ظرفیت کل: {c.capacity}",f"✅ ثبت‌شده: {a}",f"🪑 باقی‌مانده: {left}"]
    if w:lines.append(f"⏳ لیست انتظار: {w} نفر")
    if c.show_names:
        async with db.sessions() as s:
            names=(await s.execute(select(User.full_name).join(Prebooking,Prebooking.telegram_id==User.telegram_id)
                 .where(Prebooking.trip_id==t.id,Prebooking.status.in_(["prebooked","confirmed"])).order_by(Prebooking.created_at))).scalars().all()
        if names:lines+=["","👥 پیش‌رزروها:","، ".join(names)]
    return "\n".join(lines)

def public_kb(tid,full=False):
    label="⏳ ورود به لیست انتظار" if full else "✅ پیش‌رزرو"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label,callback_data=f"pre:join:{tid}"),
                                  InlineKeyboardButton("❌ لغو",callback_data=f"pre:cancel:{tid}")],
                                 [InlineKeyboardButton("🔄 بروزرسانی",callback_data=f"pre:refresh:{tid}")]])

async def refresh(c,tid):
    db=c.application.bot_data["db"]; x=await cfg(db,tid); t=await trip(db,tid)
    if not x or not t:return
    a,_=await counts(db,tid)
    body=await text(db,t,x); kb=public_kb(tid,a>=x.capacity and x.waitlist)
    async with db.sessions() as ss:
        pubs=(await ss.execute(select(PrebookingPublication).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True),
            PrebookingPublication.message_id.is_not(None)))).scalars().all()
    # Backward compatibility: update old single publication if it exists and was not migrated yet.
    legacy=[]
    if x.chat_id and x.message_id and not any(p.chat_id==x.chat_id for p in pubs):
        legacy=[(x.chat_id,x.message_id)]
    for chat_id,message_id in [(p.chat_id,p.message_id) for p in pubs]+legacy:
        try:
            await c.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=body,reply_markup=kb)
        except Exception as e:
            if "not modified" not in str(e).lower():log.exception("prebooking refresh chat=%s",chat_id)

async def passenger(update:Update,c:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; action,tid=q.data.split(":")[1:];tid=int(tid)
    db=c.application.bot_data["db"]; x=await cfg(db,tid);t=await trip(db,tid)
    if not x or not x.enabled or not t:await q.answer("پیش‌رزرو فعال نیست.",show_alert=True);return
    if action=="refresh":await q.answer("بروزرسانی شد");await refresh(c,tid);return
    now=datetime.now(timezone.utc)
    async with db.sessions() as s:
        u=(await s.execute(select(User).where(User.telegram_id==q.from_user.id))).scalar_one_or_none()
        if not u:
            me=await c.bot.get_me();await q.answer()
            await q.message.reply_text("برای پیش‌رزرو، ابتدا پروفایل کژوان را کامل کن. بعد از ثبت‌نام مستقیم به همین سفر برمی‌گردی.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 ثبت‌نام و ادامه پیش‌رزرو",url=f"https://t.me/{me.username}?start=prebook_{tid}")]]));return
        r=(await s.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==u.telegram_id))).scalar_one_or_none()
        if action=="join":
            if x.deadline_at and now>aware(x.deadline_at):await q.answer("مهلت تمام شده.",show_alert=True);return
            if r and r.status in ("prebooked","confirmed","waitlist"):await q.answer("قبلاً ثبت شده‌اید.",show_alert=True);return
            a=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status.in_(["prebooked","confirmed"])))
            st="prebooked" if int(a or 0)<x.capacity else "waitlist"
            if st=="waitlist" and not x.waitlist:await q.answer("ظرفیت تکمیل است.",show_alert=True);return
            p=max(0,x.regular_price-x.early_discount)
            if r:r.status=st;r.price_snapshot=p;r.discount_snapshot=x.early_discount;r.updated_at=now
            else:s.add(Prebooking(trip_id=tid,telegram_id=u.telegram_id,status=st,price_snapshot=p,discount_snapshot=x.early_discount))
            await s.commit();await q.answer("پیش‌رزرو ثبت شد." if st=="prebooked" else "وارد لیست انتظار شدید.",show_alert=True)
            if st=="prebooked":
                pay=max(0,int(x.regular_price or 0)-int(x.early_discount or 0));owner=f" به نام {x.payment_recipient}" if x.payment_recipient else ""
                account=html.escape(x.payment_account or "شماره پرداخت هنوز ثبت نشده")
                recipient=html.escape(x.payment_recipient or "")
                await c.bot.send_message(q.from_user.id,
                    f"✅ پیش‌رزرو شما برای «{html.escape(t.title)}» ثبت شد.\n\n"
                    f"💰 مبلغ قابل پرداخت: {money(pay)}\n"
                    f"🎁 تخفیف شما: {money(x.early_discount)}\n\n"
                    f"💳 شماره کارت/حساب/شبا:\n<code>{account}</code>"
                    + (f"\n👤 به نام: {recipient}" if recipient else "")
                    + "\n\nبعد از واریز، عکس رسید را همین‌جا بفرستید.",
                    parse_mode="HTML")
        else:
            if not r or r.status not in ("prebooked","confirmed","waitlist"):await q.answer("رزرو فعالی ندارید.",show_alert=True);return
            await q.answer()
            await q.message.reply_text(
                f"⚠️ با ادامه لغو، نام شما از فهرست پیش‌رزرو «{t.title}» خارج می‌شود.\nآیا از لغو مطمئن هستید؟",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ بله، لغو شود",callback_data=f"preconfirm:yes:{tid}"),
                    InlineKeyboardButton("↩️ خیر",callback_data=f"preconfirm:no:{tid}")
                ]]))
            return
            active=r.status in ("prebooked","confirmed"); penalty=0
            penalty_start=aware(x.cancel_from_at) if x.cancel_from_at else (aware(x.execution_at)-timedelta(hours=x.cancel_hours) if x.execution_at and x.cancel_hours else None)
            if active and penalty_start and x.cancel_points and now>=penalty_start:
                penalty=min(int(u.points or 0),x.cancel_points);u.points=int(u.points or 0)-penalty;r.penalty_points=penalty
                if penalty:s.add(Activity(telegram_id=u.telegram_id,activity_type="prebooking_cancel_penalty",title=f"جریمه لغو دیرهنگام {t.title}",details=f"-{penalty} امتیاز"))
            r.status="cancelled";r.updated_at=now
            if active and x.waitlist:
                nxt=(await s.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status=="waitlist").order_by(Prebooking.created_at).limit(1))).scalar_one_or_none()
                if nxt:nxt.status="prebooked";nxt.updated_at=now
            await s.commit();await q.answer("لغو شد"+(f"؛ {penalty} امتیاز جریمه شد." if penalty else "."),show_alert=True)
    await refresh(c,tid)



async def cancel_confirm(update,c):
    q=update.callback_query;z=q.data.split(":");choice=z[1];tid=int(z[2])
    if choice=="no":
        await q.answer("لغو انجام نشد.");await q.edit_message_text("↩️ پیش‌رزرو شما بدون تغییر باقی ماند.");return
    db=c.application.bot_data["db"];x=await cfg(db,tid);t=await trip(db,tid);now=datetime.now(timezone.utc)
    async with db.sessions() as ss:
        u=(await ss.execute(select(User).where(User.telegram_id==q.from_user.id))).scalar_one_or_none()
        r=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==q.from_user.id))).scalar_one_or_none()
        if not u or not r or r.status not in ("prebooked","confirmed","waitlist"):
            await q.answer("رزرو فعالی ندارید.",show_alert=True);return
        active=r.status in ("prebooked","confirmed");penalty=0
        penalty_start=aware(x.cancel_from_at) if x and x.cancel_from_at else (aware(x.execution_at)-timedelta(hours=x.cancel_hours) if x and x.execution_at and x.cancel_hours else None)
        if active and penalty_start and x.cancel_points and now>=penalty_start:
            penalty=min(int(u.points or 0),int(x.cancel_points or 0));u.points=int(u.points or 0)-penalty;r.penalty_points=penalty
            if penalty:ss.add(Activity(telegram_id=u.telegram_id,activity_type="prebooking_cancel_penalty",title=f"جریمه لغو دیرهنگام {t.title}",details=f"-{penalty} امتیاز"))
        r.status="cancelled";r.updated_at=now
        if active and x.waitlist:
            nxt=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status=="waitlist").order_by(Prebooking.created_at).limit(1))).scalar_one_or_none()
            if nxt:nxt.status="prebooked";nxt.updated_at=now
        await ss.commit()
    await q.answer("لغو شد.",show_alert=True)
    await q.edit_message_text("✅ پیش‌رزرو شما لغو شد."+ (f"\n➖ {penalty} امتیاز جریمه اعمال شد." if penalty else ""))
    await refresh(c,tid)

async def receipt_photo(update,c):
    if not update.effective_chat or update.effective_chat.type!="private" or not update.message or not update.message.photo:return
    uid=update.effective_user.id;db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        rows=(await ss.execute(select(Prebooking,Trip).join(Trip,Trip.id==Prebooking.trip_id).where(
            Prebooking.telegram_id==uid,Prebooking.status=="prebooked").order_by(Prebooking.created_at.desc()))).all()
    if not rows:return
    if len(rows)>1 and not c.user_data.get("receipt_trip_id"):
        c.user_data["pending_receipt_file_id"]=update.message.photo[-1].file_id
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(t.title[:55],callback_data=f"receipttrip:{t.id}")] for _,t in rows])
        await update.message.reply_text("این رسید مربوط به کدام سفر است؟",reply_markup=kb);return
    tid=int(c.user_data.pop("receipt_trip_id",0) or rows[0][1].id)
    await save_and_forward_receipt(update,c,tid,update.message.photo[-1].file_id)

async def receipt_trip_pick(update,c):
    q=update.callback_query;tid=int(q.data.split(":")[1]);file_id=c.user_data.pop("pending_receipt_file_id",None)
    if not file_id:await q.answer("رسید پیدا نشد؛ دوباره عکس را بفرست.",show_alert=True);return
    await q.answer();await save_and_forward_receipt(update,c,tid,file_id)

async def save_and_forward_receipt(update,c,tid,file_id):
    uid=update.effective_user.id;db=c.application.bot_data["db"];t=await trip(db,tid)
    async with db.sessions() as ss:
        pb=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==uid,Prebooking.status=="prebooked"))).scalar_one_or_none()
        u=(await ss.execute(select(User).where(User.telegram_id==uid))).scalar_one_or_none()
        if not pb or not u:
            await update.effective_message.reply_text("برای این سفر پیش‌رزرو در انتظار پرداخت پیدا نشد.");return
        rec=PrebookingReceipt(trip_id=tid,telegram_id=uid,file_id=file_id,status="pending");ss.add(rec);await ss.commit();await ss.refresh(rec)
        amount=pb.price_snapshot
    await update.effective_message.reply_text("✅ رسید دریافت شد و برای بررسی ادمین ارسال شد.")
    caption=f"🧾 رسید پرداخت جدید\n\n👤 {u.full_name}\n📱 {u.phone}\n🧳 {t.title}\n💰 مبلغ مورد انتظار: {money(amount)}"
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید پرداخت",callback_data=f"receipt:approve:{rec.id}"),
                              InlineKeyboardButton("❌ رد رسید",callback_data=f"receipt:reject:{rec.id}")]])
    for aid in c.application.bot_data["settings"].admin_ids:
        try:await c.bot.send_photo(chat_id=aid,photo=file_id,caption=caption,reply_markup=kb)
        except Exception:log.exception("send receipt to admin=%s",aid)

async def receipt_review(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    _,act,rid=q.data.split(":");rid=int(rid);db=c.application.bot_data["db"];now=datetime.now(timezone.utc)
    async with db.sessions() as ss:
        rec=(await ss.execute(select(PrebookingReceipt).where(PrebookingReceipt.id==rid))).scalar_one_or_none()
        if not rec:await q.answer("رسید پیدا نشد.",show_alert=True);return
        if rec.status!="pending":await q.answer("این رسید قبلاً بررسی شده.",show_alert=True);return
        pb=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==rec.trip_id,Prebooking.telegram_id==rec.telegram_id))).scalar_one_or_none()
        t=(await ss.execute(select(Trip).where(Trip.id==rec.trip_id))).scalar_one_or_none()
        u=(await ss.execute(select(User).where(User.telegram_id==rec.telegram_id))).scalar_one_or_none()
        rec.status="approved" if act=="approve" else "rejected";rec.reviewed_at=now;rec.reviewed_by=q.from_user.id
        if act=="approve" and pb and pb.status=="prebooked":pb.status="confirmed";pb.updated_at=now
        await ss.commit()
    if act=="approve":
        await q.answer("پرداخت تأیید شد.");await q.edit_message_caption(caption=(q.message.caption or "")+"\n\n✅ پرداخت تأیید شد.")
        try:await c.bot.send_message(rec.telegram_id,f"✅ پرداخت شما برای «{t.title}» تأیید شد.\nوضعیت رزرو: 🟢 رزرو قطعی")
        except Exception:log.exception("notify approved receipt")
        await refresh(c,rec.trip_id)
    else:
        await q.answer("رسید رد شد.");await q.edit_message_caption(caption=(q.message.caption or "")+"\n\n❌ رسید تأیید نشد.")
        try:await c.bot.send_message(rec.telegram_id,f"❌ رسید پرداخت شما برای «{t.title}» تأیید نشد.\nدر صورت نیاز، تصویر رسید صحیح را دوباره همین‌جا ارسال کنید.")
        except Exception:log.exception("notify rejected receipt")

async def export_confirmed(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();tid=int(q.data.split(":")[2]);db=c.application.bot_data["db"];t=await trip(db,tid)
    async with db.sessions() as ss:
        rows=(await ss.execute(select(Prebooking,User).join(User,User.telegram_id==Prebooking.telegram_id).where(
            Prebooking.trip_id==tid,Prebooking.status=="confirmed").order_by(Prebooking.updated_at))).all()
        receipt_rows=(await ss.execute(select(PrebookingReceipt).where(
            PrebookingReceipt.trip_id==tid,PrebookingReceipt.status=="approved"))).scalars().all()
        btc_rows=(await ss.execute(select(BtcMembership))).scalars().all()
    latest={}
    for r in receipt_rows:
        if r.telegram_id not in latest or (r.reviewed_at or r.submitted_at)>(latest[r.telegram_id].reviewed_at or latest[r.telegram_id].submitted_at):latest[r.telegram_id]=r
    btc={b.telegram_id:b.btc_code for b in btc_rows}
    out=io.StringIO();out.write("\ufeffنام و نام خانوادگی,موبایل,KZH,BTC,مبلغ پرداختی,تخفیف,تاریخ پیش‌رزرو,تاریخ تأیید,ادمین تأییدکننده\n")
    def esc(v):return '"'+str(v or "").replace('"','""')+'"'
    for pb,u in rows:
        rr=latest.get(u.telegram_id)
        vals=[u.full_name,u.phone,u.member_code,btc.get(u.telegram_id),pb.price_snapshot,pb.discount_snapshot,fdt(pb.created_at),fdt(rr.reviewed_at) if rr else "",rr.reviewed_by if rr else ""]
        out.write(",".join(esc(v) for v in vals)+"\n")
    data=out.getvalue().encode("utf-8")
    await q.message.reply_document(document=InputFile(io.BytesIO(data),filename=f"confirmed_prebookings_{tid}.csv"),
        caption=f"📊 رزروهای قطعی — {t.title}\nتعداد: {len(rows)}")


JMONTHS=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
JWD=["ش","ی","د","س","چ","پ","ج"]

def gregorian_to_jalali(gy,gm,gd):
    gdm=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400+gd+gdm[gm-1]
    jy=-1595+33*(days//12053);days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:
        jy+=(days-1)//365;days=(days-1)%365
    if days<186:
        jm=1+days//31;jd=1+days%31
    else:
        jm=7+(days-186)//30;jd=1+(days-186)%30
    return jy,jm,jd

def jalali_to_gregorian(jy,jm,jd):
    jy+=1595
    days=-355668+365*jy+(jy//33)*8+((jy%33)+3)//4+jd
    days+=(jm-1)*31 if jm<7 else (jm-7)*30+186
    gy=400*(days//146097);days%=146097
    if days>36524:
        gy+=100*((days-1)//36524);days=(days-1)%36524
        if days>=365:days+=1
    gy+=4*(days//1461);days%=1461
    if days>365:
        gy+=(days-1)//365;days=(days-1)%365
    gd=days+1
    leap=(gy%4==0 and gy%100!=0) or gy%400==0
    sal=[0,31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31]
    gm=1
    while gm<=12 and gd>sal[gm]:
        gd-=sal[gm];gm+=1
    return gy,gm,gd

def jmonth_days(jy,jm):
    if jm<=6:return 31
    if jm<=11:return 30
    gy1,gm1,gd1=jalali_to_gregorian(jy,1,1)
    gy2,gm2,gd2=jalali_to_gregorian(jy+1,1,1)
    return 30 if (datetime(gy2,gm2,gd2)-datetime(gy1,gm1,gd1)).days==366 else 29

def cal_kb(tid,kind,jy,jm):
    rows=[[InlineKeyboardButton("◀️",callback_data=f"pc:nav:{tid}:{kind}:{jy}:{jm}:-1"),
           InlineKeyboardButton(f"{JMONTHS[jm-1]} {jy}",callback_data="pc:none"),
           InlineKeyboardButton("▶️",callback_data=f"pc:nav:{tid}:{kind}:{jy}:{jm}:1")]]
    rows.append([InlineKeyboardButton(x,callback_data="pc:none") for x in JWD])
    gy,gm,gd=jalali_to_gregorian(jy,jm,1)
    # Python weekday Mon=0; Persian calendar Saturday=0
    offset=(datetime(gy,gm,gd).weekday()+2)%7
    cells=[None]*offset+list(range(1,jmonth_days(jy,jm)+1))
    while len(cells)%7:cells.append(None)
    for i in range(0,len(cells),7):
        rows.append([InlineKeyboardButton(" " if d is None else str(d),
            callback_data="pc:none" if d is None else f"pc:day:{tid}:{kind}:{jy}:{jm}:{d}") for d in cells[i:i+7]])
    rows.append([InlineKeyboardButton("❌ انصراف",callback_data=f"pc:cancel:{tid}:{kind}")])
    return InlineKeyboardMarkup(rows)

def hour_kb(tid,kind,jy,jm,jd):
    rows=[]
    for start in range(0,24,4):
        rows.append([InlineKeyboardButton(f"{h:02d}:00",callback_data=f"pc:hour:{tid}:{kind}:{jy}:{jm}:{jd}:{h}") for h in range(start,start+4)])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به تقویم",callback_data=f"pc:back:{tid}:{kind}:{jy}:{jm}")])
    return InlineKeyboardMarkup(rows)

def minute_kb(tid,kind,jy,jm,jd,h):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{h:02d}:{m:02d}",callback_data=f"pc:min:{tid}:{kind}:{jy}:{jm}:{jd}:{h}:{m}") for m in (0,15,30,45)
    ],[InlineKeyboardButton("⬅️ انتخاب ساعت",callback_data=f"pc:day:{tid}:{kind}:{jy}:{jm}:{jd}")]])

async def calendar_start(q,tid,kind):
    now=datetime.now(IR);jy,jm,jd=gregorian_to_jalali(now.year,now.month,now.day)
    title={"deadline":"مهلت پیش‌رزرو","execute":"زمان اجرای سفر","penalty":"شروع بازه جریمه"}[kind]
    await q.message.reply_text(f"📅 {title}\nتاریخ شمسی را انتخاب کن:",reply_markup=cal_kb(tid,kind,jy,jm))

async def calendar_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer()
    z=q.data.split(":");act=z[1]
    if act=="none":return
    tid=int(z[2]);kind=z[3]
    if act=="cancel":
        await q.edit_message_text("❌ انتخاب تاریخ لغو شد.");return
    if act=="nav":
        jy,jm,delta=map(int,z[4:7]);jm+=delta
        if jm<1:jy-=1;jm=12
        if jm>12:jy+=1;jm=1
        await q.edit_message_reply_markup(reply_markup=cal_kb(tid,kind,jy,jm));return
    if act=="back":
        jy,jm=map(int,z[4:6]);await q.edit_message_text("📅 تاریخ شمسی را انتخاب کن:",reply_markup=cal_kb(tid,kind,jy,jm));return
    if act=="day":
        jy,jm,jd=map(int,z[4:7]);await q.edit_message_text(f"📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 ساعت را انتخاب کن:",reply_markup=hour_kb(tid,kind,jy,jm,jd));return
    if act=="hour":
        jy,jm,jd,h=map(int,z[4:8]);await q.edit_message_text(f"📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 دقیقه را انتخاب کن:",reply_markup=minute_kb(tid,kind,jy,jm,jd,h));return
    if act=="min":
        jy,jm,jd,h,m=map(int,z[4:9]);gy,gm,gd=jalali_to_gregorian(jy,jm,jd)
        local=datetime(gy,gm,gd,h,m,tzinfo=IR);utc=local.astimezone(timezone.utc)
        db=c.application.bot_data["db"]
        async with db.sessions() as ss:
            x=(await ss.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            setattr(x,{"deadline":"deadline_at","execute":"execution_at","penalty":"cancel_from_at"}[kind],utc);await ss.commit()
        label={"deadline":"مهلت پیش‌رزرو","execute":"زمان اجرای سفر","penalty":"شروع بازه جریمه"}[kind]
        await q.edit_message_text(f"✅ {label} ذخیره شد:\n📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 {h:02d}:{m:02d}")
        await refresh(c,tid)

def akb(tid,x):
    return InlineKeyboardMarkup([
      [InlineKeyboardButton(("🟢" if x.enabled else "⚪")+" فعال/غیرفعال",callback_data=f"pa:toggle:{tid}")],
      [InlineKeyboardButton("👥 ظرفیت",callback_data=f"pa:cap:{tid}"),InlineKeyboardButton("💰 قیمت",callback_data=f"pa:price:{tid}")],
      [InlineKeyboardButton("🎁 تخفیف تومانی",callback_data=f"pa:disc:{tid}"),InlineKeyboardButton("⏳ مهلت پیش‌رزرو",callback_data=f"pa:deadline:{tid}")],
      [InlineKeyboardButton("🚌 زمان اجرای سفر",callback_data=f"pa:execute:{tid}")],
      [InlineKeyboardButton("📅 شروع بازه جریمه",callback_data=f"pa:penaltydate:{tid}"),InlineKeyboardButton("➖ امتیاز جریمه",callback_data=f"pa:cp:{tid}")],
      [InlineKeyboardButton("💳 شماره پرداخت",callback_data=f"pa:payaccount:{tid}"),InlineKeyboardButton("👤 صاحب حساب",callback_data=f"pa:payname:{tid}")],
      [InlineKeyboardButton(("🟢" if x.waitlist else "⚪")+" لیست انتظار",callback_data=f"pa:wait:{tid}"),
       InlineKeyboardButton(("🟢" if x.show_names else "⚪")+" نمایش اسامی",callback_data=f"pa:names:{tid}")],
      [InlineKeyboardButton("📣 گروه‌های انتشار پیش‌رزرو",callback_data=f"pa:publish:{tid}")],
      [InlineKeyboardButton("➕ افزودن دستی مسافر",callback_data=f"pa:add:{tid}")],
      [InlineKeyboardButton("👥 مشاهده پیش‌رزروها",callback_data=f"pa:list:{tid}")],
      [InlineKeyboardButton("📊 اکسل رزروهای قطعی",callback_data=f"pexport:confirmed:{tid}")]])

async def panel(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();tid=int(q.data.split(":")[-1]);db=c.application.bot_data["db"];x=await cfg(db,tid,True);t=await trip(db,tid);a,w=await counts(db,tid)
    await q.message.reply_text(f"🎟 تنظیمات پیش‌رزرو — {t.title}\n\nوضعیت: {'فعال' if x.enabled else 'غیرفعال'}\nظرفیت: {x.capacity} | ثبت: {a} | انتظار: {w}\nقیمت: {money(x.regular_price)}\nتخفیف: {money(x.early_discount)}\nمهلت: {fdt(x.deadline_at)}\nاجرای سفر: {fdt(x.execution_at)}\nشروع بازه جریمه: {fdt(x.cancel_from_at)}\nجریمه: {x.cancel_points} امتیاز",reply_markup=akb(tid,x))

async def register_prebooking_group(update,c):
    if not admin(update.effective_user.id,c):return
    chat=update.effective_chat
    if not chat or chat.type not in ("group","supergroup"):
        await update.effective_message.reply_text("این دستور را داخل گروهی بزن که می‌خواهی پیش‌رزروها در آن قابل انتشار باشد.");return
    db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        g=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.chat_id==chat.id))).scalar_one_or_none()
        if g:g.title=chat.title or str(chat.id);g.active=True;g.updated_at=datetime.now(timezone.utc)
        else:ss.add(PrebookingGroup(chat_id=chat.id,title=chat.title or str(chat.id),active=True))
        await ss.commit()
    await update.effective_message.reply_text("✅ این گروه به مقصدهای انتشار پیش‌رزرو اضافه شد.\nاز این به بعد در پنل هر سفر می‌توانی انتخابش کنی.")

async def publication_picker(q,c,tid):
    db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        groups=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.active.is_(True)).order_by(PrebookingGroup.title))).scalars().all()
        selected=set((await ss.execute(select(PrebookingPublication.chat_id).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all())
    if not groups:
        await q.message.reply_text("هنوز هیچ گروهی برای انتشار پیش‌رزرو ثبت نشده.\n\nداخل هر گروه موردنظر یک‌بار دستور /prebookinggroup را بزن، بعد برگرد اینجا.");return
    rows=[]
    for g in groups:
        mark="✅" if g.chat_id in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {g.title}"[:60],callback_data=f"ppub:toggle:{tid}:{g.chat_id}")])
    rows += [[InlineKeyboardButton("📣 انتشار / بروزرسانی در گروه‌های انتخاب‌شده",callback_data=f"ppub:send:{tid}")],
             [InlineKeyboardButton("🗑 حذف پیام از گروه‌های ازانتخاب‌خارج‌شده",callback_data=f"ppub:cleanup:{tid}")]]
    await q.message.reply_text("📣 گروه‌های انتشار پیش‌رزرو\n\nیک یا چند گروه را انتخاب کن. این بخش مستقل از «ثبت سفرهای من» است.",reply_markup=InlineKeyboardMarkup(rows))

async def publication_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");act=z[1];tid=int(z[2]);db=c.application.bot_data["db"]
    if act=="toggle":
        chat_id=int(z[3])
        async with db.sessions() as ss:
            pub=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.chat_id==chat_id))).scalar_one_or_none()
            if pub:pub.active=not pub.active
            else:ss.add(PrebookingPublication(trip_id=tid,chat_id=chat_id,active=True))
            await ss.commit()
        await q.edit_message_reply_markup(reply_markup=(await _publication_keyboard(db,tid)));return
    if act=="send":
        x=await cfg(db,tid);t=await trip(db,tid)
        if not x.enabled or x.capacity<=0:
            await q.answer("اول پیش‌رزرو را فعال و ظرفیت را تعیین کن.",show_alert=True);return
        aa,_=await counts(db,tid);body=await text(db,t,x);kb=public_kb(tid,aa>=x.capacity and x.waitlist)
        async with db.sessions() as ss:
            pubs=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all()
            if not pubs:
                await q.answer("حداقل یک گروه انتخاب کن.",show_alert=True);return
            ok=0;failed=0
            for pub in pubs:
                try:
                    if pub.message_id:
                        try:
                            await c.bot.edit_message_text(chat_id=pub.chat_id,message_id=pub.message_id,text=body,reply_markup=kb)
                        except Exception as e:
                            if "not modified" not in str(e).lower(): raise
                    else:
                        m=await c.bot.send_message(pub.chat_id,body,reply_markup=kb);pub.message_id=m.message_id
                    ok+=1
                except Exception:
                    failed+=1;log.exception("publish prebooking chat=%s",pub.chat_id)
            await ss.commit()
        await q.answer(f"انجام شد: {ok} گروه" + (f" | خطا: {failed}" if failed else ""),show_alert=True);return
    if act=="cleanup":
        async with db.sessions() as ss:
            pubs=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(False),
                PrebookingPublication.message_id.is_not(None)))).scalars().all()
            removed=0
            for pub in pubs:
                try:await c.bot.delete_message(pub.chat_id,pub.message_id);removed+=1
                except Exception:log.exception("delete prebooking publication chat=%s",pub.chat_id)
                pub.message_id=None
            await ss.commit()
        await q.answer(f"{removed} پیام حذف شد.",show_alert=True)

async def _publication_keyboard(db,tid):
    async with db.sessions() as ss:
        groups=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.active.is_(True)).order_by(PrebookingGroup.title))).scalars().all()
        selected=set((await ss.execute(select(PrebookingPublication.chat_id).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all())
    rows=[[InlineKeyboardButton(f"{'✅' if g.chat_id in selected else '⬜'} {g.title}"[:60],callback_data=f"ppub:toggle:{tid}:{g.chat_id}")] for g in groups]
    rows += [[InlineKeyboardButton("📣 انتشار / بروزرسانی در گروه‌های انتخاب‌شده",callback_data=f"ppub:send:{tid}")],
             [InlineKeyboardButton("🗑 حذف پیام از گروه‌های ازانتخاب‌خارج‌شده",callback_data=f"ppub:cleanup:{tid}")]]
    return InlineKeyboardMarkup(rows)

async def action(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return ConversationHandler.END
    await q.answer();_,a,tid=q.data.split(":");tid=int(tid);db=c.application.bot_data["db"];x=await cfg(db,tid,True)
    if a in ("toggle","wait","names"):
        async with db.sessions() as s:
            z=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            attr={"toggle":"enabled","wait":"waitlist","names":"show_names"}[a];setattr(z,attr,not getattr(z,attr));await s.commit()
        await q.message.reply_text("✅ تغییر کرد.");await refresh(c,tid);return ConversationHandler.END
    if a in ("deadline","execute","penaltydate"):
        await calendar_start(q,tid,"penalty" if a=="penaltydate" else a)
        return ConversationHandler.END
    states={"cap":CAP,"price":PRICE,"disc":DISC,"cp":CANCEL_POINTS,"payaccount":PAY_ACCOUNT,"payname":PAY_NAME}
    if a in states:
        c.user_data["pre_tid"]=tid;c.user_data["pre_state"]=states[a]
        prompts={"cap":"ظرفیت کل؟ فقط عدد","price":"قیمت اصلی به تومان؟ فقط عدد","disc":"تخفیف پیش‌رزرو به تومان؟ فقط عدد","cp":"جریمه چند امتیاز باشد؟","payaccount":"شماره کارت/حساب/شبا برای پرداخت را بفرست:","payname":"نام صاحب حساب را بفرست:"}
        await q.message.reply_text(prompts[a]);return states[a]
    if a=="add":
        return await preadd_start(update,c)
    if a=="publish":
        await publication_picker(q,c,tid);return ConversationHandler.END
    if a=="list":
        async with db.sessions() as s:
            rows=(await s.execute(select(User.full_name,Prebooking.status,Prebooking.price_snapshot,Prebooking.discount_snapshot).join(Prebooking,Prebooking.telegram_id==User.telegram_id).where(Prebooking.trip_id==tid).order_by(Prebooking.created_at))).all()
        lab={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 قطعی","waitlist":"⏳ انتظار","cancelled":"⚪ لغو"}
        if not rows:
            await q.message.reply_text("هنوز کسی ثبت نشده.");return ConversationHandler.END
        async with db.sessions() as ss:
            rr=(await ss.execute(select(User.telegram_id,User.full_name,Prebooking.status).join(Prebooking,Prebooking.telegram_id==User.telegram_id).where(Prebooking.trip_id==tid).order_by(Prebooking.created_at))).all()
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"{lab.get(st,st)} | {name}"[:60],callback_data=f"pview:person:{tid}:{uid}")] for uid,name,st in rr])
        await q.message.reply_text("👥 پیش‌رزروها — برای تغییر وضعیت روی نام بزن:",reply_markup=kb)
    return ConversationHandler.END

async def value(update,c):
    st=c.user_data["pre_state"];tid=c.user_data["pre_tid"];v=(update.message.text or "").strip();db=c.application.bot_data["db"]
    try:
        async with db.sessions() as s:
            x=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            if st in (DEADLINE,EXECUTE):
                d=datetime.strptime(v,"%Y-%m-%d %H:%M").replace(tzinfo=IR).astimezone(timezone.utc);setattr(x,"deadline_at" if st==DEADLINE else "execution_at",d)
            elif st in (PAY_ACCOUNT,PAY_NAME):
                if not v:raise ValueError()
                setattr(x,{PAY_ACCOUNT:"payment_account",PAY_NAME:"payment_recipient"}[st],v)
            else:
                n=int(v.replace(",","").replace("٬",""));assert n>=0
                setattr(x,{CAP:"capacity",PRICE:"regular_price",DISC:"early_discount",CANCEL_HOURS:"cancel_hours",CANCEL_POINTS:"cancel_points"}[st],n)
            await s.commit()
        await update.message.reply_text("✅ ذخیره شد.");await refresh(c,tid);return ConversationHandler.END
    except Exception:
        await update.message.reply_text("فرمت درست نیست؛ دوباره وارد کن.");return st

async def mine(update,c):
    db=c.application.bot_data["db"]
    async with db.sessions() as s:
        rows=(await s.execute(select(Prebooking,Trip).join(Trip,Trip.id==Prebooking.trip_id).where(Prebooking.telegram_id==update.effective_user.id,Prebooking.status.in_(["prebooked","confirmed","waitlist"])).order_by(Prebooking.created_at.desc()))).all()
    if not rows:await update.message.reply_text("در حال حاضر پیش‌رزرو فعالی ندارید.");return
    lab={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 قطعی","waitlist":"⏳ انتظار"};lines=["📝 ثبت‌نام‌های من",""]
    for r,t in rows:lines += [f"{lab.get(r.status,r.status)} — {t.title}",f"💳 مبلغ: {money(r.price_snapshot)}",f"🎁 تخفیف: {money(r.discount_snapshot)}",""]
    await update.message.reply_text("\n".join(lines))

async def preadd_start(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();tid=int(q.data.split(":")[2])
    c.user_data["preadd_tid"]=tid;c.user_data["preadd_waiting"]=True
    await q.message.reply_text("🔎 نام، شماره موبایل، KZH، BTC یا Telegram ID مسافر را وارد کن:")

async def preadd_search(update,c):
    if not admin(update.effective_user.id,c) or not c.user_data.get("preadd_waiting"):return
    value=(update.message.text or "").strip();db=c.application.bot_data["db"];tid=int(c.user_data["preadd_tid"])
    users=await db.search_users(value,limit=10)
    if not users:
        await update.message.reply_text("مسافری پیدا نشد. دوباره جستجو کن.");return
    rows=[[InlineKeyboardButton(f"{u.full_name} | {u.phone}"[:60],callback_data=f"padd:pick:{tid}:{u.telegram_id}")] for u in users]
    rows.append([InlineKeyboardButton("❌ لغو",callback_data=f"padd:cancel:{tid}")])
    await update.message.reply_text("مسافر را انتخاب کن:",reply_markup=InlineKeyboardMarkup(rows))

async def preadd_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");act=z[1];tid=int(z[2]);db=c.application.bot_data["db"]
    if act=="cancel":
        c.user_data.pop("preadd_waiting",None);c.user_data.pop("preadd_tid",None);await q.edit_message_text("لغو شد.");return
    uid=int(z[3])
    if act=="pick":
        u=await db.get_user(uid)
        await q.edit_message_text(f"👤 {u.full_name}\nوضعیت موردنظر را انتخاب کن:",reply_markup=InlineKeyboardMarkup([
          [InlineKeyboardButton("🟡 پیش‌رزرو",callback_data=f"padd:set:{tid}:{uid}:prebooked"),
           InlineKeyboardButton("🟢 رزرو قطعی",callback_data=f"padd:set:{tid}:{uid}:confirmed")],
          [InlineKeyboardButton("⏳ لیست انتظار",callback_data=f"padd:set:{tid}:{uid}:waitlist"),
           InlineKeyboardButton("⚪ لغو",callback_data=f"padd:set:{tid}:{uid}:cancelled")]]));return
    if act=="set":
        status=z[4];x=await cfg(db,tid,True)
        async with db.sessions() as ss:
            r=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==uid))).scalar_one_or_none()
            price=max(0,x.regular_price-x.early_discount)
            if r:r.status=status;r.updated_at=datetime.now(timezone.utc)
            else:ss.add(Prebooking(trip_id=tid,telegram_id=uid,status=status,price_snapshot=price,discount_snapshot=x.early_discount))
            await ss.commit()
        c.user_data.pop("preadd_waiting",None);c.user_data.pop("preadd_tid",None)
        u=await db.get_user(uid);labels={"prebooked":"پیش‌رزرو","confirmed":"رزرو قطعی","waitlist":"لیست انتظار","cancelled":"لغو"}
        await q.edit_message_text(f"✅ {u.full_name} با وضعیت «{labels[status]}» ثبت شد.")
        await refresh(c,tid)

async def preperson_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");tid=int(z[2]);uid=int(z[3]);db=c.application.bot_data["db"];u=await db.get_user(uid)
    await q.message.reply_text(f"👤 {u.full_name}\nوضعیت جدید:",reply_markup=InlineKeyboardMarkup([
      [InlineKeyboardButton("🟡 پیش‌رزرو",callback_data=f"padd:set:{tid}:{uid}:prebooked"),InlineKeyboardButton("🟢 قطعی",callback_data=f"padd:set:{tid}:{uid}:confirmed")],
      [InlineKeyboardButton("⏳ انتظار",callback_data=f"padd:set:{tid}:{uid}:waitlist"),InlineKeyboardButton("⚪ لغو",callback_data=f"padd:set:{tid}:{uid}:cancelled")]]))

def flow():
    return ConversationHandler(entry_points=[CallbackQueryHandler(panel,pattern=r"^pa:view:\d+$"),CallbackQueryHandler(action,pattern=r"^pa:(toggle|wait|names|publish|list|cap|price|disc|deadline|execute|penaltydate|cp|payaccount|payname|add|pick|status):\d+(?::[^:]+)?$")],
      states={CAP:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],DISC:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],CANCEL_HOURS:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],CANCEL_POINTS:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PAY_ACCOUNT:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PAY_NAME:[MessageHandler(filters.TEXT&~filters.COMMAND,value)]},fallbacks=[],allow_reentry=True)

async def loop(app):
    while True:
        try:
            db=app.bot_data["db"]
            async with db.sessions() as s:ids=(await s.execute(select(PrebookingPublication.trip_id).join(PrebookingSettings,PrebookingSettings.trip_id==PrebookingPublication.trip_id).where(PrebookingSettings.enabled.is_(True),PrebookingPublication.active.is_(True),PrebookingPublication.message_id.is_not(None)).distinct())).scalars().all()
            ctx=type("C",(),{"application":app,"bot":app.bot})()
            for tid in ids:await refresh(ctx,tid)

            # رزرو قطعی + رسید تاییدشده + رسیدن زمان اجرای سفر
            # => ثبت خودکار مسافر به عنوان «شرکت کرده» در سفرهای من.
            now=datetime.now(timezone.utc)
            async with db.sessions() as s:
                due=(await s.execute(
                    select(Prebooking.trip_id,Prebooking.telegram_id)
                    .join(PrebookingSettings,PrebookingSettings.trip_id==Prebooking.trip_id)
                    .join(PrebookingReceipt,
                          (PrebookingReceipt.trip_id==Prebooking.trip_id) &
                          (PrebookingReceipt.telegram_id==Prebooking.telegram_id))
                    .where(
                        Prebooking.status=="confirmed",
                        PrebookingReceipt.status=="approved",
                        PrebookingSettings.execution_at.is_not(None),
                        PrebookingSettings.execution_at<=now
                    ).distinct()
                )).all()
            for tid,uid in due:
                async with db.sessions() as s:
                    participant=(await s.execute(select(TripParticipant).where(
                        TripParticipant.trip_id==tid,
                        TripParticipant.telegram_id==uid
                    ))).scalar_one_or_none()
                if participant and participant.status=="attended":
                    continue
                await db.register_trip_participant(tid,uid)
                await db.set_trip_participant_status(tid,uid,"attended")
                try:
                    t=await db.get_trip(tid)
                    await app.bot.send_message(uid,
                        f"✅ سفر «{t.title if t else 'کژوان'}» به‌صورت خودکار در تاریخچه سفرهای شما به عنوان «شرکت کرده» ثبت شد.")
                except Exception:
                    log.exception("auto attendance notification trip=%s user=%s",tid,uid)
        except Exception:log.exception("prebooking timer")
        await asyncio.sleep(3600)

async def initialize_prebooking(app):
    from sqlalchemy import text as sql_text
    async with app.bot_data["db"].engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS cancel_from_at TIMESTAMPTZ"))
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS payment_recipient VARCHAR(255) DEFAULT ''"))
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS payment_account VARCHAR(255) DEFAULT ''"))
        await conn.execute(sql_text("""
            INSERT INTO prebooking_publications (trip_id, chat_id, message_id, active, created_at)
            SELECT trip_id, chat_id, message_id, TRUE, NOW()
            FROM prebooking_settings
            WHERE chat_id IS NOT NULL AND message_id IS NOT NULL
            ON CONFLICT (trip_id, chat_id) DO NOTHING
        """))
    asyncio.create_task(loop(app))

async def profile_prebookings(update,c):
    q=update.callback_query
    await q.answer()
    db=c.application.bot_data["db"];uid=q.from_user.id
    async with db.sessions() as ss:
        rows=(await ss.execute(select(Prebooking,Trip).join(Trip,Trip.id==Prebooking.trip_id).where(
            Prebooking.telegram_id==uid,Prebooking.status.in_(["prebooked","confirmed","waitlist"])
        ).order_by(Prebooking.created_at.desc()))).all()
        receipts=(await ss.execute(select(PrebookingReceipt).where(
            PrebookingReceipt.telegram_id==uid).order_by(PrebookingReceipt.submitted_at.desc()))).scalars().all()
    if not rows:
        await q.message.reply_text("🎟 پیش‌رزروهای من\n\nدر حال حاضر پیش‌رزرو فعالی ندارید.");return
    latest={}
    for rr in receipts:
        if rr.trip_id not in latest:latest[rr.trip_id]=rr
    status_label={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 رزرو قطعی","waitlist":"⏳ لیست انتظار"}
    receipt_label={"pending":"⏳ رسید در حال بررسی","approved":"✅ پرداخت تأیید شده","rejected":"❌ رسید رد شده"}
    rows_kb=[]
    for pb,t in rows:
        rr=latest.get(t.id)
        pay_state=receipt_label.get(rr.status,"💳 در انتظار پرداخت") if rr else "💳 در انتظار پرداخت"
        rows_kb.append([InlineKeyboardButton(f"{status_label.get(pb.status,pb.status)} | {t.title}"[:60],callback_data=f"preprofile:view:{t.id}")])
        if pb.status=="prebooked":
            rows_kb.append([InlineKeyboardButton(f"💳 پرداخت و بررسی ثبت‌نام | {pay_state}"[:60],callback_data=f"preprofile:payment:{t.id}")])
        elif pb.status=="confirmed":
            rows_kb.append([InlineKeyboardButton("✅ مشاهده تأیید رزرو",callback_data=f"preprofile:payment:{t.id}")])
    await q.message.reply_text("🎟 پیش‌رزروهای من\n\nسفر موردنظر را انتخاب کنید:",reply_markup=InlineKeyboardMarkup(rows_kb))

async def profile_prebooking_cb(update,c):
    q=update.callback_query;await q.answer()
    z=q.data.split(":");act=z[1];tid=int(z[2]);uid=q.from_user.id;db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        pb=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==uid))).scalar_one_or_none()
        t=(await ss.execute(select(Trip).where(Trip.id==tid))).scalar_one_or_none()
        x=(await ss.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one_or_none()
        rr=(await ss.execute(select(PrebookingReceipt).where(
            PrebookingReceipt.trip_id==tid,PrebookingReceipt.telegram_id==uid
        ).order_by(PrebookingReceipt.submitted_at.desc()).limit(1))).scalar_one_or_none()
    if not pb or not t:
        await q.message.reply_text("این پیش‌رزرو پیدا نشد.");return
    sl={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 رزرو قطعی","waitlist":"⏳ لیست انتظار","cancelled":"⚪ لغو"}
    if act=="view":
        await q.message.reply_text(
            f"🧳 {t.title}\n"
            f"وضعیت: {sl.get(pb.status,pb.status)}\n"
            f"💰 مبلغ ثبت‌شده: {money(pb.price_snapshot)}\n"
            f"🎁 تخفیف: {money(pb.discount_snapshot)}\n"
            f"📅 ثبت پیش‌رزرو: {fdt(pb.created_at)}")
        return
    if pb.status=="confirmed":
        await q.message.reply_text(f"✅ رزرو «{t.title}» قطعی است و پرداخت شما تأیید شده.");return
    if pb.status=="waitlist":
        await q.message.reply_text(f"⏳ شما برای «{t.title}» در لیست انتظار هستید. هنوز نیازی به پرداخت نیست.");return
    state="💳 هنوز رسیدی ثبت نشده."
    if rr:
        state={"pending":"⏳ رسید شما ارسال شده و در حال بررسی ادمین است.","approved":"✅ پرداخت تأیید شده است.","rejected":"❌ رسید قبلی تأیید نشده؛ می‌توانید رسید صحیح را دوباره بفرستید."}.get(rr.status,state)
    account=html.escape((x.payment_account if x else "") or "شماره پرداخت هنوز ثبت نشده")
    recipient=html.escape((x.payment_recipient if x else "") or "")
    await q.message.reply_text(
        f"💳 پرداخت — «{html.escape(t.title)}»\n\n"
        f"💰 مبلغ قابل پرداخت: {money(pb.price_snapshot)}\n"
        f"💳 شماره کارت/حساب/شبا:\n<code>{account}</code>"
        + (f"\n👤 به نام: {recipient}" if recipient else "")
        + f"\n\n{state}\n\nبرای ارسال یا اصلاح رسید، عکس رسید را همین‌جا در PV بفرستید.",
        parse_mode="HTML")

def handlers():
    return [flow(),CommandHandler("prebookinggroup",register_prebooking_group),CallbackQueryHandler(publication_cb,pattern=r"^ppub:"),CallbackQueryHandler(calendar_cb,pattern=r"^pc:"),CallbackQueryHandler(preadd_cb,pattern=r"^padd:"),CallbackQueryHandler(preperson_cb,pattern=r"^pview:person:"),CallbackQueryHandler(receipt_review,pattern=r"^receipt:(approve|reject):\d+$"),CallbackQueryHandler(receipt_trip_pick,pattern=r"^receipttrip:\d+$"),CallbackQueryHandler(cancel_confirm,pattern=r"^preconfirm:(yes|no):\d+$"),CallbackQueryHandler(export_confirmed,pattern=r"^pexport:confirmed:\d+$"),CallbackQueryHandler(profile_prebookings,pattern=r"^preprofile:open$"),CallbackQueryHandler(profile_prebooking_cb,pattern=r"^preprofile:(view|payment):\d+$"),CallbackQueryHandler(passenger,pattern=r"^pre:(join|cancel|refresh):\d+$"),MessageHandler(filters.Regex(r"^📝 ثبت‌نام‌های من$"),mine),MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE,receipt_photo),MessageHandler(filters.TEXT & ~filters.COMMAND,preadd_search)]
