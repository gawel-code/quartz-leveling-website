# Quartz Forever — suivi de progression de guilde (WoW Forever)
import os, re, json, sqlite3, datetime
from pathlib import Path
import requests
from flask import Flask, render_template_string, request, abort, jsonify

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
    "Paladin": "#F48CBA", "Chaman": "#0070DD", "Chamane": "#0070DD",
}


def maintenant():
    return datetime.datetime.now().isoformat(timespec="minutes")


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


def verifier_exploits(con, nom, classe, ancien, nouveau):
    for palier in PALIERS:
        if not (ancien < palier <= nouveau):
            continue
        if con.execute("SELECT 1 FROM exploits WHERE palier=? AND nom=?", (palier, nom)).fetchone():
            continue
        deja = con.execute("SELECT COUNT(*) FROM exploits WHERE palier=?", (palier,)).fetchone()[0]
        rang = deja + 1
        if palier == 60:
            con.execute("INSERT INTO exploits VALUES(?,?,?,?)", (palier, nom, rang, maintenant()))
            discord(f"{MEDAILLES.get(rang, '🏆')} **{nom}** ({classe}) atteint le **niveau 60** ! "
                    f"{ordinal(rang)} de la guilde à toucher le sommet. Félicitations !")
        elif deja < 3:
            con.execute("INSERT INTO exploits VALUES(?,?,?,?)", (palier, nom, rang, maintenant()))
            discord(f"{MEDAILLES[rang]} **{nom}** ({classe}) est le {ordinal(rang)} de la guilde "
                    f"à atteindre le **niveau {palier}** !")


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


def integrer(persos, source="serveur"):
    """Fusionne des données : garde toujours le niveau le plus haut et complète les races."""
    nouveaux = 0
    with db() as con:
        for nom, race, classe, niveau in persos:
            row = con.execute("SELECT niveau, race FROM personnages WHERE nom=?", (nom,)).fetchone()
            race_connue = race not in (None, "", "?")
            if row and niveau < row["niveau"]:
                if race_connue and row["race"] in (None, "?"):
                    con.execute("UPDATE personnages SET race=? WHERE nom=?", (race, nom))
                continue
            if row and not race_connue:
                race = row["race"]
            ancien = row["niveau"] if row else 1
            if row is None or niveau > row["niveau"]:
                con.execute("INSERT INTO historique VALUES(?,?,?)", (nom, niveau, maintenant()))
                verifier_exploits(con, nom, classe, ancien, niveau)
                nouveaux += 1
            con.execute("""INSERT INTO personnages VALUES(?,?,?,?,?)
                ON CONFLICT(nom) DO UPDATE SET race=excluded.race, classe=excluded.classe,
                niveau=excluded.niveau, maj=excluded.maj""",
                        (nom, race, classe, niveau, maintenant()))
        con.execute("INSERT INTO envois VALUES(?,?,?,?)", (source, maintenant(), len(persos), nouveaux))
    return nouveaux


def lire_api_blizzard():
    """À brancher quand l'espace de noms Forever sera publié par Blizzard."""
    return []


def collecter():
    persos = lire_api_blizzard()
    if not persos and EXPORT.exists():
        persos = analyser_export(EXPORT.read_text(encoding="utf-8"))
    return integrer(persos, "serveur") if persos else 0


