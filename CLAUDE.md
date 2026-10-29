# Quartz Forever — suivi de progression de guilde WoW Forever

Projet de Gaël. Réponds en **français**. Gaël est développeur : explications
concises, pas de pédagogie de base.

## Contexte
- **WoW Forever** (Blizzard) : lancement mondial le **5 novembre 2026** (minuit,
  heure de Paris). Niveau max 60, toutes les races de Classic, **paladin et chaman
  disponibles des deux côtés**.
- Guilde **Quartz Forever**, **Horde**, serveur **PvE**.
- Objectif : site public qui suit la progression des membres (race, classe,
  niveau), tableau d'honneur, annonces Discord.
- **API Blizzard** : l'espace de noms Forever n'est pas (encore) publié. On
  collecte donc via un **addon en jeu** dont les membres envoient le fichier
  SavedVariables. `lire_api_blizzard()` dans `app.py` est le point de branchement
  prévu pour l'API quand elle existera (Classic Era : `profile-classic1x-eu`).

## Architecture
```
WoW (addon GuildExport) → GuildExport.lua (SavedVariables, écrit à la déconnexion / /reload)
   → envoi-guilde.ps1 (auto) ou formulaire /contribuer (manuel), clé perso par membre
   → app Flask + SQLite dans une app locale Home Assistant (HAOS)
   → https://quartz.gawel.be via Cloudflare Tunnel
Home Assistant → rest_command → /collecter (horaire) et /recap (9 h / 21 h) → webhook Discord
```

## Arborescence
- `ha-app/quartz_forever/` : l'app Home Assistant (config.yaml, build.yaml,
  Dockerfile, run.sh, app.py, logo.png = cristal détouré 256 px,
  banniere.jpg = grotte de cristaux en fond d'en-tête). **C'est le code du serveur.**
- L'addon WoW **GuildExport** vit dans le dépôt séparé **gawel-code/quartz-leveling-addon**. Format qu'il exporte
  (contrat avec `analyser_export()` du serveur, à garder synchronisé) :
  `["Nom"] = "Nom;Race;Classe;Niveau"`.
- `client/` : script PowerShell d'envoi automatique + lanceur .bat pour les membres.
- `docs/README-guilde.md` : mode d'emploi non technique pour la guilde.
- `ha/configuration.yaml` : rest_command à ajouter côté Home Assistant.
- `ha/deployer-quartz.sh` : déploiement de l'app depuis GitHub (voir plus bas).
- `tools/verifier_api_blizzard.py` : test de l'API Blizzard sur Classic Era.
- `tools/generer_cles.py` : génère/renouvelle les clés des membres dans `cles.txt`.
- `tests/test_app.py` : tests pytest du serveur (`pytest -q`).

## Serveur (app.py)
- Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.
- Tables : `personnages`, `historique` (chaque montée de niveau), `exploits`
  (UNIQUE palier+nom → une annonce ne part jamais deux fois), `envois`.
- Fusion : on garde toujours le **niveau le plus haut** ; une race connue n'est
  jamais écrasée par « ? ».
- Annonces Discord (`verifier_exploits`) : chaque palier de 10 pour **tout le monde**,
  avec le rang (médaille pour le top 3, sinon ⭐ / 🏆 au 60) ; sans classement, tous
  les 5 niveaux dès 20 (25, 35, 45) et chaque niveau dès 50. Un envoi qui saute
  plusieurs niveaux n'annonce que les paliers de 10 franchis + le plus haut niveau
  « simple » s'il dépasse le dernier palier. Seuls les paliers de 10 sont stockés
  dans `exploits` ; le tableau d'honneur affiche le top 3 (10–50) et tous les 60.
- Routes : `/` (classement, tableau d'honneur, fil d'activité), `/contribuer`
  (formulaire), `POST /envoyer` (header `X-Cle`), `/collecter`, `/recap`,
  `/export.json`, `POST /reinitialiser` (vide toute la base, copie dans
  `<DB>.avant-reset`) — ces quatre protégées par `?token=`.
- Variables d'env (posées par run.sh depuis les options de l'app) : `NOM_GUILDE`,
  `GUILDE_TOKEN`, `DISCORD_WEBHOOK`, `GUILDE_DB=/data/guilde.db`,
  `GUILDE_CLES=/config/cles.txt`, `GUILDE_EXPORT`. Webhook vide = messages
  seulement dans le journal (mode test).

