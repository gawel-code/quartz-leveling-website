#!/bin/bash
# Déploie l'app Quartz Forever depuis GitHub vers /local_apps/quartz_forever,
# puis met à jour (ou reconstruit) l'app locale. À lancer dans Terminal & SSH.
#
# Installation (une fois) :
#   ajouter dans /homeassistant/secrets.yaml :  quartz_github_token: github_pat_XXXX
#   (à défaut, le jeton brut seul dans /homeassistant/.quartz_token)
#   (jeton « fine-grained », dépôt quartz-leveling-website seul, Contents : Read-only)
#   copier ce script dans /homeassistant/, puis : sed -i 's/\r$//' deployer-quartz.sh && chmod +x deployer-quartz.sh
#
# Usage : /homeassistant/deployer-quartz.sh [branche|tag|commit]   (défaut : main)
set -e
REF="${1:-main}"
SECRETS=/homeassistant/secrets.yaml
CLE_SECRET=quartz_github_token
FICHIER_JETON=/homeassistant/.quartz_token
CIBLE=/local_apps/quartz_forever
SLUG=local_quartz_forever

JETON=""
if [ -f "$SECRETS" ]; then
  JETON=$(sed -n "s/^$CLE_SECRET:[[:space:]]*//p" "$SECRETS" | head -n 1 | tr -d "\r\"' ")
fi
if [ -z "$JETON" ] && [ -s "$FICHIER_JETON" ]; then
  JETON=$(tr -d '\r\n ' < "$FICHIER_JETON")
fi
[ -n "$JETON" ] || { echo "Jeton GitHub absent : clé $CLE_SECRET dans $SECRETS (ou $FICHIER_JETON)"; exit 1; }
[ -d "$CIBLE" ] || { echo "Dossier de l'app absent : $CIBLE"; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Téléchargement de $REF…"
curl -fsSL -H "Authorization: Bearer $JETON" \
  "https://api.github.com/repos/gawel-code/quartz-leveling-website/tarball/$REF" -o "$TMP/src.tgz"
tar -xzf "$TMP/src.tgz" -C "$TMP"
SRC=$(echo "$TMP"/gawel-code-quartz-leveling-website-*/ha-app/quartz_forever)
[ -f "$SRC/config.yaml" ] || { echo "Archive inattendue : ha-app/quartz_forever introuvable"; exit 1; }

cp -r "$SRC"/. "$CIBLE"/
VERSION=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' "$CIBLE/config.yaml")
echo "Code copié (version $VERSION)."

# Champ « version » ou « version_latest » de `ha apps info` (sortie YAML, guillemets éventuels).
info() { ha apps info "$SLUG" | sed -n "s/^$1:[[:space:]]*//p" | tr -d "\"' "; }

# Le Supervisor ne voit pas toujours la nouvelle version juste après `ha store reload` : sans
# attente, `ha apps update` ne trouve rien et un rebuild laisse l'ancienne version installée.
ha store reload
for i in 1 2 3 4 5 6; do
  [ "$(info version_latest)" = "$VERSION" ] && break
  sleep 5
  ha store reload
done
[ "$(info version_latest)" = "$VERSION" ] || {
  echo "ÉCHEC : le Supervisor ne voit pas la version $VERSION (version_latest = $(info version_latest))."; exit 1; }

if [ "$(info version)" = "$VERSION" ]; then
  echo "Version $VERSION déjà installée : reconstruction de l'image."
  ha apps rebuild "$SLUG"
else
  echo "Mise à jour $(info version) → $VERSION…"
  ha apps update "$SLUG"
fi
INSTALLEE=$(info version)
[ "$INSTALLEE" = "$VERSION" ] || { echo "ÉCHEC : version installée $INSTALLEE au lieu de $VERSION."; exit 1; }
echo "Version $VERSION installée. Démarrage de l'app…"
sleep 10
ha apps logs "$SLUG" | tail -5
