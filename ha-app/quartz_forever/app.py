# Quartz Forever — suivi de progression de guilde (WoW Forever)
import os, re, json, hmac, secrets, sqlite3, datetime, bisect
from pathlib import Path
from urllib.parse import urlencode
import requests
from flask import Flask, render_template_string, request, abort, jsonify, send_file, session, redirect
from markupsafe import Markup
from itsdangerous import URLSafeTimedSerializer, BadSignature

# ---------- Configuration ----------
DB = os.getenv("GUILDE_DB", "guilde.db")
EXPORT = Path(os.getenv("GUILDE_EXPORT", "GuildExport.lua"))
FICHIER_CLES = Path(os.getenv("GUILDE_CLES", "cles.txt"))
WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
TOKEN = os.getenv("GUILDE_TOKEN", "change-moi")
NOM_GUILDE = os.getenv("NOM_GUILDE", "Quartz Forever")
# Version de l'app (config.yaml copié dans l'image) : affichée en pied de page et ajoutée aux URL
# des images pour que navigateurs et Cloudflare reprennent les nouvelles après un déploiement.
_config = Path(__file__).with_name("config.yaml")
_version = re.search(r'^version:\s*"?([^"\n]+)', _config.read_text(encoding="utf-8"), re.M) if _config.exists() else None
VERSION = _version.group(1).strip() if _version else "dev"
URL_SITE = os.getenv("GUILDE_URL", "https://quartz.gawel.be").rstrip("/")
# Connexion Discord (OAuth2) : active seulement si l'identifiant et le secret sont renseignés.
DISCORD_ID = os.getenv("DISCORD_CLIENT_ID") or "1565628978633515028"
DISCORD_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_SERVEUR = os.getenv("DISCORD_SERVEUR_ID") or "801395490372583426"
DISCORD_ROLE = os.getenv("DISCORD_ROLE_ID", "1549720665844613130")  # vide = tout membre du serveur
ADMINS = {i.strip() for i in (os.getenv("DISCORD_ADMINS") or "161139977328132107").split(",") if i.strip()}
API_DISCORD = "https://discord.com/api/v10"
# API Blizzard (v1.9.0) : roster de la guilde lu à chaque /collecter ; active si les quatre sont renseignés.
BNET_ID = os.getenv("BNET_CLIENT_ID", "")
BNET_SECRET = os.getenv("BNET_CLIENT_SECRET", "")
BNET_REGION = os.getenv("BNET_REGION") or "eu"
BNET_ESPACE = os.getenv("BNET_ESPACE") or "classic1x"  # Classic Era ; à changer pour Forever
BNET_ROYAUME = os.getenv("BNET_ROYAUME", "")
BNET_GUILDE = os.getenv("BNET_GUILDE", "")
PSEUDO_VALIDE = re.compile(r"^[^\s:|#]{2,24}$")
BATTLETAG_VALIDE = re.compile(r"^[^\W\d_]\w{1,11}#\d{4,6}$")  # Nom#1234 : 2 à 12 caractères, pas d'espace
PALIERS = [10, 20, 30, 40, 50, 60]
MEDAILLES = {1: "🥇", 2: "🥈", 3: "🥉"}
COULEURS = {
    "Guerrier": "#C69B6D", "Mage": "#3FC7EB", "Prêtre": "#FFFFFF", "Prêtresse": "#FFFFFF",
    "Voleur": "#FFF468", "Voleuse": "#FFF468", "Druide": "#FF7C0A", "Druidesse": "#FF7C0A",
    "Chasseur": "#AAD372", "Chasseresse": "#AAD372", "Démoniste": "#8788EE",
    "Paladin": "#F48CBA", "Chaman": "#2E8FEF", "Chamane": "#2E8FEF",
}


# Emblèmes de classe dessinés pour le site (SVG 24×24, trait) : aucune image externe.
EMBLEMES = {
    "guerrier": "M5 19 19 5M14 5h5v5M5 5l14 14M5 14v5h5",
    "mage": "M12 3v18M3 12h18M6 6l12 12M18 6 6 18",
    "pretre": "M12 3v18M6 9h12",
    "voleur": "M12 3l2 10h-4zM8 13h8M12 13v5M10.5 21h3",
    "druide": "M5 19C5 10 11 5 20 4c-1 9-6 15-15 15zM5 19l8-8",
    "chasseur": "M7 3a13 13 0 0 1 0 18M7 3v18M3 12h17M17 9l3 3-3 3",
    "demoniste": "M12 3c1 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-4 2-7 2 1 3 3 3 5 1-2 1-6 1-9z",
    "paladin": "M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6zM12 8v8M9 11h6",
    "chaman": "M13 2 5 14h6l-1 8 8-12h-6z",
}
CLASSES = {"Guerrier": "guerrier", "Guerrière": "guerrier", "Mage": "mage", "Prêtre": "pretre",
           "Prêtresse": "pretre", "Voleur": "voleur", "Voleuse": "voleur", "Druide": "druide",
           "Druidesse": "druide", "Chasseur": "chasseur", "Chasseresse": "chasseur",
           "Démoniste": "demoniste", "Paladin": "paladin", "Chaman": "chaman", "Chamane": "chaman"}


def couleur(classe):
    return COULEURS.get(classe or "", "#8a9ab5")


def embleme(classe):
    """Emblème SVG de la classe (point d'interrogation si inconnue)."""
    trace = EMBLEMES.get(CLASSES.get(classe or ""), "M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.5")
    return Markup('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="%s"/></svg>' % trace)


def maintenant():
    return datetime.datetime.now().isoformat(timespec="seconds")


