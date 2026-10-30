# Quartz Forever — suivi de progression de guilde (WoW Forever)
import os, re, json, hmac, secrets, sqlite3, datetime
from pathlib import Path
from urllib.parse import urlencode
import requests
from flask import Flask, render_template_string, request, abort, jsonify, send_file, session, redirect

# ---------- Configuration ----------
DB = os.getenv("GUILDE_DB", "guilde.db")
EXPORT = Path(os.getenv("GUILDE_EXPORT", "GuildExport.lua"))
FICHIER_CLES = Path(os.getenv("GUILDE_CLES", "cles.txt"))
WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
TOKEN = os.getenv("GUILDE_TOKEN", "change-moi")
NOM_GUILDE = os.getenv("NOM_GUILDE", "Quartz Forever")
URL_SITE = os.getenv("GUILDE_URL", "https://quartz.gawel.be").rstrip("/")
# Connexion Discord (OAuth2) : active seulement si l'identifiant et le secret sont renseignés.
DISCORD_ID = os.getenv("DISCORD_CLIENT_ID") or "1565628978633515028"
DISCORD_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_SERVEUR = os.getenv("DISCORD_SERVEUR_ID") or "801395490372583426"
DISCORD_ROLE = os.getenv("DISCORD_ROLE_ID", "1549720665844613130")  # vide = tout membre du serveur
ADMINS = {i.strip() for i in (os.getenv("DISCORD_ADMINS") or "161139977328132107").split(",") if i.strip()}
API_DISCORD = "https://discord.com/api/v10"
PSEUDO_VALIDE = re.compile(r"^[^\s:|#]{2,24}$")
PALIERS = [10, 20, 30, 40, 50, 60]
MEDAILLES = {1: "🥇", 2: "🥈", 3: "🥉"}
COULEURS = {
    "Guerrier": "#C69B6D", "Mage": "#3FC7EB", "Prêtre": "#FFFFFF", "Prêtresse": "#FFFFFF",
    "Voleur": "#FFF468", "Voleuse": "#FFF468", "Druide": "#FF7C0A", "Druidesse": "#FF7C0A",
    "Chasseur": "#AAD372", "Chasseresse": "#AAD372", "Démoniste": "#8788EE",
    "Paladin": "#F48CBA", "Chaman": "#2E8FEF", "Chamane": "#2E8FEF",
}


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


def verifier_exploits(con, nom, classe, ancien, nouveau, annonces):
    """Enregistre les paliers franchis et prépare les annonces (envoyées par annoncer())."""
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


def integrer(persos, source="serveur", dates=None):
    """Fusionne des données : garde toujours le niveau le plus haut, complète les races
    et date les montées de niveau (dates de l'addon si fournies, sinon date de réception)."""
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
            con.execute("""INSERT INTO personnages VALUES(?,?,?,?,?)
                ON CONFLICT(nom) DO UPDATE SET race=excluded.race, classe=excluded.classe,
                niveau=excluded.niveau, maj=excluded.maj""",
                        (nom, race, classe, niveau, maintenant()))
        con.execute("INSERT INTO envois VALUES(?,?,?,?)", (source, maintenant(), len(persos), nouveaux))
        annoncer(con, annonces, source)
    return nouveaux


def lire_api_blizzard():
    """À brancher quand l'espace de noms Forever sera publié par Blizzard."""
    return []


def collecter():
    persos = lire_api_blizzard()
    dates = {}
    if not persos and EXPORT.exists():
        texte = EXPORT.read_text(encoding="utf-8")
        persos, dates = analyser_export(texte), analyser_dates(texte)
    return integrer(persos, "serveur", dates) if persos else 0


# ---------- Récapitulatif ----------
def gains(con, heures):
    limite = (datetime.datetime.now() - datetime.timedelta(hours=heures)).isoformat(timespec="seconds")
    res = {}
    for p in con.execute("SELECT nom, niveau FROM personnages").fetchall():
        avant = con.execute("""SELECT niveau FROM historique WHERE nom=? AND date<=?
                               ORDER BY date DESC LIMIT 1""", (p["nom"], limite)).fetchone()
        if avant is None:
            avant = con.execute("SELECT MIN(niveau) AS niveau FROM historique WHERE nom=?",
                                (p["nom"],)).fetchone()
        base = avant["niveau"] if avant and avant["niveau"] is not None else p["niveau"]
        res[p["nom"]] = p["niveau"] - base
    return res


