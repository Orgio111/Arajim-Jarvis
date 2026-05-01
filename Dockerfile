FROM python:3.11-slim AS backend

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend ./backend
COPY .env.example ./.env.example

RUN mkdir -p data logs versions

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM node:20-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json ./
RUN npm install
COPY frontend ./
RUN npm run build


FROM nginx:1.27-alpine AS frontend

COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY <<'NGINX' /etc/nginx/conf.d/default.conf
server {
  listen 80;
  location /api/ { proxy_pass http://backend:8000/api/; proxy_set_header Host $host; }
  location /ws   { proxy_pass http://backend:8000/ws;
                   proxy_http_version 1.1;
                   proxy_set_header Upgrade $http_upgrade;
                   proxy_set_header Connection "upgrade"; }
  location /     { try_files $uri /index.html; }
}
NGINX

EXPOSE 80