def depuis_epoch(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def date_lisible(iso):
    return datetime.datetime.fromisoformat(iso).strftime("le %d/%m à %H h %M")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS personnages(
            nom TEXT PRIMARY KEY, race TEXT, classe TEXT, niveau INTEGER, maj TEXT);
        CREATE TABLE IF NOT EXISTS historique(
            nom TEXT, niveau INTEGER, date TEXT);
        CREATE TABLE IF NOT EXISTS exploits(
            palier INTEGER, nom TEXT, rang INTEGER, date TEXT, UNIQUE(palier, nom));
        CREATE TABLE IF NOT EXISTS envois(
            pseudo TEXT, date TEXT, personnages INTEGER, nouveautes INTEGER);
        CREATE TABLE IF NOT EXISTS comptes(
            discord_id TEXT PRIMARY KEY, pseudo TEXT UNIQUE COLLATE NOCASE,
            cle TEXT UNIQUE, discord_nom TEXT, lie_le TEXT);
        """)
        con.execute("""CREATE TABLE IF NOT EXISTS inactifs(
            nom TEXT PRIMARY KEY, motif TEXT, date TEXT)""")  # v1.8.0 : mules, banques… hors progression
        con.execute("""CREATE TABLE IF NOT EXISTS proprietaires(
            nom TEXT PRIMARY KEY, pseudo TEXT, source TEXT, date TEXT)""")  # v1.6.0 : perso → joueur
        con.execute("""CREATE TABLE IF NOT EXISTS rangs(
            id INTEGER PRIMARY KEY, nom TEXT)""")  # v1.10.0 : noms des rangs, gardés par la remise à zéro
        if "rang" not in {c[1] for c in con.execute("PRAGMA table_info(personnages)")}:
            con.execute("ALTER TABLE personnages ADD COLUMN rang INTEGER")  # v1.10.0 : n° lu dans le roster
        colonnes = {c[1] for c in con.execute("PRAGMA table_info(comptes)")}
        if "battletag" not in colonnes:
            con.execute("ALTER TABLE comptes ADD COLUMN battletag TEXT")  # v1.5.0 : lu sur Discord
        if "battletag_saisi" not in colonnes:
            con.execute("ALTER TABLE comptes ADD COLUMN battletag_saisi TEXT")  # v1.5.1 : saisi sur /moi


# ---------- Discord ----------
def discord(message):
    if not WEBHOOK:
        print("[Discord désactivé]", message, flush=True)
        return
    try:
        requests.post(WEBHOOK, json={"content": message}, timeout=10)
    except requests.RequestException as e:
        print("Erreur Discord :", e, flush=True)


# ---------- Exploits (annoncés une seule fois) ----------
def ordinal(n):
    return "1ᵉʳ" if n == 1 else f"{n}ᵉ"


def niveau_annonce(niveau):
    """Niveaux annoncés sans classement : tous les 5 dès 20, chaque niveau dès 50."""
    return niveau >= 50 or (niveau >= 20 and niveau % 5 == 0)


def date_atteinte(con, nom, niveau):
    """Date à laquelle un personnage a atteint un niveau : la plus ancienne connue à ce niveau ou au-delà."""
    return con.execute("SELECT MIN(date) FROM historique WHERE nom=? AND niveau>=?", (nom, niveau)).fetchone()[0]


def reclasser(con, palier):
    """Rangs d'un palier selon la date réelle d'atteinte (et non l'ordre de réception)."""
    rows = con.execute("SELECT rowid FROM exploits WHERE palier=? ORDER BY date, nom", (palier,)).fetchall()
    for rang, r in enumerate(rows, 1):
        con.execute("UPDATE exploits SET rang=? WHERE rowid=?", (rang, r[0]))


def noms_rangs(con):
    """{n° de rang: nom} défini dans l'admin (référentiel, pas vidé par la remise à zéro)."""
    return {r["id"]: r["nom"] for r in con.execute("SELECT id, nom FROM rangs")}


def inactifs(con):
    """Personnages exclus de la progression (mules, banques…) : {nom: motif}."""
    return {r[0]: r[1] for r in con.execute("SELECT nom, motif FROM inactifs")}


MOTIFS = {"mule": "Mule", "banque": "Banque", "autre": "Autre"}


def desactiver(con, nom, motif):
    """Exclut un personnage : il sort du classement, du tableau d'honneur, des annonces, du récap et
    de la courbe. Ses niveaux continuent d'être enregistrés."""
    con.execute("INSERT OR REPLACE INTO inactifs VALUES(?,?,?)", (nom, motif, maintenant()))
    paliers = [r[0] for r in con.execute("SELECT palier FROM exploits WHERE nom=?", (nom,))]
    con.execute("DELETE FROM exploits WHERE nom=?", (nom,))
    for palier in paliers:
        reclasser(con, palier)


def reactiver(con, nom):
    """Réintègre un personnage : ses paliers reprennent leur rang selon leur date réelle, sans annonce."""
    con.execute("DELETE FROM inactifs WHERE nom=?", (nom,))
    row = con.execute("SELECT niveau FROM personnages WHERE nom=?", (nom,)).fetchone()
    for palier in PALIERS:
        date = date_atteinte(con, nom, palier) if row and row["niveau"] >= palier else None
        if date:
            con.execute("INSERT OR IGNORE INTO exploits VALUES(?,?,?,?)", (palier, nom, 0, date))
            reclasser(con, palier)


def verifier_exploits(con, nom, classe, ancien, nouveau, annonces):
    """Enregistre les paliers franchis et prépare les annonces (envoyées par annoncer())."""
    if con.execute("SELECT 1 FROM inactifs WHERE nom=?", (nom,)).fetchone():
        return  # mule, banque… : ni palier ni annonce
    # Paliers de 10 : annoncés pour tout le monde, avec le rang (médaille pour le top 3).
    dernier = None
    for palier in PALIERS:
        if not (ancien < palier <= nouveau):
            continue
        dernier = palier
        if con.execute("SELECT 1 FROM exploits WHERE palier=? AND nom=?", (palier, nom)).fetchone():
            continue
        date = date_atteinte(con, nom, palier)
        con.execute("INSERT INTO exploits VALUES(?,?,?,?)", (palier, nom, 0, date))
        reclasser(con, palier)
        annonces.append({"date": date, "nom": nom, "classe": classe, "palier": palier})
    # Autres niveaux, sans classement : seulement le plus haut franchi, s'il dépasse le palier annoncé
    # (un envoi qui saute plusieurs niveaux ne produit pas une rafale de messages).
    autres = [n for n in range(ancien + 1, nouveau + 1) if n not in PALIERS and niveau_annonce(n)]
    if autres and (dernier is None or autres[-1] > dernier):
        n = autres[-1]
        annonces.append({"date": date_atteinte(con, nom, n), "nom": nom, "classe": classe, "niveau": n})


def annoncer(con, annonces, source="serveur"):
    """Annonces d'un envoi, en un seul message Discord (une ligne par annonce, dans l'ordre
    chronologique), une fois tout le fichier intégré : les rangs tiennent compte de tous les
    personnages du même envoi. (Entre deux envois, un rang déjà annoncé peut encore être
    corrigé sur le tableau d'honneur.) Le membre qui a envoyé les données est cité une fois
    à la fin (sauf collecte serveur)."""
    lignes = []
    for a in sorted(annonces, key=lambda a: a["date"]):  # tri stable : ordre du fichier à date égale
        nom, classe, quand = a["nom"], a["classe"], date_lisible(a["date"])
        if "niveau" in a:
            lignes.append(f"⬆️ **{nom}** ({classe}) passe **niveau {a['niveau']}** ({quand}) !")
            continue
        palier = a["palier"]
        rang = con.execute("SELECT rang FROM exploits WHERE palier=? AND nom=?", (palier, nom)).fetchone()[0]
        medaille = MEDAILLES.get(rang, "🏆" if palier == 60 else "⭐")
        if palier == 60:
            lignes.append(f"{medaille} **{nom}** ({classe}) atteint le **niveau 60** {quand} ! "
                          f"{ordinal(rang)} de la guilde à toucher le sommet. Félicitations !")
        else:
            lignes.append(f"{medaille} **{nom}** ({classe}) est le {ordinal(rang)} de la guilde "
                          f"à atteindre le **niveau {palier}** ({quand}) !")
    if not lignes:
        return
    if source != "serveur":
        lignes.append("_— via " + re.sub(r"([\\*_~`|>])", r"\\\1", source) + "_")
    # Discord limite un message à 2000 caractères : découpe par lignes si besoin.
    bloc = ""
    for ligne in lignes:
        if bloc and len(bloc) + 1 + len(ligne) > 1900:
            discord(bloc)
            bloc = ""
        bloc = f"{bloc}\n{ligne}" if bloc else ligne
    discord(bloc)


def corriger_exploits(con, nom):
    """Avance la date d'un palier déjà enregistré si une date plus ancienne est connue, puis reclasse."""
    for e in con.execute("SELECT palier, date FROM exploits WHERE nom=?", (nom,)).fetchall():
        date = date_atteinte(con, nom, e["palier"])
        if date and date < e["date"]:
            con.execute("UPDATE exploits SET date=? WHERE palier=? AND nom=?", (date, e["palier"], nom))
            reclasser(con, e["palier"])


# ---------- Contributeurs ----------
def cles_fichier():
    """Clés de cles.txt (lignes Pseudo:clé) : {pseudo: clé}."""
    if not FICHIER_CLES.exists():
        return {}
    cles = {}
    for ligne in FICHIER_CLES.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and ":" in ligne:
            pseudo, c = ligne.split(":", 1)
            cles[pseudo.strip()] = c.strip()
    return cles


def contributeur(cle):
    """Renvoie le pseudo associé à une clé, ou None. Une clé créée ou régénérée depuis le site
    (table comptes) remplace celle de cles.txt pour ce pseudo."""
    if not cle or not cle.strip():
        return None
    cle = cle.strip()
    with db() as con:
        r = con.execute("SELECT pseudo FROM comptes WHERE cle=?", (cle,)).fetchone()
        if r:
            return r[0]
        remplacees = {p.casefold() for (p,) in con.execute("SELECT pseudo FROM comptes WHERE cle IS NOT NULL")}
    for pseudo, c in cles_fichier().items():
        if hmac.compare_digest(c.encode(), cle.encode()) and pseudo.casefold() not in remplacees:
            return pseudo
    return None


def cle_du_compte(compte):
    return compte["cle"] or cles_fichier().get(compte["pseudo"]) or next(
        (c for p, c in cles_fichier().items() if p.casefold() == compte["pseudo"].casefold()), None)


def pseudo_du_fichier(nom):
    """Pseudo de cles.txt correspondant à nom (sans tenir compte de la casse), ou None."""
    return next((p for p in cles_fichier() if p.casefold() == nom.casefold()), None)


def lier(con, d, pseudo, cle=None):
    con.execute("INSERT INTO comptes(discord_id, pseudo, cle, discord_nom, lie_le, battletag) VALUES(?,?,?,?,?,?)",
                (d["id"], pseudo, cle, d["nom"], maintenant(), d.get("battletag")))


def liaison_auto(con, d):
    """Relie le compte Discord au pseudo de cles.txt identique à l'un de ses noms Discord
    (surnom sur le serveur, nom affiché, nom d'utilisateur), si ce pseudo est encore libre."""
    for nom in d.get("noms", [d["nom"]]):
        pseudo = pseudo_du_fichier(nom)
        if pseudo and not con.execute("SELECT 1 FROM comptes WHERE pseudo=?", (pseudo,)).fetchone():
            lier(con, d, pseudo)
            return pseudo
    return None


def nouvelle_cle(con):
    prises = set(cles_fichier().values())
    while True:
        cle = secrets.token_urlsafe(18)
        if cle not in prises and not con.execute("SELECT 1 FROM comptes WHERE cle=?", (cle,)).fetchone():
            return cle


# ---------- Collecte ----------
def analyser_export(texte):
    """Extrait (nom, race, classe, niveau) d'un fichier GuildExport.lua."""
    persos = []
    for l in re.findall(r'\["[^"]+"\]\s*=\s*"([^"]+)"', texte):
        morceaux = l.split(";")
        if len(morceaux) == 4 and morceaux[3].isdigit():
            nom, race, classe, niveau = morceaux
            persos.append((nom, race, classe, int(niveau)))
    return persos


def analyser_mes_persos(texte):
    """Personnages du compte WoW qui a écrit le fichier (table GuildExportMesPersos, addon ≥ 1.2.0) :
    SavedVariables est commun à tous les personnages d'un compte."""
    bloc = re.search(r"GuildExportMesPersos\s*=\s*\{(.*?)\}", texte, re.S)
    return re.findall(r'\["([^"]+)"\]', bloc.group(1)) if bloc else []


def analyser_rangs(texte):
    """{nom: n° de rang} de la table GuildExportRangs (addon ≥ 1.3.0, 0 = maître de guilde)."""
    bloc = re.search(r"GuildExportRangs\s*=\s*\{(.*?)\}", texte, re.S)
    return {nom: int(r) for nom, r in re.findall(r'\["([^"]+)"\]\s*=\s*"(\d{1,2})"', bloc.group(1))} if bloc else {}


# Sources d'association personnage → joueur. « admin » (choix d'un officier) l'emporte sur tout ;
# « blizzard » est réservée à une future connexion Battle.net (liste des persos du compte).
SOURCES = {"admin": "attribué par un officier", "blizzard": "vérifié par Battle.net",
           "addon": "détecté par l'addon", "manuel": "ajouté à la main", "nom": "même nom que le pseudo"}


def associer(con, pseudo, noms, source):
    """Associe des personnages à un joueur. « admin » remplace tout et n'est remplacé que par un
    autre choix d'officier ; « blizzard » remplace l'addon et les saisies ; l'addon remplace les
    saisies ; une saisie manuelle ne prend jamais le perso d'un autre."""
    for nom in noms:
        r = con.execute("SELECT pseudo, source FROM proprietaires WHERE nom=?", (nom,)).fetchone()
        if r and source != "admin" and (
                r["source"] == "admin"
                or r["source"] == "blizzard" and source != "blizzard"
                or source == "manuel" and (r["source"] != "manuel" or r["pseudo"] != pseudo)):
            continue
        con.execute("INSERT OR REPLACE INTO proprietaires VALUES(?,?,?,?)", (nom, pseudo, source, maintenant()))


def contributeurs(con, limite=None):
    """Classement des membres qui envoient des fichiers : montées de niveau signalées (premier
    à les transmettre), puis nombre d'envois. La collecte serveur n'est pas comptée."""
    discord_de = {c["pseudo"].casefold(): c["discord_id"] for c in con.execute("SELECT pseudo, discord_id FROM comptes")}
    lignes = con.execute("""SELECT pseudo, COUNT(*) envois, SUM(nouveautes) montees, SUM(personnages) lus,
        MAX(date) dernier FROM envois WHERE pseudo != 'serveur' GROUP BY pseudo
        ORDER BY montees DESC, envois DESC, dernier DESC""" + (f" LIMIT {int(limite)}" if limite else "")).fetchall()
    return [{**dict(l), "discord": discord_de.get(l["pseudo"].casefold())} for l in lignes]


def joueurs(con):
    """Pseudos connus (cles.txt et comptes reliés), triés."""
    return sorted(set(cles_fichier()) | {r[0] for r in con.execute("SELECT pseudo FROM comptes")}, key=str.casefold)


def proprietaires(con, noms):
    """{nom du perso: {pseudo, discord, source}} : table proprietaires, sinon perso du même nom qu'un pseudo."""
    pseudos = {p.casefold(): p for p in cles_fichier()}
    discord_de = {}
    for c in con.execute("SELECT pseudo, discord_id FROM comptes"):
        pseudos[c["pseudo"].casefold()] = c["pseudo"]
        discord_de[c["pseudo"].casefold()] = c["discord_id"]
    lignes = {r["nom"]: r for r in con.execute("SELECT * FROM proprietaires")}
    res = {}
    for nom in noms:
        if nom in lignes:
            pseudo, source = lignes[nom]["pseudo"], lignes[nom]["source"]
        elif nom.casefold() in pseudos:
            pseudo, source = pseudos[nom.casefold()], "nom"
        else:
            continue
        res[nom] = {"pseudo": pseudo, "discord": discord_de.get(pseudo.casefold()), "source": source}
    return res


def analyser_dates(texte):
    """Extrait {nom: {niveau: date ISO}} de la table GuildExportNiveaux ("10@horodatage,11@…",
    horodatages en secondes de l'horloge du serveur WoW)."""
    dates = {}
    for nom, valeur in re.findall(r'\["([^"]+)"\]\s*=\s*"(\d+@\d+(?:,\d+@\d+)*)"', texte):
        for paire in valeur.split(","):
            niveau, ts = map(int, paire.split("@"))
            if 1 <= niveau <= 60 and 0 < ts < 4102444800:  # avant 2100
                dates.setdefault(nom, {})[niveau] = depuis_epoch(ts)
    return dates


def dater(con, nom, connues, plafond, nouveau=None):
    """Enregistre les dates de passage de niveau dans l'historique : la plus ancienne connue gagne,
    jamais dans le futur ; sans date fournie, le nouveau niveau prend la date de réception."""
    limite = maintenant()
    for niveau, date in connues.items():
        if niveau > plafond:
            continue
        date = min(date, limite)
        row = con.execute("SELECT date FROM historique WHERE nom=? AND niveau=?", (nom, niveau)).fetchone()
        if row is None:
            con.execute("INSERT INTO historique VALUES(?,?,?)", (nom, niveau, date))
        elif date < row["date"]:
            con.execute("UPDATE historique SET date=? WHERE nom=? AND niveau=?", (date, nom, niveau))
    if nouveau is not None and not con.execute(
            "SELECT 1 FROM historique WHERE nom=? AND niveau=?", (nom, nouveau)).fetchone():
        con.execute("INSERT INTO historique VALUES(?,?,?)", (nom, nouveau, limite))
    # Un niveau ne peut pas avoir été atteint après un niveau supérieur.
    plus_tot = None
    for r in con.execute("SELECT rowid, date FROM historique WHERE nom=? ORDER BY niveau DESC",
                         (nom,)).fetchall():
        if plus_tot is not None and r["date"] > plus_tot:
            con.execute("UPDATE historique SET date=? WHERE rowid=?", (plus_tot, r["rowid"]))
        else:
            plus_tot = r["date"]


def integrer(persos, source="serveur", dates=None, rangs=None):
    """Fusionne des données : garde toujours le niveau le plus haut, complète les races
    et date les montées de niveau (dates de l'addon si fournies, sinon date de réception).
    rangs = {nom: n° de rang dans la guilde} (API Blizzard) ; sans, le rang connu est gardé."""
    dates = dates or {}
    nouveaux, annonces = 0, []
    with db() as con:
        for nom, race, classe, niveau in persos:
            row = con.execute("SELECT niveau, race FROM personnages WHERE nom=?", (nom,)).fetchone()
            race_connue = race not in (None, "", "?")
            if row and niveau < row["niveau"]:
                if race_connue and row["race"] in (None, "?"):
                    con.execute("UPDATE personnages SET race=? WHERE nom=?", (race, nom))
                dater(con, nom, dates.get(nom, {}), row["niveau"])
                corriger_exploits(con, nom)
                continue
            if row and not race_connue:
                race = row["race"]
            ancien = row["niveau"] if row else 1
            monte = row is None or niveau > row["niveau"]
            dater(con, nom, dates.get(nom, {}), niveau, niveau if monte else None)
            corriger_exploits(con, nom)
            if monte:
                verifier_exploits(con, nom, classe, ancien, niveau, annonces)
                nouveaux += 1
            con.execute("""INSERT INTO personnages(nom, race, classe, niveau, maj) VALUES(?,?,?,?,?)
                ON CONFLICT(nom) DO UPDATE SET race=excluded.race, classe=excluded.classe,
                niveau=excluded.niveau, maj=excluded.maj""",
                        (nom, race, classe, niveau, maintenant()))
        for nom, rang in (rangs or {}).items():
            con.execute("UPDATE personnages SET rang=? WHERE nom=?", (rang, nom))
        con.execute("INSERT INTO envois VALUES(?,?,?,?)", (source, maintenant(), len(persos), nouveaux))
        annoncer(con, annonces, source)
    return nouveaux


# ---------- API Blizzard ----------
_bnet = {"jeton": None, "expire": 0, "race": {}, "class": {}}


def slug(texte):
    return texte.strip().lower().replace("'", "").replace(" ", "-")


def bnet_actif():
    return bool(BNET_ID and BNET_SECRET and BNET_ROYAUME and BNET_GUILDE)


def bnet_get(chemin, espace):
    """GET sur l'API (jeton client_credentials gardé jusqu'à son expiration) ; None si échec."""
    if not _bnet["jeton"] or _bnet["expire"] < datetime.datetime.now().timestamp():
        r = requests.post("https://oauth.battle.net/token", data={"grant_type": "client_credentials"},
                          auth=(BNET_ID, BNET_SECRET), timeout=15)
        if r.status_code != 200:
            print("API Blizzard : jeton refusé", r.status_code, flush=True)
            return None
        d = r.json()
        _bnet["jeton"] = d["access_token"]
        _bnet["expire"] = datetime.datetime.now().timestamp() + d.get("expires_in", 3600) - 60
    r = requests.get(f"https://{BNET_REGION}.api.blizzard.com{chemin}",
                     params={"namespace": f"{espace}-{BNET_ESPACE}-{BNET_REGION}", "locale": "fr_FR"},
                     headers={"Authorization": f"Bearer {_bnet['jeton']}"}, timeout=15)
    if r.status_code != 200:
        print("API Blizzard :", chemin, r.status_code, flush=True)
        return None
    return r.json()


def libelles(type_):
    """{id: nom français} des races ou classes jouables, lu une fois par démarrage."""
    if not _bnet[type_]:
        d = bnet_get(f"/data/wow/playable-{type_}/index", "static") or {}
        _bnet[type_] = {x["id"]: x["name"] for x in d.get("races" if type_ == "race" else "classes", [])}
    return _bnet[type_]


def lire_api_blizzard():
    """Roster de la guilde via l'API → (persos au format d'analyser_export(), dates, rangs). Une montée de
    niveau est datée par la dernière connexion du perso (profil), borne haute plus juste que l'heure
    de collecte, si elle est postérieure à la dernière fois qu'on l'a vu à l'ancien niveau (sinon
    c'est l'heure de connexion d'une session encore en cours). ([], {}, {}) si inactif ou en échec."""
    if not bnet_actif():
        return [], {}, {}
    try:
        d = bnet_get(f"/data/wow/guild/{slug(BNET_ROYAUME)}/{slug(BNET_GUILDE)}/roster", "profile")
        if not d:
            return [], {}, {}
        races, classes = libelles("race"), libelles("class")
        persos = {}
        for m in d.get("members", []):
            c = m.get("character", {})
            nom, niveau = c.get("name"), c.get("level") or 0
            if not nom or (nom in persos and persos[nom][3] >= niveau):
                continue  # homonyme sur un royaume connecté : le plus haut niveau l'emporte
            persos[nom] = (nom, races.get(c.get("playable_race", {}).get("id"), "?"),
                           classes.get(c.get("playable_class", {}).get("id"), "?"), niveau,
                           c.get("realm", {}).get("slug") or slug(BNET_ROYAUME), m.get("rank"))
        dates = {}
        with db() as con:
            for nom, _, _, niveau, royaume, _ in persos.values():
                row = con.execute("SELECT niveau, maj FROM personnages WHERE nom=?", (nom,)).fetchone()
                if row and niveau <= row["niveau"]:
                    continue
                profil = bnet_get(f"/profile/wow/character/{royaume}/{nom.lower()}", "profile") or {}
                ts = profil.get("last_login_timestamp")
                if not ts or profil.get("level") != niveau:
                    continue
                date = depuis_epoch(ts / 1000)
                if row is None or date >= row["maj"]:
                    dates[nom] = {niveau: date}
        rangs = {p[0]: p[5] for p in persos.values() if isinstance(p[5], int)}
        return [p[:4] for p in persos.values()], dates, rangs
    except (requests.RequestException, ValueError, KeyError) as e:
        print("API Blizzard : erreur", e, flush=True)
        return [], {}, {}


def collecter():
    """Intègre l'API Blizzard si elle répond, sinon le fichier déposé côté serveur.
    Renvoie (nombre de mises à jour, source lue ou None)."""
    persos, dates, rangs = lire_api_blizzard()
    source = "blizzard" if persos else None
    if not persos and EXPORT.exists():
        texte = EXPORT.read_text(encoding="utf-8")
        persos, dates, rangs = analyser_export(texte), analyser_dates(texte), analyser_rangs(texte)
        source = "fichier" if persos else None
    return (integrer(persos, "serveur", dates, rangs) if persos else 0), source


# ---------- Récapitulatif ----------
def gains(con, heures):
    limite = (datetime.datetime.now() - datetime.timedelta(hours=heures)).isoformat(timespec="seconds")
    res = {}
    for p in con.execute("SELECT nom, niveau FROM personnages WHERE nom NOT IN (SELECT nom FROM inactifs)").fetchall():
        avant = con.execute("""SELECT niveau FROM historique WHERE nom=? AND date<=?
                               ORDER BY date DESC LIMIT 1""", (p["nom"], limite)).fetchone()
        if avant is None:
            avant = con.execute("SELECT MIN(niveau) AS niveau FROM historique WHERE nom=?",
                                (p["nom"],)).fetchone()
        base = avant["niveau"] if avant and avant["niveau"] is not None else p["niveau"]
        res[p["nom"]] = p["niveau"] - base
    return res


DEBUT_COURBE = datetime.date(2026, 11, 4)   # veille du lancement de WoW Forever
FIN_COURBE_MIN = datetime.date(2027, 1, 1)  # l'axe s'allonge tout seul au-delà


def aujourdhui():
    return datetime.date.today()


def quantile(valeurs, q):
    """Quantile par interpolation linéaire (valeurs triées)."""
    if not valeurs:
        return None
    pos = (len(valeurs) - 1) * q
    bas = int(pos)
    haut = min(bas + 1, len(valeurs) - 1)
    return round(valeurs[bas] + (valeurs[haut] - valeurs[bas]) * (pos - bas), 2)


def courbe(con, mes_noms=()):
    """Séries quotidiennes de la courbe de progression, du 4 novembre à aujourd'hui (fin de journée) :
    nombre de persos, moyenne, quartiles, min, max, et la courbe de chaque perso de mes_noms.
    Les personnages exclus (mules, banques) ne comptent pas."""
    exclus = inactifs(con)
    hist = {}
    for r in con.execute("SELECT nom, niveau, date FROM historique ORDER BY date"):
        if r["nom"] not in exclus:
            h = hist.setdefault(r["nom"], ([], []))
            h[0].append(r["date"])
            h[1].append(max(r["niveau"], h[1][-1] if h[1] else 0))  # niveau atteint, jamais en baisse
    jour = aujourdhui()
    fin = max(FIN_COURBE_MIN, jour)
    jours, d = [], DEBUT_COURBE
    while d <= min(jour, fin):
        jours.append(d)
        d += datetime.timedelta(days=1)
    series = {k: [] for k in ("n", "moyenne", "min", "q1", "mediane", "q3", "max")}
    persos = {n: [] for n in mes_noms if n in hist}
    for j in jours:
        borne = (j + datetime.timedelta(days=1)).isoformat() + "T00:00:00"
        niveaux = {}
        for nom, (dates, nivs) in hist.items():
            i = bisect.bisect_left(dates, borne)
            if i:
                niveaux[nom] = nivs[i - 1]
        v = sorted(niveaux.values())
        series["n"].append(len(v))
        series["moyenne"].append(round(sum(v) / len(v), 2) if v else None)
        series["min"].append(v[0] if v else None)
        series["max"].append(v[-1] if v else None)
        for k, q in (("q1", .25), ("mediane", .5), ("q3", .75)):
            series[k].append(quantile(v, q))
        for nom in persos:
            persos[nom].append(niveaux.get(nom))
    classes = {r["nom"]: r["classe"] for r in con.execute("SELECT nom, classe FROM personnages")}
    return {"debut": DEBUT_COURBE.isoformat(), "fin": fin.isoformat(), "jours": [j.isoformat() for j in jours],
            **series, "persos": [{"nom": n, "classe": classes.get(n, ""), "couleur": couleur(classes.get(n)),
                                  "niveaux": niv} for n, niv in persos.items()]}


def recap():
    with db() as con:
        persos = con.execute("""SELECT * FROM personnages WHERE nom NOT IN (SELECT nom FROM inactifs)
                                ORDER BY niveau DESC, nom""").fetchall()
        g = gains(con, 12)
    if not persos:
        return
    moyenne = sum(p["niveau"] for p in persos) / len(persos)
    lignes = [f"📜 **Progression de {NOM_GUILDE}** — {len(persos)} membres, niveau moyen {moyenne:.1f}"]
    for i, p in enumerate(persos[:15], 1):
        gain = f" (+{g[p['nom']]})" if g.get(p["nom"], 0) > 0 else ""
        lignes.append(f"`{i:>2}.` **{p['nom']}** — {p['classe']} {p['niveau']}{gain}")
    top = max(g.items(), key=lambda x: x[1], default=(None, 0))
    if top[1] > 0:
        lignes.append(f"🔥 Plus grosse progression sur 12 h : **{top[0]}** (+{top[1]} niveaux)")
    discord("\n".join(lignes))


# ---------- Web ----------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 Mo max par envoi


def cle_de_session():
    """Clé de signature des cookies de session, créée une fois à côté de la base."""
    f = Path(DB).with_name("secret.key")
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


app.secret_key = cle_de_session()
app.config.update(SESSION_COOKIE_SECURE=URL_SITE.startswith("https"), SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30))

STYLE = """
<link rel="icon" href="logo.png?v={{ version }}">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Manrope:wght@400;500;600;700&display=swap">
<style>
:root{--nuit:#070b14;--nuit2:#0c1322;--verre:rgba(148,196,255,.05);--verre2:rgba(148,196,255,.09);
--trait:rgba(148,196,255,.12);--trait2:rgba(148,196,255,.22);--texte:#e6eefb;--doux:#8a9ab5;--pale:#5d6b85;
--cristal:#5fd8f5;--cristal2:#a7b8ff;--givre:#d9f6ff;--or:#f0c35a;--argent:#c9d3e3;--bronze:#d68f5c;
--vert:#5ee3a6;--rouge:#ff8a7a;--alerte:#ffb454;
--f-titre:"Sora","Manrope",system-ui,sans-serif;--f-corps:"Manrope",system-ui,-apple-system,"Segoe UI",sans-serif;
color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--nuit);color:var(--texte);font-family:var(--f-corps);font-size:15px;line-height:1.5;
background-image:radial-gradient(900px 480px at 15% -10%,rgba(95,216,245,.13),transparent 60%),
radial-gradient(700px 420px at 95% 0%,rgba(167,184,255,.10),transparent 60%);background-repeat:no-repeat}
.page{max-width:1080px;margin:0 auto;padding:28px 16px 56px;display:flex;flex-direction:column;gap:40px}
h1,h2,h3{font-family:var(--f-titre);margin:0}
h2{font-size:1.15rem;font-weight:600;display:flex;align-items:baseline;gap:10px}
h2 small{font-family:var(--f-corps);font-size:.8rem;color:var(--doux);font-weight:500}
a{color:var(--cristal);text-decoration:none}
.num{font-variant-numeric:tabular-nums}
.sec{display:flex;flex-direction:column;gap:14px}
.carte{background:var(--verre);border:1px solid var(--trait);border-radius:16px}
header{display:flex;align-items:center;gap:22px;flex-wrap:wrap;position:relative;overflow:hidden;
padding:clamp(22px,4vw,40px);min-height:220px;border-radius:20px;border:1px solid var(--trait2);
background:linear-gradient(90deg,rgba(7,11,20,.92) 0%,rgba(7,11,20,.7) 45%,rgba(7,11,20,.15) 100%),
linear-gradient(0deg,rgba(7,11,20,.55),transparent 40%),url(banniere.jpg?v={{ version }}) center 40%/cover no-repeat,var(--nuit2);
box-shadow:0 18px 60px rgba(0,0,0,.45),0 0 60px rgba(95,216,245,.08)}
@media (min-width:861px){header{min-height:260px;
background:linear-gradient(90deg,rgba(7,11,20,1) 0%,rgba(7,11,20,.96) 30%,rgba(7,11,20,.55) 55%,rgba(7,11,20,.05) 100%),
linear-gradient(0deg,rgba(7,11,20,.5),transparent 35%),url(banniere.jpg?v={{ version }}) right 58%/72% auto no-repeat,var(--nuit)}}
.logo{flex:0 0 auto;width:clamp(72px,11vw,120px);position:relative}
.logo::before{content:"";position:absolute;inset:-35% -45%;border-radius:50%;pointer-events:none;
background:radial-gradient(closest-side,rgba(95,216,245,.32),rgba(95,216,245,.08) 55%,transparent)}
.logo img{position:relative;display:block;width:100%;height:auto;filter:drop-shadow(0 6px 14px rgba(0,0,0,.55))}
.titre{flex:1 1 260px;min-width:0}
h1{font-size:clamp(1.6rem,4vw,2.2rem);font-weight:700;letter-spacing:-.02em;
background:linear-gradient(100deg,var(--givre),var(--cristal) 55%,var(--cristal2));-webkit-background-clip:text;background-clip:text;color:transparent}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{font-size:.75rem;font-weight:600;color:var(--doux);border:1px solid var(--trait);border-radius:999px;padding:3px 10px;background:var(--verre)}
.tag.horde{color:var(--rouge);border-color:rgba(255,138,122,.3)}
.tag.live{color:var(--vert);border-color:rgba(94,227,166,.3)}
.tag.live::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--vert);margin-right:6px;vertical-align:1px;box-shadow:0 0 6px var(--vert)}
.cta,button{font-family:var(--f-titre);font-weight:600;font-size:.88rem;color:var(--nuit);background:linear-gradient(135deg,var(--givre),var(--cristal));
padding:10px 16px;border:0;border-radius:12px;box-shadow:0 6px 24px rgba(95,216,245,.25);white-space:nowrap;cursor:pointer}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--cristal);outline-offset:2px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat{padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.stat b{font-family:var(--f-titre);font-size:1.9rem;font-weight:600;letter-spacing:-.02em}
.stat span{color:var(--doux);font-size:.8rem;font-weight:500}
.stat em{font-style:normal;font-size:.75rem;color:var(--vert);font-weight:600}
@media (max-width:680px){.stats{grid-template-columns:repeat(2,1fr)}}
.p60{padding:18px;display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:center;
background:linear-gradient(120deg,rgba(240,195,90,.12),rgba(240,195,90,.02) 60%),var(--verre);border-color:rgba(240,195,90,.3)}
.p60 h3{font-size:1rem;color:var(--or);font-weight:600;line-height:1.25}
.p60 h3 small{display:block;font-family:var(--f-corps);color:var(--doux);font-size:.75rem;font-weight:500}
.p60 .liste{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.heros{display:flex;align-items:center;gap:10px;background:rgba(7,11,20,.45);border:1px solid var(--trait);border-radius:12px;padding:10px 12px;min-width:0}
.heros .r{font-family:var(--f-titre);font-weight:700;color:var(--or);font-size:.9rem;min-width:22px}
.heros div,.e div{display:flex;flex-direction:column;min-width:0}
.heros b,.e b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.heros small{color:var(--doux);font-size:.74rem}
@media (max-width:720px){.p60{grid-template-columns:1fr}.p60 .liste{grid-template-columns:1fr}}
.paliers{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.palier{padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.palier h3{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--doux);font-family:var(--f-corps);font-weight:700}
.palier h3 b{font-family:var(--f-titre);font-size:1.4rem;color:var(--texte);margin-left:4px}
.e{display:grid;grid-template-columns:18px 1fr;gap:8px;align-items:start;font-size:.86rem}
.e .m{width:18px;height:18px;border-radius:50%;margin-top:2px;display:grid;place-items:center;font:700 .62rem var(--f-titre);color:var(--nuit)}
.m1{background:var(--or)}.m2{background:var(--argent)}.m3{background:var(--bronze)}
.e small{color:var(--pale);font-size:.72rem}
.vide{color:var(--pale);font-size:.82rem}
@media (max-width:860px){.paliers{grid-template-columns:repeat(2,1fr)}}
.barre-outils{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between}
select,input{background:var(--nuit2);color:var(--texte);border:1px solid var(--trait);border-radius:10px;padding:8px 10px;font:500 .88rem var(--f-corps)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:640px}
th,td{padding:10px 12px;text-align:left;font-size:.88rem;white-space:nowrap}
th{color:var(--pale);font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.09em;border-bottom:1px solid var(--trait)}
tbody tr+tr td{border-top:1px solid rgba(148,196,255,.06)}
tbody tr:hover{background:var(--verre2)}
td.rang{color:var(--pale);font-weight:700;width:36px}
td.nom{font-weight:700}
.joueur{font:500 .78rem var(--f-corps);color:var(--doux);margin-left:6px;text-decoration:none;white-space:nowrap}
.rang-guilde{color:var(--doux);font-size:.85rem;white-space:nowrap}
a.joueur:hover{color:var(--cristal);text-decoration:underline}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;vertical-align:1px}
.niv{display:inline-grid;place-items:center;min-width:36px;padding:3px 8px;border-radius:8px;font:700 .9rem var(--f-titre);background:var(--verre2);border:1px solid var(--trait)}
.niv.max{color:var(--nuit);background:linear-gradient(135deg,#ffe29a,var(--or));border-color:transparent}
.barre{background:rgba(148,196,255,.08);border-radius:99px;height:6px;width:110px;overflow:hidden}
.barre i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--cristal2),var(--cristal))}
.barre i.max{background:linear-gradient(90deg,#ffe29a,var(--or))}
.gain{color:var(--vert);font-weight:700;font-size:.82rem;background:rgba(94,227,166,.1);border-radius:6px;padding:2px 6px}
.fil-carte{padding:18px}
ul.fil{list-style:none;margin:0;padding:0}
ul.fil li{display:grid;grid-template-columns:44px 1fr auto;gap:12px;align-items:center;padding:8px 0;font-size:.88rem}
ul.fil li+li{border-top:1px solid rgba(148,196,255,.06)}
ul.fil .nv{font:700 .85rem var(--f-titre);text-align:center;border-radius:8px;padding:3px 0;background:var(--verre2)}
ul.fil .nv.max{background:linear-gradient(135deg,#ffe29a,var(--or));color:var(--nuit)}
ul.fil small{color:var(--pale);font-size:.75rem}
footer{color:var(--pale);font-size:.78rem;display:flex;align-items:center;gap:10px}
footer img{width:16px;opacity:.7}
.formulaire{padding:22px;display:flex;flex-direction:column;gap:16px;max-width:560px}
.formulaire label{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:.88rem}
.formulaire small{color:var(--doux);font-weight:500;overflow-wrap:anywhere}
.msg{padding:10px 14px;border-radius:10px;font-size:.9rem;border:1px solid}
.ok{color:var(--vert);background:rgba(94,227,166,.08);border-color:rgba(94,227,166,.3)}
.err{color:var(--rouge);background:rgba(255,138,122,.08);border-color:rgba(255,138,122,.3)}
.actions,.boutons{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.cta.sec,button.sec{background:transparent;color:var(--texte);border:1px solid var(--trait2);box-shadow:none}
.formulaire form{display:flex;flex-direction:column;gap:12px}
.formulaire h2{margin:0}
.formulaire p{margin:0}
.formulaire a:not(.cta){color:var(--cristal)}
.bloc{padding:20px 22px;display:flex;flex-direction:column;gap:14px;min-width:0}
.bloc>p,.bloc form p{margin:0}
.bloc label{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:.88rem}
.bloc small,.bloc .aide{color:var(--doux);font-size:.8rem;font-weight:500;overflow-wrap:anywhere}
.bloc form{display:flex;flex-direction:column;gap:12px}
.bloc-tete{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
padding-bottom:12px;border-bottom:1px solid var(--trait)}
.bloc-tete h2 .ic{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:9px;background:var(--verre2);
border:1px solid var(--trait);font-size:.9rem}
.grille2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:760px){.grille2{grid-template-columns:1fr}}
.infos{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;margin:0;font-size:.9rem}
.infos dt{color:var(--doux);font-weight:500}.infos dd{margin:0;font-weight:600;overflow-wrap:anywhere}
.puce{display:inline-block;font-size:.7rem;font-weight:700;letter-spacing:.02em;border-radius:999px;padding:2px 8px;
border:1px solid var(--trait);color:var(--doux);background:var(--verre);white-space:nowrap}
.puce.verifie{color:var(--vert);border-color:rgba(94,227,166,.3)}
.puce.admin{color:var(--or);border-color:rgba(240,195,90,.35)}
.ligne{display:flex;gap:8px;align-items:stretch;flex-wrap:wrap}.ligne input{flex:1 1 200px;min-width:0}
.persos,.bloc form.persos{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.perso{--c:#8a9ab5;display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:14px;min-width:0;text-align:left;
background:linear-gradient(90deg,color-mix(in srgb,var(--c) 14%,transparent),transparent 70%),rgba(7,11,20,.45);
border:1px solid color-mix(in srgb,var(--c) 30%,transparent);border-left:3px solid var(--c);color:var(--texte);font:inherit}
.embleme{flex:0 0 auto;display:grid;place-items:center;width:38px;height:38px;border-radius:11px;
background:color-mix(in srgb,var(--c) 22%,var(--nuit2));border:1px solid color-mix(in srgb,var(--c) 55%,transparent);
box-shadow:0 0 14px color-mix(in srgb,var(--c) 25%,transparent)}
.embleme svg{width:22px;height:22px;fill:none;stroke:var(--c);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.embleme.mini{width:26px;height:26px;border-radius:8px}.embleme.mini svg{width:15px;height:15px}
.perso-id{display:flex;flex-direction:column;min-width:0;flex:1}
.perso-id b{font-family:var(--f-titre);font-weight:600;color:var(--c);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.perso-id small{color:var(--doux);font-size:.76rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.perso .niv{font-size:.8rem;min-width:30px;padding:2px 6px}
.perso form{margin:0}
.retirer{display:grid;place-items:center;width:28px;height:28px;padding:0;border-radius:8px;font-size:1rem;line-height:1}
button.perso{cursor:pointer;box-shadow:none;white-space:normal;transition:transform .12s,border-color .12s}
button.perso:hover{transform:translateY(-1px);border-color:var(--c)}
button.perso .plus{font:700 1.1rem var(--f-titre);color:var(--c);opacity:.8}
.vide-etat{padding:18px;border:1px dashed var(--trait2);border-radius:14px;color:var(--doux);font-size:.88rem;text-align:center}
.recherche{width:220px;max-width:100%}
.filtres{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
@media (max-width:600px){.recherche,.filtres{width:100%}.filtres>*{flex:1}}
.bloc .table-wrap{margin:0 -22px;padding:0 22px}
.bloc table{min-width:700px}
td .persoligne{display:flex;align-items:center;gap:10px}
td .persoligne b{font-family:var(--f-titre);font-weight:600;color:var(--c)}
td .persoligne small{color:var(--doux);font-size:.74rem;display:block;font-weight:500}
.danger{border-color:rgba(255,138,122,.3);background:linear-gradient(120deg,rgba(255,138,122,.07),transparent 60%),var(--verre)}
button.danger-btn{background:linear-gradient(135deg,#ffc2b8,var(--rouge));box-shadow:0 6px 24px rgba(255,138,122,.2)}
.puces{display:flex;flex-wrap:wrap;gap:6px}
.ligne-form,.bloc form.ligne-form{display:flex;flex-direction:row;gap:6px;align-items:center}
.puce.exclu{color:var(--alerte);border-color:rgba(255,180,84,.35)}
tr.exclu td:first-child,tr.exclu td:nth-child(2){opacity:.55}
.contribs{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.courbe-carte{position:relative}
.courbe{width:100%;min-height:240px}
.courbe svg{display:block;overflow:visible}
.courbe .grille{stroke:rgba(148,196,255,.1);stroke-width:1}
.courbe .axe{fill:var(--pale);font:500 11px var(--f-corps)}
.courbe .etiquette{fill:var(--texte);font:600 11.5px var(--f-corps)}
.courbe .aujourdhui{stroke:rgba(148,196,255,.25);stroke-width:1}
.courbe .reticule{stroke:var(--givre);stroke-width:1;opacity:.55}
.courbe .vide-courbe{fill:var(--doux);font:500 14px var(--f-corps)}
.legende{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:.78rem;color:var(--doux)}
.legende span{display:inline-flex;align-items:center;gap:6px}
.legende i.trait{display:inline-block;width:14px;height:3px;border-radius:2px}
.legende i.bande{display:inline-block;width:14px;height:10px;border-radius:3px}
.infobulle{position:absolute;z-index:2;pointer-events:none;background:rgba(7,11,20,.96);border:1px solid var(--trait2);
border-radius:10px;padding:8px 10px;font-size:.78rem;color:var(--doux);box-shadow:0 10px 30px rgba(0,0,0,.45);min-width:150px}
.infobulle>b{display:block;color:var(--texte);font-family:var(--f-titre);font-weight:600;margin-bottom:4px}
.infobulle div{display:flex;align-items:center;gap:6px;white-space:nowrap}
.infobulle i{display:inline-block;width:12px;height:3px;border-radius:2px;flex:0 0 auto}
.infobulle strong{color:var(--texte);font-variant-numeric:tabular-nums}
.donnees summary{cursor:pointer;color:var(--doux);font-size:.82rem}
.donnees .table-wrap{max-height:280px;overflow:auto;margin-top:8px}
.donnees table{min-width:520px}
@media (max-width:720px){.contribs{grid-template-columns:1fr}}
.contrib{display:flex;align-items:center;gap:12px;padding:14px 16px;min-width:0}
.contrib .m{flex:0 0 auto;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font:700 .85rem var(--f-titre);color:var(--nuit)}
.contrib div{display:flex;flex-direction:column;min-width:0}
.contrib>div>b{font-family:var(--f-titre);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.contrib>div>b a{color:var(--texte)}.contrib>div>b a:hover{color:var(--cristal)}
.contrib small{color:var(--doux);font-size:.78rem}.contrib small b{color:var(--texte)}
</style>
"""

PIED = """<footer><img src="logo.png?v={{ version }}" alt="">{{ guilde }} · v{{ version }}</footer>"""

ENTETE = """<header>
<div class="logo"><img src="logo.png?v={{ version }}" alt="Logo {{ guilde }}"></div>
<div class="titre"><h1>{{ titre or guilde }}</h1>
<div class="meta"><span class="tag horde">Horde</span><span class="tag">WoW Forever · PvE</span>
{% if maj %}<span class="tag live">Mis à jour {{ maj }}</span>{% endif %}</div></div>
<div class="actions">{% if titre %}<a class="cta" href="./">← Retour au classement</a>
{% else %}<a class="cta" href="contribuer">Envoyer mes données</a>{% endif %}
{% if discord_actif %}{% if session.discord %}<a class="cta sec" href="moi">Mon compte</a><a class="cta sec" href="deconnexion">Déconnexion</a>
{% else %}<a class="cta sec" href="{{ url_connexion() }}">Connexion Discord</a>{% endif %}{% endif %}</div>
</header>"""

PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ guilde }} — Progression</title>""" + STYLE + """</head><body><div class="page">
""" + ENTETE + """

