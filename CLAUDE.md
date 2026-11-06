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
- Flux habituel : PR → « oui merge » → déploiement (mise à jour de l'app HA, automatique ou lancée
  par Claude via le connecteur depuis la v1.11.0) → vérification par Claude via le connecteur HA.
- Jamais de secret commité (webhook Discord, token de l'app, secret client Discord, clés).

## Contexte
- **WoW Forever** (Blizzard) : lancement mondial le **5 novembre 2026** (minuit,
  heure de Paris). Niveau max 60, toutes les races de Classic, **paladin et chaman
  disponibles des deux côtés**.
- Guilde **Quartz Forever**, **Horde**, serveur **PvE**.
- Objectif : site public qui suit la progression des membres (race, classe,
  niveau), tableau d'honneur, annonces Discord.
- **API Blizzard** : la guilde Forever est lisible depuis le 5/11 après-midi (sans royaume) ; collecte
  par l'API (`lire_api_blizzard()`, v1.13.0 pour Forever) **et** par l'**addon en jeu** dont les membres
  envoient le fichier SavedVariables (mêmes noms « Prénom Nom », les deux se complètent).

## Architecture
```
WoW (addon « Quartz Guild Exporter », dossier GuildExport) → GuildExport.lua (SavedVariables, écrit à la déconnexion / /reload)
   → envoi-guilde.ps1 (auto) ou formulaire /contribuer (manuel), clé perso par membre
     (clé affichée sur /moi après connexion Discord ; connecté, /contribuer n'en demande pas)
   → app Flask + SQLite, app Home Assistant (HAOS) installée depuis ce dépôt (dépôt d'apps)
   → https://quartz.gawel.be via Cloudflare Tunnel
Home Assistant → rest_command → /collecter (toutes les 30 min depuis le 5/11) et /recap (9 h / 21 h) → webhook Discord
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
- L'addon WoW **Quartz Guild Exporter** (dossier et fichier `GuildExport`, nom affiché depuis l'addon 1.3.1) vit dans le dépôt séparé **gawel-code/quartz-leveling-addon**. Format qu'il exporte
  (contrat avec `analyser_export()` du serveur, à garder synchronisé) :
  `["Nom"] = "Nom;Race;Classe;Niveau"`. Dates de niveau (v1.3.0) dans la table
  `GuildExportNiveaux` : `["Nom"] = "10@horodatage,11@horodatage"` (`analyser_dates()`). Rangs
  (addon 1.3.0) dans `GuildExportRangs` : `["Nom"] = "3"` (`analyser_rangs()`, 0 = maître de guilde).
  **Noms de famille** (vu en jeu le 5/11) : sur Forever, un perso s'appelle « Prénom Nom »
  (« Gawel Zugzug », « Wagyu Steak ») ; les noms contiennent donc des **espaces** (OK pour les
  expressions du serveur, `[^"]+`). La liste de guilde donne le nom complet, `UnitName()` seulement
  le prénom : l'addon ≤ 1.3.1 notait races et `GuildExportMesPersos` au prénom (race « ? » sur le
  site, perso non associé). Corrigé dans l'addon 1.3.2 (nom complet retrouvé par GUID, sinon prénom
  unique), sans changement de format.
  Piège vu le 5/11 : envoyer `Interface\AddOns\GuildExport\GuildExport.lua` (le **code** de l'addon,
  même nom) au lieu du fichier de `WTF\…\SavedVariables\` → « Fichier vide ou invalide » (400).
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
- `repository.yaml` (v1.11.0) : fait du dépôt un dépôt d'apps HA (le Supervisor trouve
  `ha-app/quartz_forever/config.yaml` en parcourant le dépôt).
- `tools/verifier_api_blizzard.py` : essais de l'API Blizzard (bibliothèque standard seulement) :
  jeton `client_credentials` (`BNET_CLIENT_ID` / `BNET_CLIENT_SECRET`), index races/classes
  (`static-…`), `--royaumes` (`dynamic-…`), `--guilde` (roster → lignes `Nom;Race;Classe;Niveau`,
  forme attendue de `lire_api_blizzard()`), `--perso` (profil). `--jeu classic1x` par défaut ;
  `--jeu forever` (v1.13.0) : `--version-static 1.60.1_70399` par défaut (`VERSIONS`), pas de royaume
  (`--guilde "Quartz Forever"`, `--perso gawel-zugzug`). `--compte` (v1.13.0) : OAuth « authorization code »
  `wow.profile` (`jeton_utilisateur()` : navigateur + mini-serveur sur `http://localhost:8765/`, `--port`,
  `state` vérifié ; adresse à déclarer dans les « Redirect URLs » du client), puis `/profile/user/wow` :
  persos du compte, liens `character` / `protected_character` suivis, guilde + roster ; réponses brutes
  dans `compte-<jeu>.json` (`.gitignore`). Non testable depuis une session Claude.
