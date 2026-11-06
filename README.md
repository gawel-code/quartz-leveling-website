# Quartz Forever — suivi de progression de guilde

Site public de progression de la guilde **Quartz Forever** (Horde, serveur PvE) sur
**World of Warcraft: Forever** (lancement le 5 novembre 2026, niveau max 60) :
classement des membres, tableau d'honneur des paliers, classement des morts, fil d'activité et annonces Discord.

**En ligne :** https://quartz.gawel.be — **Version du serveur :** 1.15.1

## Fonctionnement

Les données viennent de deux sources qui se complètent : l'**API Blizzard** (roster de la guilde
et profils, lus par le site à chaque collecte, depuis la v1.13.0 pour Forever) et un **addon en
jeu**, dont les membres envoient le fichier de sauvegarde au site (dates de niveau plus précises,
races des membres dont le profil n'est pas publié).

```
WoW + addon GuildExport ──► GuildExport.lua (SavedVariables, écrit à la déconnexion / /reload)
        │
        ├─► client/envoi-guilde.ps1 (envoi automatique)  ─┐
        └─► formulaire https://quartz.gawel.be/contribuer ─┴─► POST /envoyer (clé perso)
                                                                    │
                          app Flask + SQLite (app locale Home Assistant, HAOS)
                                                                    │
            Cloudflare Tunnel ◄─────────────────────────────────────┤
            Home Assistant : collecte /30 min + récap 9 h / 21 h ───┴─► webhook Discord
```

- **Addon** : dépôt séparé [gawel-code/quartz-leveling-addon](https://github.com/gawel-code/quartz-leveling-addon).
  Il exporte la liste de guilde (nom, race, classe, niveau) et l'heure des montées de niveau.
- **Connexion Discord** (OAuth2) : un membre du serveur Discord de la guilde, avec le rôle
  de la guilde, se connecte sur `/moi`, relie son compte à son pseudo (avec sa clé actuelle,
  ou en choisissant un pseudo : une clé est alors créée) et y retrouve sa clé. Si son surnom sur
  le serveur, son nom affiché ou son nom d'utilisateur Discord est un pseudo libre de `cles.txt`,
  le compte est relié automatiquement dès la connexion. Si le membre a lié Battle.net à Discord
  (*Paramètres → Connexions*), son **BattleTag** est récupéré et affiché sur `/moi` et `/admin` ;
  sinon il peut le saisir lui-même sur `/moi` (marqué « saisi » dans l'admin, non vérifié). Connecté, il
  envoie son fichier sans saisir de clé. Les admins (IDs Discord) passent toujours et ont `/admin`.
- **Personnages ↔ joueurs** : dans le classement, chaque personnage affiche son joueur
  (`@Pseudo`), avec un lien vers son profil Discord si son compte est relié. L'association vient,
  par ordre de fiabilité : de l'addon (≥ 1.2.0, table `GuildExportMesPersos` : les persos du compte
  WoW qui a écrit le fichier sont associés au pseudo de la clé qui l'envoie), d'un ajout à la main
  sur `/moi` (« C'est mon personnage »), ou d'un perso qui porte le nom du pseudo. Une future
  connexion Battle.net (armurerie) pourra fournir une source vérifiée « blizzard ». Dans `/admin`,
  un officier associe n'importe quel perso à n'importe quel joueur ou le dissocie : son choix
  l'emporte sur tout et n'est jamais remplacé automatiquement.
- **Envoi** : chaque membre a une clé personnelle (`cles.txt` côté serveur, ou créée sur le site). Le script
  PowerShell renvoie le fichier dès qu'il change ; le formulaire `/contribuer` permet un envoi manuel.
- **Fusion** : on garde toujours le niveau le plus haut ; une race connue n'est jamais
  écrasée par `?`. Envoyer un vieux fichier ne fait rien régresser.
- **Dates réelles** : quand l'addon fournit l'heure d'une montée de niveau, c'est elle qui
  compte (la plus ancienne connue gagne, jamais dans le futur) ; sinon, l'heure de réception.
- **Courbe de progression** (accueil) : du 4 novembre au 1ᵉʳ janvier au minimum (l'axe s'allonge
  ensuite tout seul), jour après jour : niveau moyen, plage où se trouvent 50 % des membres (Q1–Q3)
  et plus haut niveau ; les personnages du membre connecté y sont tracés à la couleur de leur classe.
  Survol : tous les chiffres du jour ; « Voir les données » : le tableau.
- **Fiche personnage** (`/perso/<nom>`, v1.12.0) : récap du leveling d'un membre : race, classe,
  rang de guilde, joueur ; place au classement, rythme moyen (niveaux par jour entre le premier et
  le dernier niveau vus, affiché après 24 h de données), niveaux gagnés en 24 h ; paliers 10 → 60 avec date réelle, rang dans la
  guilde et temps depuis le palier précédent ; courbe du perso face à la guilde ; historique daté de
  chaque niveau. Lien depuis le classement, le tableau d'honneur, le fil d'activité et « Mes
  personnages » (`/moi`). Un perso inconnu ou exclu (mule, banque) donne une 404.
- **Mules et banques** : dans `/admin`, un personnage peut être exclu de la progression (mule,
  banque, autre) : il sort du classement, du tableau d'honneur, des annonces, du récap et de la
  courbe ; ses niveaux restent enregistrés et « Réintégrer » lui rend ses paliers, sans annonce.
- **Contributeurs** : la page d'accueil met en avant les 3 membres qui ont signalé le plus de
  montées de niveau (premier envoi à les apprendre au site), puis le plus d'envois ; la liste
  complète (envois, persos lus, dernier envoi) est dans `/admin`. La collecte serveur ne compte pas.
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
| `ha-app/quartz_forever/` | **le serveur** : app locale Home Assistant (`config.yaml`, `Dockerfile`, `run.sh`, `app.py`, images ; `icon.png` = icône de l'app dans Home Assistant) |
| `client/` | envoi automatique pour les membres (Windows) : `lancer.bat` (double-clic ; demande la clé au premier lancement, trouve le fichier, journal dans `%APPDATA%\QuartzForever\envoi.log`), `changer-cle.bat`, `envoi-guilde.ps1` |
| `docs/README-guilde.md` | mode d'emploi non technique pour la guilde |
| `ha/configuration.yaml` | `rest_command` et automatisations à ajouter dans Home Assistant |
| `repository.yaml` | déclare ce dépôt comme dépôt d'apps Home Assistant |
| `tools/generer_cles.py` | génère ou renouvelle les clés des membres dans `cles.txt` |
| `tools/verifier_api_blizzard.py` | teste l'API Blizzard sur Classic Era ou Forever (`--jeu forever`, `--version-static`) : jeton, races/classes, royaumes, roster de guilde, profil (`--perso gawel-zugzug` sur Forever) ; `--compte` : connexion Battle.net (`wow.profile`, retour sur `http://localhost:8765/` à déclarer sur develop.battle.net), persos du compte et ce que répondent leurs liens, réponses brutes dans `compte-<jeu>.json` (non commité) ; `BNET_CLIENT_ID` / `BNET_CLIENT_SECRET`, `--help` |
| `tests/test_app.py` | tests du serveur |
| `CLAUDE.md` | notes de projet détaillées (état, pièges de déploiement, to-do) |

## Serveur

Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.

### Routes

| Route | Accès | Rôle |
|---|---|---|
| `GET /` | public | classement, tableau d'honneur, classement des morts, fil d'activité |
| `GET /perso/<nom>` | public | fiche d'un personnage (404 si inconnu ou exclu) |
| `GET/POST /contribuer` | clé du membre | formulaire d'envoi du fichier `GuildExport.lua` |
| `POST /envoyer` | en-tête `X-Cle` | envoi du fichier (utilisé par le script PowerShell) |
| `GET/POST /collecter` | `?token=` | lit le roster sur l'API Blizzard (si configurée), sinon intègre le fichier déposé côté serveur ; renvoie `mises_a_jour` et `source` (`blizzard`, `fichier` ou `null`) |
| `GET/POST /recap` | `?token=` | publie le récapitulatif sur Discord |
| `GET /connexion`, `/auth/discord/callback`, `/deconnexion` | public | connexion Discord (OAuth2, scopes `identify guilds.members.read connections`) ; les boutons pointent directement sur discord.com (ouverture de l'app Discord sur mobile si installée), `/connexion` reste une redirection équivalente |
| `GET/POST /moi` | session Discord | relier son compte, afficher / régénérer sa clé |
| `GET/POST /admin` | admin Discord | comptes reliés (délier), clés sans compte, vider la progression |
| `GET /export.json` | `?token=` | export complet de la base |
| `POST /reinitialiser` | `?token=` | vide la base (copie de sauvegarde dans `guilde.db.avant-reset`) |

Si l'option `token` est vide, les routes protégées sont fermées.

### Données

Tables SQLite (`/data/guilde.db`) : `personnages` (état courant), `historique` (une ligne
par niveau atteint, avec sa date), `exploits` (paliers de 10, rang par date réelle),
`envois` (journal des envois), `morts` (statistiques de morts de l'API, v1.14.0), `proprietaires` (perso → pseudo, source), `inactifs` (persos exclus :
mules, banques), `comptes` (Discord ↔ pseudo, BattleTag lu sur Discord ou saisi ; clé créée sur le site, sinon
celle de `cles.txt`, qu'elle remplace). Dates ISO à la seconde. `/reinitialiser` vide la
progression, les envois, les morts, les associations et les exclusions de personnages, mais pas les comptes (pseudos, clés,
BattleTags), les noms des rangs ni les sessions. Les sessions sont signées par `/data/secret.key` (créée au premier démarrage).

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
| `bnet_client_id` / `bnet_client_secret` | client API créé sur develop.battle.net ; vide = API Blizzard désactivée |
| `bnet_region` | région de l'API (`eu`) |
| `bnet_espace` | jeu dans l'espace de noms : `classic1x` (Classic Era, SoD, Anniversary) ; `forever` pour WoW Forever |
| `bnet_version_static` | version de l'espace statique (races, classes), ex. `1.60.1_70399` → `static-1.60.1_70399-forever-eu` ; vide = sans version, puis repli sur la version citée par le roster |
| `bnet_royaume` / `bnet_guilde` | royaume et guilde lus (noms ou slugs) ; `bnet_guilde` vide = API désactivée ; `bnet_royaume` **vide pour Forever** (guildes sans royaume) |

**API Blizzard** (v1.9.0) : à chaque `/collecter`, le roster de la guilde (nom, race, classe,
niveau) est lu et fusionné comme un envoi (niveau le plus haut gardé, annonces normales, sans
« via »). Une montée de niveau est datée par la dernière connexion du personnage (profil), si
elle est postérieure à la collecte précédente, sinon par l'heure de collecte ; l'addon, plus
précis, l'emporte s'il donne une date plus ancienne. Homonymes sur des royaumes connectés : le
plus haut niveau l'emporte. API en panne → repli sur le fichier déposé côté serveur.

**WoW Forever** (v1.13.0, réglages : `bnet_espace = forever`, `bnet_royaume` vide, `bnet_guilde =
Quartz Forever`) : la guilde se lit sans royaume (`/data/wow/guild/quartz-forever/roster`,
`profile-forever-eu`). Un perso y a un prénom et un nom de famille (`surname`) ; il est enregistré
sous « Prénom Nom » (« Gawel Zugzug »), **comme l'addon**, ce qui met à jour les fiches existantes
au lieu de les dupliquer. Le roster étant en retard sur les profils, le profil de chaque membre
(`/profile/wow/character/gawel-zugzug`) est lu à chaque collecte : niveau le plus haut des deux,
montée datée par la dernière connexion. Une classe déjà connue n'est jamais remplacée (l'API la
donne au masculin, l'addon au féminin). Espaces de noms : `profile-` et `dynamic-forever-eu`,
statique versionné `static-1.60.1_70399-forever-eu` (`static-forever-eu` répond aussi depuis le
5/11). Forever ajoute deux races : « Éolide de l'Ordre suprême » (Alliance) et « Éolide
sculpte-vents » (Horde).

**Morts** (v1.14.0) : pour chaque membre dont le profil est publié, la collecte lit aussi
`/profile/wow/character/{slug}/achievements/statistics` (une requête de plus par membre) et en garde
la catégorie « Morts » : total, « Donjons et raids » (total et donjons à 5), « En extérieur »
(noyade, chute…) ; la sous-catégorie « Résurrection » est ignorée. Un perso jamais mort n'a pas
cette catégorie : 0. Un compteur ne baisse jamais (profil publié en retard). L'accueil affiche le
**classement des morts** (total, une colonne par catégorie, « Autres » = total − catégories, surtout
les créatures en extérieur ; détail au survol du total), la fiche du perso le détail et sa place.

**Spécialisations** (v1.15.0) : la collecte lit aussi `/profile/wow/character/{slug}/specializations`
(une requête de plus par membre au profil publié). Comme sur Classic, l'API donne les arbres de talents
du groupe actif avec le rang de chaque talent : la spé retenue est l'arbre le plus fourni (égalité : le
premier listé), la répartition est gardée pour l'infobulle (« Equilibre — Equilibre 9 · Restauration 8 »,
« Protection — 7 points »). Une icône dessinée pour le site, inspirée de l'icône de la spé en jeu
(27 spés : bouclier pour Protection, patte pour Maîtrise des bêtes, lune pour Équilibre…), s'affiche
devant la classe dans le classement, la fiche (« Guerrier Protection »), « Mon compte » et l'admin.

**Rangs de la guilde** (v1.10.0) : le roster de l'API et l'addon (≥ 1.3.0, table `GuildExportRangs`)
donnent le numéro de rang de chaque membre (0 = maître de guilde, même numérotation), pas son nom. Les noms se définissent dans `/admin` (bloc « Rangs de la guilde ») ; le
classement de la page d'accueil affiche une colonne « Rang » dès qu'un rang est connu (« Rang N »
tant qu'il n'a pas de nom). Ces noms forment un référentiel : la remise à zéro ne les vide pas.
Un fichier sans `GuildExportRangs` (addon < 1.3.0) garde le rang déjà connu ; sinon le dernier
envoi ou la dernière collecte l'emporte.

Les clés des membres sont dans `/app_configs/ee5b467c_quartz_forever/cles.txt`
(une ligne `Pseudo:clé` par membre, relu à chaque envoi, sans redémarrage).

## Déploiement

L'app est installée depuis ce dépôt, déclaré comme **dépôt d'apps Home Assistant**
(`repository.yaml`, URL `https://github.com/gawel-code/quartz-leveling-website`, dépôt public).
Slug **`ee5b467c_quartz_forever`**, hôte interne **`ee5b467c-quartz-forever`**, exposée par
Cloudflare Tunnel sur `quartz.gawel.be`. Configuration, base (`guilde.db`, `secret.key`) et
`cles.txt` : `/app_configs/ee5b467c_quartz_forever/` (inclus dans les sauvegardes HA).

**Déployer** = merger dans `main` une version dont `version` (`ha-app/quartz_forever/config.yaml`)
a été augmentée. HA propose alors la mise à jour (Paramètres → Apps), installée automatiquement
(« Mise à jour automatique » activée) ou tout de suite par Claude via le connecteur HA. Aucune
console. La version s'affiche en pied de page et suffixe les URL des images (`logo.png?v=…`),
ce qui contourne le cache de Cloudflare et des navigateurs.

Historique : jusqu'à la v1.11.0, l'app était une app locale (`local_quartz_forever`) déployée
par un script dans Terminal & SSH ; migrée vers le dépôt d'apps le 30/10/2026 (base copiée
depuis `/app_configs/local_quartz_forever/`), ancienne app désinstallée et script supprimé.

Côté Home Assistant, `rest_command.quartz_collecter` et `rest_command.quartz_recap`
sont appelés par deux automatisations (collecte toutes les 30 minutes, récap à 9 h et 21 h).
L'API Blizzard autorise 36 000 requêtes/h (100/s) ; une collecte en consomme 1 + 1 par perso
qui a pris un niveau, donc on peut collecter souvent sans risque.

## Développement

```bash
pip install flask requests pytest
pytest -q
```

## Historique des versions

| Version | Changements |
|---|---|
| 1.15.1 | Collecte plus rapide : profil, statistiques et spé de chaque membre lus en parallèle (8 requêtes simultanées) ; à la suite, la collecte dépassait les 10 s du `rest_command` de Home Assistant (erreur, récap de 9 h / 21 h bloqué) ; gunicorn `--timeout 120` |
| 1.15.0 | Spécialisation de chaque perso lue sur l'API Blizzard (arbre de talents le plus fourni, colonnes `personnages.specialisation` et `talents`) ; icône de spé dessinée pour le site (27 spés, inspirées des icônes du jeu) devant la classe, répartition des talents en infobulle ; couleur de classe aussi pour les libellés au féminin de l'addon (« Guerrière » était en blanc) ; filtre de classe du classement sans doublons masculin / féminin |
| 1.14.0 | Classement des morts : statistiques de morts lues sur l'API Blizzard à chaque collecte (table `morts`, par catégorie : donjons et raids, en extérieur, autres), classement sur l'accueil, détail sur la fiche ; vidées par la remise à zéro, incluses dans `/export.json` |
| 1.13.0 | API Blizzard pour WoW Forever : guilde lue sans royaume, persos enregistrés sous « Prénom Nom » comme l'addon (fusion avec les fiches existantes), profil de chaque membre lu à chaque collecte (niveau plus récent que le roster, date de dernière connexion), classe connue jamais remplacée (garde le féminin) ; option `bnet_version_static` (espace statique versionné) ; `tools/verifier_api_blizzard.py --jeu forever` et `--compte` (connexion Battle.net, persos du compte) |
| 1.12.1 | fiche personnage : rythme moyen affiché seulement après 24 h de données (5 niveaux en 1 h 30 donnaient « 73,9 niveaux par jour ») |
| 1.12.0 | fiche par personnage `/perso/<nom>` : identité, place, rythme, paliers (date, rang, durée), courbe face à la guilde, historique des niveaux ; liens depuis l'accueil et `/moi` |
| 1.11.0 | dépôt déclaré comme dépôt d'apps Home Assistant (`repository.yaml`) pour des mises à jour sans console ; base et clé de session déplacées de `/data` vers `/config` (`/app_configs/<slug>/`), migration automatique au démarrage ; lien vers le site sur la fiche de l'app |
| 1.10.1 | connexion Discord : liens directs vers discord.com (l'app Discord peut s'ouvrir sur mobile) et `state` signé valable 10 min, indépendant du cookie (le retour marche dans un autre navigateur) ; colonne « Vers 60 » renommée « Progression » ; dans l'admin, mention quand aucun membre n'a encore de rang connu (colonne « Rang » cachée) |
| 1.10.0 | rangs de la guilde : numéro lu dans le roster de l'API, et dans le fichier de l'addon ≥ 1.3.0 (`GuildExportRangs`), noms définis dans l'admin (conservés par la remise à zéro), colonne « Rang » dans le classement de l'accueil |
| 1.9.0 | collecte automatique par l'API Blizzard (roster de guilde, races et classes en français, montées datées par la dernière connexion) ; options `bnet_*` ; `/collecter` indique la source lue ; script `tools/verifier_api_blizzard.py` enrichi (royaumes, roster, profil) |
| 1.8.0 | courbe de progression sur l'accueil (moyenne, Q1–Q3, plus haut niveau, persos du membre connecté) ; exclusion des mules et banques dans l'admin ; icône du cristal pour l'app dans Home Assistant (`icon.png`) |
| 1.7.0 | meilleurs contributeurs : top 3 sur la page d'accueil, liste complète dans l'admin ; la remise à zéro vide aussi les associations personnage ↔ joueur |
| 1.6.1 | « Mon compte » en blocs (profil, clé, personnages) ; personnages en cartes aux couleurs de classe avec emblème, ajout en un clic avec recherche ; admin en blocs pleine largeur, tableau de tous les persos avec choix du joueur sur chaque ligne et filtres |
| 1.6.0 | personnages reliés à leur joueur et à son profil Discord dans le classement (addon ≥ 1.2.0, ajout à la main sur « Mon compte », même nom que le pseudo) ; dans l'admin, associer / dissocier n'importe quel perso (choix prioritaire) |
| 1.5.1 | BattleTag saisi à la main sur « Mon compte » quand Battle.net n'est pas lié à Discord ; boutons « Mon compte » et « Déconnexion » (ou « Connexion Discord ») dans l'en-tête de toutes les pages |
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
