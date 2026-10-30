# 💎 Suivi de progression de Quartz Forever — Mode d'emploi

## C'est quoi ?
Un site, **https://quartz.gawel.be**, qui affiche le niveau de tous les membres de
la guilde, un tableau d'honneur avec des médailles, et des annonces automatiques
sur Discord quand quelqu'un atteint un palier.

Comme Blizzard ne fournit pas encore ces informations pour Forever, **c'est nous
qui les collectons**, grâce à un petit addon. Plus il y a de membres qui
participent, plus le classement est à jour !

## Est-ce que c'est sans risque ?
Oui. L'addon se contente de **lire la liste de guilde**, la même que tu vois en
appuyant sur J. Il ne touche ni à ton compte ni à ton mot de passe. Les seules
informations partagées sont le nom, la race, la classe et le niveau des membres.

---

## Étape 1 — Installer l'addon (obligatoire, 2 minutes)
1. Télécharge le dossier `GuildExport` (lien donné sur Discord).
2. Copie-le dans `World of Warcraft\_forever_\Interface\AddOns\`
3. Lance le jeu. Sur l'écran de sélection des personnages, clique sur **AddOns**
   et vérifie que **Guild Export** est bien coché.

💡 Le jeu ne donne pas la race des joueurs dans la liste de guilde. L'addon la
retient quand tu **cibles** ou **survoles** un membre, ou quand tu es **en
groupe** avec lui.

⚠️ Le jeu n'enregistre le fichier qu'à la **déconnexion** ou quand tu tapes
`/reload`. Les données partent donc après ta session de jeu.

---

## Étape 2 — Récupérer ta clé personnelle

Va sur **https://quartz.gawel.be/moi** et clique sur **Connexion Discord** (il faut
être sur le serveur Discord de la guilde, avec le rôle de la guilde).
- Si ton pseudo Discord (ou ton surnom sur le serveur) est ton pseudo de guilde, ton
  compte est relié tout seul et ta clé s'affiche directement.
- Si Gaël t'a déjà envoyé une clé en MP : colle-la dans « J'ai déjà reçu une clé ».
- Sinon : choisis ton pseudo, une clé est créée pour toi.

Discord te demande aussi l'accès à tes connexions : si ton compte Battle.net est lié à Discord
(*Paramètres → Connexions*), ton **BattleTag** est enregistré (visible seulement par toi et les
officiers). Sinon, tu peux le saisir toi-même sur cette page (format `Nom#1234`).

Ta clé reste affichée sur cette page (bouton **Copier la clé**). Tu peux aussi en
générer une nouvelle si elle a fuité.

Sur cette même page, **Mes personnages** liste tes personnages : ceux de ton compte WoW sont
ajoutés tout seuls à chaque envoi de ton fichier, et tu peux en ajouter à la main (« C'est mon
personnage »). Dans le classement, ils affichent ton pseudo avec un lien vers ton profil Discord.

## Étape 3 — Envoyer tes données (choisis UNE des deux options)

### Option A — Automatique (recommandé, à faire une seule fois)
1. Récupère ta **clé personnelle** (étape 2).
2. Télécharge `envoi-guilde.ps1`, `lancer.bat` et `changer-cle.bat`, mets-les dans le
   même dossier.
3. Double-clique sur `lancer.bat`. La première fois, il te demande ta clé (colle
   uniquement la clé) et trouve tout seul le fichier de l'addon. S'il ne le trouve pas,
   colle le chemin du dossier `SavedVariables` de ton compte WoW.

Une fenêtre noire s'ouvre : laisse-la ouverte pendant que tu joues (tu peux la
réduire). Elle envoie tes données à chaque fois que le jeu les enregistre. Pour qu'elle
démarre avec Windows : `Windows + R`, tape `shell:startup`, et place un **raccourci**
vers `lancer.bat` dans le dossier qui s'ouvre.

Ta clé et l'emplacement du fichier sont retenus dans `%APPDATA%\QuartzForever\`, avec
un journal des envois (`envoi.log`). Pour changer de clé ou de dossier, double-clique
sur `changer-cle.bat`.

### Option B — À la main, sans rien installer
1. Après ta session, va sur **https://quartz.gawel.be/contribuer**.
2. Connecte-toi avec Discord (ou entre ta clé) et choisis le fichier `GuildExport.lua`, dans
   `World of Warcraft\_forever_\WTF\Account\TON_COMPTE\SavedVariables\`
3. Clique sur **Envoyer**.

---

## Questions fréquentes

**Mon niveau n'est pas à jour.** Fais un `/reload` en jeu, puis attends une
minute (option A) ou renvoie le fichier (option B).

**Une race s'affiche avec un « ? ».** Personne n'a encore croisé ce joueur avec
l'addon. Ça se complète tout seul.

**Deux personnes envoient des données différentes ?** Le site garde toujours le
**niveau le plus haut**. Pas de risque d'écraser les données de quelqu'un.

**Ma clé est perdue ou quelqu'un l'a vue.** Sur https://quartz.gawel.be/moi, clique sur
**Générer une nouvelle clé**, puis double-clique sur `changer-cle.bat` pour la donner au
script.

## Et si j'envoie mon fichier en retard ?
Pas de souci : l'addon **note l'heure de chaque montée de niveau** (la tienne à la
seconde près, celles des autres quand il les voit passer dans la liste de guilde).
C'est cette heure-là qui compte pour le tableau d'honneur, pas l'heure de l'envoi.
Le message Discord part à l'envoi, mais le tableau d'honneur se remet dans l'ordre
si quelqu'un d'autre était en fait arrivé avant.

## Les récompenses 🏆
- 🥇🥈🥉 Les **trois premiers** à atteindre les niveaux 10, 20, 30, 40 et 50
  reçoivent une médaille au tableau d'honneur.
- 📣 **Chaque joueur** est annoncé sur Discord à chaque dizaine (10, 20… 60),
  avec son rang d'arrivée ; puis tous les 5 niveaux à partir de 20 (25, 35, 45)
  et à **chaque niveau** à partir de 50.
- 🎉 **Chaque joueur** qui atteint le **niveau 60** est félicité sur Discord.
- 📜 Un récapitulatif est publié **à 9 h et à 21 h**.

Bonne aventure en Azeroth ! ⚔️