<section class="stats">
 <div class="carte stat"><span>Membres suivis</span><b class="num">{{ persos|length }}</b><em>{{ actifs }} actifs en 24 h</em></div>
 <div class="carte stat"><span>Niveau moyen</span><b class="num">{{ moyenne }}</b><em>&nbsp;</em></div>
 <div class="carte stat"><span>Niveau 60</span><b class="num">{{ nb60 }}</b><em>&nbsp;</em></div>
 <div class="carte stat"><span>Niveaux gagnés en 24 h</span><b class="num">+{{ total24 }}</b><em>&nbsp;</em></div>
</section>

<section class="carte bloc courbe-carte">
<div class="bloc-tete"><h2>Progression de la guilde <small>niveau de chaque membre, jour après jour</small></h2>
<div class="legende" id="legende" aria-hidden="true"></div></div>
<div class="courbe" id="courbe" role="img" aria-label="Courbe de progression des niveaux de la guilde depuis le 4 novembre"></div>
<div class="infobulle" id="infobulle" hidden></div>
{% if not connecte and discord_actif %}<small><a href="{{ url_connexion() }}">Connecte-toi</a> pour voir tes personnages sur la courbe.</small>{% endif %}
<details class="donnees"><summary>Voir les données</summary><div class="table-wrap"><table><thead><tr><th>Jour</th><th>Persos</th><th>Moyenne</th>
<th>Q1</th><th>Médiane</th><th>Q3</th><th>Min</th><th>Max</th>{% for c in donnees_courbe.persos %}<th>{{ c.nom }}</th>{% endfor %}</tr></thead><tbody>
{% for j in donnees_courbe.jours %}{% set i = loop.index0 %}<tr><td>{{ j[8:] }}/{{ j[5:7] }}</td><td class="num">{{ donnees_courbe.n[i] }}</td>
{% for k in ("moyenne", "q1", "mediane", "q3", "min", "max") %}<td class="num">{{ donnees_courbe[k][i] if donnees_courbe[k][i] is not none else "—" }}</td>{% endfor %}
{% for c in donnees_courbe.persos %}<td class="num">{{ c.niveaux[i] if c.niveaux[i] is not none else "—" }}</td>{% endfor %}</tr>
{% else %}<tr><td colspan="8">La courbe démarre le 4 novembre.</td></tr>{% endfor %}</tbody></table></div></details>
<script type="application/json" id="donnees-courbe">{{ donnees_courbe|tojson }}</script>
</section>