- `tools/generer_cles.py` : génère/renouvelle les clés des membres dans `cles.txt`.
- `tests/test_app.py` : tests pytest du serveur (`pytest -q`).

## Serveur (app.py)
- Flask + SQLite, servi par gunicorn (1 worker) sur le port 8080.
- Tables : `personnages`, `historique` (chaque montée de niveau), `exploits`
  (UNIQUE palier+nom → une annonce ne part jamais deux fois), `envois`, `comptes`
  (connexion Discord, voir plus bas), `proprietaires` (personnage → joueur, v1.6.0), `inactifs`
  (v1.8.0), `rangs` (référentiel des noms de rangs, v1.10.0), `morts` (v1.14.0). `personnages.rang` (n° de rang,
  v1.10.0), `personnages.specialisation` / `talents` (v1.15.0) : les `INSERT` dans `personnages` nomment leurs colonnes (ne plus écrire `VALUES(?,?,?,?,?)`).
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
  `state` (v1.10.1) : jeton `itsdangerous` signé par la clé de session (sel `discord-etat`),
  valable `ETAT_VALIDITE` = 600 s, **pas stocké en session** (`url_discord()`, `etat_valide()`) :
  l'app Discord mobile rouvre l'URL de retour dans le navigateur par défaut, qui n'a pas forcément
  le cookie de départ. Contrepartie assumée : pas de liaison au navigateur (CSRF de connexion
  théorique, limité à un compte membre de la guilde). Les liens « Connexion Discord » des templates
  appellent `url_connexion()` (contexte) → URL discord.com directe : seul un lien touché (pas une
  redirection) laisse iOS / Android ouvrir l'app ; `/connexion` reste une redirection équivalente.
  **L'app Discord ne s'ouvre pas pour la connexion, par choix de Discord** (testé par Gaël le 30/10 :
  page web sur mobile). `https://discord.com/.well-known/apple-app-site-association` exclut
  explicitement `/oauth2/authorize` avec un `response_type` (« Exclude oauth2 flows that have a
  specified response type from deep linking ») et ne prend en charge que l'ajout d'apps ou de bots
  (sans `response_type`) ; or `response_type=code` est obligatoire pour la connexion. Android
  (`assetlinks.json`, app `com.discord`) : probablement pareil, non vérifié (filtres déclarés dans
  l'app). Pas de contournement côté site : se connecter une fois à discord.com dans le navigateur
  du téléphone (ensuite un seul tap, ou aucun avec `prompt=none`), session du site de 30 jours.
  Le `state` signé reste utile (retour dans un autre navigateur).
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
  secret, guilde ; royaume facultatif depuis v1.13.0). `bnet_get()` : jeton `client_credentials` gardé
  dans `_bnet` jusqu'à expiration, `namespace = espace_bnet()` = `{profile|dynamic|static}-{BNET_ESPACE}-
  {BNET_REGION}`, `fr_FR`, None si ≠ 200 ; statique versionné possible (v1.13.0, `static-{version}-…`).
  `libelles(type_, version_roster)` met en cache les index race/classe : essaie `BNET_VERSION_STATIC`
  (vide = sans version) puis la version citée par les liens du roster (`version_static()` ; repli
  seulement : sur Classic, `static-1.15.7_60013-classic1x-eu` cité par le roster → 404).
  `chemin_guilde()` : `/data/wow/guild/{royaume}/{guilde}`, ou sans royaume si `BNET_ROYAUME` est vide
  (Forever). `identite(c)` → (nom en base, chemin du profil) : avec `surname` (Forever) → **« Prénom Nom »**
  (espace, comme l'addon ≥ 1.3.2 : l'API met à jour les fiches de l'addon) et `/profile/wow/character/{slug}`
  (`slug` du roster, `gawel-zugzug`) ; sinon nom seul et profil par royaume. Roster → tuples
  `analyser_export()` ; homonyme = plus haut niveau. **Profil de chaque membre à chaque collecte**
  (v1.13.0 ; le roster Forever est en retard : Wagyu 15 au roster, 17 au profil le 5/11) : niveau =
  max(roster, profil). Date du niveau = `last_login_timestamp` si le profil a le même niveau et si la date ≥ `personnages.maj` (dernière
  vue à l'ancien niveau ; sinon heure de connexion d'une session en cours) ; sinon `dater()` prend
  l'heure de collecte. `collecter()` → `(mises_a_jour, source)` (`blizzard` / `fichier` / None),
  source d'envoi `serveur` (pas de « via », hors contributeurs). Erreur réseau → `([], {})` → repli fichier.
- Rangs (v1.10.0) : `lire_api_blizzard()` → `(persos, dates, rangs)`, `rangs = {nom: rank}` du roster
  (entier, 0 = maître de guilde) ; `analyser_rangs(texte)` lit le bloc `GuildExportRangs` de l'addon
  ≥ 1.3.0 (`/envoyer`, `/contribuer`, repli fichier de `/collecter`) ; `integrer(..., rangs)` met à
  jour `personnages.rang` (le dernier envoi l'emporte ; sans table, ancien addon, le rang est gardé). Table `rangs(id PK, nom)` = référentiel
  saisi dans `/admin` (action `rangs` : champs `rang_<id>`, vide = supprimer, + `nouveau_id` /
  `nouveau_nom`), **non vidée** par `reinitialiser()`, dans `/export.json`. `noms_rangs(con)`.
  Bloc admin « Rangs de la guilde » : n° connus (`rangs` ∪ `personnages.rang`) + effectifs ; mention
  (v1.10.1) quand aucun perso n'a de rang (vu en prod le 30/10 : noms saisis, colonne cachée car
  les persos de Progress venaient d'une collecte v1.9.0 et l'API était coupée).
  Accueil : colonne « Rang » seulement si un perso a un rang (`avec_rangs`), nom ou « Rang N ».
  L'API ne fournit pas les noms des rangs ni les rôles (tank/soigneur/DPS).
- Morts (v1.14.0) : `lire_api_blizzard()` → `(persos, dates, rangs, morts)` ; pour chaque profil en 200
  (seulement : un profil 404 n'a pas de statistiques), `{chemin_profil}/achievements/statistics` →
  `analyser_morts()` : catégorie id `STAT_MORTS` = 122 « Morts » → `[(stat_id, catégorie, libellé, n)]`,
  catégorie « Total » pour les stats directes (id 60 = total), sinon nom de la sous-catégorie (125
  « Donjons et raids » : 321 total, 918 donjons à 5 ; 126 « En extérieur » : 112 noyade, 114 chute…) ;
  127 « Résurrection » ignorée ; pas de catégorie 122 (jamais mort) → total 0. `enregistrer_morts()`
  (appelé par `collecter()` après `integrer()`) : table `morts(nom, stat, categorie, libelle, quantite,
  maj, PK(nom, stat))`, `quantite = MAX(ancienne, nouvelle)`. `classement_morts(con)` → `(catégories,
  lignes)` hors exclus, tri total décroissant ; valeur d'une catégorie = sa stat « Nombre total… »
  sinon la somme (`valeur_categorie()`), ordre `ORDRE_MORTS` puis A→Z, + colonne « Autres » = total −
  catégories (`AUTRES_MORTS` dans le détail ; vu le 6/11 : la plupart des morts sont hors catégorie,
  Ooah 21 dont 1 en donjon). Accueil : bloc `#morts` (💀 au 1ᵉʳ, détail en `title`), caché sans
  données ; fiche : bloc `#morts` (détail + place). Vidée par `reinitialiser()`, dans `/export.json`.
  L'API donne aussi (non exploités) : `experience` (XP dans le niveau), victimes, quêtes, donjons,
  métiers, voyages, consommables. **Pas de temps de jeu (`/played`)** nulle part dans l'API.
