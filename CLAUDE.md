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
  SavedVariables. `lire_api_blizzard()` (v1.9.0) lit déjà le roster de guilde sur l'API
  (testée en production sur Classic, `classic1x`) : il restera à renseigner l'espace de noms,
  le royaume et la guilde de Forever (options `bnet_*`).

## Architecture
```
WoW (addon GuildExport) → GuildExport.lua (SavedVariables, écrit à la déconnexion / /reload)
   → envoi-guilde.ps1 (auto) ou formulaire /contribuer (manuel), clé perso par membre
     (clé affichée sur /moi après connexion Discord ; connecté, /contribuer n'en demande pas)
   → app Flask + SQLite dans une app locale Home Assistant (HAOS)
   → https://quartz.gawel.be via Cloudflare Tunnel
Home Assistant → rest_command → /collecter (toutes les 15 min) et /recap (9 h / 21 h) → webhook Discord
/collecter → API Blizzard (roster de guilde, si options bnet_*) sinon fichier déposé côté serveur
```

## Arborescence
- `README.md` : présentation du projet, routes, déploiement, historique des versions
  (à compléter à chaque bump de `version`).
- `ha-app/quartz_forever/` : l'app Home Assistant (config.yaml, build.yaml,
  Dockerfile, run.sh, app.py, logo.png = cristal détouré 204×256 (bord érodé de 3 px et adouci en v1.4.2 pour retirer le liseré clair),
  banniere.jpg = grotte de cristaux en fond d'en-tête, icon.png = cristal 128×128 transparent : icône
  de l'app dans la liste des apps de Home Assistant, lue par le Supervisor dans le dossier de l'app,
  pas dans l'image ; `logo.png` sert aussi de logo sur la fiche de l'app). **C'est le code du serveur.**
- L'addon WoW **GuildExport** vit dans le dépôt séparé **gawel-code/quartz-leveling-addon**. Format qu'il exporte
  (contrat avec `analyser_export()` du serveur, à garder synchronisé) :
  `["Nom"] = "Nom;Race;Classe;Niveau"`. Dates de niveau (v1.3.0) dans la table
  `GuildExportNiveaux` : `["Nom"] = "10@horodatage,11@horodatage"` (`analyser_dates()`). Rangs
  (addon 1.3.0) dans `GuildExportRangs` : `["Nom"] = "3"` (`analyser_rangs()`, 0 = maître de guilde).
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
- `tools/verifier_api_blizzard.py` : essais de l'API Blizzard (bibliothèque standard seulement) :
  jeton `client_credentials` (`BNET_CLIENT_ID` / `BNET_CLIENT_SECRET`), index races/classes
  (`static-…`), `--royaumes` (`dynamic-…`), `--guilde` (roster → lignes `Nom;Race;Classe;Niveau`,
  forme attendue de `lire_api_blizzard()`), `--perso` (profil). `--jeu classic1x` par défaut.
- `tools/generer_cles.py` : génère/renouvelle les clés des membres dans `cles.txt`.
- `tests/test_app.py` : tests pytest du serveur (`pytest -q`).

