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
