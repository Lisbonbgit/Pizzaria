#!/usr/bin/env bash
# ==========================================================
# Backup da base de dados MongoDB (Atlas ou local).
#
# Lê MONGO_URL e DB_NAME do backend/.env, faz mongodump comprimido
# e mantém apenas os últimos N dias.
#
# Uso manual:   ./scripts/backup_mongo.sh
# Cron diário (03:00):
#   0 3 * * * /caminho/Pizzaria/scripts/backup_mongo.sh >> /var/log/pizzaria-backup.log 2>&1
#
# Requisitos: mongodump (pacote "mongodb-database-tools").
# ==========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$ROOT_DIR/backend/.env"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERRO: não encontrei $ENV_FILE" >&2
  exit 1
fi

# Carregar MONGO_URL e DB_NAME do .env (sem expor o resto)
MONGO_URL="$(grep -E '^MONGO_URL=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '"' )"
DB_NAME="$(grep -E '^DB_NAME=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '"' )"

if [[ -z "$MONGO_URL" || -z "$DB_NAME" ]]; then
  echo "ERRO: MONGO_URL ou DB_NAME em falta no .env" >&2
  exit 1
fi

if ! command -v mongodump >/dev/null 2>&1; then
  echo "ERRO: 'mongodump' não está instalado." >&2
  echo "Instale com:  sudo apt-get install -y mongodb-database-tools" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${DB_NAME}_${STAMP}.archive.gz"

echo "[$(date)] A criar backup de '$DB_NAME' → $OUT"
mongodump --uri="$MONGO_URL" --db="$DB_NAME" --archive="$OUT" --gzip

echo "[$(date)] A remover backups com mais de $RETENTION_DAYS dias"
find "$BACKUP_DIR" -name "${DB_NAME}_*.archive.gz" -type f -mtime +"$RETENTION_DAYS" -delete

echo "[$(date)] Backup concluído."
