# ---------- Pizzaria backend (FastAPI) ----------
FROM python:3.11-slim

# Evita ficheiros .pyc e força logs sem buffer (úteis em containers)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Lisbon

WORKDIR /app

# Instalar dependências primeiro (melhor cache de layers)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY . .

# Utilizador não-root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

# server.py expõe "app" (FastAPI). Em produção corre via uvicorn.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