## Déploiement Home Assistant — pièges déjà rencontrés
- HAOS récent : les apps locales vivent dans **`/local_apps`** (plus `/addons`,
  qui n'est plus scanné). Les configs d'apps sont dans **`/app_configs`**.
  Le fichier des clés est donc `/app_configs/local_quartz_forever/cles.txt`
  (format `Pseudo:clé`, une ligne par membre, relu à chaque envoi).
- Slug : `local_quartz_forever` ; hostname interne : `local-quartz-forever`.
- Dans Terminal & SSH, la config HA est sous **`/homeassistant`** (pas `/config`).
  Le collage peut être déformé par le *bracketed paste* (1ʳᵉ lettre mangée, `~` final) :
  taper à la main `printf '\e[?2004l'`.
- CLI dans Terminal & SSH : `ha apps install|start|restart|rebuild|logs local_quartz_forever`,
  `ha store reload`. Le shell est **BusyBox** (pas de `ls -b`, `grep` limité).
- Fichiers créés via File editor = fins de ligne **CRLF** → casser bash.
  Toujours `sed -i 's/\r$//'` avant d'exécuter un script collé.
- Déploiement : l'app locale n'est pas liée à GitHub (dépôt privé). Lancer
  `/homeassistant/deployer-quartz.sh [réf]` (copie de `ha/deployer-quartz.sh`) dans
  Terminal & SSH : télécharge `ha-app/quartz_forever` de `main` (ou de la réf donnée)
  avec le jeton lecture seule `quartz_github_token` de `/homeassistant/secrets.yaml`
  (repli : `/homeassistant/.quartz_token`), copie dans
  `/local_apps/quartz_forever/`, puis `ha store reload` + update (ou rebuild).
  Bumper `version` dans `config.yaml` à chaque changement. `/data` et `cles.txt` ne bougent pas.
- Cloudflared (app `396f0234_cloudflared`) : `additional_hosts` contient
  `mcp.gawel.be → http://homeassistant:9583` (connecteur MCP de Claude, **ne pas
  supprimer**) et `quartz.gawel.be → http://local-quartz-forever:8080`.
  Redémarrer Cloudflared coupe le connecteur MCP quelques secondes.

## État au 29 octobre 2026
- ✅ App installée et démarrée, site en ligne sur https://quartz.gawel.be
- ✅ Route Cloudflared configurée
- ✅ `cles.txt` créé (30 membres, pseudos sans espaces ni `|` : `Metam-Zap`, `Tryal-Inelah`…)
- ✅ Automatisations HA (collecte horaire, récap 9 h / 21 h) actives ; connecteur MCP HA = URL avec chemin secret, sans OAuth
- ✅ Design « cristal » (v1.1.0) déployé via `deployer-quartz.sh` ; jeton `quartz_github_token` dans `secrets.yaml`
- ⬜ Voir la to-do ci-dessous

## To-do
1. ~~Créer `cles.txt` avec les clés des membres.~~ ✅ fait
2. ~~Automatisations HA~~ ✅ fait (29/10) : `rest_command.quartz_collecter` / `quartz_recap`
   chargés (secrets internes, token de l'app renseigné, appels testés → 200),
   automatisations `automation.quartz_collecte_horaire` (toutes les heures à :00) et
   `automation.quartz_recap_discord_9_h_21_h` (9 h / 21 h : collecte puis récap) actives.
3. ~~Webhook Discord~~ ✅ fait (29/10) : option `discord_webhook` de l'app renseignée,
   app redémarrée. Les annonces et récaps partent désormais pour de vrai.
4. Tester de bout en bout : envoi via /contribuer, classement, tableau d'honneur,
   `/export.json?token=…`.
5. Vérifier le numéro `## Interface:` de l'addon sur le client Forever ; tester
   l'addon en jeu (race via cible/survol/groupe).
6. Créer un client API sur develop.battle.net, lancer `tools/verifier_api_blizzard.py` sur un
   perso Classic Era ; vérifier si l'endpoint de liste de guilde existe.
7. Surveiller la publication de l'espace de noms API Forever ; brancher
   `lire_api_blizzard()`.
8. Distribuer à la guilde : addon, `client/`, `docs/README-guilde.md`, clés en MP.
9. Plus tard : sauvegarde nuitière de `/export.json` par Home Assistant.
10. Plus tard : notification HA (en plus de Discord) quand un membre passe 60.
11. Idées en attente : graphiques de progression, fiche par personnage, maquette
    artefact pour présenter le projet à la guilde.
