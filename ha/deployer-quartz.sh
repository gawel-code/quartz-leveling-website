#!/bin/bash
# Déploie l'app Quartz Forever depuis GitHub vers /local_apps/quartz_forever,
# puis met à jour (ou reconstruit) l'app locale. À lancer dans Terminal & SSH.
#
# Installation (une fois) :
#   printf '%s' 'github_pat_XXXX' > /homeassistant/.quartz_token && chmod 600 /homeassistant/.quartz_token
#   (jeton « fine-grained », dépôt quartz-leveling-website seul, Contents : Read-only)
#   copier ce script dans /homeassistant/, puis : sed -i 's/\r$//' deployer-quartz.sh && chmod +x deployer-quartz.sh
#
# Usage : /homeassistant/deployer-quartz.sh [branche|tag|commit]   (défaut : main)
set -e
REF="${1:-main}"
JETON=/homeassistant/.quartz_token
CIBLE=/local_apps/quartz_forever
SLUG=local_quartz_forever

[ -s "$JETON" ] || { echo "Jeton GitHub absent : $JETON"; exit 1; }
[ -d "$CIBLE" ] || { echo "Dossier de l'app absent : $CIBLE"; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Téléchargement de $REF…"
curl -fsSL -H "Authorization: Bearer $(cat "$JETON")" \
  "https://api.github.com/repos/gawel-code/quartz-leveling-website/tarball/$REF" -o "$TMP/src.tgz"
tar -xzf "$TMP/src.tgz" -C "$TMP"
SRC=$(echo "$TMP"/gawel-code-quartz-leveling-website-*/ha-app/quartz_forever)
[ -f "$SRC/config.yaml" ] || { echo "Archive inattendue : ha-app/quartz_forever introuvable"; exit 1; }

cp -r "$SRC"/. "$CIBLE"/
echo "Code copié ($(grep '^version' "$CIBLE/config.yaml"))."
ha store reload
ha apps update "$SLUG" || ha apps rebuild "$SLUG"
ha apps logs "$SLUG" | tail -5