# ---------- Récapitulatif ----------
def gains(con, heures):
    limite = (datetime.datetime.now() - datetime.timedelta(hours=heures)).isoformat(timespec="minutes")
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
<style>
:root{--fond:#14100d;--carte:#1f1915;--bord:#3a2e24;--or:#d4a64a;--rouge:#b3261e;
--quartz:#c9a3e8;--texte:#ece2cf;--doux:#a8998a}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.page{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
header{border-bottom:2px solid var(--rouge);padding-bottom:12px;margin-bottom:24px}
h1{font-family:Georgia,serif;color:var(--or);margin:0;font-size:2rem}
h2{font-family:Georgia,serif;color:var(--or);font-size:1.3rem;margin:32px 0 12px}
.sous{color:var(--doux);font-size:.9rem;margin-top:4px}
a{color:var(--quartz)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:14px}
.stat b{display:block;font-size:1.6rem;color:var(--or)}
.stat span{color:var(--doux);font-size:.85rem}
.honneur{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.palier{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:12px}
.palier.p60{border-color:var(--or);grid-column:1/-1}
.palier h3{margin:0 0 8px;font-size:1rem;color:var(--quartz)}
.palier div{font-size:.9rem;margin:3px 0}
.palier small{color:var(--doux)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--carte);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bord);font-size:.92rem}
th{color:var(--doux);font-weight:600;background:#261e18}
.barre{background:#2c241d;border-radius:4px;height:6px;width:90px}
.barre i{display:block;height:6px;border-radius:4px;background:linear-gradient(90deg,var(--rouge),var(--or))}
.gain{color:#7fd17f;font-size:.85rem}
select,input,button{background:var(--carte);color:var(--texte);border:1px solid var(--bord);border-radius:6px;padding:8px}
button{background:var(--rouge);border-color:var(--rouge);cursor:pointer;font-weight:600}
ul.fil{list-style:none;padding:0;margin:0}
ul.fil li{padding:6px 0;border-bottom:1px solid var(--bord);font-size:.9rem}
ul.fil small{color:var(--doux)}
.msg{padding:10px;border-radius:6px;margin:12px 0}
.ok{background:#1d3b1d}.err{background:#4a1a17}
form p{margin:12px 0}
</style>
"""

PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ guilde }} — Progression</title>""" + STYLE + """</head><body><div class="page">
<header><h1>💎 {{ guilde }}</h1>
<div class="sous">WoW Forever · Horde · Serveur PvE ·
Dernière mise à jour : {{ maj or "—" }} · <a href="contribuer">📤 Envoyer mes données</a></div></header>

<div class="stats">
 <div class="stat"><b>{{ persos|length }}</b><span>Membres suivis</span></div>
 <div class="stat"><b>{{ moyenne }}</b><span>Niveau moyen</span></div>
 <div class="stat"><b>{{ nb60 }}</b><span>Niveau 60</span></div>
 <div class="stat"><b>+{{ total24 }}</b><span>Niveaux gagnés en 24 h</span></div>
</div>

<h2>🏆 Tableau d'honneur</h2>
<div class="honneur">
{% for p in paliers %}
 <div class="palier {{ 'p60' if p == 60 else '' }}">
  <h3>{{ "Panthéon du niveau 60" if p == 60 else "Niveau " ~ p }}</h3>
  {% for e in exploits.get(p, []) %}
   <div>{{ medailles.get(e.rang, "🏆") }} <span style="color:{{ couleur(classes.get(e.nom, '')) }}">{{ e.nom }}</span>
   <small>{{ e.date[:16].replace("T", " ") }}</small></div>
  {% else %}<div><small>Personne pour l'instant…</small></div>{% endfor %}
 </div>
{% endfor %}
</div>

<h2>📊 Classement</h2>
<p><select id="filtre" onchange="filtrer(this.value)"><option value="">Toutes les classes</option>
{% for c in liste_classes %}<option>{{ c }}</option>{% endfor %}</select></p>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Nom</th><th>Race</th><th>Classe</th><th>Niveau</th><th>Vers 60</th><th>24 h</th></tr></thead><tbody>
{% for p in persos %}
<tr data-classe="{{ p.classe }}"><td>{{ loop.index }}</td>
<td style="color:{{ couleur(p.classe) }};font-weight:600">{{ "👑 " if p.niveau == 60 else "" }}{{ p.nom }}</td>
<td>{{ p.race }}</td><td>{{ p.classe }}</td><td><b>{{ p.niveau }}</b></td>
<td><div class="barre"><i style="width:{{ (p.niveau / 60 * 100)|round|int }}%"></i></div></td>
<td>{% if g24.get(p.nom, 0) > 0 %}<span class="gain">+{{ g24[p.nom] }}</span>{% endif %}</td></tr>
{% else %}<tr><td colspan="7">Aucune donnée pour l'instant. Envoie ton fichier GuildExport.lua !</td></tr>{% endfor %}
</tbody></table></div>

<h2>⚡ Dernières montées de niveau</h2>
<ul class="fil">
{% for r in recents %}<li><b style="color:{{ couleur(classes.get(r.nom, '')) }}">{{ r.nom }}</b> passe niveau <b>{{ r.niveau }}</b>
<small>· {{ r.date.replace("T", " ") }}</small></li>{% else %}<li><small>Rien pour l'instant.</small></li>{% endfor %}
</ul>
</div>
<script>
function filtrer(c){document.querySelectorAll("tbody tr[data-classe]").forEach(function(tr){
 tr.style.display=(!c||tr.dataset.classe===c)?"":"none";});}
</script></body></html>"""

FORMULAIRE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Envoyer mes données</title>""" + STYLE + """</head><body><div class="page">
<header><h1>📤 Envoyer mes données</h1>
<div class="sous"><a href="./">← Retour au classement</a></div></header>
{% if message %}<div class="msg {{ classe }}">{{ message }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">
<p><label>Ta clé personnelle<br><input type="password" name="cle" required style="width:100%;max-width:400px"></label></p>
<p><label>Ton fichier GuildExport.lua<br><input type="file" name="fichier" accept=".lua" required></label></p>
<p><small style="color:var(--doux)">Il se trouve dans
World of Warcraft\\_forever_\\WTF\\Account\\TON_COMPTE\\SavedVariables\\</small></p>
<p><button type="submit">Envoyer</button></p>
</form></div></body></html>"""


def verifier_token():
    if request.args.get("token") != TOKEN:
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
        nb60=sum(1 for p in persos if p["niveau"] == 60),
        moyenne=f"{sum(p['niveau'] for p in persos) / len(persos):.1f}" if persos else "—",
        maj=max((p["maj"] for p in persos), default="").replace("T", " "),
        classes={p["nom"]: p["classe"] for p in persos},
        liste_classes=sorted({p["classe"] for p in persos}),
        couleur=lambda c: COULEURS.get(c, "#ece2cf"))


@app.route("/collecter", methods=["GET", "POST"])
def route_collecter():
    verifier_token()
    return jsonify(ok=True, mises_a_jour=collecter())


@app.route("/recap", methods=["GET", "POST"])
def route_recap():
    verifier_token()
    recap()
    return jsonify(ok=True)


@app.route("/envoyer", methods=["POST"])
def route_envoyer():
    pseudo = contributeur(request.headers.get("X-Cle"))
    if not pseudo:
        abort(403)
    persos = analyser_export(request.get_data(as_text=True))
    if not persos:
        return jsonify(ok=False, erreur="Fichier vide ou invalide"), 400
    return jsonify(ok=True, personnages=len(persos), nouveautes=integrer(persos, pseudo))


@app.route("/contribuer", methods=["GET", "POST"])
def route_contribuer():
    if request.method == "GET":
        return render_template_string(FORMULAIRE)
    pseudo = contributeur(request.form.get("cle"))
    if not pseudo:
        return render_template_string(FORMULAIRE, message="Clé inconnue.", classe="err"), 403
    f = request.files.get("fichier")
    persos = analyser_export(f.read().decode("utf-8", errors="ignore")) if f else []
    if not persos:
        return render_template_string(FORMULAIRE, message="Fichier vide ou invalide.", classe="err"), 400
    n = integrer(persos, pseudo)
    return render_template_string(FORMULAIRE, classe="ok",
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