<section class="sec">
<h2>Tableau d'honneur <small>les trois premiers à chaque palier</small></h2>
<div class="carte p60"><h3>Panthéon du niveau 60<small>chaque membre qui atteint 60</small></h3><div class="liste">
{% for e in exploits.get(60, []) %}
 <div class="heros"><span class="r">{{ e.rang }}</span><div><b style="color:{{ couleur(classes.get(e.nom, '')) }}">{{ e.nom }}</b>
 <small>{{ classes.get(e.nom, '') }} · {{ e.date[:16].replace("T", " ") }}</small></div></div>
{% else %}<span class="vide">Personne pour l'instant…</span>{% endfor %}
</div></div>
<div class="paliers">
{% for p in paliers if p != 60 %}
 <div class="carte palier"><h3>Niveau<b>{{ p }}</b></h3>
 {% for e in exploits.get(p, [])[:3] %}
  <div class="e"><span class="m m{{ e.rang }}">{{ e.rang }}</span><div><b style="color:{{ couleur(classes.get(e.nom, '')) }}">{{ e.nom }}</b>
  <small>{{ e.date[:16].replace("T", " ") }}</small></div></div>
 {% else %}<span class="vide">Personne pour l'instant…</span>{% endfor %}
 </div>
{% endfor %}
</div>
</section>