- Spécialisations (v1.15.0) : 4ᵉ valeur de `lire_api_blizzard()` = `details = {nom: {"morts", "spe"}}`
  (profil en 200 seulement ; 3 requêtes par membre : profil, statistiques, spés, lues en parallèle par
  `lire_profil()` depuis la v1.15.1 : garder la collecte sous les 10 s du `rest_command`). `{chemin_profil}/specializations`
  → `analyser_spe()` : groupe `is_active`, arbres = `specializations[]` avec `talents[].talent_rank` (pas de
  champ « spé active » sur Forever, vu le 6/11) ; spé = arbre au plus de points (égalité : 1ᵉʳ listé),
  répartition « A 9 · B 8 » ; aucun point → None (rien d'écrit). `enregistrer_spes()` → colonnes
  `personnages.specialisation` / `talents` (ajoutées par `init_db()`), dernière lecture gagnante.
  Index Forever (`static-…/playable-specialization/index`, ids propres à Forever : 257 = Protection
  guerrier) : 27 spés, libellés fr_FR dont « Equilibre » sans accent, « Combat élémentaire »,
  « Combat farouche », « Magie de l'ombre ». `SPES[(classe CLASSES, normaliser(spé))] = (couleur a,
  couleur b, SVG)` : icônes maison inspirées des icônes du jeu (fond dégradé radial `--a`/`--b`, liseré
  doré, motif clair, `.p` = plein) ; `icone_spe(classe, spe, talents)` (contexte des templates) →
  `<span class="spe" title=…>`, vide si inconnue. Affichée devant la classe : classement, fiche
  (+ nom de la spé), `carte_perso` (/moi), admin.
- Fiche personnage (v1.12.0) : route `/perso/<path:nom>` (nom URL-encodé, espaces des noms de
  famille → `%20` via `|urlencode`), gabarit `FICHE` avec `<base href="../">` (liens relatifs de
  `ENTETE`/`STYLE`). `fiche(con, nom)` → None si inconnu **ou exclu** (404), sinon `perso`,
  `paliers` (date `date_atteinte()`, rang d'`exploits`, `duree` depuis le palier précédent, le 1ᵉʳ
  depuis le premier niveau vu), `historique` (récent en haut, durée depuis le niveau précédent),
  `courbe` (= `courbe(con, [nom])`), `place` / `membres` (hors exclus), `rythme` (niveaux/jour entre
  premier et dernier niveau de `historique`, None si < 24 h depuis la v1.12.1 : vu en prod le 5/11, Gawel Zugzug
  2 → 7 en 1 h 30 affichait « 73,9 niveaux par jour »), `gain24`, `joueur`, `nom_rang`. `duree()`
  formate « 45 min », « 6 h », « 1 j 12 h ». JS de la courbe partagé dans `COURBE_JS` (accueil + fiche).
  Liens `a.lien-perso` dans le classement, le tableau d'honneur, le fil ; bouton « Fiche » sur `/moi`.
- Stockage (v1.11.0) : `GUILDE_DB=/config/guilde.db` ; `secret.key` et `guilde.db.avant-reset` à côté
  (`cle_de_session()` suit le dossier de la base). `run.sh` déplace une fois `guilde.db`,
  `guilde.db.avant-reset` et `secret.key` de `/data` vers `/config` s'ils n'y sont pas déjà.
  `/config` = `/app_configs/<slug>/` (Terminal & SSH, sauvegardes HA). `GuildExport.lua` reste dans `/data`.
- Variables d'env (posées par run.sh depuis les options de l'app) : `NOM_GUILDE`,
  `GUILDE_TOKEN`, `DISCORD_WEBHOOK`, `GUILDE_DB=/config/guilde.db`,
  `GUILDE_CLES=/config/cles.txt`, `GUILDE_EXPORT`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`,
  `DISCORD_SERVEUR_ID`, `DISCORD_ROLE_ID`, `DISCORD_ADMINS`, `BNET_CLIENT_ID`, `BNET_CLIENT_SECRET`,
  `BNET_REGION` (`eu`), `BNET_ESPACE` (`classic1x`), `BNET_VERSION_STATIC` (vide), `BNET_ROYAUME`, `BNET_GUILDE`. Webhook vide = messages
  seulement dans le journal (mode test).
