# Teste l'API Blizzard sur Classic Era, en préparation de lire_api_blizzard() pour Forever.
# Aucune dépendance (bibliothèque standard). Identifiants à créer sur https://develop.battle.net,
# passés par les variables d'environnement BNET_CLIENT_ID et BNET_CLIENT_SECRET.
#
#   python3 tools/verifier_api_blizzard.py --royaumes
#   python3 tools/verifier_api_blizzard.py --royaume firemaw --guilde "Nom de guilde"
#   python3 tools/verifier_api_blizzard.py --royaume firemaw --perso Nomduperso
#
# Espaces de noms : profile-<jeu>-<région> (persos, guildes), static-… (races, classes),
# dynamic-… (royaumes). Classic Era = classic1x ; à remplacer par celui de Forever.
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

LOCALE = "fr_FR"


def slug(texte):
    return texte.strip().lower().replace("'", "").replace(" ", "-")


class Api:
    def __init__(self, region, jeu):
        self.region, self.jeu = region, jeu
        cid, secret = os.getenv("BNET_CLIENT_ID"), os.getenv("BNET_CLIENT_SECRET")
        if not cid or not secret:
            sys.exit("BNET_CLIENT_ID et BNET_CLIENT_SECRET doivent être définis.")
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request("https://oauth.battle.net/token",
                                     data=b"grant_type=client_credentials",
                                     headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                self.jeton = json.load(r)["access_token"]
        except urllib.error.HTTPError as e:
            sys.exit(f"Jeton refusé ({e.code}) : identifiants invalides ? {e.read()[:200]!r}")
        print("✓ jeton obtenu")

    def get(self, chemin, espace):
        params = urllib.parse.urlencode({"namespace": f"{espace}-{self.jeu}-{self.region}",
                                         "locale": LOCALE})
        url = f"https://{self.region}.api.blizzard.com{urllib.parse.quote(chemin)}?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.jeton}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, None


def noms(api, type_):
    """{id: nom français} des races ou des classes jouables."""
    code, d = api.get(f"/data/wow/playable-{type_}/index", "static")
    if code != 200:
        print(f"✗ index playable-{type_} : {code}")
        return {}
    cle = "races" if type_ == "race" else "classes"
    res = {x["id"]: x["name"] for x in d[cle]}
    print(f"✓ {len(res)} {cle} : {', '.join(sorted(res.values()))}")
    return res


def royaumes(api):
    code, d = api.get("/data/wow/realm/index", "dynamic")
    if code != 200:
        sys.exit(f"✗ liste des royaumes : {code}")
    for r in sorted(d["realms"], key=lambda r: r["slug"]):
        print(f"  {r['slug']:<28} {r['name']}")


def guilde(api, royaume, nom, races, classes):
    code, d = api.get(f"/data/wow/guild/{royaume}/{slug(nom)}/roster", "profile")
    if code != 200:
        print(f"✗ roster de {nom} sur {royaume} : {code}")
        return
    membres = d.get("members", [])
    print(f"✓ roster : {len(membres)} membres")
    persos = []
    for m in membres:
        c = m["character"]
        race = races.get(c.get("playable_race", {}).get("id"), "?")
        classe = classes.get(c.get("playable_class", {}).get("id"), "?")
        persos.append((c["name"], race, classe, c.get("level", 0)))
    persos.sort(key=lambda p: -p[3])
    # Même forme que analyser_export() : ce que lire_api_blizzard() devra renvoyer.
    for p in persos[:15]:
        print("  " + ";".join(map(str, p)))
    if len(persos) > 15:
        print(f"  … et {len(persos) - 15} autres")
    print("  champs d'un membre :", json.dumps(membres[0], ensure_ascii=False)[:400] if membres else "—")


def perso(api, royaume, nom):
    code, d = api.get(f"/profile/wow/character/{royaume}/{nom.lower()}", "profile")
    if code != 200:
        print(f"✗ profil de {nom} : {code} (404 = inconnu, ou pas joué depuis longtemps)")
        return
    print(f"✓ {d['name']} — {d['race']['name']} {d['character_class']['name']} niveau {d['level']}"
          f", guilde : {d.get('guild', {}).get('name', '—')}"
          f", dernière connexion (ms) : {d.get('last_login_timestamp', '—')}")


def main():
    p = argparse.ArgumentParser(description="Essais de l'API Blizzard (Classic Era par défaut).")
    p.add_argument("--region", default="eu")
    p.add_argument("--jeu", default="classic1x", help="classic1x = Classic Era")
    p.add_argument("--royaume", default="firemaw", help="slug du royaume")
    p.add_argument("--guilde", help="nom de la guilde (converti en slug)")
    p.add_argument("--perso", help="nom d'un personnage")
    p.add_argument("--royaumes", action="store_true", help="liste les royaumes et s'arrête")
    a = p.parse_args()

    api = Api(a.region, a.jeu)
    if a.royaumes:
        royaumes(api)
        return
    races, classes = noms(api, "race"), noms(api, "class")
    if a.guilde:
        guilde(api, a.royaume, a.guilde, races, classes)
    if a.perso:
        perso(api, a.royaume, a.perso)
    if not a.guilde and not a.perso:
        print("Rien d'autre à tester : ajoute --guilde ou --perso (ou --royaumes).")


if __name__ == "__main__":
    main()