<section class="sec">
<div class="barre-outils"><h2>Classement <small id="compte">{{ persos|length }} membres</small></h2>
<select id="filtre" aria-label="Filtrer par classe" onchange="filtrer(this.value)"><option value="">Toutes les classes</option>
{% for c in liste_classes %}<option>{{ c }}</option>{% endfor %}</select></div>
<div class="carte table-wrap"><table><thead><tr><th>#</th><th>Personnage</th><th>Race</th><th>Classe</th>{% if avec_rangs %}<th>Rang</th>{% endif %}<th>Niveau</th><th>Progression</th><th>24 h</th></tr></thead><tbody>
{% for p in persos %}
<tr data-classe="{{ p.classe }}"><td class="rang num">{{ loop.index }}</td>
<td class="nom" style="color:{{ couleur(p.classe) }}"><span class="dot" style="background:{{ couleur(p.classe) }}"></span>{{ p.nom }}
{%- set pr = proprios.get(p.nom) %}{% if pr %} {% if pr.discord %}<a class="joueur" href="https://discord.com/users/{{ pr.discord }}" target="_blank" rel="noopener" title="Profil Discord de {{ pr.pseudo }}">@{{ pr.pseudo }}</a>{% else %}<span class="joueur">@{{ pr.pseudo }}</span>{% endif %}{% endif %}</td>
<td>{{ p.race }}</td><td>{{ p.classe }}</td>
{% if avec_rangs %}<td class="rang-guilde">{% if p.rang is not none %}{{ rangs.get(p.rang) or "Rang " ~ p.rang }}{% endif %}</td>{% endif %}
<td><span class="niv num{{ ' max' if p.niveau == 60 else '' }}">{{ p.niveau }}</span></td>
<td><div class="barre"><i class="{{ 'max' if p.niveau == 60 else '' }}" style="width:{{ (p.niveau / 60 * 100)|round|int }}%"></i></div></td>
<td>{% if g24.get(p.nom, 0) > 0 %}<span class="gain num">+{{ g24[p.nom] }}</span>{% endif %}</td></tr>
{% else %}<tr><td colspan="{{ 8 if avec_rangs else 7 }}">Aucune donnée pour l'instant. Envoie ton fichier GuildExport.lua !</td></tr>{% endfor %}
</tbody></table></div>
</section>

{% if top %}<section class="sec">
<h2>Meilleurs contributeurs <small>merci pour vos envois !</small></h2>
<div class="contribs">{% for c in top %}
 <div class="carte contrib"><span class="m m{{ loop.index }}">{{ loop.index }}</span>
 <div><b>{% if c.discord %}<a href="https://discord.com/users/{{ c.discord }}" target="_blank" rel="noopener">{{ c.pseudo }}</a>{% else %}{{ c.pseudo }}{% endif %}</b>
 <small><b class="num">{{ c.montees }}</b> montée{{ "s" if c.montees > 1 }} de niveau signalée{{ "s" if c.montees > 1 }} · {{ c.envois }} envoi{{ "s" if c.envois > 1 }}</small></div></div>
{% endfor %}</div>
</section>{% endif %}

<section class="carte fil-carte sec">
<h2>Dernières montées de niveau</h2>
<ul class="fil">
{% for r in recents %}<li><span class="nv num{{ ' max' if r.niveau == 60 else '' }}">{{ r.niveau }}</span>
<span><b style="color:{{ couleur(classes.get(r.nom, '')) }}">{{ r.nom }}</b>
{{ "atteint le niveau max" if r.niveau == 60 else "passe niveau " ~ r.niveau }}</span>
<small>{{ r.date[:16].replace("T", " ") }}</small></li>{% else %}<li><small>Rien pour l'instant.</small></li>{% endfor %}
</ul>
</section>

