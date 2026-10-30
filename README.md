# Quartz Forever — suivi de progression de guilde

Site public de progression de la guilde **Quartz Forever** (Horde, serveur PvE) sur
**World of Warcraft: Forever** (lancement le 5 novembre 2026, niveau max 60) :
classement des membres, tableau d'honneur des paliers, fil d'activité et annonces Discord.

**En ligne :** https://quartz.gawel.be — **Version du serveur :** 1.5.0

## Fonctionnement

L'API Blizzard n'expose pas (encore) les données de WoW Forever. Les données viennent
donc d'un addon en jeu, dont les membres envoient le fichier de sauvegarde au site.

```
WoW + addon GuildExport ──► GuildExport.lua (SavedVariables, écrit à la déconnexion / /reload)
        │
        ├─► client/envoi-guilde.ps1 (envoi automatique)  ─┐
        └─► formulaire https://quartz.gawel.be/contribuer ─┴─► POST /envoyer (clé perso)
                                                                    │
                          app Flask + SQLite (app locale Home Assistant, HAOS)
                                                                    │
            Cloudflare Tunnel ◄─────────────────────────────────────┤
            Home Assistant : collecte horaire + récap 9 h / 21 h ───┴─► webhook Discord
```

- **Addon** : dépôt séparé [gawel-code/quartz-leveling-addon](https://github.com/gawel-code/quartz-leveling-addon).
  Il exporte la liste de guilde (nom, race, classe, niveau) et l'heure des montées de niveau.
- **Connexion Discord** (OAuth2) : un membre du serveur Discord de la guilde, avec le rôle
  de la guilde, se connecte sur `/moi`, relie son compte à son pseudo (avec sa clé actuelle,
  ou en choisissant un pseudo : une clé est alors créée) et y retrouve sa clé. Si son surnom sur
  le serveur, son nom affiché ou son nom d'utilisateur Discord est un pseudo libre de `cles.txt`,
  le compte est relié automatiquement dès la connexion. Si le membre a lié Battle.net à Discord
  (*Paramètres → Connexions*), son **BattleTag** est récupéré et affiché sur `/moi` et `/admin`. Connecté, il
  envoie son fichier sans saisir de clé. Les admins (IDs Discord) passent toujours et ont `/admin`.
- **Envoi** : chaque membre a une clé personnelle (`cles.txt` côté serveur, ou créée sur le site). Le script
  PowerShell renvoie le fichier dès qu'il change ; le formulaire `/contribuer` permet un envoi manuel.
- **Fusion** : on garde toujours le niveau le plus haut ; une race connue n'est jamais
  écrasée par `?`. Envoyer un vieux fichier ne fait rien régresser.
- **Dates réelles** : quand l'addon fournit l'heure d'une montée de niveau, c'est elle qui
  compte (la plus ancienne connue gagne, jamais dans le futur) ; sinon, l'heure de réception.
- **Tableau d'honneur** : les paliers 10, 20, 30, 40, 50 et 60 sont classés **par date
  réelle**. Un envoi tardif ne fait pas perdre son rang : le tableau se remet dans l'ordre.

### Annonces Discord

| Niveaux | Annonce |
|---|---|
| 10, 20, 30, 40, 50, 60 | pour chaque joueur, avec son rang d'arrivée (🥇🥈🥉 pour le top 3, ⭐ ensuite, 🏆 au 60) |
| 25, 35, 45 | pour chaque joueur, sans classement |
| 51 à 59 | chaque niveau, sans classement |
| récap | 9 h et 21 h : classement, gains sur 12 h, plus grosse progression |

Les annonces d'un même envoi partent en **un seul message** (une ligne par annonce, découpé
au-delà de 2000 caractères), chacune avec la date réelle du passage de niveau, et se
terminent une fois par le membre qui a envoyé les données (« — via Pseudo », pseudo de `cles.txt`). Un envoi qui saute plusieurs
niveaux annonce les paliers de 10 franchis et seulement le plus haut des autres niveaux.
Une annonce de palier ne part qu'une fois. Le rang annoncé tient compte de tous les personnages du même envoi ;
le tableau d'honneur du site peut ensuite le corriger.

## Contenu du dépôt

| Chemin | Rôle |
|---|---|
| `ha-app/quartz_forever/` | **le serveur** : app locale Home Assistant (`config.yaml`, `Dockerfile`, `run.sh`, `app.py`, images) |
| `client/` | envoi automatique pour les membres (Windows) : `lancer.bat` (double-clic ; demande la clé au premier lancement, trouve le fichier, journal dans `%APPDATA%\QuartzForever\envoi.log`), `changer-cle.bat`, `envoi-guilde.ps1` |
| `docs/README-guilde.md` | mode d'emploi non technique pour la guilde |
| `ha/configuration.yaml` | `rest_command` et automatisations à ajouter dans Home Assistant |
| `ha/deployer-quartz.sh` | déploiement de l'app depuis GitHub (à lancer dans Terminal & SSH) |
| `tools/generer_cles.py` | génère ou renouvelle les clés des membres dans `cles.txt` |
| `tools/verifier_api_blizzard.py` | teste l'API Blizzard sur Classic Era |
| `tests/test_app.py` | tests du serveur |
| `CLAUDE.md` | notes de projet détaillées (état, pièges de déploiement, to-do) |

## Serveur

Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.

### Routes

