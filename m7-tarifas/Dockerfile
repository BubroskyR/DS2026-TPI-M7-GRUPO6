# Imagen de la API de M7, con una versión fija de Python (RNF-04).
FROM python:3.12.15-slim

WORKDIR /app

# Primero las dependencias: si solo cambia el código, Docker reutiliza esta capa.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# La API no corre como administrador del contenedor.
RUN useradd --create-home m7
USER m7

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