<footer><img src="logo.png?v={{ version }}" alt="">{{ guilde }} · données collectées par l'addon GuildExport · v{{ version }}</footer>
</div>
<script>
// ---------- Courbe de progression (SVG dessiné à la main, aucune bibliothèque) ----------
(function(){
 var D=JSON.parse(document.getElementById("donnees-courbe").textContent),
  boite=document.getElementById("courbe"),bulle=document.getElementById("infobulle"),NS="http://www.w3.org/2000/svg",
  MOIS=["janv.","févr.","mars","avr.","mai","juin","juil.","août","sept.","oct.","nov.","déc."],
  JOUR=864e5,t0=Date.parse(D.debut),t1=Date.parse(D.fin),CRISTAL="#5fd8f5";
 function el(n,a,p){var e=document.createElementNS(NS,n);for(var k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e;}
 function txt(n,a,t,p){var e=el(n,a,p);e.textContent=t;return e;}
 function date(i){return new Date(t0+i*JOUR);}
 function court(d){return d.getUTCDate()+" "+MOIS[d.getUTCMonth()];}
 function fr(v){return v===""?"":String(Math.round(v*10)/10).replace(".",",");}
 var series=[{nom:"Moyenne",cle:"moyenne",couleur:CRISTAL,epais:2.5},{nom:"Plus haut niveau",cle:"max",couleur:"#8a9ab5",epais:1.5}];
 // Légende : clés en trait, texte en couleur de texte
 var leg=document.getElementById("legende");
 function cle(nom,couleur,bande){var s=document.createElement("span");var k=document.createElement("i");
  k.className=bande?"bande":"trait";k.style.background=couleur;s.appendChild(k);s.appendChild(document.createTextNode(nom));leg.appendChild(s);}
 cle("Moyenne",CRISTAL);cle("50 % des membres (Q1–Q3)","rgba(95,216,245,.35)",true);cle("Plus haut niveau","#8a9ab5");
 D.persos.forEach(function(p){cle(p.nom,p.couleur);});
 function dessiner(){
  boite.textContent="";var L=boite.clientWidth,H=L<560?240:320,g={h:14,d:D.persos.length&&D.persos.length<=4?84:18,b:30,gauche:34};
  var svg=el("svg",{width:L,height:H,viewBox:"0 0 "+L+" "+H},boite),W=L-g.gauche-g.d,Hh=H-g.h-g.b;
  function X(i){return g.gauche+(t0+i*JOUR-t0)/(t1-t0)*W;}
  function Y(v){return g.h+Hh-(v/60)*Hh;}
  for(var v=0;v<=60;v+=10){el("line",{x1:g.gauche,x2:g.gauche+W,y1:Y(v),y2:Y(v),"class":"grille"},svg);
   txt("text",{x:g.gauche-8,y:Y(v)+4,"text-anchor":"end","class":"axe"},v,svg);}
  var nb=Math.round((t1-t0)/JOUR),pas=7*Math.max(1,Math.ceil(60/(W/(nb/7))));
  for(var i=0;i<=nb;i+=pas){el("line",{x1:X(i),x2:X(i),y1:g.h+Hh,y2:g.h+Hh+4,"class":"grille"},svg);
   txt("text",{x:X(i),y:H-8,"text-anchor":"middle","class":"axe"},court(date(i)),svg);}
  var n=D.jours.length;
  if(!n||!D.n.some(function(x){return x>0;})){
   txt("text",{x:g.gauche+W/2,y:g.h+Hh/2,"text-anchor":"middle","class":"vide-courbe"},
    n?"Pas encore de données.":"La courbe démarre le 4 novembre, veille du lancement.",svg);return;}
  // Aujourd'hui
  el("line",{x1:X(n-1),x2:X(n-1),y1:g.h,y2:g.h+Hh,"class":"aujourdhui"},svg);
  // Bande Q1–Q3
  var haut=[],bas=[];for(var i=0;i<n;i++)if(D.q1[i]!==null){haut.push(X(i)+","+Y(D.q3[i]));bas.unshift(X(i)+","+Y(D.q1[i]));}
  if(haut.length>1)el("polygon",{points:haut.concat(bas).join(" "),fill:CRISTAL,"fill-opacity":.13},svg);
  function ligne(vals,couleur,epais){var d="",lev=true;vals.forEach(function(v,i){if(v===null){lev=true;return;}
   d+=(lev?"M":"L")+X(i).toFixed(1)+" "+Y(v).toFixed(1);lev=false;});
   return el("path",{d:d,fill:"none",stroke:couleur,"stroke-width":epais,"stroke-linejoin":"round","stroke-linecap":"round"},svg);}
  ligne(D.max,"#8a9ab5",1.5);ligne(D.moyenne,CRISTAL,2.5);
  // Personnages du joueur connecté : trait couleur de classe, point final cerclé, étiquette
  var etiquettes=[];
  D.persos.forEach(function(p){ligne(p.niveaux,p.couleur,2);var j=-1;p.niveaux.forEach(function(v,i){if(v!==null)j=i;});
   if(j<0)return;el("circle",{cx:X(j),cy:Y(p.niveaux[j]),r:4.5,fill:p.couleur,stroke:"#0c1322","stroke-width":2},svg);
   etiquettes.push({x:X(j)+8,y:Y(p.niveaux[j])+4,t:p.nom+" · "+p.niveaux[j]});});
  if(D.persos.length<=4){etiquettes.sort(function(a,b){return a.y-b.y;});
   etiquettes.forEach(function(e,k){if(k&&e.y-etiquettes[k-1].y<13)e.y=etiquettes[k-1].y+13;
    txt("text",{x:e.x,y:e.y,"class":"etiquette"},e.t,svg);});}
  // Survol : réticule + infobulle avec toutes les séries du jour
  var reticule=el("line",{y1:g.h,y2:g.h+Hh,"class":"reticule",visibility:"hidden"},svg),
   zone=el("rect",{x:g.gauche,y:g.h,width:W,height:Hh,fill:"transparent",tabindex:0},svg);
  function montrer(i){i=Math.max(0,Math.min(n-1,i));reticule.setAttribute("x1",X(i));reticule.setAttribute("x2",X(i));
   reticule.setAttribute("visibility","visible");bulle.textContent="";
   var t=document.createElement("b");t.textContent=court(date(i))+" · "+D.n[i]+" membre"+(D.n[i]>1?"s":"");bulle.appendChild(t);
   function rang(nom,v,couleur){if(v===null||v===undefined)return;var r=document.createElement("div");
    var k=document.createElement("i");k.style.background=couleur;r.appendChild(k);
    var s=document.createElement("strong");s.textContent=fr(v);r.appendChild(s);
    r.appendChild(document.createTextNode(" "+nom));bulle.appendChild(r);}
   D.persos.forEach(function(p){rang(p.nom,p.niveaux[i],p.couleur);});
   rang("moyenne",D.moyenne[i],CRISTAL);rang("médiane",D.mediane[i],"rgba(95,216,245,.5)");
   if(D.q1[i]!==null)rang("50 % des membres entre "+fr(D.q1[i])+" et "+fr(D.q3[i]),"","rgba(95,216,245,.35)");
   rang("plus haut",D.max[i],"#8a9ab5");rang("plus bas",D.min[i],"#5d6b85");
   bulle.hidden=false;var bx=X(i)+14,lb=bulle.offsetWidth;if(bx+lb>L)bx=X(i)-14-lb;
   bulle.style.left=(boite.offsetLeft+Math.max(0,bx))+"px";bulle.style.top=(boite.offsetTop+g.h+8)+"px";}
  function cacher(){reticule.setAttribute("visibility","hidden");bulle.hidden=true;}
  function indice(ev){var r=svg.getBoundingClientRect();return Math.round((ev.clientX-r.left-g.gauche)/W*(t1-t0)/JOUR);}
  zone.addEventListener("pointermove",function(ev){montrer(indice(ev));});
  zone.addEventListener("pointerleave",cacher);
  var focus=n-1;zone.addEventListener("focus",function(){montrer(focus);});zone.addEventListener("blur",cacher);
  zone.addEventListener("keydown",function(ev){if(ev.key==="ArrowLeft")focus=Math.max(0,focus-1);
   else if(ev.key==="ArrowRight")focus=Math.min(n-1,focus+1);else return;ev.preventDefault();montrer(focus);});
 }
 dessiner();var att;window.addEventListener("resize",function(){clearTimeout(att);att=setTimeout(dessiner,120);});
})();
function filtrer(c){var n=0;document.querySelectorAll("tbody tr[data-classe]").forEach(function(tr){
 var ok=!c||tr.dataset.classe===c;tr.style.display=ok?"":"none";if(ok)n++;});
 document.getElementById("compte").textContent=n+" membre"+(n>1?"s":"");}
</script></body></html>"""

FORMULAIRE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Envoyer mes données</title>""" + STYLE + """</head><body><div class="page">
""" + ENTETE + """
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
<form class="carte formulaire" method="post" enctype="multipart/form-data">
{% if pseudo %}<p>Envoi au nom de <b>{{ pseudo }}</b> (connecté avec Discord) · <a href="moi">Mon compte</a></p>
{% else %}<label for="cle">Ta clé personnelle<input id="cle" type="password" name="cle" required>
{% if discord_actif %}<small>ou <a href="{{ url_connexion() }}">connecte-toi avec Discord</a> pour ne plus la saisir</small>{% endif %}</label>{% endif %}
<label for="fichier">Ton fichier GuildExport.lua<input id="fichier" type="file" name="fichier" accept=".lua" required>
<small>Il se trouve dans World of Warcraft\\_forever_\\WTF\\Account\\TON_COMPTE\\SavedVariables\\</small></label>
<div><button type="submit">Envoyer</button></div>
</form>""" + PIED + """</div></body></html>"""

# Carte d'un personnage : emblème de classe, nom à la couleur de la classe, race, classe, niveau.
PERSO = """{% macro carte_perso(nom, info) -%}
<span class="embleme">{{ embleme(info.classe if info else '') }}</span>
<span class="perso-id"><b>{{ nom }}</b><small>{% if info %}{{ info.race ~ ' · ' if info.race and info.race != '?' }}{{ info.classe }}{% else %}hors de la guilde{% endif %}</small></span>
{%- if info %}<span class="niv num{{ ' max' if info.niveau == 60 else '' }}">{{ info.niveau }}</span>{% endif %}
{%- endmacro %}"""

COMPTE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mon compte</title>""" + STYLE + """</head><body>""" + PERSO + """<div class="page">
""" + ENTETE + """
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
{% if not session.discord %}
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">🔑</span>Connexion</h2></div>
 <p>Connecte-toi avec ton compte Discord : il faut être sur le serveur de la guilde, avec le rôle de la guilde.</p>
 <div><a class="cta" href="{{ url_connexion() }}">Connexion Discord</a></div></section>
{% elif not compte %}
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">👋</span>Bienvenue {{ session.discord.nom }}</h2>
 {% if admin %}<a class="cta sec" href="admin">Administration</a>{% endif %}</div>
 <p>Première connexion : relie ton compte Discord à ton pseudo de guilde, avec l'une des deux options.</p></section>
<div class="grille2">
 <section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">🔑</span>J'ai déjà une clé</h2></div>
 <form method="post"><input type="hidden" name="action" value="lier">
 <label for="ancienne">Clé reçue en message privé<input id="ancienne" type="password" name="cle" required></label>
 <div><button type="submit">Relier avec ma clé</button></div></form></section>
 <section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">✨</span>Je n'ai pas de clé</h2></div>
 <form method="post"><input type="hidden" name="action" value="creer">
 <label for="pseudo">Choisis ton pseudo
 <input id="pseudo" name="pseudo" required maxlength="24" value="{{ session.discord.nom }}"></label>
 <small>2 à 24 caractères, sans espace ni « : ». Une clé est créée pour toi.</small>
 <div><button type="submit">Créer ma clé</button></div></form></section>
</div>
{% else %}
<div class="grille2">
 <section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">👤</span>Profil</h2>
 {% if admin %}<a class="cta sec" href="admin">Administration</a>{% endif %}</div>
 <dl class="infos"><dt>Pseudo</dt><dd>{{ compte.pseudo }}</dd>
 <dt>Discord</dt><dd>{{ session.discord.nom }}</dd>
 <dt>BattleTag</dt><dd>{% if compte.battletag %}{{ compte.battletag }} <span class="puce verifie">lié à Discord</span>
 {% elif compte.battletag_saisi %}{{ compte.battletag_saisi }} <span class="puce">saisi</span>{% else %}<span class="aide">non renseigné</span>{% endif %}</dd></dl>
 {% if not compte.battletag %}
 <form method="post"><input type="hidden" name="action" value="battletag">
 <label for="battletag">{{ "Modifier mon BattleTag" if compte.battletag_saisi else "Ajouter mon BattleTag" }}</label>
 <div class="ligne"><input id="battletag" name="battletag" maxlength="20" placeholder="Nom#1234" value="{{ compte.battletag_saisi or '' }}">
 <button class="sec" type="submit">Enregistrer</button></div>
 <small>Ou lie Battle.net à Discord (Paramètres → Connexions) puis reconnecte-toi : il sera lu automatiquement. Vide = effacer.</small></form>
 {% endif %}
 </section>
 <section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">🔑</span>Ma clé d'envoi</h2></div>
 {% if cle %}
 <label for="cle">À coller dans le script d'envoi automatique
 <div class="ligne"><input id="cle" type="text" value="{{ cle }}" readonly onclick="this.select()">
 <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('cle').value);this.textContent='Copiée !'">Copier</button></div></label>
 {% else %}<p>Aucune clé active : génère-en une.</p>{% endif %}
 <div class="boutons"><a class="cta sec" href="contribuer">Envoyer mes données</a>
 <form method="post" onsubmit="return confirm('L\\'ancienne clé ne fonctionnera plus : relance changer-cle.bat sur ton PC. Continuer ?')">
 <input type="hidden" name="action" value="regenerer"><button class="sec" type="submit">Générer une nouvelle clé</button></form></div>
 <small>Garde-la pour toi : elle permet d'envoyer des données en ton nom.</small>
 </section>
</div>
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">⚔️</span>Mes personnages <small>{{ mes_persos|length }}</small></h2></div>
 {% if mes_persos %}<div class="persos">
 {% for m in mes_persos %}{% set info = infos.get(m.nom) %}
 <div class="perso" style="--c:{{ couleur(info.classe if info else '') }}">{{ carte_perso(m.nom, info) }}
 {% if m.nom in exclus %}<span class="puce exclu" title="Exclu de la progression par un officier">{{ motifs.get(exclus[m.nom], "exclu") }}</span>{% endif %}
 {% if m.source == "manuel" %}<form method="post"><input type="hidden" name="action" value="retirer"><input type="hidden" name="nom" value="{{ m.nom }}">
 <button class="sec retirer" type="submit" title="Retirer {{ m.nom }}" aria-label="Retirer {{ m.nom }}">×</button></form>
 {% else %}<span class="puce{{ ' admin' if m.source == 'admin' else '' }}" title="{{ sources[m.source] }}">{{ {"admin": "officier", "addon": "addon", "nom": "pseudo", "blizzard": "Battle.net"}[m.source] }}</span>{% endif %}
 </div>{% endfor %}</div>
 {% else %}<div class="vide-etat">Aucun personnage pour l'instant. Envoie ton fichier GuildExport.lua ou ajoute-les ci-dessous.</div>{% endif %}
 <small>Les personnages de ton compte WoW sont ajoutés tout seuls à chaque envoi (addon GuildExport 1.2.0 ou plus).
 Dans le classement, ils affichent ton pseudo avec un lien vers ton profil Discord.</small>
 {% if libres %}
 <div class="bloc-tete"><h2><span class="ic">＋</span>Ajouter un personnage <small>clique sur le tien</small></h2>
 <input class="recherche" type="search" placeholder="Rechercher…" aria-label="Rechercher un personnage" oninput="filtrerPersos(this.value)"></div>
 <form method="post" class="persos" id="libres"><input type="hidden" name="action" value="reclamer">
 {% for n in libres %}{% set info = infos.get(n) %}
 <button class="perso" type="submit" name="nom" value="{{ n }}" data-nom="{{ n|lower }}" style="--c:{{ couleur(info.classe if info else '') }}">{{ carte_perso(n, info) }}<span class="plus">+</span></button>
 {% endfor %}</form>
 {% endif %}
</section>
<script>
function filtrerPersos(q){q=q.toLowerCase();document.querySelectorAll("#libres button[data-nom]").forEach(function(b){
 b.style.display=b.dataset.nom.indexOf(q)>=0?"":"none";});}
