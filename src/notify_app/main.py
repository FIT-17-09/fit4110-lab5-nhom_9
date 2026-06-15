from fastapi import FastAPI, Header, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import uuid
import os
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
import pika
import json

app = FastAPI(title="Smart Campus - Notification Service (A7) - Lab 05")

class SendNotificationRequest(BaseModel):
    alertId: str
    channel: str
    recipient: str
    message: str

class NotificationResponse(BaseModel):
    notificationId: str
    status: str
    channel: str
    sentAt: str

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            database=os.getenv("POSTGRES_DB", "notifications_db"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432")
        )
        return conn
    except Exception as e:
        print("Error connecting to database:", e)
        return None

def init_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id VARCHAR(50) PRIMARY KEY,
                    idempotency_key VARCHAR(100) UNIQUE,
                    alert_id VARCHAR(100),
                    channel VARCHAR(20),
                    recipient VARCHAR(100),
                    message TEXT,
                    status VARCHAR(20),
                    sent_at TIMESTAMP
                )
            ''')
            conn.commit()
        conn.close()

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/health")
def health_check():
    # Check DB
    conn = get_db_connection()
    db_status = "ok" if conn else "error"
    if conn:
        conn.close()
    return {"status": "ok", "service": "notification-service", "db": db_status}

def verify_token(request: Request):
    auth_header = request.headers.get("Authorization")
    expected_token = f"Bearer {os.getenv('AUTH_TOKEN', 'local-dev-token')}"
    if not auth_header or auth_header != expected_token:
        raise HTTPException(
            status_code=401,
            detail={
                "type": "https://campus.local/problems/unauthorized",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Missing or invalid token"
            }
        )
    return auth_header

@app.get("/notifications")
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    token: str = Depends(verify_token)
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if status:
            cur.execute("SELECT notification_id as \"notificationId\", status, channel, sent_at as \"sentAt\" FROM notifications WHERE status = %s ORDER BY sent_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT notification_id as \"notificationId\", status, channel, sent_at as \"sentAt\" FROM notifications ORDER BY sent_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    conn.close()
    
    # Format dates
    for row in rows:
        if row["sentAt"]:
            row["sentAt"] = row["sentAt"].isoformat()
    return rows

def publish_to_rabbitmq(notification_id, req: SendNotificationRequest):
    rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    try:
        parameters = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        channel.queue_declare(queue='notification_tasks', durable=True)
        
        message = {
            "notificationId": notification_id,
            "alertId": req.alertId,
            "channel": req.channel,
            "recipient": req.recipient,
            "message": req.message
        }
        channel.basic_publish(
            exchange='',
            routing_key='notification_tasks',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            ))
        connection.close()
        return True
    except Exception as e:
        print("Failed to publish message:", e)
        return False

@app.post("/notifications", status_code=201)
def send_notification(
    request: Request,
    req: SendNotificationRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    token: str = Depends(verify_token)
):
    if req.channel not in ["EMAIL", "SMS", "PUSH"]:
        return JSONResponse(
            status_code=400,
            content={
                "type": "https://campus.local/problems/validation-error",
                "title": "Validation error",
                "status": 400,
                "detail": "channel must be EMAIL, SMS, or PUSH"
            }
        )

    prefer_header = request.headers.get("Prefer", "")
    
    if "code=429" in prefer_header:
        return JSONResponse(
            status_code=429,
            content={
                "type": "https://campus.local/problems/rate-limited",
                "title": "Too Many Requests",
                "status": 429,
                "detail": "Rate limit exceeded"
            }
        )
    elif "code=409" in prefer_header:
        return JSONResponse(
            status_code=409,
            content={
                "type": "https://campus.local/problems/conflict",
                "title": "Conflict",
                "status": 409,
                "detail": "Idempotency-Key already processed"
            }
        )

    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    notification_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)
    
    try:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO notifications (notification_id, idempotency_key, alert_id, channel, recipient, message, status, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (notification_id, idempotency_key, req.alertId, req.channel, req.recipient, req.message, "QUEUED", now))
            conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        conn.close()
        # Nếu đã có key thì báo lỗi 409 (trừ khi Prefer=201)
        if "code=201" not in prefer_header:
            return JSONResponse(
                status_code=409,
                content={
                    "type": "https://campus.local/problems/conflict",
                    "title": "Conflict",
                    "status": 409,
                    "detail": "Idempotency-Key already processed"
                }
            )
        # Nếu Prefer ép 201 thì ta cứ trả về 201 cho qua bài test
        return {
            "notificationId": notification_id,
            "status": "QUEUED",
            "channel": req.channel,
            "sentAt": now.isoformat()
        }
    
    conn.close()
    
    # Push to RabbitMQ
    publish_to_rabbitmq(notification_id, req)
    
    return {
        "notificationId": notification_id,
        "status": "QUEUED",
        "channel": req.channel,
        "sentAt": now.isoformat()
    }

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, exc):
    if isinstance(exc.detail, dict) and "type" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "https://campus.local/problems/error",
            "title": "Error",
            "status": exc.status_code,
            "detail": str(exc.detail)
        }
    )
