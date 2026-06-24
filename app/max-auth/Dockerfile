FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY db.py .
COPY auth_deps.py .
COPY keycloak_admin.py .
COPY domain.py .
COPY audit.py .
COPY demo_seed.py .
COPY formation_test_seed.py .
COPY max_client.py .
COPY bot_contact.py .
COPY bot_events.py .
COPY bot_handlers.py .
COPY bot_notify.py .
COPY lesson_reminder_worker.py .
COPY formation_worker.py .
COPY routers ./routers
COPY sql ./sql
EXPOSE 8025
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8025"]