</script>
{% endif %}
""" + PIED + """</div></body></html>"""

ADMIN = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Administration</title>""" + STYLE + """</head><body><div class="page">
""" + ENTETE + """
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">⚔️</span>Personnages ↔ joueurs
 <small>{{ lignes|selectattr("pseudo")|list|length }} associés sur {{ lignes|length }}</small></h2>
 <div class="filtres"><select aria-label="Filtrer" onchange="filtrerAdmin()" id="f-etat"><option value="">Tous</option>
 <option value="libre">Sans joueur</option><option value="lie">Associés</option><option value="exclu">Exclus de la progression</option></select>
 <input class="recherche" type="search" id="f-texte" placeholder="Personnage ou joueur…" aria-label="Rechercher" oninput="filtrerAdmin()"></div></div>
 <div class="table-wrap"><table><thead><tr><th>Personnage</th><th>Niveau</th><th>Joueur</th><th>Source</th><th></th><th>Progression</th></tr></thead><tbody>
 {% for l in lignes %}{% set info = l.info %}
 <tr data-texte="{{ (l.nom ~ ' ' ~ (l.pseudo or ''))|lower }}" data-etat="{{ 'lie' if l.pseudo else 'libre' }}{{ ' exclu' if l.inactif }}"{{ ' class="exclu"'|safe if l.inactif }}>
 <td><span class="persoligne" style="--c:{{ couleur(info.classe if info else '') }}"><span class="embleme mini">{{ embleme(info.classe if info else '') }}</span>
 <span><b>{{ l.nom }}</b><small>{% if info %}{{ info.race ~ ' · ' if info.race and info.race != '?' }}{{ info.classe }}{% else %}hors de la guilde{% endif %}</small></span></span></td>
 <td>{% if info %}<span class="niv num{{ ' max' if info.niveau == 60 else '' }}">{{ info.niveau }}</span>{% endif %}</td>
 <td><select name="pseudo" form="a{{ loop.index }}" aria-label="Joueur de {{ l.nom }}"><option value="">— aucun —</option>
 {% for j in joueurs %}<option{{ ' selected' if l.pseudo == j }}>{{ j }}</option>{% endfor %}</select></td>
 <td>{% if l.source %}<span class="puce{{ ' admin' if l.source == 'admin' else '' }}">{{ sources[l.source] }}</span>{% endif %}</td>
 <td><form id="a{{ loop.index }}" method="post"><input type="hidden" name="action" value="associer"><input type="hidden" name="nom" value="{{ l.nom }}">
 <button class="sec" type="submit">Enregistrer</button></form></td>
 <td>{% if l.inactif %}<form method="post" class="ligne-form"><input type="hidden" name="action" value="reactiver"><input type="hidden" name="nom" value="{{ l.nom }}">
 <span class="puce exclu">{{ motifs.get(l.inactif, l.inactif) }}</span><button class="sec" type="submit">Réintégrer</button></form>
 {% elif l.info %}<form method="post" class="ligne-form"><input type="hidden" name="action" value="desactiver"><input type="hidden" name="nom" value="{{ l.nom }}">
 <select name="motif" aria-label="Motif d'exclusion de {{ l.nom }}">{% for k, v in motifs.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
 <button class="sec" type="submit">Exclure</button></form>{% endif %}</td></tr>
 {% else %}<tr><td colspan="6">Aucun personnage pour l'instant.</td></tr>{% endfor %}
 </tbody></table></div>
 <small>Un choix d'officier l'emporte sur l'addon et les ajouts des joueurs, et n'est jamais remplacé automatiquement.
 « — aucun — » retire l'association enregistrée (un perso au nom d'un pseudo reste relié d'office).
 « Exclure » sort une mule ou une banque du classement, du tableau d'honneur, des annonces, du récap et de la courbe
 (ses niveaux restent enregistrés ; « Réintégrer » lui rend ses paliers sans nouvelle annonce).</small>
</section>
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">🎖️</span>Rangs de la guilde <small>{{ rangs|length }}</small></h2></div>
 <form method="post"><input type="hidden" name="action" value="rangs">
 <div class="table-wrap"><table><thead><tr><th>N°</th><th>Nom affiché</th><th>Membres</th></tr></thead><tbody>
 {% for r in rangs %}<tr><td class="num">{{ r.id }}{{ " (maître de guilde)" if r.id == 0 }}</td>
 <td><input name="rang_{{ r.id }}" value="{{ r.nom }}" maxlength="40" placeholder="Rang {{ r.id }}" aria-label="Nom du rang {{ r.id }}"></td>
 <td class="num">{{ r.membres }}</td></tr>
 {% endfor %}<tr><td><input name="nouveau_id" type="number" min="0" max="20" placeholder="N°" aria-label="Numéro du nouveau rang"></td>
 <td><input name="nouveau_nom" maxlength="40" placeholder="Ajouter un rang…" aria-label="Nom du nouveau rang"></td><td></td></tr>
 </tbody></table></div><div><button type="submit">Enregistrer les rangs</button></div></form>
 <small>Les numéros viennent du roster de l'API Blizzard (0 = maître de guilde, puis dans l'ordre des rangs en jeu).
 Un nom vide efface ce nom. Ces noms ne sont pas touchés par la remise à zéro de la progression.</small></section>
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">📤</span>Contributeurs <small>{{ contribs|length }}</small></h2></div>
 <div class="table-wrap"><table><thead><tr><th>#</th><th>Joueur</th><th>Montées signalées</th><th>Envois</th><th>Persos lus</th><th>Dernier envoi</th></tr></thead><tbody>
 {% for c in contribs %}<tr><td class="rang num">{{ loop.index }}</td>
 <td class="nom">{% if c.discord %}<a href="https://discord.com/users/{{ c.discord }}" target="_blank" rel="noopener">{{ c.pseudo }}</a>{% else %}{{ c.pseudo }}{% endif %}</td>
 <td class="num">{{ c.montees }}</td><td class="num">{{ c.envois }}</td><td class="num">{{ c.lus }}</td>
 <td>{{ c.dernier[:16].replace("T", " ") }}</td></tr>
 {% else %}<tr><td colspan="6">Aucun envoi pour l'instant.</td></tr>{% endfor %}
 </tbody></table></div>
 <small>Une montée est comptée pour le membre dont l'envoi l'a apprise en premier au site. La remise à zéro de la progression remet ce compteur à zéro.</small>
</section>
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">💬</span>Comptes Discord reliés <small>{{ comptes|length }}</small></h2></div>
 <div class="table-wrap"><table><thead><tr><th>Pseudo</th><th>Discord</th><th>BattleTag</th><th>Clé</th><th>Relié le</th><th></th></tr></thead><tbody>
 {% for c in comptes %}<tr><td class="nom">{{ c.pseudo }}</td><td>{{ c.discord_nom }}</td>
 <td>{% if c.battletag %}{{ c.battletag }}{% elif c.battletag_saisi %}{{ c.battletag_saisi }} <span class="puce">saisi</span>{% else %}—{% endif %}</td>
 <td>{{ "créée sur le site" if c.cle else "cles.txt" }}</td><td>{{ c.lie_le[:16].replace("T", " ") }}</td>
 <td><form method="post" onsubmit="return confirm('Délier ce compte ? La clé créée sur le site sera supprimée.')">
 <input type="hidden" name="action" value="delier"><input type="hidden" name="discord_id" value="{{ c.discord_id }}">
 <button class="sec" type="submit">Délier</button></form></td></tr>
 {% else %}<tr><td colspan="6">Aucun compte relié.</td></tr>{% endfor %}
 </tbody></table></div></section>
<section class="carte bloc"><div class="bloc-tete"><h2><span class="ic">🗝️</span>Clés de cles.txt sans compte Discord <small>{{ sans_compte|length }}</small></h2></div>
 {% if sans_compte %}<div class="puces">{% for p in sans_compte %}<span class="puce">{{ p }}</span>{% endfor %}</div>
 {% else %}<p>Tout le monde est relié.</p>{% endif %}</section>
<section class="carte bloc danger"><div class="bloc-tete"><h2><span class="ic">⚠️</span>Zone dangereuse</h2></div>
 <form method="post" onsubmit="return confirm('Vider toute la progression ? Une copie est gardée.')">
 <input type="hidden" name="action" value="reinitialiser"><div><button class="danger-btn" type="submit">Vider la base de progression</button></div></form>
 <small>Personnages, historique, tableau d'honneur, envois (contributeurs) et associations personnage ↔ joueur.
 Les comptes Discord, les pseudos, les clés et les BattleTags sont conservés, et personne n'est déconnecté.</small></section>
""" + PIED + """</div>
<script>
function filtrerAdmin(){var e=document.getElementById("f-etat").value,q=document.getElementById("f-texte").value.toLowerCase();
 document.querySelectorAll("tr[data-etat]").forEach(function(tr){
  tr.style.display=(!e||tr.dataset.etat.split(" ").indexOf(e)>=0)&&tr.dataset.texte.indexOf(q)>=0?"":"none";});}
</script></body></html>"""


@app.context_processor
def contexte():
    return {"discord_actif": bool(DISCORD_SECRET), "version": VERSION, "couleur": couleur, "embleme": embleme,
            "url_connexion": url_discord}


def est_admin():
    return bool(session.get("discord")) and session["discord"]["id"] in ADMINS


def compte_connecte(con):
    d = session.get("discord")
    return d and con.execute("SELECT * FROM comptes WHERE discord_id=?", (d["id"],)).fetchone()


def verifier_token():
    # Token vide dans les options = routes protégées fermées (sinon ?token= suffirait).
    if not TOKEN or not hmac.compare_digest(request.args.get("token", "").encode(), TOKEN.encode()):
        abort(403)


@app.route("/")
def index():
    with db() as con:
        actifs_sql = "nom NOT IN (SELECT nom FROM inactifs)"
        persos = con.execute(f"SELECT * FROM personnages WHERE {actifs_sql} ORDER BY niveau DESC, nom").fetchall()
        rows = con.execute("SELECT * FROM exploits ORDER BY palier, rang").fetchall()
        recents = con.execute(f"SELECT * FROM historique WHERE {actifs_sql} ORDER BY date DESC LIMIT 15").fetchall()
        g24 = gains(con, 24)
        proprios = proprietaires(con, [p["nom"] for p in persos])
        top = contributeurs(con, 3)
        compte = compte_connecte(con)
        mes_noms = [n for n, a in proprios.items()
                    if compte and a["pseudo"].casefold() == compte["pseudo"].casefold()]
        donnees_courbe = courbe(con, mes_noms)
        rangs = noms_rangs(con)
    exploits = {}
    for e in rows:
        exploits.setdefault(e["palier"], []).append(e)
    return render_template_string(
        PAGE, guilde=NOM_GUILDE, persos=persos, paliers=PALIERS, exploits=exploits,
        medailles=MEDAILLES, recents=recents, g24=g24, proprios=proprios, top=top, rangs=rangs,
        avec_rangs=any(p["rang"] is not None for p in persos),
        donnees_courbe=donnees_courbe, connecte=bool(compte),
        total24=sum(v for v in g24.values() if v > 0),
        actifs=sum(1 for v in g24.values() if v > 0),
        nb60=sum(1 for p in persos if p["niveau"] == 60),
        moyenne=f"{sum(p['niveau'] for p in persos) / len(persos):.1f}" if persos else "—",
        maj=max((p["maj"] for p in persos), default="")[:16].replace("T", " "),
        classes={p["nom"]: p["classe"] for p in persos},
        liste_classes=sorted({p["classe"] for p in persos}),
        couleur=lambda c: COULEURS.get(c, "#e6eefb"))  # texte clair par défaut dans le classement


def formulaire(**kw):
    return render_template_string(FORMULAIRE, guilde=NOM_GUILDE, titre="Envoyer mes données", **kw)


def page_compte(**kw):
    return render_template_string(COMPTE, guilde=NOM_GUILDE, titre="Mon compte", admin=est_admin(), **kw)


@app.route("/<any('logo.png', 'banniere.jpg'):fichier>")
def route_image(fichier):
    return send_file(Path(__file__).with_name(fichier), max_age=86400)


@app.route("/collecter", methods=["GET", "POST"])
def route_collecter():
    verifier_token()
    mises_a_jour, source = collecter()
    return jsonify(ok=True, mises_a_jour=mises_a_jour, source=source)


@app.route("/recap", methods=["GET", "POST"])
def route_recap():
    verifier_token()
    recap()
    return jsonify(ok=True)


@app.route("/reinitialiser", methods=["POST"])
def route_reinitialiser():
    """Vide toutes les tables (tests). Copie de sauvegarde dans <DB>.avant-reset."""
    verifier_token()
    return jsonify(ok=True, supprimes=reinitialiser())


def reinitialiser():
    """Vide la progression et les associations de personnages, pas les comptes (pseudos, clés,
    BattleTags) ni les sessions. Copie de sauvegarde dans <DB>.avant-reset."""
    with db() as con, sqlite3.connect(DB + ".avant-reset") as copie:
        con.backup(copie)
        return {t: con.execute(f"DELETE FROM {t}").rowcount
                for t in ("personnages", "historique", "exploits", "envois", "proprietaires", "inactifs")}


@app.route("/envoyer", methods=["POST"])
def route_envoyer():
    pseudo = contributeur(request.headers.get("X-Cle"))
    if not pseudo:
        abort(403)
    texte = request.get_data(as_text=True)
    persos = analyser_export(texte)
    if not persos:
        return jsonify(ok=False, erreur="Fichier vide ou invalide"), 400
    n = integrer(persos, pseudo, analyser_dates(texte), analyser_rangs(texte))
    with db() as con:
        associer(con, pseudo, analyser_mes_persos(texte), "addon")
    return jsonify(ok=True, personnages=len(persos), nouveautes=n)


@app.route("/contribuer", methods=["GET", "POST"])
def route_contribuer():
    with db() as con:
        compte = compte_connecte(con)
    connecte = compte["pseudo"] if compte else None
    if request.method == "GET":
        return formulaire(pseudo=connecte)
    pseudo = connecte or contributeur(request.form.get("cle"))
    if not pseudo:
        return formulaire(message="Clé inconnue.", classe="err"), 403
    f = request.files.get("fichier")
    texte = f.read().decode("utf-8", errors="ignore") if f else ""
    persos = analyser_export(texte)
    if not persos:
        return formulaire(message="Fichier vide ou invalide.", classe="err", pseudo=connecte), 400
    n = integrer(persos, pseudo, analyser_dates(texte), analyser_rangs(texte))
    with db() as con:
        associer(con, pseudo, analyser_mes_persos(texte), "addon")
    return formulaire(classe="ok", pseudo=connecte,
                      message=f"Merci {pseudo} ! {len(persos)} personnages lus, {n} mises à jour.")


# ---------- Connexion Discord ----------
# v1.10.1 : le state OAuth est un jeton signé et horodaté, pas une valeur rangée dans la session.
# Le retour de Discord aboutit ainsi même dans un autre navigateur que celui de départ (l'app
# Discord mobile rouvre l'URL de retour dans le navigateur par défaut). Les liens « Connexion
# Discord » pointent directement sur discord.com : un lien touché, et non une redirection, est
# ce qui permet à iOS / Android d'ouvrir l'app Discord si elle est installée.
ETAT_VALIDITE = 600  # secondes


def signeur_etat():
    return URLSafeTimedSerializer(app.secret_key, salt="discord-etat")


def url_discord():
    """URL d'autorisation Discord avec un state frais."""
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "response_type": "code", "client_id": DISCORD_ID, "scope": "identify guilds.members.read connections",
        "redirect_uri": URL_SITE + "/auth/discord/callback", "prompt": "none",
        "state": signeur_etat().dumps(secrets.token_urlsafe(8))})


