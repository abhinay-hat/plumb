FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY --from=frontend /src/dist ./frontend/dist

# Hugging Face Spaces runs the container as uid 1000, so the audit log — the
# only thing plumb writes — has to be owned by that user before the drop.
RUN useradd --uid 1000 --create-home plumb \
    && mkdir -p /app/audit \
    && chown -R plumb:plumb /app
USER plumb

# Spaces injects PORT; 8000 keeps `docker compose up` and the README identical.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
