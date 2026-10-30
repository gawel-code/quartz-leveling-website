# Quartz Forever — suivi de progression de guilde WoW Forever

Projet de Gaël. Réponds en **français**. Gaël est développeur : explications
concises, pas de pédagogie de base.

## Règles de travail (demandées par Gaël)
- **Avant chaque PR et chaque merge**, mettre à jour dans le même commit :
  - `README.md` : version en tête, fonctionnement, routes, options, **historique des versions** ;
  - `CLAUDE.md` : section *État* (date, version déployée / en attente), détails techniques
    touchés, to-do. Relire les deux pour retirer ce qui est devenu faux.
- Bumper `version` dans `ha-app/quartz_forever/config.yaml` à chaque changement de l'app
  (sinon pas de mise à jour côté HA, et les images restent en cache).
- Flux habituel : PR → « oui merge » → Gaël déploie → vérification par Claude via le connecteur HA.
- Jamais de secret commité (webhook Discord, token de l'app, secret client Discord, clés).

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
     (clé affichée sur /moi après connexion Discord ; connecté, /contribuer n'en demande pas)
   → app Flask + SQLite dans une app locale Home Assistant (HAOS)
   → https://quartz.gawel.be via Cloudflare Tunnel
Home Assistant → rest_command → /collecter (horaire) et /recap (9 h / 21 h) → webhook Discord
```

## Arborescence
- `README.md` : présentation du projet, routes, déploiement, historique des versions
  (à compléter à chaque bump de `version`).
- `ha-app/quartz_forever/` : l'app Home Assistant (config.yaml, build.yaml,
  Dockerfile, run.sh, app.py, logo.png = cristal détouré 204×256 (bord érodé de 3 px et adouci en v1.4.2 pour retirer le liseré clair),
  banniere.jpg = grotte de cristaux en fond d'en-tête). **C'est le code du serveur.**
- L'addon WoW **GuildExport** vit dans le dépôt séparé **gawel-code/quartz-leveling-addon**. Format qu'il exporte
  (contrat avec `analyser_export()` du serveur, à garder synchronisé) :
  `["Nom"] = "Nom;Race;Classe;Niveau"`. Dates de niveau (v1.3.0) dans la table
  `GuildExportNiveaux` : `["Nom"] = "10@horodatage,11@horodatage"` (`analyser_dates()`).
- `client/` : envoi automatique pour les membres. `lancer.bat` (double-clic) lance
  `envoi-guilde.ps1` : au 1er lancement demande la clé (validée par un envoi vide → 400 = ok,
  403 = refusée), cherche `_forever_\WTF\Account\*\SavedVariables\GuildExport.lua`
  (sinon demande le chemin), retient tout dans `%APPDATA%\QuartzForever\config.json`,
  journal `envoi.log` ; renvoie le fichier dès qu'il change (sondage 30 s) ; redemande la
  clé si le site la refuse. `changer-cle.bat` = `-Reconfigurer`. Le .ps1 doit garder son
  **BOM UTF-8** (sinon accents cassés sous Windows PowerShell 5.1). Variables de test :
  `QUARTZ_SERVEUR`, `QUARTZ_UNE_FOIS`.
- `docs/README-guilde.md` : mode d'emploi non technique pour la guilde.
- `ha/configuration.yaml` : rest_command à ajouter côté Home Assistant.
- `ha/deployer-quartz.sh` : déploiement de l'app depuis GitHub (voir plus bas).
- `tools/verifier_api_blizzard.py` : test de l'API Blizzard sur Classic Era.
- `tools/generer_cles.py` : génère/renouvelle les clés des membres dans `cles.txt`.
- `tests/test_app.py` : tests pytest du serveur (`pytest -q`).

## Serveur (app.py)
- Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.
- Tables : `personnages`, `historique` (chaque montée de niveau), `exploits`
  (UNIQUE palier+nom → une annonce ne part jamais deux fois), `envois`, `comptes`
  (connexion Discord, voir plus bas).
- Fusion : on garde toujours le **niveau le plus haut** ; une race connue n'est
  jamais écrasée par « ? ».
- Dates (v1.3.0) : une montée de niveau est datée par l'addon quand il l'a vue
  (`GuildExportNiveaux`), sinon par la date de réception. `dater()` garde la date la plus
  ancienne connue, la plafonne à maintenant et rend l'historique monotone (un niveau ne
  peut pas être plus récent qu'un niveau supérieur). Dates ISO à la seconde.
- Classement des paliers **par date réelle** (`reclasser()`) : les annonces d'un envoi sont
  préparées par `verifier_exploits()` puis envoyées par `annoncer()` une fois tout le fichier
  intégré, triées par date (v1.3.1, corrige deux « 1ᵉʳ » dans un même envoi) ; entre deux
  envois, le rang annoncé est celui connu à la réception ; le tableau d'honneur se corrige si une date plus
  ancienne arrive ensuite (`corriger_exploits()`, sans nouvelle annonce).
- Annonces Discord (`verifier_exploits` prépare, `annoncer()` envoie **un message par envoi**,
  une ligne par annonce avec la date réelle, puis « _— via Pseudo_ » une fois à la fin (pseudo
  de `cles.txt` ; rien pour la collecte serveur) ; découpé par lignes au-delà de ~1900 caractères) : chaque palier de 10 pour **tout le monde**,
  avec le rang (médaille pour le top 3, sinon ⭐ / 🏆 au 60) ; sans classement, tous
  les 5 niveaux dès 20 (25, 35, 45) et chaque niveau dès 50. Un envoi qui saute
  plusieurs niveaux n'annonce que les paliers de 10 franchis + le plus haut niveau
  « simple » s'il dépasse le dernier palier. Seuls les paliers de 10 sont stockés
  dans `exploits` ; le tableau d'honneur affiche le top 3 (10–50) et tous les 60.
- Routes : `/` (classement, tableau d'honneur, fil d'activité), `/contribuer`
  (formulaire), `POST /envoyer` (header `X-Cle`), `/collecter`, `/recap`,
  `/export.json`, `POST /reinitialiser` (vide toute la base, copie dans
  `<DB>.avant-reset`) — ces quatre protégées par `?token=`.
- Connexion Discord (v1.4.0, OAuth2 code, scopes `identify guilds.members.read connections`) : `/connexion`
  → Discord → `/auth/discord/callback` (vérifie `state`, être sur le serveur `discord_serveur_id`
  et avoir le rôle `discord_role_id` ; les IDs de `discord_admins` passent toujours) → session
  Flask (cookie signé par `/data/secret.key`, 30 jours). `/moi` : relier son compte à un pseudo
  (avec sa clé existante, ou en choisissant un pseudo absent de `cles.txt` → clé créée), afficher
  / régénérer sa clé. Liaison automatique (v1.4.1, `liaison_auto()`) : à la connexion, si le surnom
  sur le serveur, le nom affiché ou le nom d'utilisateur Discord est un pseudo de `cles.txt` encore
  libre (casse ignorée), le compte y est relié ; « choisir son pseudo » relie aussi un pseudo de
  `cles.txt` s'il correspond à un de ces noms. Risque assumé : un membre qui prend le surnom d'un
  autre avant lui récupère sa clé (seulement avec le rôle de la guilde ; l'admin peut délier). Table `comptes(discord_id, pseudo, cle, discord_nom, lie_le, battletag)` : `cle` NULL =
  clé de `cles.txt` ; une clé du site **remplace** celle de `cles.txt` pour ce pseudo
  (`contributeur()`). Connecté et relié, `/contribuer` n'exige plus de clé. `/admin` (admins) :
  délier un compte, voir les clés de `cles.txt` sans compte, vider la progression (pas les comptes).
  Secret vide = connexion désactivée (404), tout le reste marche comme avant. `URL_SITE`
  (`GUILDE_URL`, défaut https://quartz.gawel.be) sert à l'URL de redirection.
- BattleTag (v1.5.0) : scope `connections`, `GET /users/@me/connections` à chaque connexion → entrée
  `type == "battlenet"`, champ `name` (ex. `Gawel#2345`) ; stocké dans `comptes.battletag`
  (colonne ajoutée par `init_db()` sur les anciennes bases), remis à jour (ou effacé) à chaque
  connexion ; un échec de lecture ne bloque pas la connexion. Visible sur `/moi` et `/admin`
  seulement (pas sur la page publique). Le jeton OAuth n'est pas conservé : aucune lecture hors connexion.
- Variables d'env (posées par run.sh depuis les options de l'app) : `NOM_GUILDE`,
  `GUILDE_TOKEN`, `DISCORD_WEBHOOK`, `GUILDE_DB=/data/guilde.db`,
  `GUILDE_CLES=/config/cles.txt`, `GUILDE_EXPORT`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
  `DISCORD_SERVEUR_ID`, `DISCORD_ROLE_ID`, `DISCORD_ADMINS`. Webhook vide = messages
  seulement dans le journal (mode test).
- Version (v1.4.3) : `VERSION` est lue dans `config.yaml` (copié dans l'image par le Dockerfile),
  affichée en pied de page (`PIED`) et ajoutée aux URL des images (`logo.png?v=…`,
  `banniere.jpg?v=…`) : Cloudflare et les navigateurs gardent les images en cache
  (`max-age=86400`) ; sans ce suffixe, l'ancien logo à fond gris de la v1.1.0 restait affiché.

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

## État au 30 octobre 2026 (v1.4.3 déployée, v1.5.0 en PR)
- ✅ Connexion Discord (v1.4.0, testée par Gaël) : application Discord **Quartz Forever** (Client ID
  `1565628978633515028`, redirection `https://quartz.gawel.be/auth/discord/callback`), serveur
  `801395490372583426`, rôle `1549720665844613130`, admin = Gaël `161139977328132107` (valeurs par
  défaut des options). **Secret client** renseigné dans l'option `discord_client_secret` (jamais
  commité ; le connecteur HA renvoie les options en clair, ne jamais le recopier).
  Compte de Gaël relié au pseudo `Gael`.
- ✅ v1.4.1 : liaison automatique par nom Discord ; v1.4.2 : logo redétouré, halo dans l'en-tête.
- ✅ v1.4.3 : version en pied de page, images en `?v=version` (vérifié en ligne : pied « v1.4.3 »).
- 🔜 v1.5.0 : BattleTag via les connexions Discord. Après déploiement, chacun doit se **reconnecter**
  (nouvelle autorisation demandée par Discord) pour que son BattleTag soit lu.
- ✅ App installée et démarrée, site en ligne sur https://quartz.gawel.be
- ✅ Route Cloudflared configurée
- ✅ `cles.txt` vérifié (30 membres, 0 ligne invalide, 0 CRLF, ni pseudo ni clé en double ;
  pseudos sans espaces ni `|`, accents possibles : `Metam-Zap`, `Patéhenkrout`, `Finwë`…).
  Ligne de test `TestClaude` retirée (clé refusée → 403) ; copie dans `cles.txt.bak`.
- ⏸️ Automatisations HA (collecte horaire, récap 9 h / 21 h) **coupées jusqu'au lancement** :
  `automation.quartz_reactivation_au_lancement` les réactive à la date/heure de
  `input_datetime.quartz_lancement_wow_forever` (5/11/2026 00:00, changer la date si besoin).
- ⚠️ Webhook Discord (option `discord_webhook`) **remis sur le canal de test** (29/10) ;
  à rebasculer sur le vrai salon de progression avant le lancement (l'URL n'est jamais commitée)
- ✅ Test de bout en bout validé (envoi direct + formulaire, fusion, annonces, récap,
  `/export.json`, script `client/` sous Windows). ⚠️ La base contient encore les **données de test**
  du 29/10 : la vider avant la distribution (bouton de `/admin`, les comptes sont conservés).
- ✅ v1.2.0 : nouvelles règles d'annonce ; v1.2.1 : cristal HD détouré + bannière
- ✅ Connecteur MCP Home Assistant de Claude : URL avec chemin secret, **sans OAuth**
  (si « needs_reconnect » → supprimer et recréer le connecteur avec l'URL complète)

## Outils utiles pour Claude (via le connecteur HA)
- Appeler l'app directement : `ha_manage_app(slug="local_quartz_forever", port=8080,
  path=..., method=...)` — permet `/export.json?token=…`, `POST /reinitialiser?token=…`,
  `POST /envoyer` (header `X-Cle`) sans passer par Cloudflare (bloqué par le proxy de session).
- `rest_command.quartz_collecter` / `quartz_recap` : `ha_call_service(..., return_response=True)`.
  `rest_command.quartz_reinitialiser` (voir `ha/configuration.yaml`) **n'est pas** configuré côté HA.
- Logs de l'app : `ha_get_logs(source="supervisor", slug="local_quartz_forever")`.
- Le connecteur ne lit pas les fichiers (`cles.txt`, `configuration.yaml`) : passer par Terminal & SSH.
- « Clé inconnue » sur `/contribuer` alors que `cles.txt` est bon = clé mal saisie
  (ligne entière collée, autoremplissage du navigateur) ; l'app lit bien
  `/app_configs/local_quartz_forever/cles.txt`.

## To-do
1. ~~Créer `cles.txt` avec les clés des membres.~~ ✅ fait
2. ~~Automatisations HA~~ ✅ fait (29/10) : `rest_command.quartz_collecter` / `quartz_recap`
   chargés (secrets internes, token de l'app renseigné, appels testés → 200),
   automatisations `automation.quartz_collecte_horaire` (toutes les heures à :00) et
   `automation.quartz_recap_discord_9_h_21_h` (9 h / 21 h : collecte puis récap) ;
   coupées jusqu'au 5/11, réactivation automatique (voir État).
3. Webhook Discord : configuré, mais **actuellement sur le canal de test** → remettre le vrai
   salon de progression dans l'option `discord_webhook` avant le 5/11.
4. ~~Tester de bout en bout~~ ✅ fait (29/10), base remise à zéro ensuite.
5. Vérifier le numéro `## Interface:` de l'addon sur le client Forever ; tester
   l'addon en jeu (race via cible/survol/groupe).
6. Créer un client API sur develop.battle.net, lancer `tools/verifier_api_blizzard.py` sur un
   perso Classic Era ; vérifier si l'endpoint de liste de guilde existe.
7. Surveiller la publication de l'espace de noms API Forever ; brancher
   `lire_api_blizzard()`.
8. **Prochaine étape** — distribuer à la guilde : addon, `client/`, `docs/README-guilde.md`,
   lien https://quartz.gawel.be/moi (connexion Discord : liaison auto si le nom Discord = pseudo,
   sinon clé en MP ou nouveau pseudo).
9. Plus tard : sauvegarde nuitière de `/export.json` par Home Assistant.
10. Plus tard : notification HA (en plus de Discord) quand un membre passe 60.
11. Idées en attente : graphiques de progression, fiche par personnage, maquette
    artefact pour présenter le projet à la guilde.
