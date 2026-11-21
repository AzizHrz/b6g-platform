# Passerelle REST I-07 (T21.3). Les certificats du réseau Fabric sont montés en lecture seule dans /crypto.
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js .
USER node
ENV PORT=8082
EXPOSE 8082
ENTRYPOINT ["node", "/app/server.js"]
