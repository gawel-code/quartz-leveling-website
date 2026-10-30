"""Tests du serveur. Lancer : pip install flask requests pytest && pytest -q"""
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
    assert d["personnages"] == d["exploits"] == d["historique"] == d["envois"] == []


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
    assert "Pseudo sur le site : <b>Gael</b>" in r.text and 'value="abc123"' in r.text
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
    assert "BattleTag : <b>Gawel#2345</b> (lié à Discord)" in r.text and 'id="battletag"' not in r.text
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
    assert "Gaël#21456 <small>(saisi)</small>" in c.get("/admin").text
    c.get("/deconnexion")
    # Le BattleTag lu sur Discord prime ; la saisie est conservée en réserve
    connecter(nick="Gael", connexions=[{"type": "battlenet", "name": "Gael#1111"}])
    assert "Gael#1111</b> (lié à Discord)" in c.get("/moi").text
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
    assert "<b>Grommash</b><small>détecté par l&#39;addon</small>" in r.text


def test_reclamer_et_retirer_un_personnage(discord_client):
    c, connecter = discord_client
    envoyer(c, LUA2)
    connecter(nick="Gael")
    r = c.get("/moi")
    assert '<option>Zuljin</option>' in r.text and '<option>Mok</option>' in r.text
    r = c.post("/moi", data={"action": "reclamer", "nom": "Zuljin"})
    assert "Zuljin est associé" in r.text and '<option>Zuljin</option>' not in r.text
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
    assert "Personnage retiré" in r.text and '<option>Zuljin</option>' in r.text


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
    assert "Grommash" not in c.get("/admin").text.split("Personnages associés")[1].split("</table>")[0]
    # La remise à zéro de la progression garde les associations
    c.post("/admin", data={"action": "reinitialiser"})
    assert len(c.get("/export.json?token=tok").json["proprietaires"]) == 1
