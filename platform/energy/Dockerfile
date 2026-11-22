# Exporteur énergie (M09) conteneurisé, sur le réseau b6g-obs (collecte par Prometheus sans passer par le pare-feu).
FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir "httpx>=0.27" "pyyaml>=6" "fastapi>=0.110" "uvicorn>=0.29"
COPY energy_exporter.py power_model.yaml ./
USER 10001
ENV B6G_PROM_URL=http://prometheus:9090 PORT=9105
EXPOSE 9105
ENTRYPOINT ["uvicorn", "energy_exporter:app", "--host", "0.0.0.0", "--port", "9105"]