- Version (v1.4.3) : `VERSION` est lue dans `config.yaml` (copié dans l'image par le Dockerfile),
  affichée en pied de page (`PIED`) et ajoutée aux URL des images (`logo.png?v=…`,
  `banniere.jpg?v=…`) : Cloudflare et les navigateurs gardent les images en cache
  (`max-age=86400`) ; sans ce suffixe, l'ancien logo à fond gris de la v1.1.0 restait affiché.

## Déploiement Home Assistant — pièges déjà rencontrés
- **App installée depuis le dépôt d'apps** (depuis le 30/10/2026) : dépôt store `ee5b467c`
  = `https://github.com/gawel-code/quartz-leveling-website` (public, sans jeton), slug
  **`ee5b467c_quartz_forever`**, hostname interne **`ee5b467c-quartz-forever`**. Options, watchdog
  et mise à jour automatique activés. Configs d'apps dans **`/app_configs`** : clés, base et clé de
  session dans `/app_configs/ee5b467c_quartz_forever/` (`cles.txt` au format `Pseudo:clé`, relu à
  chaque envoi ; `guilde.db`, `guilde.db.avant-reset`, `secret.key`).
- **Déployer** (après « oui merge », `version` bumpée) : `ha_manage_app(action="check_updates")`
  puis `ha_manage_app(slug="ee5b467c_quartz_forever", action="update")`, puis vérifier le pied de
  page ; ou attendre la mise à jour automatique (le Supervisor relit le store périodiquement).
- Ancienne app locale `local_quartz_forever` (hôte `local-quartz-forever`) : désinstallée le 30/10.
  Si le dossier `/local_apps/quartz_forever` existe encore, elle reste listée « disponible » dans le
  store (sans effet) ; le supprimer dans Terminal & SSH la fait disparaître.
- Dans Terminal & SSH, la config HA est sous **`/homeassistant`** (pas `/config`).
  Le collage peut être déformé par le *bracketed paste* (1ʳᵉ lettre mangée, `~` final) :
  taper à la main `printf '\e[?2004l'`.
- CLI dans Terminal & SSH : `ha apps install|start|restart|rebuild|logs ee5b467c_quartz_forever`,
  `ha store reload`. Le shell est **BusyBox** (pas de `ls -b`, `grep` limité).
- Fichiers créés via File editor = fins de ligne **CRLF** → casser bash.
  Toujours `sed -i 's/\r$//'` avant d'exécuter un script collé.
- Ancien déploiement (app locale, jusqu'à la v1.11.0) : script `deployer-quartz.sh` (supprimé du
  dépôt le 30/10, visible dans l'historique git) lancé dans Terminal & SSH, avec un jeton GitHub
  lecture seule `quartz_github_token` dans `/homeassistant/secrets.yaml` (ne sert plus : à retirer
  et à révoquer sur GitHub). Piège vu : `ha apps update` lancé juste après `ha store reload` ne
  voyait pas encore la nouvelle version.
- Slug d'une app de dépôt = `<SHA-1[:8] de l'URL du dépôt>_<slug>` : l'URL ne doit pas changer
  (sinon nouveau slug, nouvelle migration).
- Cloudflared (app `396f0234_cloudflared`) : `additional_hosts` contient
  `mcp.gawel.be → http://homeassistant:9583` (connecteur MCP de Claude, **ne pas
  supprimer**) et `quartz.gawel.be → http://ee5b467c-quartz-forever:8080` (depuis le 30/10 ;
  `external_hostname` = `ha.gawel.be`). Modifiable via `ha_manage_app(options=…)` en renvoyant
  **toute** la liste `additional_hosts`, puis redémarrage (le connecteur coupe ~1 min, normal).

## État au 6 novembre 2026 (v1.15.1 déployée)
- ✅ v1.15.1 (mergée le 6/11, PR #44 ; **déployée et vérifiée vers 19 h 55** : `rest_command.quartz_collecter`
  → 200 sans timeout, `source: blizzard`, pied « v1.15.1 », icônes de spé présentes, avant le récap de 21 h) : profils lus en parallèle (`lire_profil()`, `ThreadPoolExecutor(BNET_PARALLELE = 8)`,
  la boucle de `lire_api_blizzard()` ne fait plus que la logique), gunicorn `--timeout 120` (`run.sh`).
  Vu le 6/11 après le déploiement de la v1.15.0 : `rest_command.quartz_collecter` → « Timeout when calling
  resource » (10 s par défaut côté HA ; 3 requêtes × 28 membres à la suite ≈ 12 s ; la v1.14.0 prenait
  déjà ~8 s). La collecte se termine quand même côté serveur, mais l'automatisation du récap (collecte puis
  récap, sans `continue_on_error`) s'arrête sur l'erreur. En local via le proxy de session : 59 s → 10 s.
