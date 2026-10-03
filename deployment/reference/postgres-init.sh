#!/bin/sh
# Create the OpenFGA and Keycloak databases with passwords read from secret files.
set -eu
psql --username "$POSTGRES_USER" --dbname postgres -v ON_ERROR_STOP=1 \
  -v fga_password="$(cat /run/secrets/fga_db_password)" \
  -v keycloak_password="$(cat /run/secrets/keycloak_db_password)" <<'SQL'
CREATE USER openfga WITH PASSWORD :'fga_password';
CREATE DATABASE openfga OWNER openfga;
CREATE USER keycloak WITH PASSWORD :'keycloak_password';
CREATE DATABASE keycloak OWNER keycloak;
SQL
