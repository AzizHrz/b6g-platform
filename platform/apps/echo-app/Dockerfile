# b6g-echo-app (T09.1) : image multi-étapes.
# Étape 1 : compilation du code en bytecode (vérifie la syntaxe à la construction).
FROM python:3.12-alpine AS build
WORKDIR /src
COPY app.py .
RUN python -m py_compile app.py && python -c "import ast,sys; ast.parse(open('app.py').read())"

# Étape 2 : image d'exécution minimale, utilisateur non privilégié.
FROM python:3.12-alpine
LABEL org.opencontainers.image.title="b6g-echo-app" \
      org.opencontainers.image.description="Application de test B6G : écho, charge CPU, latence b6g_app_request_latency_ms"
RUN adduser -D -u 10001 app
WORKDIR /app
COPY --from=build /src/app.py .
USER 10001
ENV PORT=8080 B6G_TIER=local PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=2s CMD wget -qO- http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["python", "/app/app.py"]
