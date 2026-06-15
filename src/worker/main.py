import os
import time
import json
import psycopg2
import pika
import threading
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Worker Service Healthcheck")

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

def process_message(ch, method, properties, body):
    msg = json.loads(body)
    notif_id = msg.get("notificationId")
    channel = msg.get("channel")
    recipient = msg.get("recipient")
    print(f"[{notif_id}] Sending {channel} to {recipient}...")
    
    # Simulate work
    time.sleep(2)
    
    # Update DB
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE notifications SET status = 'SENT' WHERE notification_id = %s", (notif_id,))
                conn.commit()
            print(f"[{notif_id}] Marked as SENT.")
        except Exception as e:
            print(f"[{notif_id}] Error updating DB:", e)
        finally:
            conn.close()
    
    ch.basic_ack(delivery_tag=method.delivery_tag)

def start_worker():
    rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    while True:
        try:
            parameters = pika.URLParameters(rabbitmq_url)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue='notification_tasks', durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='notification_tasks', on_message_callback=process_message)
            
            print("Worker is waiting for messages.")
            channel.start_consuming()
        except Exception as e:
            print("RabbitMQ connection failed, retrying in 5 seconds...", e)
            time.sleep(5)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "worker-service"}

if __name__ == "__main__":
    # Start RabbitMQ consumer in a background thread
    worker_thread = threading.Thread(target=start_worker, daemon=True)
    worker_thread.start()
    
    # Start FastAPI healthcheck server
    uvicorn.run(app, host="0.0.0.0", port=9000)
