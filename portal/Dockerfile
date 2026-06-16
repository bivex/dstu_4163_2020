# Портал підписання документів — бекенд (FastAPI + доменне ядро dilovod4)
FROM python:3.12-slim

# системні залежності для reportlab (шрифти), збірки UAPKI та openssl
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation \
        cmake \
        make \
        g++ \
        gcc \
        libssl-dev \
        libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# спершу залежності — кеш шарів
COPY portal/requirements.txt /app/portal/requirements.txt
RUN pip install --no-cache-dir -r /app/portal/requirements.txt

# доменне ядро + портал + бібліотека EUSign (для клієнтського підпису) + UAPKI + CAs
COPY src /app/src
COPY portal /app/portal
COPY external/EUSignES6 /app/external/EUSignES6
COPY external/UAPKI /app/external/UAPKI
COPY .euscp_store /app/.euscp_store

# Збираємо нативну бібліотеку UAPKI для Linux всередині контейнера
RUN rm -rf /app/external/UAPKI/library/build && \
    cd /app/external/UAPKI/library && \
    bash build-uapki.sh && \
    cd build/out && \
    ln -sf libuapki.so.* libuapki.so && \
    ln -sf libuapkic.so.* libuapkic.so && \
    ln -sf libuapkif.so.* libuapkif.so && \
    ln -sf libcm-pkcs12.so.* libcm-pkcs12.so

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORTAL_DATABASE_URL=sqlite:////data/portal.db

# каталог для SQLite та збережених документів (том)
RUN mkdir -p /data

EXPOSE 8000

# health-check на /health
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "portal.main:app", "--host", "0.0.0.0", "--port", "8000"]