def etat_valide(etat):
    try:
        signeur_etat().loads(etat or "", max_age=ETAT_VALIDITE)
        return True
    except BadSignature:  # y compris SignatureExpired
        return False


@app.route("/connexion")
def route_connexion():
    if not DISCORD_SECRET:
        abort(404)
    return redirect(url_discord())


@app.route("/auth/discord/callback")
def route_retour_discord():
    if not DISCORD_SECRET or "code" not in request.args or not etat_valide(request.args.get("state")):
        return page_compte(message="Connexion annulée ou expirée, réessaie.", classe="err"), 400
    try:
        r = requests.post(API_DISCORD + "/oauth2/token", auth=(DISCORD_ID, DISCORD_SECRET), timeout=10, data={
            "grant_type": "authorization_code", "code": request.args["code"],
            "redirect_uri": URL_SITE + "/auth/discord/callback"})
        r.raise_for_status()
        entete = {"Authorization": "Bearer " + r.json()["access_token"]}
        r = requests.get(API_DISCORD + "/users/@me", headers=entete, timeout=10)
        r.raise_for_status()
        utilisateur = r.json()
        membre = requests.get(f"{API_DISCORD}/users/@me/guilds/{DISCORD_SERVEUR}/member", headers=entete, timeout=10)
        connexions = requests.get(API_DISCORD + "/users/@me/connections", headers=entete, timeout=10)
    except (requests.RequestException, KeyError, ValueError) as e:
        print("Erreur de connexion Discord :", e, flush=True)
        return page_compte(message="Discord ne répond pas, réessaie dans un instant.", classe="err"), 502
    membre = membre.json() if membre.status_code == 200 else None
    if utilisateur["id"] not in ADMINS:  # les admins passent toujours
        if not membre:
            return page_compte(message="Tu n'es pas sur le serveur Discord de la guilde.", classe="err"), 403
        if DISCORD_ROLE and DISCORD_ROLE not in membre.get("roles", []):
            return page_compte(message="Il te faut le rôle de la guilde sur Discord.", classe="err"), 403
    noms = [n for n in ((membre or {}).get("nick"), utilisateur.get("global_name"), utilisateur["username"]) if n]
    session.clear()
    session.permanent = True
    session["discord"] = d = {"id": utilisateur["id"], "nom": noms[0], "noms": noms,
                              "battletag": battletag(connexions)}
    with db() as con:
        con.execute("UPDATE comptes SET discord_nom=?, battletag=? WHERE discord_id=?",
                    (d["nom"], d["battletag"], d["id"]))
        if not compte_connecte(con):
            liaison_auto(con, d)
    return redirect(URL_SITE + "/moi")


def battletag(reponse):
    """BattleTag du compte Battle.net lié au compte Discord (scope connections), ou None.
    Un échec de cette lecture ne bloque pas la connexion."""
    try:
        liste = reponse.json() if reponse.status_code == 200 else []
        return next((c["name"] for c in liste if c.get("type") == "battlenet" and c.get("name")), None)
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


@app.route("/deconnexion")
def route_deconnexion():
    session.clear()
    return redirect("./")


@app.route("/moi", methods=["GET", "POST"])
def route_moi():
    if not DISCORD_SECRET:
        abort(404)
    d = session.get("discord")
    if not d:
        return page_compte()
    message, classe = None, "ok"
    with db() as con:
        compte = compte_connecte(con)
        action = request.form.get("action") if request.method == "POST" else None
        if action == "lier" and not compte:
            pseudo = contributeur(request.form.get("cle"))
            if not pseudo:
                message, classe = "Clé inconnue.", "err"
            elif con.execute("SELECT 1 FROM comptes WHERE pseudo=?", (pseudo,)).fetchone():
                message, classe = "Ce pseudo est déjà relié à un autre compte Discord : contacte un officier.", "err"
            else:
                lier(con, d, pseudo)
                message = f"Compte relié à {pseudo}."
        elif action == "creer" and not compte:
            pseudo = request.form.get("pseudo", "").strip()
            if not PSEUDO_VALIDE.match(pseudo):
                message, classe = "Pseudo invalide : 2 à 24 caractères, sans espace ni « : ».", "err"
            elif con.execute("SELECT 1 FROM comptes WHERE pseudo=?", (pseudo,)).fetchone():
                message, classe = "Ce pseudo est déjà relié à un autre compte Discord : contacte un officier.", "err"
            elif pseudo_du_fichier(pseudo):
                # Pseudo déjà dans cles.txt : relié seulement s'il correspond à un nom Discord du membre.
                if pseudo.casefold() in {n.casefold() for n in d.get("noms", [d["nom"]])}:
                    lier(con, d, pseudo_du_fichier(pseudo))
                    message = f"Compte relié à {pseudo_du_fichier(pseudo)} (même nom que sur Discord)."
                else:
                    message, classe = ("Ce pseudo a déjà une clé : utilise « J'ai déjà reçu une clé », "
                                       "ou prends ce pseudo comme surnom sur le serveur Discord."), "err"
            else:
                lier(con, d, pseudo, nouvelle_cle(con))
                message = f"Bienvenue {pseudo} ! Ta clé est prête."
        elif action == "battletag" and compte:
            saisi = request.form.get("battletag", "").strip()
            if saisi and not BATTLETAG_VALIDE.match(saisi):
                message, classe = "BattleTag invalide : il doit ressembler à Nom#1234.", "err"
            else:
                con.execute("UPDATE comptes SET battletag_saisi=? WHERE discord_id=?", (saisi or None, d["id"]))
                message = f"BattleTag enregistré : {saisi}." if saisi else "BattleTag effacé."
        elif action == "reclamer" and compte:
            nom = request.form.get("nom", "")
            deja = proprietaires(con, [nom]).get(nom)
            if not con.execute("SELECT 1 FROM personnages WHERE nom=?", (nom,)).fetchone():
                message, classe = "Personnage inconnu.", "err"
            elif deja and deja["pseudo"].casefold() != compte["pseudo"].casefold():
                message, classe = f"{nom} est déjà associé à {deja['pseudo']} : contacte un officier.", "err"
            else:
                associer(con, compte["pseudo"], [nom], "manuel")
                message = f"{nom} est associé à ton compte."
        elif action == "retirer" and compte:
            con.execute("DELETE FROM proprietaires WHERE nom=? AND pseudo=? AND source='manuel'",
                        (request.form.get("nom", ""), compte["pseudo"]))
            message = "Personnage retiré."
        elif action == "regenerer" and compte:
            con.execute("UPDATE comptes SET cle=? WHERE discord_id=?", (nouvelle_cle(con), d["id"]))
            message = "Nouvelle clé créée. L'ancienne ne fonctionne plus."
        compte = compte_connecte(con)
        mes_persos, libres, infos, exclus = [], [], {}, {}
        if compte:
            noms = [r["nom"] for r in con.execute("SELECT nom FROM personnages ORDER BY nom")]
            proprios = proprietaires(con, set(noms) | {r["nom"] for r in con.execute("SELECT nom FROM proprietaires")})
            mes_persos = [{"nom": n, **p} for n, p in sorted(proprios.items())
                          if p["pseudo"].casefold() == compte["pseudo"].casefold()]
            libres = [n for n in noms if n not in proprios]
        infos = {r["nom"]: r for r in con.execute("SELECT * FROM personnages")}
        exclus = inactifs(con)
    return page_compte(compte=compte, cle=cle_du_compte(compte) if compte else None, sources=SOURCES,
                       mes_persos=mes_persos, libres=libres, infos=infos, exclus=exclus, motifs=MOTIFS,
                       message=message, classe=classe), 400 if classe == "err" else 200


@app.route("/admin", methods=["GET", "POST"])
def route_admin():
    if not est_admin():
        abort(403)
    message, classe = None, "ok"
    action = request.form.get("action") if request.method == "POST" else None
    if action == "delier":
        with db() as con:
            con.execute("DELETE FROM comptes WHERE discord_id=?", (request.form.get("discord_id"),))
        message = "Compte délié."
    elif action == "associer":
        nom, pseudo = request.form.get("nom", ""), request.form.get("pseudo", "")
        with db() as con:
            connus = {r[0] for r in con.execute("SELECT nom FROM personnages UNION SELECT nom FROM proprietaires")}
            if nom in connus and not pseudo:
                con.execute("DELETE FROM proprietaires WHERE nom=?", (nom,))
                message = f"{nom} n'est plus associé."
            elif nom in connus and pseudo in joueurs(con):
                associer(con, pseudo, [nom], "admin")
                message = f"{nom} est associé à {pseudo}."
            else:
                message, classe = "Personnage ou joueur inconnu.", "err"
    elif action == "desactiver" and request.form.get("motif") in MOTIFS:
        nom = request.form.get("nom", "")
        with db() as con:
            if con.execute("SELECT 1 FROM personnages WHERE nom=?", (nom,)).fetchone():
                desactiver(con, nom, request.form["motif"])
                message = f"{nom} est exclu de la progression ({MOTIFS[request.form['motif']].lower()})."
            else:
                message, classe = "Personnage inconnu.", "err"
    elif action == "reactiver":
        nom = request.form.get("nom", "")
        with db() as con:
            reactiver(con, nom)
        message = f"{nom} est réintégré dans la progression."
    elif action == "dissocier":
        with db() as con:
            con.execute("DELETE FROM proprietaires WHERE nom=?", (request.form.get("nom"),))
        message = "Personnage dissocié."
    elif action == "rangs":
        with db() as con:
            for cle, valeur in request.form.items():
                if not (cle.startswith("rang_") and cle[5:].isdigit()):
                    continue
                nom = valeur.strip()[:40]
                if nom:
                    con.execute("INSERT INTO rangs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET nom=excluded.nom",
                                (int(cle[5:]), nom))
                else:
                    con.execute("DELETE FROM rangs WHERE id=?", (int(cle[5:]),))
            nouveau = request.form.get("nouveau_id", "").strip()
            if nouveau.isdigit() and request.form.get("nouveau_nom", "").strip():
                con.execute("INSERT INTO rangs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET nom=excluded.nom",
                            (int(nouveau), request.form["nouveau_nom"].strip()[:40]))
        message = "Noms des rangs enregistrés."
    elif action == "reinitialiser":
        vides = reinitialiser()
        message = (f"Base vidée ({vides['personnages']} personnages, {vides['proprietaires']} associations). "
                   "Copie dans guilde.db.avant-reset.")
    with db() as con:
        comptes = con.execute("SELECT * FROM comptes ORDER BY pseudo").fetchall()
        tous_persos = sorted({r[0] for r in con.execute(
            "SELECT nom FROM personnages UNION SELECT nom FROM proprietaires")}, key=str.casefold)
        proprios = proprietaires(con, tous_persos)
        infos = {r["nom"]: r for r in con.execute("SELECT * FROM personnages")}
        exclus = inactifs(con)
        lignes = [{"nom": n, "info": infos.get(n), "pseudo": proprios.get(n, {}).get("pseudo"),
                   "source": proprios.get(n, {}).get("source"), "inactif": exclus.get(n)} for n in tous_persos]
        lignes.sort(key=lambda l: (l["pseudo"] is not None, -(l["info"]["niveau"] if l["info"] else 0), l["nom"].casefold()))
        liste_joueurs = joueurs(con)
        contribs = contributeurs(con)
        noms = noms_rangs(con)
        effectifs = dict(con.execute("SELECT rang, COUNT(*) FROM personnages WHERE rang IS NOT NULL GROUP BY rang").fetchall())
        liste_rangs = [{"id": i, "nom": noms.get(i, ""), "membres": effectifs.get(i, 0)}
                       for i in sorted(set(noms) | set(effectifs))]
    lies = {c["pseudo"].casefold() for c in comptes}
    return render_template_string(
        ADMIN, guilde=NOM_GUILDE, titre="Administration", comptes=comptes, message=message, classe=classe,
        lignes=lignes, sources=SOURCES, joueurs=liste_joueurs, contribs=contribs, motifs=MOTIFS, rangs=liste_rangs,
        sans_compte=sorted((p for p in cles_fichier() if p.casefold() not in lies), key=str.casefold))


@app.route("/export.json")
def route_export():
    verifier_token()
    with db() as con:
        donnees = {
            "guilde": NOM_GUILDE,
            "genere_le": maintenant(),
            "personnages": [dict(r) for r in con.execute("SELECT * FROM personnages ORDER BY niveau DESC, nom")],
            "historique": [dict(r) for r in con.execute("SELECT * FROM historique ORDER BY date")],
            "exploits": [dict(r) for r in con.execute("SELECT * FROM exploits ORDER BY palier, rang")],
            "envois": [dict(r) for r in con.execute("SELECT * FROM envois ORDER BY date")],
            "proprietaires": [dict(r) for r in con.execute("SELECT * FROM proprietaires ORDER BY nom")],
            "inactifs": [dict(r) for r in con.execute("SELECT * FROM inactifs ORDER BY nom")],
            "rangs": [dict(r) for r in con.execute("SELECT * FROM rangs ORDER BY id")],
        }
    return app.response_class(
        json.dumps(donnees, ensure_ascii=False, indent=2), mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=guilde-export.json"})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
