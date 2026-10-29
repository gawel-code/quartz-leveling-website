#!/usr/bin/with-contenv bashio
export NOM_GUILDE="$(bashio::config 'nom_guilde')"
export GUILDE_TOKEN="$(bashio::config 'token')"
export DISCORD_WEBHOOK="$(bashio::config 'discord_webhook')"
export GUILDE_DB=/data/guilde.db
export GUILDE_CLES=/config/cles.txt
export GUILDE_EXPORT=/data/GuildExport.lua
export PYTHONPATH=/app
[ -f /config/cles.txt ] || echo "# Une ligne par membre : Pseudo:cle-secrete" > /config/cles.txt
cd /data
python3 -c "import app; app.init_db()"
bashio::log.info "Quartz Forever démarré sur le port 8080"
exec gunicorn -w 1 -b 0.0.0.0:8080 app:app