def recap():
    with db() as con:
        persos = con.execute("SELECT * FROM personnages ORDER BY niveau DESC, nom").fetchall()
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
<link rel="icon" href="logo.png">
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
linear-gradient(0deg,rgba(7,11,20,.55),transparent 40%),url(banniere.jpg) center 40%/cover no-repeat,var(--nuit2);
box-shadow:0 18px 60px rgba(0,0,0,.45),0 0 60px rgba(95,216,245,.08)}
@media (min-width:861px){header{min-height:260px;
background:linear-gradient(90deg,rgba(7,11,20,1) 0%,rgba(7,11,20,.96) 30%,rgba(7,11,20,.55) 55%,rgba(7,11,20,.05) 100%),
linear-gradient(0deg,rgba(7,11,20,.5),transparent 35%),url(banniere.jpg) right 58%/72% auto no-repeat,var(--nuit)}}
.logo{flex:0 0 auto;width:clamp(64px,10vw,96px)}
.logo img{display:block;width:100%;height:auto;filter:drop-shadow(0 0 18px rgba(95,216,245,.55))}
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
.formulaire small{color:var(--doux);font-weight:500;word-break:break-all}
.msg{padding:10px 14px;border-radius:10px;font-size:.9rem;border:1px solid}
.ok{color:var(--vert);background:rgba(94,227,166,.08);border-color:rgba(94,227,166,.3)}
.err{color:var(--rouge);background:rgba(255,138,122,.08);border-color:rgba(255,138,122,.3)}
.actions,.boutons{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.cta.sec,button.sec{background:transparent;color:var(--texte);border:1px solid var(--trait2);box-shadow:none}
.formulaire form{display:flex;flex-direction:column;gap:12px}
.formulaire h2{margin:0}
.formulaire p{margin:0}
.formulaire a:not(.cta){color:var(--cristal)}
</style>
"""

ENTETE = """<header>
<div class="logo"><img src="logo.png" alt="Logo {{ guilde }}"></div>
<div class="titre"><h1>{{ titre or guilde }}</h1>
<div class="meta"><span class="tag horde">Horde</span><span class="tag">WoW Forever · PvE</span>
{% if maj %}<span class="tag live">Mis à jour {{ maj }}</span>{% endif %}</div></div>
<div class="actions">{% if titre %}<a class="cta" href="./">← Retour au classement</a>
{% else %}<a class="cta" href="contribuer">Envoyer mes données</a>{% endif %}
{% if discord_actif and not titre %}<a class="cta sec" href="{{ 'moi' if session.discord else 'connexion' }}">{{ "Mon compte" if session.discord else "Connexion Discord" }}</a>{% endif %}</div>
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
<div class="carte table-wrap"><table><thead><tr><th>#</th><th>Personnage</th><th>Race</th><th>Classe</th><th>Niveau</th><th>Vers 60</th><th>24 h</th></tr></thead><tbody>
{% for p in persos %}
<tr data-classe="{{ p.classe }}"><td class="rang num">{{ loop.index }}</td>
<td class="nom" style="color:{{ couleur(p.classe) }}"><span class="dot" style="background:{{ couleur(p.classe) }}"></span>{{ p.nom }}</td>
<td>{{ p.race }}</td><td>{{ p.classe }}</td>
<td><span class="niv num{{ ' max' if p.niveau == 60 else '' }}">{{ p.niveau }}</span></td>
<td><div class="barre"><i class="{{ 'max' if p.niveau == 60 else '' }}" style="width:{{ (p.niveau / 60 * 100)|round|int }}%"></i></div></td>
<td>{% if g24.get(p.nom, 0) > 0 %}<span class="gain num">+{{ g24[p.nom] }}</span>{% endif %}</td></tr>
{% else %}<tr><td colspan="7">Aucune donnée pour l'instant. Envoie ton fichier GuildExport.lua !</td></tr>{% endfor %}
</tbody></table></div>
</section>

<section class="carte fil-carte sec">
<h2>Dernières montées de niveau</h2>
<ul class="fil">
{% for r in recents %}<li><span class="nv num{{ ' max' if r.niveau == 60 else '' }}">{{ r.niveau }}</span>
<span><b style="color:{{ couleur(classes.get(r.nom, '')) }}">{{ r.nom }}</b>
{{ "atteint le niveau max" if r.niveau == 60 else "passe niveau " ~ r.niveau }}</span>
<small>{{ r.date[:16].replace("T", " ") }}</small></li>{% else %}<li><small>Rien pour l'instant.</small></li>{% endfor %}
</ul>
</section>

<footer><img src="logo.png" alt="">{{ guilde }} · données collectées par l'addon GuildExport</footer>
</div>
<script>
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
{% if discord_actif %}<small>ou <a href="connexion">connecte-toi avec Discord</a> pour ne plus la saisir</small>{% endif %}</label>{% endif %}
<label for="fichier">Ton fichier GuildExport.lua<input id="fichier" type="file" name="fichier" accept=".lua" required>
<small>Il se trouve dans World of Warcraft\\_forever_\\WTF\\Account\\TON_COMPTE\\SavedVariables\\</small></label>
<div><button type="submit">Envoyer</button></div>
</form></div></body></html>"""

COMPTE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mon compte</title>""" + STYLE + """</head><body><div class="page">
""" + ENTETE + """
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
<section class="carte formulaire">
{% if not session.discord %}
 <p>Connecte-toi avec ton compte Discord (il faut être sur le serveur de la guilde, avec le rôle de la guilde).</p>
 <div><a class="cta" href="connexion">Connexion Discord</a></div>
{% else %}
 <p>Connecté avec Discord : <b>{{ session.discord.nom }}</b>{% if admin %} · <a href="admin">Administration</a>{% endif %}
 · <a href="deconnexion">Se déconnecter</a></p>
 {% if compte %}
 <p>Pseudo sur le site : <b>{{ compte.pseudo }}</b></p>
 {% if cle %}
 <label for="cle">Ta clé personnelle (à coller dans le script d'envoi automatique)
 <input id="cle" type="text" value="{{ cle }}" readonly onclick="this.select()"></label>
 {% else %}<p>Aucune clé active : génère-en une.</p>{% endif %}
 <div class="boutons">{% if cle %}<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('cle').value);this.textContent='Copiée !'">Copier la clé</button>{% endif %}
 <a class="cta sec" href="contribuer">Envoyer mes données</a></div>
 <form method="post" onsubmit="return confirm('L\\'ancienne clé ne fonctionnera plus : relance changer-cle.bat sur ton PC. Continuer ?')">
 <input type="hidden" name="action" value="regenerer"><div><button class="sec" type="submit">Générer une nouvelle clé</button></div></form>
 {% else %}
 <h2>Première connexion</h2>
 <p>Relie ton compte Discord à ton pseudo de guilde.</p>
 <form method="post"><input type="hidden" name="action" value="lier">
 <label for="ancienne">J'ai déjà reçu une clé en message privé<input id="ancienne" type="password" name="cle" required></label>
 <div><button type="submit">Relier avec ma clé</button></div></form>
 <form method="post"><input type="hidden" name="action" value="creer">
 <label for="pseudo">Je n'ai pas de clé : choisis ton pseudo
 <input id="pseudo" name="pseudo" required maxlength="24" value="{{ session.discord.nom }}">
 <small>2 à 24 caractères, sans espace ni « : ». Une clé est créée pour toi.</small></label>
 <div><button type="submit">Créer ma clé</button></div></form>
 {% endif %}
{% endif %}
</section></div></body></html>"""

ADMIN = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Administration</title>""" + STYLE + """</head><body><div class="page">
""" + ENTETE + """
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
<section class="sec"><h2>Comptes Discord reliés <small>{{ comptes|length }}</small></h2>
<div class="carte table-wrap"><table><thead><tr><th>Pseudo</th><th>Discord</th><th>Clé</th><th>Relié le</th><th></th></tr></thead><tbody>
{% for c in comptes %}<tr><td class="nom">{{ c.pseudo }}</td><td>{{ c.discord_nom }}</td>
<td>{{ "créée sur le site" if c.cle else "cles.txt" }}</td><td>{{ c.lie_le[:16].replace("T", " ") }}</td>
<td><form method="post" onsubmit="return confirm('Délier ce compte ? La clé créée sur le site sera supprimée.')">
<input type="hidden" name="action" value="delier"><input type="hidden" name="discord_id" value="{{ c.discord_id }}">
<button class="sec" type="submit">Délier</button></form></td></tr>
{% else %}<tr><td colspan="5">Aucun compte relié.</td></tr>{% endfor %}
</tbody></table></div></section>
<section class="carte formulaire sec"><h2>Clés de cles.txt sans compte Discord</h2>
<p>{{ sans_compte|join(", ") if sans_compte else "aucune" }}</p></section>
<section class="carte formulaire sec"><h2>Zone dangereuse</h2>
<form method="post" onsubmit="return confirm('Vider toute la progression ? Une copie est gardée.')">
<input type="hidden" name="action" value="reinitialiser"><div><button type="submit">Vider la base de progression</button></div></form>
<small>Personnages, historique, exploits et envois. Les comptes et les clés sont conservés.</small></section>
</div></body></html>"""


@app.context_processor
def contexte():
    return {"discord_actif": bool(DISCORD_SECRET)}


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
        persos = con.execute("SELECT * FROM personnages ORDER BY niveau DESC, nom").fetchall()
        rows = con.execute("SELECT * FROM exploits ORDER BY palier, rang").fetchall()
        recents = con.execute("SELECT * FROM historique ORDER BY date DESC LIMIT 15").fetchall()
        g24 = gains(con, 24)
    exploits = {}
    for e in rows:
        exploits.setdefault(e["palier"], []).append(e)
    return render_template_string(
        PAGE, guilde=NOM_GUILDE, persos=persos, paliers=PALIERS, exploits=exploits,
        medailles=MEDAILLES, recents=recents, g24=g24,
        total24=sum(v for v in g24.values() if v > 0),
        actifs=sum(1 for v in g24.values() if v > 0),
        nb60=sum(1 for p in persos if p["niveau"] == 60),
        moyenne=f"{sum(p['niveau'] for p in persos) / len(persos):.1f}" if persos else "—",
        maj=max((p["maj"] for p in persos), default="")[:16].replace("T", " "),
        classes={p["nom"]: p["classe"] for p in persos},
        liste_classes=sorted({p["classe"] for p in persos}),
        couleur=lambda c: COULEURS.get(c, "#e6eefb"))


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
    return jsonify(ok=True, mises_a_jour=collecter())


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
    """Vide la progression (pas les comptes). Copie de sauvegarde dans <DB>.avant-reset."""
    with db() as con, sqlite3.connect(DB + ".avant-reset") as copie:
        con.backup(copie)
        return {t: con.execute(f"DELETE FROM {t}").rowcount
                for t in ("personnages", "historique", "exploits", "envois")}


@app.route("/envoyer", methods=["POST"])
def route_envoyer():
    pseudo = contributeur(request.headers.get("X-Cle"))
    if not pseudo:
        abort(403)
    texte = request.get_data(as_text=True)
    persos = analyser_export(texte)
    if not persos:
        return jsonify(ok=False, erreur="Fichier vide ou invalide"), 400
    return jsonify(ok=True, personnages=len(persos),
                   nouveautes=integrer(persos, pseudo, analyser_dates(texte)))


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
    n = integrer(persos, pseudo, analyser_dates(texte))
    return formulaire(classe="ok", pseudo=connecte,
                      message=f"Merci {pseudo} ! {len(persos)} personnages lus, {n} mises à jour.")


# ---------- Connexion Discord ----------
@app.route("/connexion")
def route_connexion():
    if not DISCORD_SECRET:
        abort(404)
    session["etat"] = secrets.token_urlsafe(24)
    return redirect("https://discord.com/oauth2/authorize?" + urlencode({
        "response_type": "code", "client_id": DISCORD_ID, "scope": "identify guilds.members.read",
        "redirect_uri": URL_SITE + "/auth/discord/callback", "state": session["etat"], "prompt": "none"}))


@app.route("/auth/discord/callback")
def route_retour_discord():
    etat = session.pop("etat", None)
    if (not DISCORD_SECRET or not etat or "code" not in request.args
            or not hmac.compare_digest(etat.encode(), request.args.get("state", "").encode())):
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
    except (requests.RequestException, KeyError, ValueError) as e:
        print("Erreur de connexion Discord :", e, flush=True)
        return page_compte(message="Discord ne répond pas, réessaie dans un instant.", classe="err"), 502
    membre = membre.json() if membre.status_code == 200 else None
    if utilisateur["id"] not in ADMINS:  # les admins passent toujours
        if not membre:
            return page_compte(message="Tu n'es pas sur le serveur Discord de la guilde.", classe="err"), 403
        if DISCORD_ROLE and DISCORD_ROLE not in membre.get("roles", []):
            return page_compte(message="Il te faut le rôle de la guilde sur Discord.", classe="err"), 403
    nom = (membre or {}).get("nick") or utilisateur.get("global_name") or utilisateur["username"]
    session.clear()
    session.permanent = True
    session["discord"] = {"id": utilisateur["id"], "nom": nom}
    with db() as con:
        con.execute("UPDATE comptes SET discord_nom=? WHERE discord_id=?", (nom, utilisateur["id"]))
    return redirect(URL_SITE + "/moi")


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
                con.execute("INSERT INTO comptes VALUES(?,?,NULL,?,?)", (d["id"], pseudo, d["nom"], maintenant()))
                message = f"Compte relié à {pseudo}."
        elif action == "creer" and not compte:
            pseudo = request.form.get("pseudo", "").strip()
            if not PSEUDO_VALIDE.match(pseudo):
                message, classe = "Pseudo invalide : 2 à 24 caractères, sans espace ni « : ».", "err"
            elif (pseudo.casefold() in {p.casefold() for p in cles_fichier()}
                  or con.execute("SELECT 1 FROM comptes WHERE pseudo=?", (pseudo,)).fetchone()):
                message, classe = "Ce pseudo a déjà une clé : utilise « J'ai déjà reçu une clé ».", "err"
            else:
                con.execute("INSERT INTO comptes VALUES(?,?,?,?,?)",
                            (d["id"], pseudo, nouvelle_cle(con), d["nom"], maintenant()))
                message = f"Bienvenue {pseudo} ! Ta clé est prête."
        elif action == "regenerer" and compte:
            con.execute("UPDATE comptes SET cle=? WHERE discord_id=?", (nouvelle_cle(con), d["id"]))
            message = "Nouvelle clé créée. L'ancienne ne fonctionne plus."
        compte = compte_connecte(con)
    return page_compte(compte=compte, cle=cle_du_compte(compte) if compte else None,
                       message=message, classe=classe), 400 if classe == "err" else 200


@app.route("/admin", methods=["GET", "POST"])
def route_admin():
    if not est_admin():
        abort(403)
    message = None
    action = request.form.get("action") if request.method == "POST" else None
    if action == "delier":
        with db() as con:
            con.execute("DELETE FROM comptes WHERE discord_id=?", (request.form.get("discord_id"),))
        message = "Compte délié."
    elif action == "reinitialiser":
        vides = reinitialiser()
        message = f"Base de progression vidée ({vides['personnages']} personnages). Copie dans guilde.db.avant-reset."
    with db() as con:
        comptes = con.execute("SELECT * FROM comptes ORDER BY pseudo").fetchall()
    lies = {c["pseudo"].casefold() for c in comptes}
    return render_template_string(
        ADMIN, guilde=NOM_GUILDE, titre="Administration", comptes=comptes, message=message, classe="ok",
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
        }
    return app.response_class(
        json.dumps(donnees, ensure_ascii=False, indent=2), mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=guilde-export.json"})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