- ✅ v1.15.0 (mergée le 6/11, PR #43) : icône de spécialisation devant la classe (voir *Serveur*). Rejouée en local
  contre la vraie API le 6/11 : 24 persos sur 26 avec une spé (Funzie Forever et Sept Entrion : profil 404).
  **Déployée et vérifiée le 6/11 vers 19 h 35** : pied « v1.15.0 », 24 icônes, Jazeel en brun, filtre sans doublons.
  Corrige aussi la couleur des classes au féminin : `COULEURS` est indexé par classe de `CLASSES`
  (`couleur(classe, defaut)`) ; vu en prod le 6/11 : Jazeel Sorrowbane et Murène Gilehjon (« Guerrière »)
  en blanc dans le classement (la classe gardée est celle de l'addon, au féminin).
  Filtre de classe de l'accueil : valeur = `cle_classe()` (clé de `CLASSES`), libellé = `NOMS_CLASSES`
  (masculin) ; `data-classe` des lignes = la clé (avant : « Guerrier » et « Guerrière » séparés).
- ✅ v1.14.0 (mergée le 6/11, PR #42) : classement des morts par l'API (voir *Serveur*). Rejouée en local
  contre la vraie API puis **déployée et vérifiée le 6/11 vers 18 h 45** (`check_updates` + `update`,
  collecte → `source: blizzard`) : pied « v1.14.0 », « 180 morts dans la guilde », Ooah Perfectoil en tête (21).
- Profils 404 (6/11) : pas un écart roster/site (mêmes 20 persos le 5/11) ni des persos inactifs (les
  trois niveaux 21 étaient en 404) ; publication différée par Blizzard : Lendive Forever et Gawel
  Zugzug sont passés en 200 ensuite. Plus que 3 profils en 404 le 6/11 (funzie-forever, sept-entrion,
  patéhenkrout-bourguignon).
- Annonces silencieuses entre 21 et 24 : normal (paliers de 10, puis 25/35/45 ; vérifié le 5/11).
- ✅ v1.13.0 (mergée le 5/11, PR #39) : API Blizzard pour Forever. Rejouée contre la
  vraie API sur une copie du classement en ligne (5/11, 15 h) : 0 doublon, 0 création (Cart Forsaken,
  absent du roster, gardé), races « ? » complétées, classes féminines gardées, rangs remplis. **Pas de
  remise à zéro** (Gaël) : la base de l'addon est mise à jour. **Déployée et vérifiée le 5/11 vers 17 h 50**
  par le connecteur : `check_updates` + `update` (pied « v1.13.0 »), options `bnet_espace = forever`,
  `bnet_royaume` vide, `bnet_guilde = Quartz Forever` (seules ces trois envoyées), redémarrage, puis
  `rest_command.quartz_collecter` → `{"source": "blizzard", "mises_a_jour": 1}`. Accueil : 20 persos
  (19 du roster + Cart Forsaken), aucun doublon, **plus aucune race « ? »**, classes féminines gardées,
  rangs et @Pseudo intacts. Journal : 9 profils encore en 404 (lendive-forever, jazeel-sorrowbane,
  olich-ier, gawel-zugzug, ooah-perfectoil, garmain-jhin, diadora-forever, nounours-forever,
  funzie-forever) → niveau du roster / de l'addon, montée datée à la collecte.
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
- ✅ v1.10.0 (déployée, pied « v1.10.0 » vérifié le 30/10 ; noms de rangs saisis : Grand Chef, Petit Chef, Péon) : rangs de la guilde (n° du roster, noms dans l'admin, colonne sur
  l'accueil), lus par l'API et par l'addon 1.3.0 (mergé, à tester en jeu).
- ✅ v1.10.1 (déployée, vérifiée le 30/10 : pied « v1.10.1 », colonne « Progression », liens
  `discord.com/oauth2/authorize` avec `state` signé, `/connexion` → même URL) : connexion Discord par lien direct (app mobile) et `state` signé sans
  cookie ; « Vers 60 » → « Progression » ; mention « aucun rang connu » dans l'admin (non vérifiée :
  session admin nécessaire). Sur téléphone, la connexion reste dans le navigateur : Discord exclut
  les flux OAuth de connexion de l'ouverture dans l'app (voir *Connexion Discord*).
  Rangs vus en ligne le 30/10 (collecte ponctuelle Progress : colonne « Rang », « Rang 3 / 4 »,
  options `bnet_royaume` / `bnet_guilde` revidées ensuite).
- ✅ v1.11.0 (déployée le 30/10) : `repository.yaml` + base dans `/config`. Dernier déploiement par le
  script sur l'app locale (migration `/data` → `/config` vue dans le journal), dépôt passé en
  **public** (historique git vérifié : aucun secret), ajouté au store, app `ee5b467c_quartz_forever`
  installée, options reportées, base copiée par Gaël, démarrée (9 persos, 3 noms de rangs, comptes
  OK), Cloudflared basculé, `secrets.yaml` mis à jour par Gaël (`rest_command.quartz_collecter` →
  200 depuis la nouvelle app, l'ancienne étant arrêtée). Reste : vérifier le site dans un navigateur
  (le proxy de session Claude bloque `quartz.gawel.be`). Ancienne app désinstallée (30/10).
- ✅ Addon 1.3.1 (mergé le 3/11, doc du site mise à jour) : nom affiché **Quartz Guild Exporter** (violet,
  icône de cristal) ; dossier, fichier `GuildExport.lua` et tables inchangés (pas d'impact serveur ni `client/`).
- ✅ Addon 1.3.2 (mergé le 5/11, [release v1.3.2](https://github.com/gawel-code/quartz-leveling-addon/releases/tag/v1.3.2)) :
  noms de famille de Forever (voir *Arborescence*) ; format inchangé, pas d'impact serveur. Premier
  fichier réel de Gaël (5/11) : 8 membres, races « ? », `GuildExportMesPersos = {"Gawel"}` → association
  périmée « Gawel » dans `proprietaires` (à dissocier dans `/admin`). **Vérifié en jeu et en ligne
  le 5/11** : avec la 1.3.2, « Gawel Zugzug — Orc — Guerrier — Péon — 6 — @Gawel » sur l'accueil.
- ✅ Addon 1.3.3 (5/11) : reprise des dates de niveau notées au prénom par `PLAYER_LEVEL_UP` (≤ 1.3.1,
  exactes) sous le nom complet ; `dater()` garde la plus ancienne, l'historique de Gawel Zugzug se
  corrige au prochain envoi (≈ 1 min plus tôt).
- ✅ v1.12.0 (mergée le 5/11, PR #37) : fiche par personnage `/perso/<nom>` (voir *Serveur*),
  développée en TDD (5 tests `test_fiche_*`). **Déployée et vérifiée le 5/11** (pied « v1.12.0 », liens
  `perso/…` sur l'accueil, fiche de Gawel Zugzug OK).
- ✅ v1.12.1 (mergée le 5/11, PR #38) : rythme moyen de la fiche seulement après 24 h de données.
- ✅ Options API réglées le 5/11 (voir v1.13.0). Plus de remise à zéro : la base contient les persos réels.
- ✅ App installée et démarrée, site en ligne sur https://quartz.gawel.be
- ✅ Route Cloudflared configurée
- ✅ `cles.txt` vérifié (30 membres, 0 ligne invalide, 0 CRLF, ni pseudo ni clé en double ;
  pseudos sans espaces ni `|`, accents possibles : `Metam-Zap`, `Patéhenkrout`, `Finwë`…).
  Ligne de test `TestClaude` retirée (clé refusée → 403) ; copie dans `cles.txt.bak`.
- ✅ Automatisations HA actives depuis le lancement (collecte **toutes les 30 min** depuis le 5/11 à la demande
  de Gaël, auparavant 15 min ; récap 9 h / 21 h ; vérifié le 5/11 : dernière collecte 17 h 30), réactivées
  par `automation.quartz_reactivation_au_lancement` (`input_datetime.quartz_lancement_wow_forever`, 5/11 00:00).
  Depuis le 5/11 (v1.13.0), `/collecter` lit l'API Blizzard (repli sur le fichier si l'API échoue).
- ✅ Webhook Discord (option `discord_webhook`) sur le **vrai salon de progression** depuis le lancement
  (confirmé par Gaël ; l'URL n'est jamais commitée ni recopiée). Les annonces de la collecte par
  l'API (v1.13.0) y partent aussi, sans « — via ».
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

## API Blizzard — WoW Forever (essais des 3 et 5/11/2026)
- 3/11 (avant lancement, piste : veille quotidienne + forum API sujet 59774, message de joueur du 2/11) :
  `static-1.60.1_70399-forever-eu` → 200, `static-forever-eu` → 403, `dynamic-forever-eu` → 200 (26
  royaumes provisoires « camwow », sans nom). Classes = celles de Classic (mêmes id, libellés FR) ; races
  = Classic + **95 « Éolide de l'Ordre suprême »** (Alliance) et **96 « Éolide sculpte-vents »** (Horde).
- 5/11 7 h 30 : `static-forever-eu` → 200 ; index des royaumes → 404 (provisoires retirés, aucun réel).
- 5/11 14 h 20 : **guilde publiée, sans royaume** : `/data/wow/guild/quartz-forever` (id 80187, Horde,
  19 membres, `ruleset` Normal) et `/roster` : `character` = `name`, `surname`, `slug`
  (`lendive-forever`), `id`, `level`, `playable_race.id`, `playable_class.id`, pas de `realm` ; `rank`
  0 à 4. Profils `/profile/wow/character/{slug}` : 200 pour une partie (anar-forever, souledge-forever,
  wagyu-steak…), 404 pour 9 membres (lendive-forever, gawel-zugzug…) ; profil complet
  (`last_login_timestamp`, équipement, quêtes…). Roster en retard sur le profil.
- Identifiants de test : variables `BNET_CLIENT_ID` / `BNET_CLIENT_SECRET` de l'environnement cloud
  des sessions Claude (API EU joignable ; `us.api.blizzard.com` bloqué par le proxy).

## Outils utiles pour Claude (via le connecteur HA)
- Appeler l'app directement : `ha_manage_app(slug="ee5b467c_quartz_forever", port=8080,
  path=..., method=...)` — permet `/export.json?token=…`, `POST /reinitialiser?token=…`,
  `POST /envoyer` (header `X-Cle`) sans passer par Cloudflare (bloqué par le proxy de session).
- `rest_command.quartz_collecter` / `quartz_recap` : `ha_call_service(..., return_response=True)`.
  `rest_command.quartz_reinitialiser` (voir `ha/configuration.yaml`) **n'est pas** configuré côté HA.
- Logs de l'app : `ha_get_logs(source="supervisor", slug="ee5b467c_quartz_forever")`.
- Le connecteur ne lit pas les fichiers (`cles.txt`, `configuration.yaml`) : passer par Terminal & SSH.
- « Clé inconnue » sur `/contribuer` alors que `cles.txt` est bon = clé mal saisie
  (ligne entière collée, autoremplissage du navigateur) ; l'app lit bien
  `/app_configs/ee5b467c_quartz_forever/cles.txt`.

## To-do
1. ~~Créer `cles.txt` avec les clés des membres.~~ ✅ fait
2. ~~Automatisations HA~~ ✅ fait (29/10) : `rest_command.quartz_collecter` / `quartz_recap`
   chargés (secrets internes, token de l'app renseigné, appels testés → 200),
   automatisations `automation.quartz_collecte_horaire` (toutes les 30 min depuis le 5/11 —
   `time_pattern` `/30`, alias « Quartz – collecte toutes les 30 min », entity_id inchangé) et
   `automation.quartz_recap_discord_9_h_21_h` (9 h / 21 h : collecte puis récap) ;
   réactivées le 5/11 (voir État).
3. ~~Webhook sur le vrai salon~~ ✅ (lancement) ; ~~remise à zéro~~ abandonnée (la base contient les persos
   réels, voir v1.13.0) ;
   nettoyage de la migration : supprimer `/local_apps/quartz_forever`, retirer `quartz_github_token`
   de `secrets.yaml` (et `/homeassistant/deployer-quartz.sh`), révoquer ce jeton sur GitHub.
4. ~~Tester de bout en bout~~ ✅ fait (29/10), base remise à zéro ensuite.
5. Vérifier le numéro `## Interface:` de l'addon sur le client Forever ; tester
   l'addon en jeu (race via cible/survol/groupe).
6. ~~Client API develop.battle.net + essais Classic Era~~ ✅ fait (30/10) : roster OK avec la race.
7. ~~API Forever en production~~ ✅ fait (5/11, v1.13.0). Reste : surveiller les profils encore en
   404 (journal de l'app ; 3 le 6/11) ; un membre qui quitte la guilde reste en base (ex. Cart Forsaken, absent du
   roster le 5/11). Avec une connexion Battle.net (OAuth `wow.profile`, liste des persos du
   compte), associer les persos avec la source `blizzard` (`associer()`).
8. **Prochaine étape** — distribuer à la guilde : addon, `client/`, `docs/README-guilde.md`,
   lien https://quartz.gawel.be/moi (connexion Discord : liaison auto si le nom Discord = pseudo,
   sinon clé en MP ou nouveau pseudo).
9. Plus tard : sauvegarde nuitière de `/export.json` par Home Assistant.
10. Plus tard : notification HA (en plus de Discord) quand un membre passe 60.
11. Idées en attente : maquette
    artefact pour présenter le projet à la guilde ; autres statistiques de l'API (victimes, quêtes,
    donjons/boss, métiers, `experience` pour un niveau décimal) ; annonce Discord du 1ᵉʳ au classement des morts.