| Route | Accès | Rôle |
|---|---|---|
| `GET /` | public | classement, tableau d'honneur, fil d'activité |
| `GET/POST /contribuer` | clé du membre | formulaire d'envoi du fichier `GuildExport.lua` |
| `POST /envoyer` | en-tête `X-Cle` | envoi du fichier (utilisé par le script PowerShell) |
| `GET/POST /collecter` | `?token=` | intègre le fichier déposé côté serveur (et plus tard l'API Blizzard) |
| `GET/POST /recap` | `?token=` | publie le récapitulatif sur Discord |
| `GET /connexion`, `/auth/discord/callback`, `/deconnexion` | public | connexion Discord (OAuth2, scopes `identify guilds.members.read connections`) |
| `GET/POST /moi` | session Discord | relier son compte, afficher / régénérer sa clé |
| `GET/POST /admin` | admin Discord | comptes reliés (délier), clés sans compte, vider la progression |
| `GET /export.json` | `?token=` | export complet de la base |
| `POST /reinitialiser` | `?token=` | vide la base (copie de sauvegarde dans `guilde.db.avant-reset`) |

Si l'option `token` est vide, les routes protégées sont fermées.

### Données

Tables SQLite (`/data/guilde.db`) : `personnages` (état courant), `historique` (une ligne
par niveau atteint, avec sa date), `exploits` (paliers de 10, rang par date réelle),
`envois` (journal des envois), `comptes` (Discord ↔ pseudo et BattleTag ; clé créée sur le site, sinon
celle de `cles.txt`, qu'elle remplace). Dates ISO à la seconde. `/reinitialiser` ne touche
pas aux comptes. Les sessions sont signées par `/data/secret.key` (créée au premier démarrage).

### Options de l'app Home Assistant

| Option | Rôle |
|---|---|
| `nom_guilde` | nom affiché |
| `token` | protège `/collecter`, `/recap`, `/export.json`, `/reinitialiser` |
| `discord_webhook` | webhook du salon de progression ; vide = messages seulement dans le journal (mode test) |
| `discord_client_id` / `discord_client_secret` | application Discord (OAuth2) ; secret vide = connexion Discord désactivée |
| `discord_serveur_id` | serveur Discord de la guilde |
| `discord_role_id` | rôle exigé ; vide = tout membre du serveur |
| `discord_admins` | IDs Discord admins, séparés par des virgules (toujours acceptés, accès à `/admin`) |

Les clés des membres sont dans `/app_configs/local_quartz_forever/cles.txt`
(une ligne `Pseudo:clé` par membre, relu à chaque envoi, sans redémarrage).

## Déploiement

L'app est une app locale Home Assistant (slug `local_quartz_forever`), exposée par
Cloudflare Tunnel sur `quartz.gawel.be`. Dans Terminal & SSH :

```bash
/homeassistant/deployer-quartz.sh
```

Le script télécharge `ha-app/quartz_forever` depuis `main` (ou la référence passée en
argument), le copie dans `/local_apps/quartz_forever/` et met l'app à jour. Il faut
augmenter `version` dans `ha-app/quartz_forever/config.yaml` à chaque changement : elle
s'affiche en pied de page et suffixe les URL des images (`logo.png?v=…`), ce qui contourne
le cache de Cloudflare et des navigateurs.
La base et `cles.txt` ne sont pas touchés. Détails et pièges connus : voir `CLAUDE.md`.

Côté Home Assistant, `rest_command.quartz_collecter` et `rest_command.quartz_recap`
sont appelés par deux automatisations (collecte horaire, récap à 9 h et 21 h).

## Développement

```bash
pip install flask requests pytest
pytest -q
```

## Historique des versions

| Version | Changements |
|---|---|
| 1.5.0 | BattleTag récupéré via les connexions Discord (scope `connections`), affiché sur « Mon compte » et dans l'admin |
| 1.4.3 | numéro de version en pied de page ; URL des images suffixées `?v=version` (Cloudflare servait encore l'ancien logo) |
| 1.4.2 | cristal redétouré (plus de liseré clair), plus grand dans l'en-tête avec un halo diffus |
| 1.4.1 | liaison automatique au pseudo de `cles.txt` identique à un nom Discord (surnom, nom affiché, utilisateur) |
| 1.4.0 | connexion Discord : page « Mon compte » (relier son pseudo, voir / régénérer sa clé), envoi sans clé une fois connecté, page admin |
| 1.3.3 | un seul message Discord par envoi (une ligne par annonce), « — via Pseudo » une fois à la fin |
| 1.3.2 | chaque annonce cite le membre dont l'envoi l'a déclenchée (« — via Pseudo ») |
| 1.3.1 | annonces d'un même envoi faites après intégration de tout le fichier, dans l'ordre chronologique : plus de double « 1ᵉʳ » |
| 1.3.0 | dates réelles de montée de niveau fournies par l'addon, classement des paliers par date |
| 1.2.1 | cristal haute définition et bannière en en-tête |
| 1.2.0 | annonces pour tous les joueurs : paliers de 10 classés, 25/35/45, chaque niveau dès 50 |
| 1.1.2 | route `POST /reinitialiser` |
| 1.1.1 | token vide = routes protégées fermées |
| 1.1.0 | design « cristal » |
| 1.0.0 | première version : classement, tableau d’honneur, annonces Discord, envoi par clé |
