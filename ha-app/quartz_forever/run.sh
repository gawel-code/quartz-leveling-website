#!/usr/bin/with-contenv bashio
export NOM_GUILDE="$(bashio::config 'nom_guilde')"
export GUILDE_TOKEN="$(bashio::config 'token')"
export DISCORD_WEBHOOK="$(bashio::config 'discord_webhook')"
export DISCORD_CLIENT_ID="$(bashio::config 'discord_client_id')"
export DISCORD_CLIENT_SECRET="$(bashio::config 'discord_client_secret')"
export DISCORD_SERVEUR_ID="$(bashio::config 'discord_serveur_id')"
export DISCORD_ROLE_ID="$(bashio::config 'discord_role_id')"
export DISCORD_ADMINS="$(bashio::config 'discord_admins')"
export BNET_CLIENT_ID="$(bashio::config 'bnet_client_id')"
export BNET_CLIENT_SECRET="$(bashio::config 'bnet_client_secret')"
export BNET_REGION="$(bashio::config 'bnet_region')"
export BNET_ESPACE="$(bashio::config 'bnet_espace')"
export BNET_ROYAUME="$(bashio::config 'bnet_royaume')"
export BNET_GUILDE="$(bashio::config 'bnet_guilde')"
export GUILDE_DB=/data/guilde.db
export GUILDE_CLES=/config/cles.txt
export GUILDE_EXPORT=/data/GuildExport.lua
export PYTHONPATH=/app
[ -f /config/cles.txt ] || echo "# Une ligne par membre : Pseudo:cle-secrete" > /config/cles.txt
cd /data
python3 -c "import app; app.init_db()"
bashio::log.info "Quartz Forever démarré sur le port 8080"
exec gunicorn -w 1 -b 0.0.0.0:8080 app:app
