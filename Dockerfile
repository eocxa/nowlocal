FROM python:3.11-slim

# Instalar ffmpeg indispensable para transcodificar pistas Lossless ALAC y Dolby Atmos
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Evitar que Python genere archivos temporales __pycache__ con permisos de root
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar librerías de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del reproductor
COPY . .

EXPOSE 8000

CMD ["python", "servidor_completo.py"]