## Serveur (app.py)
- Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.
- Tables : `personnages`, `historique` (chaque montée de niveau), `exploits`
  (UNIQUE palier+nom → une annonce ne part jamais deux fois), `envois`, `comptes`
  (connexion Discord, voir plus bas), `proprietaires` (personnage → joueur, v1.6.0), `inactifs`
  (v1.8.0), `rangs` (référentiel des noms de rangs, v1.10.0). `personnages.rang` (n° de rang,
  v1.10.0) : les `INSERT` dans `personnages` nomment leurs colonnes (ne plus écrire `VALUES(?,?,?,?,?)`).
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
  `/export.json`, `POST /reinitialiser` (vide progression, envois, associations et exclusions — pas `comptes` ni `rangs` —, copie dans
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
  autre avant lui récupère sa clé (seulement avec le rôle de la guilde ; l'admin peut délier). Table `comptes(discord_id, pseudo, cle, discord_nom, lie_le, battletag, battletag_saisi)` : `cle` NULL =
  clé de `cles.txt` ; une clé du site **remplace** celle de `cles.txt` pour ce pseudo
  (`contributeur()`). Connecté et relié, `/contribuer` n'exige plus de clé. `/admin` (admins) :
  délier un compte, voir les clés de `cles.txt` sans compte, vider la progression et les associations (pas les comptes).
  Secret vide = connexion désactivée (404), tout le reste marche comme avant. `URL_SITE`
  (`GUILDE_URL`, défaut https://quartz.gawel.be) sert à l'URL de redirection.
- BattleTag (v1.5.0) : scope `connections`, `GET /users/@me/connections` à chaque connexion → entrée
  `type == "battlenet"`, champ `name` (ex. `Gawel#2345`) ; stocké dans `comptes.battletag`
  (colonne ajoutée par `init_db()` sur les anciennes bases), remis à jour (ou effacé) à chaque
  connexion ; un échec de lecture ne bloque pas la connexion. Visible sur `/moi` et `/admin`
  seulement (pas sur la page publique). Le jeton OAuth n'est pas conservé : aucune lecture hors connexion.
  Saisie manuelle (v1.5.1) : sans BattleTag Discord, `/moi` propose un champ (action `battletag`,
  `BATTLETAG_VALIDE` = `Nom#1234`, vide = effacer) → colonne `comptes.battletag_saisi` (non vérifiée,
  marquée « saisi » dans `/admin`). Le BattleTag Discord prime à l'affichage ; la saisie est gardée en réserve.
- Personnages ↔ joueurs (v1.6.0) : table `proprietaires(nom PK, pseudo, source, date)`.
  `associer()` : sources `admin` (choix d'officier, remplace tout, remplacé seulement par un autre
  choix d'officier) > `blizzard` > `addon` > `manuel` (une saisie manuelle ne prend jamais le perso
  d'un autre). `addon` = table `GuildExportMesPersos` du fichier
  (`analyser_mes_persos()`, addon ≥ 1.2.0) associée au pseudo de la clé à chaque `/envoyer` et
  `/contribuer`. `proprietaires()` ajoute d'office (source `nom`, non stockée) un perso qui porte le
  nom d'un pseudo (`cles.txt` ou `comptes`). Classement : `@Pseudo` après le nom, lien
  `https://discord.com/users/<discord_id>` si le pseudo a un compte relié. `/moi` : « Mes
  personnages » (retirer les ajouts manuels, « C'est mon personnage » parmi les persos sans joueur).
  `/admin` : formulaire « Associer » (tout perso connu × tout pseudo de `joueurs()` = `cles.txt` +
  `comptes`, source `admin`), tableau de toutes les associations (y compris `nom`, non dissociable :
  l'écraser par un choix d'officier) + « Dissocier ». **Vidé par la remise à zéro** (v1.7.0 ; les
  associations se refont au premier envoi avec l'addon), inclus dans `/export.json`.
  Source `blizzard` prévue pour une connexion Battle.net (scope `wow.profile`) quand l'API Forever existera.
- Interface (v1.6.1) : blocs `.carte.bloc` + `.bloc-tete` ; `/moi` = grille 2 colonnes (Profil avec
  BattleTag, Ma clé d'envoi) + bloc « Mes personnages » (cartes `.perso` couleur de classe, retrait
  des ajouts manuels, ajout en un clic parmi les persos libres avec recherche) ; première connexion
  = deux cartes (clé existante / nouveau pseudo). `/admin` : blocs pleine largeur ; tableau de
  **tous** les persos (sans joueur d'abord), `<select form=…>` du joueur par ligne + « Enregistrer »
  (« — aucun — » = supprimer l'association enregistrée), filtres état/texte en JS. Emblèmes de classe
  = SVG maison (`EMBLEMES`, `embleme()`, `CLASSES` gère le féminin), aucune image externe ;
  `couleur()` et `embleme()` exposés à tous les templates ; macro `carte_perso` dans `PERSO`.
- Contributeurs (v1.7.0) : `contributeurs(con, limite)` agrège `envois` par pseudo (hors `serveur`) :
  `montees` = somme de `nouveautes` (persos dont le niveau a monté, ou nouveaux, dans l'envoi : la
  montée est créditée au premier envoi qui l'apprend), `envois`, `lus`, `dernier` ; tri montées,
  envois, date. Top 3 sur `/` (bloc « Meilleurs contributeurs », caché sans envoi, lien Discord si
  compte relié), liste complète dans `/admin`. Remis à zéro avec la progression (table `envois`).
- Courbe (v1.8.0) : `courbe(con, mes_noms)` → séries quotidiennes de `DEBUT_COURBE` (4/11/2026) à
  `aujourdhui()` (patchable dans les tests) ; axe jusqu'à `max(FIN_COURBE_MIN = 1/1/2027, aujourd'hui)`.
  Niveau d'un perso en fin de journée = dernier niveau de `historique` avant minuit (`bisect`).
  Séries : `n`, `moyenne`, `min`, `q1`, `mediane`, `q3` (`quantile()`, interpolation linéaire), `max`,
  + `persos` du joueur connecté (via `proprietaires()`), couleur de classe. Exclus ignorés. JSON dans
  `<script id="donnees-courbe">`, dessiné en SVG par du JS maison dans `PAGE` (aucune bibliothèque) :
  bande Q1–Q3, moyenne, plus haut niveau, persos avec point final et étiquette (≤ 4), réticule +
  infobulle (`textContent`), clavier (←/→), redessin au redimensionnement, tableau dans `<details>`.
- Exclusions (v1.8.0) : table `inactifs(nom PK, motif, date)`, `MOTIFS` mule/banque/autre.
  `desactiver()` supprime les exploits du perso et reclasse ; `reactiver()` les recrée depuis
  `historique` (`date_atteinte`) sans annonce. `verifier_exploits()` ignore un exclu (ni palier ni
  annonce) ; exclus filtrés de `/` (classement, stats, fil), `gains()`, `recap()`, `courbe()`. Ses
  niveaux restent suivis. `/admin` : colonne « Progression » (motif + Exclure / Réintégrer), filtre
  « Exclus ». `/moi` : pastille sur un perso exclu. Vidé par la remise à zéro, dans `/export.json`.
- API Blizzard (v1.9.0) : `lire_api_blizzard()` → `(persos, dates)`, active si `bnet_actif()` (id,
  secret, royaume, guilde). `bnet_get()` : jeton `client_credentials` gardé dans `_bnet` jusqu'à
  expiration, `namespace = {profile|static}-{BNET_ESPACE}-{BNET_REGION}`, `fr_FR`, None si ≠ 200.
  `libelles()` met en cache les index race/classe. Roster → tuples `analyser_export()` ; homonyme =
  plus haut niveau. Pour un perso nouveau ou qui monte : profil (royaume du membre) → date du niveau
  = `last_login_timestamp` si le profil a le même niveau et si la date ≥ `personnages.maj` (dernière
  vue à l'ancien niveau ; sinon heure de connexion d'une session en cours) ; sinon `dater()` prend
  l'heure de collecte. `collecter()` → `(mises_a_jour, source)` (`blizzard` / `fichier` / None),
  source d'envoi `serveur` (pas de « via », hors contributeurs). Erreur réseau → `([], {})` → repli fichier.
- Rangs (v1.10.0) : `lire_api_blizzard()` → `(persos, dates, rangs)`, `rangs = {nom: rank}` du roster
  (entier, 0 = maître de guilde) ; `analyser_rangs(texte)` lit le bloc `GuildExportRangs` de l'addon
  ≥ 1.3.0 (`/envoyer`, `/contribuer`, repli fichier de `/collecter`) ; `integrer(..., rangs)` met à
  jour `personnages.rang` (le dernier envoi l'emporte ; sans table, ancien addon, le rang est gardé). Table `rangs(id PK, nom)` = référentiel
  saisi dans `/admin` (action `rangs` : champs `rang_<id>`, vide = supprimer, + `nouveau_id` /
  `nouveau_nom`), **non vidée** par `reinitialiser()`, dans `/export.json`. `noms_rangs(con)`.
  Bloc admin « Rangs de la guilde » : n° connus (`rangs` ∪ `personnages.rang`) + effectifs.
  Accueil : colonne « Rang » seulement si un perso a un rang (`avec_rangs`), nom ou « Rang N ».
  L'API ne fournit pas les noms des rangs ni les rôles (tank/soigneur/DPS).
- Variables d'env (posées par run.sh depuis les options de l'app) : `NOM_GUILDE`,
  `GUILDE_TOKEN`, `DISCORD_WEBHOOK`, `GUILDE_DB=/data/guilde.db`,
  `GUILDE_CLES=/config/cles.txt`, `GUILDE_EXPORT`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
  `DISCORD_SERVEUR_ID`, `DISCORD_ROLE_ID`, `DISCORD_ADMINS`, `BNET_CLIENT_ID`, `BNET_CLIENT_SECRET`,
  `BNET_REGION` (`eu`), `BNET_ESPACE` (`classic1x`), `BNET_ROYAUME`, `BNET_GUILDE`. Webhook vide = messages
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

## État au 30 octobre 2026 (v1.9.0 déployée, v1.10.0 en PR)
- ✅ Connexion Discord (v1.4.0, testée par Gaël) : application Discord **Quartz Forever** (Client ID
  `1565628978633515028`, redirection `https://quartz.gawel.be/auth/discord/callback`), serveur
  `801395490372583426`, rôle `1549720665844613130`, admin = Gaël `161139977328132107` (valeurs par
  défaut des options). **Secret client** renseigné dans l'option `discord_client_secret` (jamais
  commité ; le connecteur HA renvoie les options en clair, ne jamais le recopier).
  Compte de Gaël relié au pseudo `Gael`.
- ✅ v1.4.1 : liaison automatique par nom Discord ; v1.4.2 : logo redétouré, halo dans l'en-tête.
- ✅ v1.4.3 : version en pied de page, images en `?v=version` (vérifié en ligne : pied « v1.4.3 »).
- ✅ v1.5.0 : BattleTag via les connexions Discord (déployée, vérifiée : scope `connections`,
  migration sans erreur). Chacun doit se **reconnecter** (nouvelle autorisation) pour qu'il soit lu.
- ✅ v1.5.1 (mergée ; déploiement non confirmé) : saisie manuelle du BattleTag sur `/moi` ; « Mon compte » +
  « Déconnexion » (ou « Connexion Discord ») dans l'en-tête (`ENTETE`) de **toutes** les pages.
- ✅ v1.6.0 (mergée ; déploiement non confirmé) : personnages ↔ joueurs (+ addon 1.2.0 : `GuildExportMesPersos`, mergé).
- ✅ v1.6.1 (mergée ; déploiement non confirmé) : refonte visuelle de « Mon compte » et de l'admin.
- ✅ v1.7.0 (mergée ; déploiement non confirmé) : meilleurs contributeurs (top 3 sur l'accueil, liste
  complète dans l'admin) ; la remise à zéro vide aussi `proprietaires` (garde `comptes` et les sessions).
- ✅ v1.8.0 (mergée ; déploiement non confirmé) : courbe de progression sur l'accueil, exclusion des
  mules/banques dans l'admin, et `icon.png` de l'app HA (ex-PR v1.7.1, regroupée ici).
- ✅ v1.9.0 (déployée, vérifiée le 30/10) : collecte par l'API Blizzard. Pied « v1.9.0 ». Identifiants
  Battle.net de Gaël dans `bnet_client_id` / `bnet_client_secret` (jamais commités ni recopiés depuis
  le connecteur). Essai réel avec `bnet_royaume = Firemaw`, `bnet_guilde = Progress` :
  `/collecter` → `source: "blizzard"`, 6 persos (race, classe, niveau corrects), Kwindu daté par sa
  dernière connexion (27/10 18:06), annonces parties sur le canal de test.
- 🔜 v1.10.0 (PR ouverte) : rangs de la guilde (n° du roster, noms dans l'admin, colonne sur
  l'accueil), lus par l'API et par l'addon 1.3.0 (PR gawel-code/quartz-leveling-addon ouverte).
- ⚠️ **À remettre d'équerre avant le 5/11** : `bnet_royaume` / `bnet_guilde` pointent encore sur
  Firemaw / Progress (les vider, ou y mettre notre guilde quand l'API couvrira Forever, puis
  redémarrer l'app) ; la base contient les 6 persos de Progress + 3 persos de test (Grommash,
  Zuljin, Mokvar) → remise à zéro via `/admin` (les comptes sont conservés).
- ✅ App installée et démarrée, site en ligne sur https://quartz.gawel.be
- ✅ Route Cloudflared configurée
- ✅ `cles.txt` vérifié (30 membres, 0 ligne invalide, 0 CRLF, ni pseudo ni clé en double ;
  pseudos sans espaces ni `|`, accents possibles : `Metam-Zap`, `Patéhenkrout`, `Finwë`…).
  Ligne de test `TestClaude` retirée (clé refusée → 403) ; copie dans `cles.txt.bak`.
- ⏸️ Automatisations HA (collecte toutes les 15 min depuis le 30/10, récap 9 h / 21 h) **coupées jusqu'au lancement** :
  `automation.quartz_reactivation_au_lancement` les réactive à la date/heure de
  `input_datetime.quartz_lancement_wow_forever` (5/11/2026 00:00, changer la date si besoin).
- ⚠️ Webhook Discord (option `discord_webhook`) **remis sur le canal de test** (29/10) ;
  à rebasculer sur le vrai salon de progression avant le lancement (l'URL n'est jamais commitée)
- ✅ Test de bout en bout validé (envoi direct + formulaire, fusion, annonces, récap,
  `/export.json`, script `client/` sous Windows). Données de test encore en base : voir ⚠️ ci-dessus.
- ✅ v1.2.0 : nouvelles règles d'annonce ; v1.2.1 : cristal HD détouré + bannière
- ✅ Connecteur MCP Home Assistant de Claude : URL avec chemin secret, **sans OAuth**
  (si « needs_reconnect » → supprimer et recréer le connecteur avec l'URL complète)

## API Blizzard — essais sur Classic du 30/10/2026 (`tools/verifier_api_blizzard.py`)
- Client API créé par Gaël sur develop.battle.net (identifiants chez lui, jamais commités) ;
  flux `client_credentials` OK.
- L'espace `classic1x` (EU) regroupe Classic Era, Season of Discovery, Anniversary et Season
  (`--royaumes`) ; aucun royaume Forever pour l'instant. Forever arrivera peut-être là plutôt
  que dans un nouvel espace : relancer `--royaumes` à l'approche du lancement.
- **Roster de guilde** `/data/wow/guild/{royaume}/{guilde}/roster` (`profile-…`) : marche et donne
  nom, niveau, `playable_race.id`, `playable_class.id`, rang, et le **royaume de chaque membre**
  (royaumes connectés : un membre de `<Progress>`/Firemaw est sur `gandling`). Index
  `playable-race` / `playable-class` (`static-…`, `fr_FR`) → libellés FR masculins, mêmes que le
  client (OK pour `CLASSES`, `couleur()`, `embleme()`).
- À vérifier : roster complet ? (6 membres seulement pour `<Progress>`, guilde pourtant active :
  dernière connexion d'un membre le 27/10/2026).
- Profil `/profile/wow/character/{royaume}/{nom}` : race, classe, niveau, guilde,
  `last_login_timestamp` (ms). Aucune date de montée de niveau dans l'API. En production, 5 profils
  sur 6 de `<Progress>` → **404** alors qu'ils sont dans le roster (royaumes `mograine`,
  `earthshaker`, `ashbringer`, `gandling`, `firemaw`) : sans doute des persos inactifs dont Blizzard
  ne publie plus le profil ; repli sur l'heure de collecte, comme prévu. Quotas : 36 000 req/h,
  100 req/s ; une collecte = 1 roster + 1 profil par perso qui monte.
- Branché en v1.9.0 (voir *Serveur*). À vérifier sur Forever : espace de noms, complétude du
  roster, sens exact de `last_login_timestamp` (connexion ou dernière sauvegarde ?).

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
   automatisations `automation.quartz_collecte_horaire` (toutes les 15 min depuis le 30/10 —
   `time_pattern` `/15`, alias « Quartz – collecte toutes les 15 min », entity_id inchangé) et
   `automation.quartz_recap_discord_9_h_21_h` (9 h / 21 h : collecte puis récap) ;
   coupées jusqu'au 5/11, réactivation automatique (voir État).
3. Avant le 5/11 : remettre le vrai salon de progression dans l'option `discord_webhook`
   (actuellement canal de test) ; vider `bnet_royaume` / `bnet_guilde` (Progress) ; remettre la
   base à zéro (persos de Progress et de test).
4. ~~Tester de bout en bout~~ ✅ fait (29/10), base remise à zéro ensuite.
5. Vérifier le numéro `## Interface:` de l'addon sur le client Forever ; tester
   l'addon en jeu (race via cible/survol/groupe).
6. ~~Client API develop.battle.net + essais Classic Era~~ ✅ fait (30/10) : roster OK avec la race.
7. Surveiller la publication de l'espace de noms API Forever (`--royaumes`) ; renseigner
   `bnet_espace` / `bnet_royaume` / `bnet_guilde` (`lire_api_blizzard()` est branchée en v1.9.0). Avec une connexion Battle.net (OAuth `wow.profile`, liste des persos du
   compte), associer les persos avec la source `blizzard` (`associer()`).
8. **Prochaine étape** — distribuer à la guilde : addon, `client/`, `docs/README-guilde.md`,
   lien https://quartz.gawel.be/moi (connexion Discord : liaison auto si le nom Discord = pseudo,
   sinon clé en MP ou nouveau pseudo).
9. Plus tard : sauvegarde nuitière de `/export.json` par Home Assistant.
10. Plus tard : notification HA (en plus de Discord) quand un membre passe 60.
11. Idées en attente : graphiques de progression, fiche par personnage, maquette
    artefact pour présenter le projet à la guilde.
