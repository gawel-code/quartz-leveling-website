# Quartz Forever — suivi de progression de guilde (WoW Forever)
import os, re, json, hmac, sqlite3, datetime
from pathlib import Path
import requests
from flask import Flask, render_template_string, request, abort, jsonify, send_file

# ---------- Configuration ----------
DB = os.getenv("GUILDE_DB", "guilde.db")
EXPORT = Path(os.getenv("GUILDE_EXPORT", "GuildExport.lua"))
FICHIER_CLES = Path(os.getenv("GUILDE_CLES", "cles.txt"))
WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
TOKEN = os.getenv("GUILDE_TOKEN", "change-moi")
NOM_GUILDE = os.getenv("NOM_GUILDE", "Quartz Forever")
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
    """Envoie les annonces d'un envoi, dans l'ordre chronologique, une fois tout le fichier
    intégré : les rangs annoncés tiennent compte de tous les personnages du même envoi.
    (Entre deux envois, un rang déjà annoncé peut encore être corrigé sur le tableau d'honneur.)
    Chaque message cite le membre dont l'envoi l'a déclenché (sauf collecte serveur)."""
    via = "" if source == "serveur" else " _— via " + re.sub(r"([\\*_~`|>])", r"\\\1", source) + "_"
    for a in sorted(annonces, key=lambda a: a["date"]):  # tri stable : ordre du fichier à date égale
        nom, classe, quand = a["nom"], a["classe"], date_lisible(a["date"])
        if "niveau" in a:
            discord(f"⬆️ **{nom}** ({classe}) passe **niveau {a['niveau']}** ({quand}) !{via}")
            continue
        palier = a["palier"]
        rang = con.execute("SELECT rang FROM exploits WHERE palier=? AND nom=?", (palier, nom)).fetchone()[0]
        medaille = MEDAILLES.get(rang, "🏆" if palier == 60 else "⭐")
        if palier == 60:
            discord(f"{medaille} **{nom}** ({classe}) atteint le **niveau 60** {quand} ! "
                    f"{ordinal(rang)} de la guilde à toucher le sommet. Félicitations !{via}")
        else:
            discord(f"{medaille} **{nom}** ({classe}) est le {ordinal(rang)} de la guilde "
                    f"à atteindre le **niveau {palier}** ({quand}) !{via}")


def corriger_exploits(con, nom):
    """Avance la date d'un palier déjà enregistré si une date plus ancienne est connue, puis reclasse."""
    for e in con.execute("SELECT palier, date FROM exploits WHERE nom=?", (nom,)).fetchall():
        date = date_atteinte(con, nom, e["palier"])
        if date and date < e["date"]:
            con.execute("UPDATE exploits SET date=? WHERE palier=? AND nom=?", (date, e["palier"], nom))
            reclasser(con, e["palier"])


# ---------- Contributeurs ----------
def contributeur(cle):
    """Renvoie le pseudo associé à une clé (fichier cles.txt, lignes Pseudo:clé), ou None."""
    if not cle or not FICHIER_CLES.exists():
        return None
    for ligne in FICHIER_CLES.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and ":" in ligne:
            pseudo, c = ligne.split(":", 1)
            if c.strip() == cle.strip():
                return pseudo.strip()
    return None


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
</style>
"""

ENTETE = """<header>
<div class="logo"><img src="logo.png" alt="Logo {{ guilde }}"></div>
<div class="titre"><h1>{{ "Envoyer mes données" if formulaire else guilde }}</h1>
<div class="meta"><span class="tag horde">Horde</span><span class="tag">WoW Forever · PvE</span>
{% if maj %}<span class="tag live">Mis à jour {{ maj }}</span>{% endif %}</div></div>
{% if formulaire %}<a class="cta" href="./">← Retour au classement</a>
{% else %}<a class="cta" href="contribuer">Envoyer mes données</a>{% endif %}
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
<label for="cle">Ta clé personnelle<input id="cle" type="password" name="cle" required></label>
<label for="fichier">Ton fichier GuildExport.lua<input id="fichier" type="file" name="fichier" accept=".lua" required>
<small>Il se trouve dans World of Warcraft\\_forever_\\WTF\\Account\\TON_COMPTE\\SavedVariables\\</small></label>
<div><button type="submit">Envoyer</button></div>
</form></div></body></html>"""


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
    return render_template_string(FORMULAIRE, guilde=NOM_GUILDE, formulaire=True, **kw)


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
    with db() as con, sqlite3.connect(DB + ".avant-reset") as copie:
        con.backup(copie)
        vides = {t: con.execute(f"DELETE FROM {t}").rowcount
                 for t in ("personnages", "historique", "exploits", "envois")}
    return jsonify(ok=True, supprimes=vides)


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
    if request.method == "GET":
        return formulaire()
    pseudo = contributeur(request.form.get("cle"))
    if not pseudo:
        return formulaire(message="Clé inconnue.", classe="err"), 403
    f = request.files.get("fichier")
    texte = f.read().decode("utf-8", errors="ignore") if f else ""
    persos = analyser_export(texte)
    if not persos:
        return formulaire(message="Fichier vide ou invalide.", classe="err"), 400
    n = integrer(persos, pseudo, analyser_dates(texte))
    return formulaire(classe="ok",
                      message=f"Merci {pseudo} ! {len(persos)} personnages lus, {n} mises à jour.")


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
