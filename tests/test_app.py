"""Tests du serveur. Lancer : pip install flask requests pytest && pytest -q"""
import datetime
import importlib.util
import io
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "ha-app" / "quartz_forever" / "app.py"

LUA1 = 'GuildExportDB = {\n["Grommash"] = "Grommash;Orc;Guerrier;12",\n["Zuljin"] = "Zuljin;?;Chaman;9",\n}'
LUA2 = ('GuildExportDB = {\n["Grommash"] = "Grommash;Orc;Guerrier;60",\n'
        '["Zuljin"] = "Zuljin;Troll;Chaman;21",\n["Mok"] = "Mok;Tauren;Paladin;5",\n}')


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "cles.txt").write_text("# test\nGael:abc123\n", encoding="utf-8")
    monkeypatch.setenv("GUILDE_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("GUILDE_CLES", str(tmp_path / "cles.txt"))
    monkeypatch.setenv("GUILDE_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_WEBHOOK", "")
    monkeypatch.setenv("GUILDE_URL", "http://localhost")
    monkeypatch.delenv("DISCORD_CLIENT_SECRET", raising=False)
    spec = importlib.util.spec_from_file_location("app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app.test_client()


def capturer(monkeypatch, client):
    """Remplace discord() : renvoie (lignes d'annonce, messages bruts). La ligne « — via » est
    exclue des lignes."""
    lignes, bruts = [], []

    def discord(message):
        bruts.append(message)
        lignes.extend(l for l in message.split("\n") if not l.startswith("_— via"))
    monkeypatch.setitem(client.application.view_functions["index"].__globals__, "discord", discord)
    return lignes, bruts


def envoyer(c, lua, cle="abc123"):
    return c.post("/envoyer", data=lua, headers={"X-Cle": cle})


def test_cle_invalide_refusee(client):
    assert envoyer(client, LUA1, "mauvaise").status_code == 403


def test_garde_le_niveau_le_plus_haut_et_complete_les_races(client):
    envoyer(client, LUA1)
    envoyer(client, LUA2)
    envoyer(client, LUA1)  # ancien fichier renvoyé : ne doit rien faire baisser
    d = client.get("/export.json?token=tok").json
    persos = {p["nom"]: p for p in d["personnages"]}
    assert persos["Grommash"]["niveau"] == 60
    assert persos["Zuljin"]["race"] == "Troll"


def test_exploits_annonces_une_seule_fois(client):
    envoyer(client, LUA1)
    envoyer(client, LUA2)
    envoyer(client, LUA2)
    ex = client.get("/export.json?token=tok").json["exploits"]
    paires = [(e["palier"], e["nom"]) for e in ex]
    assert len(paires) == len(set(paires))
    assert (60, "Grommash") in paires


def test_formulaire_contribuer(client):
    r = client.post("/contribuer",
                    data={"cle": "abc123", "fichier": (io.BytesIO(LUA1.encode()), "GuildExport.lua")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and "Merci" in r.text


def test_pages_et_jeton(client):
    assert client.get("/").status_code == 200
    assert client.get("/contribuer").status_code == 200
    assert client.get("/export.json").status_code == 403
    assert client.get("/recap?token=tok").json["ok"]
    assert client.get("/export.json?token=é").status_code == 403


def test_page_remplie_et_logo(client):
    envoyer(client, LUA1)
    envoyer(client, LUA2)
    r = client.get("/")
    assert "Grommash" in r.text and "Panthéon du niveau 60" in r.text
    logo = client.get("/logo.png")
    assert logo.status_code == 200 and logo.mimetype == "image/png"
    banniere = client.get("/banniere.jpg")
    assert banniere.status_code == 200 and banniere.mimetype == "image/jpeg"
    assert client.get("/app.py").status_code == 404


def test_generer_cles(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "generer_cles", APP.parent.parent.parent / "tools" / "generer_cles.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    f = tmp_path / "cles.txt"
    n1 = gen.generer(f, ["Gael", "Zuljin", "gael"])
    assert set(n1) == {"Gael", "Zuljin"}
    assert gen.generer(f, ["Gael", "Mok"]).keys() == {"Mok"}  # pseudo existant ignoré
    n3 = gen.generer(f, ["Zuljin"], renouveler=True)
    assert n3["Zuljin"] != n1["Zuljin"]
    lignes = [l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    assert lignes == [f"Gael:{n1['Gael']}", f"Zuljin:{n3['Zuljin']}", f"Mok:{lignes[2].split(':')[1]}"]


def test_token_vide_ferme_les_routes_protegees(tmp_path, monkeypatch):
    monkeypatch.setenv("GUILDE_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("GUILDE_TOKEN", "")  # option « token » laissée vide dans HA
    spec = importlib.util.spec_from_file_location("app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = mod.app.test_client()
    for route in ("/export.json", "/collecter", "/recap"):
        assert c.get(route + "?token=").status_code == 403
        assert c.get(route).status_code == 403


def test_reinitialiser(client):
    envoyer(client, LUA2)
    assert client.get("/reinitialiser?token=tok").status_code == 405
    assert client.post("/reinitialiser?token=faux").status_code == 403
    r = client.post("/reinitialiser?token=tok")
    assert r.status_code == 200 and r.json["supprimes"]["personnages"] == 3
    d = client.get("/export.json?token=tok").json
    assert d["personnages"] == d["exploits"] == d["historique"] == d["envois"] == d["proprietaires"] == []


def test_annonces_paliers_et_niveaux(client, monkeypatch):
    messages, _ = capturer(monkeypatch, client)

    def lua(*persos):
        return "GuildExportDB = {\n" + "".join(f'["{n}"] = "{n};Orc;Guerrier;{l}",\n' for n, l in persos) + "}"

    # 4 joueurs au palier 10 : tous annoncés, le 4ᵉ sans médaille
    envoyer(client, lua(("A", 10), ("B", 10), ("C", 10), ("D", 10)))
    assert len(messages) == 4 and "4ᵉ" in messages[3] and "⭐" in messages[3]
    messages.clear()
    # 10 → 24 : palier 20 seulement (21-24 ne s'annoncent pas)
    envoyer(client, lua(("A", 24)))
    assert len(messages) == 1 and "niveau 20" in messages[0]
    messages.clear()
    # 24 → 25 : annonce sans classement
    envoyer(client, lua(("A", 25)))
    assert len(messages) == 1 and messages[0].startswith("⬆️ **A** (Guerrier) passe **niveau 25** (le ")
    messages.clear()
    # 25 → 27 : rien
    envoyer(client, lua(("A", 27)))
    assert messages == []
    # 27 → 53 : paliers 30, 40, 50 + niveau 53 (pas de rafale 35, 45, 51, 52)
    envoyer(client, lua(("A", 53)))
    assert len(messages) == 4 and "niveau 53" in messages[-1]
    messages.clear()
    # 53 → 54 puis 59 → 60
    envoyer(client, lua(("A", 54)))
    assert len(messages) == 1 and "passe **niveau 54**" in messages[0]
    messages.clear()
    envoyer(client, lua(("A", 59)))
    envoyer(client, lua(("A", 60)))
    assert "niveau 59" in messages[0] and "niveau 60" in messages[1] and len(messages) == 2
    # le tableau d'honneur n'affiche que le top 3 du palier 10
    page = client.get("/").text
    assert 'class="m m3"' in page and 'class="m m4"' not in page


def lua_dates(persos, niveaux):
    """Fichier tel que l'écrit l'addon, avec la table GuildExportNiveaux (niveau@horodatage)."""
    db = "".join(f'["{n}"] = "{n};Orc;Guerrier;{l}",\n' for n, l in persos)
    nv = "".join(f'["{n}"] = "{v}",\n' for n, v in niveaux.items())
    return f"GuildExportDB = {{\n{db}}}\nGuildExportNiveaux = {{\n{nv}}}\n"


def test_dates_de_l_addon(client, monkeypatch):
    import datetime
    messages, _ = capturer(monkeypatch, client)
    g = client.application.view_functions["index"].__globals__
    base = datetime.datetime.now().replace(minute=0, second=0, microsecond=0) - datetime.timedelta(days=3)
    ts = lambda h: int((base + datetime.timedelta(hours=h)).timestamp())
    iso = lambda h: (base + datetime.timedelta(hours=h)).isoformat(timespec="seconds")

    # B envoie en premier, sans dates : il prend la date de réception (aujourd'hui) → 1ᵉʳ annoncé
    envoyer(client, lua_dates([("B", 10)], {}))
    assert "1ᵉʳ" in messages[-1]
    # A envoie ensuite, mais a atteint 10 avant (date de l'addon) : annoncé 1ᵉʳ, B recule au 2ᵉ rang
    envoyer(client, lua_dates([("A", 12)], {"A": f"10@{ts(8)},12@{ts(9)}"}))
    assert "1ᵉʳ" in messages[-1] and (base + datetime.timedelta(hours=8)).strftime("le %d/%m à %H h %M") in messages[-1]
    d = client.get("/export.json?token=tok").json
    rangs = {e["nom"]: e["rang"] for e in d["exploits"] if e["palier"] == 10}
    assert rangs == {"A": 1, "B": 2}
    hist = {(h["nom"], h["niveau"]): h["date"] for h in d["historique"]}
    assert hist[("A", 10)] == iso(8) and hist[("A", 12)] == iso(9)

    # Un autre membre envoie une date plus ancienne pour B : la plus ancienne gagne, B repasse 1ᵉʳ
    n = len(messages)
    envoyer(client, lua_dates([("B", 10)], {"B": f"10@{ts(7)}"}))
    assert len(messages) == n  # pas de nouvelle annonce
    d = client.get("/export.json?token=tok").json
    assert {e["nom"]: e["rang"] for e in d["exploits"] if e["palier"] == 10} == {"B": 1, "A": 2}

    # Une date future est ramenée à maintenant ; un niveau inférieur ne peut pas être plus récent
    envoyer(client, lua_dates([("C", 11)], {"C": f"10@{ts(24 * 365)},11@{ts(6)}"}))
    d = client.get("/export.json?token=tok").json
    hist = {(h["nom"], h["niveau"]): h["date"] for h in d["historique"]}
    assert hist[("C", 10)] <= hist[("C", 11)] == iso(6)


def test_dates_ignorees_par_analyser_export(client):
    """La table GuildExportNiveaux ne doit pas être prise pour des personnages."""
    texte = lua_dates([("A", 12)], {"A": "10@1793500000"})
    g = client.application.view_functions["index"].__globals__
    assert g["analyser_export"](texte) == [("A", "Orc", "Guerrier", 12)]
    assert list(g["analyser_dates"](texte)) == ["A"]


def test_rangs_annonces_dans_un_meme_envoi(client, monkeypatch):
    """Deux joueurs franchissent le même palier dans un même envoi : le rang annoncé suit la
    date réelle, pas l'ordre du fichier (bug : deux « 1ᵉʳ » au niveau 10)."""
    import datetime
    messages, _ = capturer(monkeypatch, client)
    g = client.application.view_functions["index"].__globals__
    now = datetime.datetime.now().replace(microsecond=0)
    ts = lambda h: int((now - datetime.timedelta(hours=h)).timestamp())
    envoyer(client, lua_dates([("Grommash", 23), ("Zuljin", 12)],
                              {"Grommash": f"20@{ts(5)},23@{ts(1)}", "Zuljin": f"10@{ts(6)},12@{ts(2)}"}))
    paliers10 = [m for m in messages if "niveau 10**" in m]
    assert len(paliers10) == 2
    assert "**Zuljin**" in paliers10[0] and "1ᵉʳ" in paliers10[0]
    assert "**Grommash**" in paliers10[1] and "2ᵉ" in paliers10[1] and "🥈" in paliers10[1]
    assert sum("1ᵉʳ" in m for m in paliers10) == 1


def test_un_message_par_envoi_avec_auteur_a_la_fin(client, monkeypatch):
    lignes, bruts = capturer(monkeypatch, client)
    envoyer(client, LUA1)  # clé de « Gael » ; Grommash passe le palier 10
    assert len(bruts) == 1
    assert bruts[0].endswith("\n_— via Gael_") and bruts[0].count("via") == 1
    assert len(lignes) == bruts[0].count("\n")
    # Pseudo avec caractères Markdown échappés ; collecte serveur sans mention
    g = client.application.view_functions["index"].__globals__
    g["integrer"]([("Thrall", "Orc", "Chaman", 10)], "Ma_x*")
    assert bruts[-1].endswith("\n_— via Ma\\_x\\*_")
    g["integrer"]([("Rexxar", "Orc", "Chasseur", 10)], "serveur")
    assert "via" not in bruts[-1]
    # Envoi sans annonce : aucun message
    n = len(bruts)
    envoyer(client, LUA1)
    assert len(bruts) == n


def test_message_decoupe_au_dela_de_2000_caracteres(client, monkeypatch):
    lignes, bruts = capturer(monkeypatch, client)
    persos = "".join(f'["Perso{i:02d}"] = "Perso{i:02d};Orc;Guerrier;10",\n' for i in range(40))
    envoyer(client, "GuildExportDB = {\n" + persos + "}")
    assert len(lignes) == 40 and len(bruts) > 1
    assert all(len(b) <= 2000 for b in bruts)
    assert bruts[-1].endswith("_— via Gael_") and sum("via" in b for b in bruts) == 1


# ---------- Connexion Discord ----------
ADMIN_ID = "161139977328132107"
ROLE = "1549720665844613130"


class Reponse:
    def __init__(self, donnees, code=200):
        self.donnees, self.status_code = donnees, code

    def json(self):
        return self.donnees

    def raise_for_status(self):
        assert self.status_code < 400


@pytest.fixture
def discord_client(client, monkeypatch):
    """Client avec la connexion Discord active. Renvoie (client, connecter(id, roles, sur_serveur))."""
    g = client.application.view_functions["index"].__globals__
    monkeypatch.setitem(g, "DISCORD_SECRET", "secret")
    profil = {}

    def post(url, **kw):
        assert url.endswith("/oauth2/token") and kw["data"]["code"] == "code-ok"
        return Reponse({"access_token": "t"})

    def get(url, **kw):
        if url.endswith("/users/@me/connections"):
            return Reponse(profil["connexions"])
        if url.endswith("/users/@me"):
            return Reponse({"id": profil["id"], "username": "user" + profil["id"], "global_name": None})
        if not profil["serveur"]:
            return Reponse({"message": "Unknown Guild"}, 404)
        return Reponse({"nick": profil["nick"] or "Surnom" + profil["id"], "roles": profil["roles"], "user": {}})
    monkeypatch.setattr(g["requests"], "post", post)
    monkeypatch.setattr(g["requests"], "get", get)

    def connecter(id_discord="42", roles=(ROLE,), sur_serveur=True, nick=None, connexions=()):
        profil.update(id=id_discord, roles=list(roles), serveur=sur_serveur, nick=nick, connexions=list(connexions))
        r = client.get("/connexion")
        assert r.status_code == 302 and "discord.com/oauth2/authorize" in r.location
        with client.session_transaction() as s:
            etat = s["etat"]
        return client.get(f"/auth/discord/callback?code=code-ok&state={etat}")
    return client, connecter


def test_discord_inactif_sans_secret(client):
    assert client.get("/connexion").status_code == 404
    assert client.get("/moi").status_code == 404
    assert "Connexion Discord" not in client.get("/").text


def test_connexion_refusee_sans_role_ou_hors_serveur(discord_client):
    c, connecter = discord_client
    assert connecter(roles=["autre"]).status_code == 403
    assert connecter(sur_serveur=False).status_code == 403
    assert "Connexion Discord" in c.get("/").text  # toujours déconnecté


def test_etat_oauth_verifie(discord_client):
    c, _ = discord_client
    c.get("/connexion")
    assert c.get("/auth/discord/callback?code=code-ok&state=falsifie").status_code == 400
    assert c.get("/moi").text.count("Connecté avec Discord") == 0


def test_lier_avec_sa_cle_puis_envoyer_sans_cle(discord_client):
    c, connecter = discord_client
    r = connecter()
    assert r.status_code == 302 and r.location.endswith("/moi")
    assert "Première connexion" in c.get("/moi").text
    assert c.post("/moi", data={"action": "lier", "cle": "mauvaise"}).status_code == 400
    r = c.post("/moi", data={"action": "lier", "cle": "abc123"})
    assert r.status_code == 200 and "Gael" in r.text and 'value="abc123"' in r.text
    assert "Mon compte" in c.get("/").text
    r = c.post("/contribuer", data={"fichier": (io.BytesIO(LUA1.encode()), "GuildExport.lua")},
               content_type="multipart/form-data")
    assert r.status_code == 200 and "Merci Gael" in r.text
    # Un autre compte Discord ne peut pas reprendre le même pseudo
    c.get("/deconnexion")
    connecter("43")
    assert c.post("/moi", data={"action": "lier", "cle": "abc123"}).status_code == 400


def test_regenerer_la_cle_remplace_celle_de_cles_txt(discord_client):
    c, connecter = discord_client
    connecter()
    c.post("/moi", data={"action": "lier", "cle": "abc123"})
    c.post("/moi", data={"action": "regenerer"})
    with c.application.app_context():
        g = c.application.view_functions["index"].__globals__
        with g["db"]() as con:
            nouvelle = con.execute("SELECT cle FROM comptes").fetchone()[0]
    assert nouvelle and nouvelle != "abc123"
    assert envoyer(c, LUA1).status_code == 403
    assert envoyer(c, LUA1, nouvelle).status_code == 200
    assert f'value="{nouvelle}"' in c.get("/moi").text


def test_creer_un_pseudo_sans_cle(discord_client):
    c, connecter = discord_client
    connecter()
    assert c.post("/moi", data={"action": "creer", "pseudo": "gael"}).status_code == 400  # déjà dans cles.txt
    assert c.post("/moi", data={"action": "creer", "pseudo": "a b"}).status_code == 400
    r = c.post("/moi", data={"action": "creer", "pseudo": "Thrall"})
    assert r.status_code == 200 and "Bienvenue Thrall" in r.text
    cle = r.text.split('id="cle" type="text" value="')[1].split('"')[0]
    assert len(cle) >= 20 and envoyer(c, LUA1, cle).status_code == 200


def test_admin(discord_client):
    c, connecter = discord_client
    connecter()
    assert c.get("/admin").status_code == 403
    c.post("/moi", data={"action": "lier", "cle": "abc123"})
    envoyer(c, LUA2)
    c.get("/deconnexion")
    # L'admin passe même sans le rôle ni le serveur
    assert connecter(ADMIN_ID, roles=[], sur_serveur=False).status_code == 302
    r = c.get("/admin")
    assert r.status_code == 200 and "Gael" in r.text
    r = c.post("/admin", data={"action": "reinitialiser"})
    assert "3 personnages" in r.text
    assert c.get("/export.json?token=tok").json["personnages"] == []
    assert "Surnom42" in r.text  # le compte relié est conservé
    c.post("/admin", data={"action": "delier", "discord_id": "42"})
    assert "Aucun compte relié" in c.get("/admin").text


def test_liaison_auto_si_le_nom_discord_correspond(discord_client, tmp_path):
    c, connecter = discord_client
    connecter(nick="gael")  # surnom sur le serveur = pseudo de cles.txt (casse ignorée)
    r = c.get("/moi")
    assert "<dt>Pseudo</dt><dd>Gael</dd>" in r.text and 'value="abc123"' in r.text
    # Un autre compte avec le même surnom ne prend pas le pseudo déjà relié
    c.get("/deconnexion")
    connecter("43", nick="Gael")
    assert "Première connexion" in c.get("/moi").text
    assert c.post("/moi", data={"action": "creer", "pseudo": "Gael"}).status_code == 400
    # Pseudo ajouté à cles.txt après la connexion : « choisir son pseudo » relie s'il correspond
    with open(tmp_path / "cles.txt", "a", encoding="utf-8") as f:
        f.write("Thrall:cle-thrall\n")
    c.get("/deconnexion")
    connecter("44", nick="Surnom44")
    assert c.post("/moi", data={"action": "creer", "pseudo": "Thrall"}).status_code == 400  # nom différent
    c.get("/deconnexion")
    connecter("45", nick="thrall")  # liaison automatique dès la connexion
    assert 'value="cle-thrall"' in c.get("/moi").text


def test_choisir_son_pseudo_relie_si_nom_discord_identique(discord_client, tmp_path):
    c, connecter = discord_client
    connecter(nick="Rexxar")
    with open(tmp_path / "cles.txt", "a", encoding="utf-8") as f:
        f.write("Rexxar:cle-rexxar\n")
    r = c.post("/moi", data={"action": "creer", "pseudo": "rexxar"})
    assert r.status_code == 200 and "même nom que sur Discord" in r.text and 'value="cle-rexxar"' in r.text


def test_version_en_pied_de_page_et_dans_les_url_des_images(client):
    import re
    version = re.search(r'^version: "([^"]+)"', (APP.parent / "config.yaml").read_text(), re.M).group(1)
    for page in ("/", "/contribuer"):
        html = client.get(page).text
        assert f"v{version}</footer>" in html and f"logo.png?v={version}" in html
    assert f"banniere.jpg?v={version}" in client.get("/").text
    assert client.get(f"/logo.png?v={version}").status_code == 200


def test_battletag_recupere_via_les_connexions_discord(discord_client):
    c, connecter = discord_client
    bnet = [{"type": "steam", "name": "gawel_steam"}, {"type": "battlenet", "name": "Gawel#2345"}]
    assert "scope=identify+guilds.members.read+connections" in c.get("/connexion").location
    connecter(ADMIN_ID, nick="Gael", connexions=bnet)  # liaison auto : BattleTag enregistré avec le compte
    r = c.get("/moi")
    assert 'Gawel#2345 <span class="puce verifie">lié à Discord</span>' in r.text and 'id="battletag"' not in r.text
    assert "Gawel#2345" in c.get("/admin").text
    # Compte Battle.net délié côté Discord : effacé à la connexion suivante
    c.get("/deconnexion")
    connecter(ADMIN_ID, nick="Gael")
    assert 'id="battletag"' in c.get("/moi").text  # plus de BattleTag Discord : formulaire de saisie


def test_echec_lecture_des_connexions_ne_bloque_pas(discord_client, monkeypatch):
    c, connecter = discord_client
    connecter(connexions=[{"type": "battlenet"}])  # sans nom
    r = c.post("/moi", data={"action": "lier", "cle": "abc123"})
    assert r.status_code == 200 and 'id="battletag"' in r.text


def test_migration_colonne_battletag(tmp_path, monkeypatch):
    import sqlite3
    with sqlite3.connect(tmp_path / "ancienne.db") as con:  # schéma v1.4.x
        con.execute("CREATE TABLE comptes(discord_id TEXT PRIMARY KEY, pseudo TEXT UNIQUE COLLATE NOCASE,"
                    " cle TEXT UNIQUE, discord_nom TEXT, lie_le TEXT)")
        con.execute("INSERT INTO comptes VALUES('42','Gael',NULL,'Gawel','2026-10-30T09:00:00')")
    monkeypatch.setenv("GUILDE_DB", str(tmp_path / "ancienne.db"))
    spec = importlib.util.spec_from_file_location("app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with mod.db() as con:
        assert dict(con.execute("SELECT * FROM comptes").fetchone())["battletag"] is None


def test_battletag_saisi_a_la_main(discord_client):
    c, connecter = discord_client
    connecter(nick="Gael")
    assert c.post("/moi", data={"action": "battletag", "battletag": "pas un tag"}).status_code == 400
    r = c.post("/moi", data={"action": "battletag", "battletag": " Gaël#21456 "})
    assert r.status_code == 200 and 'value="Gaël#21456"' in r.text
    c.get("/deconnexion")
    connecter(ADMIN_ID, nick="Admin")
    assert 'Gaël#21456 <span class="puce">saisi</span>' in c.get("/admin").text
    c.get("/deconnexion")
    # Le BattleTag lu sur Discord prime ; la saisie est conservée en réserve
    connecter(nick="Gael", connexions=[{"type": "battlenet", "name": "Gael#1111"}])
    assert 'Gael#1111 <span class="puce verifie">lié à Discord</span>' in c.get("/moi").text
    c.get("/deconnexion")
    connecter(nick="Gael")
    r = c.post("/moi", data={"action": "battletag", "battletag": ""})
    assert "BattleTag effacé" in r.text and 'value=""' in r.text


def test_mon_compte_et_deconnexion_dans_l_en_tete_de_toutes_les_pages(discord_client):
    c, connecter = discord_client
    for page in ("/", "/contribuer", "/moi"):
        html = c.get(page).text
        assert 'href="connexion">Connexion Discord</a>' in html and 'href="deconnexion"' not in html
    connecter(ADMIN_ID)
    for page in ("/", "/contribuer", "/moi", "/admin"):
        entete = c.get(page).text.split("</header>")[0]
        assert 'href="moi">Mon compte</a>' in entete and 'href="deconnexion">Déconnexion</a>' in entete


# ---------- Personnages ↔ joueurs ----------
LUA_MES_PERSOS = LUA2 + '\nGuildExportMesPersos = {\n["Grommash"] = "1793300000",\n["Reroll"] = "1793300100",\n}\n'


def test_persos_du_compte_wow_associes_a_l_envoi(discord_client):
    c, connecter = discord_client
    assert envoyer(c, LUA_MES_PERSOS).status_code == 200
    d = c.get("/export.json?token=tok").json
    assert {(p["nom"], p["pseudo"], p["source"]) for p in d["proprietaires"]} == {
        ("Grommash", "Gael", "addon"), ("Reroll", "Gael", "addon")}
    # Les entrées GuildExportMesPersos ne sont pas prises pour des personnages
    assert "Reroll" not in {p["nom"] for p in d["personnages"]}
    # Classement : Grommash affiche son joueur ; le lien Discord apparaît une fois le compte relié
    assert '<span class="joueur">@Gael</span>' in c.get("/").text
    connecter(nick="Gael")
    assert 'href="https://discord.com/users/42"' in c.get("/").text
    r = c.get("/moi")
    assert "<b>Grommash</b>" in r.text and 'title="détecté par l&#39;addon">addon</span>' in r.text


def test_reclamer_et_retirer_un_personnage(discord_client):
    c, connecter = discord_client
    envoyer(c, LUA2)
    connecter(nick="Gael")
    r = c.get("/moi")
    assert 'name="nom" value="Zuljin"' in r.text and 'name="nom" value="Mok"' in r.text
    r = c.post("/moi", data={"action": "reclamer", "nom": "Zuljin"})
    assert "Zuljin est associé" in r.text and 'type="submit" name="nom" value="Zuljin"' not in r.text
    assert 'aria-label="Retirer Zuljin"' in r.text
    assert '@Gael</a>' in c.get("/").text
    # Un autre joueur ne peut pas le prendre
    c.get("/deconnexion")
    connecter("43", nick="Thrall")
    c.post("/moi", data={"action": "creer", "pseudo": "Thrall"})
    assert c.post("/moi", data={"action": "reclamer", "nom": "Zuljin"}).status_code == 400
    assert c.post("/moi", data={"action": "reclamer", "nom": "Inconnu"}).status_code == 400
    c.get("/deconnexion")
    connecter(nick="Gael")
    r = c.post("/moi", data={"action": "retirer", "nom": "Zuljin"})
    assert "Personnage retiré" in r.text and 'type="submit" name="nom" value="Zuljin"' in r.text


def test_l_addon_l_emporte_sur_une_saisie_manuelle(discord_client):
    c, connecter = discord_client
    envoyer(c, LUA2)
    connecter("43", nick="Thrall")
    c.post("/moi", data={"action": "creer", "pseudo": "Thrall"})
    c.post("/moi", data={"action": "reclamer", "nom": "Grommash"})
    envoyer(c, LUA_MES_PERSOS)  # le fichier du compte WoW de Gael fait foi
    d = {p["nom"]: p for p in c.get("/export.json?token=tok").json["proprietaires"]}
    assert d["Grommash"]["pseudo"] == "Gael" and d["Grommash"]["source"] == "addon"


def test_perso_au_nom_du_pseudo_et_admin(discord_client, tmp_path):
    c, connecter = discord_client
    (tmp_path / "cles.txt").write_text("Gael:abc123\nMok:cle-mok\n", encoding="utf-8")
    envoyer(c, LUA_MES_PERSOS)
    assert '<span class="joueur">@Mok</span>' in c.get("/").text  # même nom que le pseudo
    connecter(ADMIN_ID, nick="Admin")
    r = c.get("/admin")
    assert "Reroll" in r.text and "détecté par l&#39;addon" in r.text
    c.post("/admin", data={"action": "dissocier", "nom": "Grommash"})
    tableau = c.get("/admin").text.split("Personnages ↔ joueurs")[1].split("</table>")[0]
    assert '<td class="nom">Grommash</td>' not in tableau and "même nom que le pseudo" in tableau  # Mok
    # La remise à zéro vide aussi les associations, mais garde les comptes et la session
    r = c.post("/admin", data={"action": "reinitialiser"})
    assert "1 associations" in r.text
    d = c.get("/export.json?token=tok").json
    assert d["proprietaires"] == d["personnages"] == []
    assert "Mon compte</a>" in c.get("/").text and "Gael" in c.get("/admin").text


def test_admin_associe_et_l_emporte_sur_l_addon(discord_client):
    c, connecter = discord_client
    envoyer(c, LUA_MES_PERSOS)  # Grommash → Gael (addon)
    connecter(ADMIN_ID, nick="Admin")
    r = c.get("/admin")
    assert 'value="Grommash"' in r.text and '<option selected>Gael</option>' in r.text
    assert c.post("/admin", data={"action": "associer", "nom": "Inconnu", "pseudo": "Gael"}).status_code == 200
    assert "Personnage ou joueur inconnu" in c.post(
        "/admin", data={"action": "associer", "nom": "Grommash", "pseudo": "Personne"}).text
    c.post("/moi", data={"action": "creer", "pseudo": "Thrall"})  # l'admin se crée un joueur
    r = c.post("/admin", data={"action": "associer", "nom": "Grommash", "pseudo": "Thrall"})
    assert "Grommash est associé à Thrall" in r.text and "attribué par un officier" in r.text
    envoyer(c, LUA_MES_PERSOS)  # l'addon ne remplace pas un choix d'officier
    d = {p["nom"]: p for p in c.get("/export.json?token=tok").json["proprietaires"]}
    assert (d["Grommash"]["pseudo"], d["Grommash"]["source"]) == ("Thrall", "admin")
    assert d["Reroll"]["pseudo"] == "Gael"
    r = c.get("/moi")  # côté joueur : pas de bouton Retirer sur un choix d'officier
    assert 'title="attribué par un officier">officier</span>' in r.text and 'aria-label="Retirer Grommash"' not in r.text


def test_admin_retire_une_association_avec_aucun(discord_client):
    c, connecter = discord_client
    envoyer(c, LUA_MES_PERSOS)
    connecter(ADMIN_ID, nick="Admin")
    r = c.post("/admin", data={"action": "associer", "nom": "Grommash", "pseudo": ""})
    assert "Grommash n&#39;est plus associé" in r.text
    assert "Grommash" not in {p["nom"] for p in c.get("/export.json?token=tok").json["proprietaires"]}


def test_emblemes_de_classe(client):
    g = client.application.view_functions["index"].__globals__
    assert 'stroke' not in g["embleme"]("Guerrier") and "<svg" in g["embleme"]("Chamane")
    assert g["embleme"]("Guerrier") != g["embleme"]("Mage") and "<svg" in g["embleme"]("Inconnue")


def test_meilleurs_contributeurs(discord_client, tmp_path):
    c, connecter = discord_client
    (tmp_path / "cles.txt").write_text("Gael:abc123\nThrall:t\nMok:m\nJaina:j\n", encoding="utf-8")
    assert "Meilleurs contributeurs" not in c.get("/").text
    envoyer(c, LUA1)                     # Gael : 2 montées
    envoyer(c, LUA2, "t")                # Thrall : 3 montées
    envoyer(c, LUA2, "m")                # Mok : 0 (déjà connu)
    envoyer(c, LUA2.replace("60", "60").replace("Mok;Tauren;Paladin;5", "Mok;Tauren;Paladin;6"), "j")  # Jaina : 1
    c.get("/collecter?token=tok")        # la collecte serveur ne compte pas
    html = c.get("/").text.split("Meilleurs contributeurs")[1].split("</section>")[0]
    assert html.index("Thrall") < html.index("Gael") < html.index("Jaina") and "Mok" not in html
    assert "<b class=\"num\">3</b> montées de niveau signalées · 1 envoi" in html
    connecter(ADMIN_ID, nick="Admin")
    admin = c.get("/admin").text.split("Contributeurs")[1].split("</table>")[0]
    assert all(n in admin for n in ("Thrall", "Gael", "Jaina", "Mok")) and "serveur" not in admin


# ---------- Courbe de progression ----------
def test_courbe_avant_le_lancement(client):
    envoyer(client, LUA2)
    html = client.get("/").text
    assert 'id="donnees-courbe"' in html and "La courbe démarre le 4 novembre" in html


def test_courbe_series_quotidiennes(discord_client, monkeypatch):
    import datetime as dt, json
    c, connecter = discord_client
    g = c.application.view_functions["index"].__globals__
    with g["db"]() as con:  # historique fabriqué : Grommash monte, Zuljin arrive le 6/11
        con.executemany("INSERT INTO historique VALUES(?,?,?)", [
            ("Grommash", 5, "2026-11-04T10:00:00"), ("Grommash", 12, "2026-11-05T22:00:00"),
            ("Grommash", 20, "2026-11-07T08:00:00"), ("Zuljin", 8, "2026-11-06T12:00:00")])
        con.executemany("INSERT INTO personnages(nom, race, classe, niveau, maj) VALUES(?,?,?,?,?)", [
            ("Grommash", "Orc", "Guerrier", 20, "2026-11-07T08:00:00"), ("Zuljin", "Troll", "Chaman", 8, "2026-11-06T12:00:00")])
        monkeypatch.setitem(g, "aujourdhui", lambda: dt.date(2026, 11, 7))
        d = g["courbe"](con, ["Grommash"])
    assert d["jours"] == ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"] and d["fin"] == "2027-01-01"
    assert d["n"] == [1, 1, 2, 2] and d["moyenne"] == [5, 12, 10, 14] and d["max"][3] == 20
    assert d["mediane"][2] == 10 and d["q1"][3] == 11 and d["q3"][3] == 17
    assert d["persos"][0]["nom"] == "Grommash" and d["persos"][0]["niveaux"] == [5, 12, 12, 20]
    # Sur la page : les persos du joueur connecté sont dans les données de la courbe
    connecter(nick="Gael")
    c.post("/moi", data={"action": "reclamer", "nom": "Zuljin"})
    brut = c.get("/").text.split('id="donnees-courbe">')[1].split("</script>")[0]
    assert [p["nom"] for p in json.loads(brut)["persos"]] == ["Zuljin"]


def test_courbe_s_allonge_apres_le_1er_janvier(client, monkeypatch):
    import datetime as dt
    g = client.application.view_functions["index"].__globals__
    monkeypatch.setitem(g, "aujourdhui", lambda: dt.date(2027, 1, 15))
    with g["db"]() as con:
        d = g["courbe"](con)
    assert d["fin"] == "2027-01-15" and len(d["jours"]) == 73


# ---------- Personnages exclus (mules, banques) ----------
def test_exclure_et_reintegrer_un_personnage(discord_client, monkeypatch):
    c, connecter = discord_client
    messages, _ = capturer(monkeypatch, c)
    envoyer(c, LUA2)  # Grommash 60, Zuljin 21, Mok 5
    connecter(ADMIN_ID, nick="Admin")
    r = c.post("/admin", data={"action": "desactiver", "nom": "Grommash", "motif": "banque"})
    assert "Grommash est exclu de la progression (banque)" in r.text and '<span class="puce exclu">Banque</span>' in r.text
    assert c.post("/admin", data={"action": "desactiver", "nom": "Inconnu", "motif": "mule"}).status_code == 200
    accueil = c.get("/").text
    classement = accueil.split("<tbody>")[1]
    assert "Grommash" not in classement and "Zuljin" in classement
    d = c.get("/export.json?token=tok").json
    assert {e["nom"] for e in d["exploits"]} == {"Zuljin"} and [e["rang"] for e in d["exploits"] if e["palier"] == 10] == [1]
    assert d["inactifs"][0]["nom"] == "Grommash" and d["personnages"][0]["niveau"] == 60  # niveaux toujours suivis
    # Un exclu ne déclenche plus d'annonce
    messages.clear()
    envoyer(c, LUA2.replace("Mok;Tauren;Paladin;5", "Mok;Tauren;Paladin;6").replace("Grommash;Orc;Guerrier;60", "Grommash;Orc;Guerrier;60"))
    assert not any("Grommash" in m for m in messages)
    # Réintégration : paliers rendus selon la date réelle, sans annonce
    messages.clear()
    r = c.post("/admin", data={"action": "reactiver", "nom": "Grommash"})
    assert "Grommash est réintégré" in r.text and not messages
    d = c.get("/export.json?token=tok").json
    assert {e["palier"] for e in d["exploits"] if e["nom"] == "Grommash"} == {10, 20, 30, 40, 50, 60}
    assert d["inactifs"] == []


def test_exclus_hors_recap_et_vides_par_la_remise_a_zero(discord_client, monkeypatch):
    c, connecter = discord_client
    _, bruts = capturer(monkeypatch, c)
    envoyer(c, LUA2)
    connecter(ADMIN_ID, nick="Admin")
    c.post("/admin", data={"action": "desactiver", "nom": "Mok", "motif": "mule"})
    bruts.clear()
    c.get("/recap?token=tok")
    assert "Mok" not in bruts[0] and "2 membres" in bruts[0]
    c.post("/admin", data={"action": "reinitialiser"})
    assert c.get("/export.json?token=tok").json["inactifs"] == []


# ---------- API Blizzard (v1.9.0) ----------
RACES_API = {"races": [{"id": 2, "name": "Orc"}, {"id": 8, "name": "Troll"}, {"id": 6, "name": "Tauren"}]}
CLASSES_API = {"classes": [{"id": 1, "name": "Guerrier"}, {"id": 7, "name": "Chaman"}]}


def membre(nom, niveau, race=2, classe=1, royaume="firemaw", rang=1):
    return {"character": {"name": nom, "level": niveau, "realm": {"slug": royaume},
                          "playable_race": {"id": race}, "playable_class": {"id": classe}}, "rank": rang}


@pytest.fixture
def blizzard(client, monkeypatch):
    """API Blizzard active et simulée. Renvoie (client, état) : état["roster"] = membres,
    état["profils"] = {nom: (niveau, last_login ms)}, état["appels"] = chemins demandés."""
    g = client.application.view_functions["index"].__globals__
    for cle, val in {"BNET_ID": "id", "BNET_SECRET": "s", "BNET_ROYAUME": "Firemaw",
                     "BNET_GUILDE": "Quartz Forever"}.items():
        monkeypatch.setitem(g, cle, val)
    etat = {"roster": [], "profils": {}, "appels": [], "jetons": 0, "panne": False}

    def post(url, **kw):
        assert url == "https://oauth.battle.net/token" and kw["auth"] == ("id", "s")
        etat["jetons"] += 1
        return Reponse({"access_token": "t", "expires_in": 86399})

    def get(url, **kw):
        chemin = url.split("api.blizzard.com")[1]
        etat["appels"].append(chemin)
        assert kw["params"]["namespace"].endswith("-classic1x-eu")
        if etat["panne"]:
            return Reponse({}, 503)
        if chemin.endswith("/playable-race/index"):
            return Reponse(RACES_API)
        if chemin.endswith("/playable-class/index"):
            return Reponse(CLASSES_API)
        if chemin == "/data/wow/guild/firemaw/quartz-forever/roster":
            return Reponse({"members": etat["roster"]})
        nom = chemin.rsplit("/", 1)[1]
        for n, (niveau, ts) in etat["profils"].items():
            if n.lower() == nom:
                return Reponse({"name": n, "level": niveau, "last_login_timestamp": ts})
        return Reponse({}, 404)
    monkeypatch.setattr(g["requests"], "post", post)
    monkeypatch.setattr(g["requests"], "get", get)
    return client, etat


def test_api_inactive_par_defaut(client, monkeypatch):
    g = client.application.view_functions["index"].__globals__
    monkeypatch.setattr(g["requests"], "get", lambda *a, **k: pytest.fail("aucun appel attendu"))
    assert client.get("/collecter?token=tok").json == {"ok": True, "mises_a_jour": 0, "source": None}


def test_collecte_par_l_api(blizzard, monkeypatch):
    c, etat = blizzard
    messages, _ = capturer(monkeypatch, c)
    etat["roster"] = [membre("Grommash", 12), membre("Zuljin", 9, 8, 7)]
    r = c.get("/collecter?token=tok").json
    assert r == {"ok": True, "mises_a_jour": 2, "source": "blizzard"}
    persos = {p["nom"]: p for p in c.get("/export.json?token=tok").json["personnages"]}
    assert (persos["Grommash"]["race"], persos["Grommash"]["classe"], persos["Grommash"]["niveau"]) == ("Orc", "Guerrier", 12)
    assert persos["Zuljin"]["race"] == "Troll" and any("Grommash" in m and "10" in m for m in messages)
    # Rien n'a bougé : pas de profil demandé, jeton et index réutilisés
    etat["appels"].clear()
    assert c.get("/collecter?token=tok").json["mises_a_jour"] == 0
    assert etat["appels"] == ["/data/wow/guild/firemaw/quartz-forever/roster"] and etat["jetons"] == 1


def test_montee_datee_par_la_derniere_connexion(blizzard):
    c, etat = blizzard
    g = c.application.view_functions["index"].__globals__
    etat["roster"] = [membre("Grommash", 12)]
    c.get("/collecter?token=tok")
    vu = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    with g["db"]() as con:  # dernière collecte il y a une heure, Grommash encore 12
        con.execute("UPDATE personnages SET maj=?", (vu,))
    connexion = datetime.datetime.now().replace(microsecond=0) - datetime.timedelta(minutes=20)
    etat["roster"] = [membre("Grommash", 14)]
    etat["profils"] = {"Grommash": (14, int(connexion.timestamp()) * 1000)}
    c.get("/collecter?token=tok")
    assert etat["appels"][-1] == "/profile/wow/character/firemaw/grommash"
    with g["db"]() as con:
        dates = dict(con.execute("SELECT niveau, date FROM historique WHERE nom='Grommash'").fetchall())
    assert dates[14] == connexion.isoformat() and dates[12] <= dates[14]
    # Connexion antérieure à la dernière collecte (session en cours) : ignorée (date de réception)
    etat["roster"] = [membre("Grommash", 15)]
    etat["profils"] = {"Grommash": (15, int((connexion - datetime.timedelta(days=1)).timestamp()) * 1000)}
    c.get("/collecter?token=tok")
    with g["db"]() as con:
        d15 = con.execute("SELECT date FROM historique WHERE nom='Grommash' AND niveau=15").fetchone()[0]
    assert d15 > connexion.isoformat()


def test_homonymes_sur_royaumes_connectes(blizzard):
    c, etat = blizzard
    etat["roster"] = [membre("Mok", 30, royaume="gandling"), membre("Mok", 12)]
    c.get("/collecter?token=tok")
    assert c.get("/export.json?token=tok").json["personnages"][0]["niveau"] == 30
    assert "/profile/wow/character/gandling/mok" in etat["appels"]


def test_api_en_panne_repli_sur_le_fichier(blizzard, tmp_path, monkeypatch):
    c, etat = blizzard
    g = c.application.view_functions["index"].__globals__
    fichier = tmp_path / "GuildExport.lua"
    fichier.write_text(LUA1, encoding="utf-8")
    monkeypatch.setitem(g, "EXPORT", fichier)
    etat["panne"] = True
    assert c.get("/collecter?token=tok").json == {"ok": True, "mises_a_jour": 2, "source": "fichier"}


# ---------- Rangs de la guilde (v1.10.0) ----------
def admin(c):
    with c.session_transaction() as s:
        s["discord"] = {"id": ADMIN_ID, "nom": "Admin"}


def test_rangs_lus_dans_le_roster_et_nommes_dans_l_admin(blizzard):
    c, etat = blizzard
    assert "<th>Rang</th>" not in c.get("/").text          # aucun rang connu : pas de colonne
    etat["roster"] = [membre("Grommash", 12, rang=0), membre("Zuljin", 9, 8, 7, rang=3)]
    c.get("/collecter?token=tok")
    accueil = c.get("/").text
    assert "<th>Rang</th>" in accueil and "Rang 0" in accueil and "Rang 3" in accueil
    admin(c)
    page = c.get("/admin").text
    assert 'name="rang_0"' in page and 'name="rang_3"' in page
    r = c.post("/admin", data={"action": "rangs", "rang_0": "Chef de guerre", "rang_3": " ",
                               "nouveau_id": "5", "nouveau_nom": "Recrue"})
    assert "Noms des rangs enregistrés" in r.text
    accueil = c.get("/").text
    assert "Chef de guerre" in accueil and "Rang 3" in accueil
    assert c.get("/export.json?token=tok").json["rangs"] == [{"id": 0, "nom": "Chef de guerre"}, {"id": 5, "nom": "Recrue"}]
    # Un envoi d'addon (sans rang) ne l'efface pas ; la remise à zéro garde le référentiel
    envoyer(c, LUA2)
    assert {p["nom"]: p["rang"] for p in c.get("/export.json?token=tok").json["personnages"]}["Grommash"] == 0
    c.post("/admin", data={"action": "reinitialiser"})
    d = c.get("/export.json?token=tok").json
    assert d["personnages"] == [] and [r["nom"] for r in d["rangs"]] == ["Chef de guerre", "Recrue"]


def test_migration_colonne_rang(tmp_path, monkeypatch):
    import sqlite3
    base = tmp_path / "v19.db"
    with sqlite3.connect(base) as con:
        con.execute("CREATE TABLE personnages(nom TEXT PRIMARY KEY, race TEXT, classe TEXT, niveau INTEGER, maj TEXT)")
        con.execute("INSERT INTO personnages VALUES('Mok','Tauren','Paladin',5,'2026-10-30T10:00:00')")
    monkeypatch.setenv("GUILDE_DB", str(base))
    spec = importlib.util.spec_from_file_location("app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = mod.app.test_client()
    assert "Mok" in c.get("/").text and "<th>Rang</th>" not in c.get("/").text


def test_rangs_lus_dans_le_fichier_de_l_addon(client):
    lua = LUA2 + ('\nGuildExportMesPersos = {\n["Grommash"] = "1793450000",\n}'
                  '\nGuildExportRangs = {\n["Grommash"] = "0",\n["Zuljin"] = "4",\n["Inconnu"] = "2",\n}')
    assert envoyer(client, lua).status_code == 200
    rangs = {p["nom"]: p["rang"] for p in client.get("/export.json?token=tok").json["personnages"]}
    assert rangs == {"Grommash": 0, "Zuljin": 4, "Mok": None}
    assert "Rang 4" in client.get("/").text
