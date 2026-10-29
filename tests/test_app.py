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
    spec = importlib.util.spec_from_file_location("app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app.test_client()


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
    messages = []
    monkeypatch.setitem(client.application.view_functions["index"].__globals__, "discord", messages.append)

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
    messages = []
    g = client.application.view_functions["index"].__globals__
    monkeypatch.setitem(g, "discord", messages.append)
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
