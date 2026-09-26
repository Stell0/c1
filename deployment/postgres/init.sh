#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres -v ON_ERROR_STOP=1 \
  -v fga_password="$OPENFGA_DB_PASSWORD" -v keycloak_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE USER openfga WITH PASSWORD :'fga_password';
CREATE DATABASE openfga OWNER openfga;
CREATE USER keycloak WITH PASSWORD :'keycloak_password';
CREATE DATABASE keycloak OWNER keycloak;
SQL
