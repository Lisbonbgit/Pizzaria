# ---------- Etapa 1: build do React ----------
FROM node:20-alpine AS build

WORKDIR /app

# URL do backend no momento do build (CRA inclui REACT_APP_* no bundle).
# Vazio = mesma origem (o Caddy encaminha /api para o backend → sem CORS).
ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

# Instalar dependências (sem lockfile no repo → yarn resolve no build)
COPY package.json ./
RUN yarn install --network-timeout 600000

# Código e build de produção
COPY . .
RUN yarn build

# ---------- Etapa 2: servir os ficheiros estáticos ----------
FROM nginx:alpine

# Config do SPA (fallback para index.html)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Ficheiros compilados
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
