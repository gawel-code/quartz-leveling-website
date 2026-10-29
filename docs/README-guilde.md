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

## Étape 2 — Envoyer tes données (choisis UNE des deux options)

### Option A — Automatique (recommandé, à faire une seule fois)
1. Demande ta **clé personnelle** à Gaël.
2. Télécharge `envoi-guilde.ps1` et `lancer.bat`, mets-les dans le même dossier.
3. Ouvre `envoi-guilde.ps1` avec le Bloc-notes et modifie les lignes du haut :
   - `$Cle` : ta clé personnelle
   - `$Fichier` : remplace `TON_COMPTE` par le nom de ton compte
     (le nom du dossier dans `WTF\Account\`)
4. Enregistre, puis double-clique sur `lancer.bat`.

Une fenêtre noire s'ouvre : laisse-la ouverte pendant que tu joues (tu peux la
réduire). Pour qu'il démarre avec Windows : `Windows + R`, tape `shell:startup`,
et place un **raccourci** vers `lancer.bat` dans le dossier qui s'ouvre.

### Option B — À la main, sans rien installer
1. Après ta session, va sur **https://quartz.gawel.be/contribuer**.
2. Entre ta clé personnelle et choisis le fichier `GuildExport.lua`, dans
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

**Ma clé est perdue ou quelqu'un l'a vue.** Préviens Gaël, il t'en donnera une
nouvelle.

## Les récompenses 🏆
- 🥇🥈🥉 Les **trois premiers** à atteindre les niveaux 10, 20, 30, 40 et 50
  reçoivent une médaille et une annonce sur Discord.
- 🎉 **Chaque joueur** qui atteint le **niveau 60** est félicité sur Discord.
- 📜 Un récapitulatif est publié **à 9 h et à 21 h**.

Bonne aventure en Azeroth ! ⚔️
