import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from googleapiclient.errors import HttpError
import smtplib
from email.message import EmailMessage

if os.getenv("RENDER") is None: 
    from dotenv import load_dotenv
    load_dotenv()

# Email Confirmation Management

# Google Calendar Service Provider
# Reminders:
#   1. the service account needs to be added to the calendar together with the google account
#   2. the calendar id can be found in the calendar specific settings
SCOPES = ["https://www.googleapis.com/auth/calendar"]
def get_calendar_service():
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not service_account_file:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set.")
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)

# Google Calendar API Usage : get calendar events
def get_events_between_hours(service, val_date: date, start_hour=9, end_hour=17):
    time_zone = ZoneInfo("Europe/Tirane")
    start_time = datetime.combine(val_date, time(start_hour, 0), tzinfo=time_zone).isoformat() # 2026-01-06T09:00:00+01:00
    end_time = datetime.combine(val_date, time(end_hour, 0), tzinfo=time_zone).isoformat() # 2026-01-06T17:00:00+01:00
    events = service.events().list(
                calendarId = "prudentalclinic2025@gmail.com",
                timeMin = start_time,
                timeMax = end_time,
                singleEvents = True,
                orderBy = "startTime"
            ).execute()
    return events.get("items", [])

def normalize_events_to_hours(events):
    normalized = []
    for event in events:
        start = datetime.fromisoformat(event["start"].get("dateTime"))
        end = datetime.fromisoformat(event["end"].get("dateTime"))
        normalized.append({
            "start": start.hour,
            "end": end.hour
        })
    return normalized

def get_free_slots(service, val_date: date, start_hour=9, end_hour=17):
    events = normalize_events_to_hours(get_events_between_hours(service, val_date, start_hour, end_hour))
    result = []
    for hour in range(start_hour, end_hour):
        ok = True
        for event in events:
            if hour >= event["start"] and hour < event["end"]:
                ok = False
        if ok:
            result.append(hour)
    return result

# Google Calendar API Usage : create calendar events
def create_calendar_event(service, title, description, start_time, end_time):
    event_body = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'Europe/Tirane',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'Europe/Tirane',
            },
        }
    try:
        event = service.events().insert(
                    calendarId='prudentalclinic2025@gmail.com',
                    body=event_body
                ).execute()
        return {
            "status": "success",
            "link": event.get("htmlLink")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating event: {e}")

# Email Confirmation
def send_confirmation_email(recipient_email, patient_name, appointment_time, service):
    msg = EmailMessage()
    msg["Subject"] = "Appointment Confirmation - Prudental Clinic"
    msg["From"] = os.getenv("EMAIL_SENDER")
    msg["To"] = recipient_email
    content = f"""
Hello {patient_name},

Your dental appointment has been confirmed.

🕒 Date & Time: {appointment_time}
🦷 Service: {service}

If you need to cancel or reschedule, please contact us via email or phone number.

Best regards,
Prudental Dental Clinic
"""
    msg.set_content(content)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(os.getenv("EMAIL_SENDER"), os.getenv("EMAIL_PASSWORD"))
            server.send_message(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

send_confirmation_email(
    recipient_email="beringtafa5@gmail.com",
    patient_name="Bering Tafa",
    appointment_time=datetime.now().strftime("%B %d, %Y at %H:%M"),
    service="Emergency Care"
)

# API Endpoints
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","https://prudental.al"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class AppointmentData(BaseModel):
    name: str                # First name of the person
    surname: str             # Last name
    service: str             # Service or appointment type
    email: str               # Email of the client
    phone_number: str        # Phone Number of the client
    message: str = ""        # Optional message or note from client
    start_time: datetime     # Start time of the appointment => End time = Start time + 1 hour

@app.get("/appointments/{val_date}")
def get_available_slots(val_date: str):
    try:
        target_date = datetime.strptime(val_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    try:
        service = get_calendar_service()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get Google Calendar Service")
    free_hours = get_free_slots(service, target_date)
    return {"date": val_date, "free_hours": free_hours}

@app.post("/appointments/")
def book_appointment(item: AppointmentData):
    formatted_description = f"""
Service: {item.service}
Email: {item.email}
Phone Number: {item.phone_number}
Notes: {item.message or 'N/A'}
    """.strip()
    result = create_calendar_event(
                service=get_calendar_service(),
                title=f"{item.name} {item.surname}",
                start_time=item.start_time.isoformat(),
                end_time=(item.start_time + timedelta(hours=1)).isoformat(),
                description=formatted_description
            )
    if result is None or result.get("status") != "success":
        raise HTTPException(status_code=500, detail="Failed to create appointment")
    else:
        send_confirmation_email(
            recipient_email=item.email,
            patient_name=f"{item.name} {item.surname}",
            appointment_time=item.start_time.strftime("%B %d, %Y at %H:%M"),
            service=item.service
        )
    return result

@app.get("/")
def root():
    return {"message":"Prudental Service"}
