# Teste l'API Blizzard sur Classic Era, en préparation de lire_api_blizzard() pour Forever.
# Aucune dépendance (bibliothèque standard). Identifiants à créer sur https://develop.battle.net,
# passés par les variables d'environnement BNET_CLIENT_ID et BNET_CLIENT_SECRET.
#
#   python3 tools/verifier_api_blizzard.py --royaumes
#   python3 tools/verifier_api_blizzard.py --royaume firemaw --guilde "Nom de guilde"
#   python3 tools/verifier_api_blizzard.py --royaume firemaw --perso Nomduperso
#   python3 tools/verifier_api_blizzard.py --jeu forever --royaumes
#   python3 tools/verifier_api_blizzard.py --jeu forever --guilde "Quartz Forever" --perso gawel-zugzug
#   python3 tools/verifier_api_blizzard.py --jeu forever --compte [--perso Gawel]
#
# --compte : connexion Battle.net (OAuth « authorization code », scope wow.profile) dans le
# navigateur, puis /profile/user/wow : liste des persos du compte avec leurs liens (character,
# protected_character), suivis pour voir ce que l'API répond (profil, royaume, guilde, roster).
# Prérequis : ajouter http://localhost:8765/ aux « Redirect URLs » du client sur develop.battle.net
# (--port pour en changer). Réponses brutes enregistrées dans compte-<jeu>.json (données
# personnelles : ne pas commiter). Le jeton utilisateur n'est ni affiché ni enregistré.
#
# Espaces de noms : profile-<jeu>-<région> (persos, guildes), static-… (races, classes),
# dynamic-… (royaumes). Classic Era = classic1x. Forever (vérifié le 03/11/2026) : profile-forever-eu
# et dynamic-forever-eu, mais le statique n'existe qu'avec la version du jeu :
# static-1.60.1_70399-forever-eu (static-forever-eu → 403). --version-static la fixe ; le roster
# et le profil donnent la version courante dans leurs liens playable_race / playable_class.
import argparse
import base64
import http.server
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

LOCALE = "fr_FR"
VERSIONS = {"forever": "1.60.1_70399"}  # version statique par défaut (03/11/2026)


def slug(texte):
    return texte.strip().lower().replace("'", "").replace(" ", "-")


class Api:
    def __init__(self, region, jeu, version_static=""):
        self.region, self.jeu, self.version_static = region, jeu, version_static
        self.cid, self.secret = os.getenv("BNET_CLIENT_ID"), os.getenv("BNET_CLIENT_SECRET")
        if not self.cid or not self.secret:
            sys.exit("BNET_CLIENT_ID et BNET_CLIENT_SECRET doivent être définis.")
        self.jeton = self.demander_jeton({"grant_type": "client_credentials"})
        print("✓ jeton obtenu")

    def demander_jeton(self, donnees):
        auth = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        req = urllib.request.Request("https://oauth.battle.net/token",
                                     data=urllib.parse.urlencode(donnees).encode(),
                                     headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)["access_token"]
        except urllib.error.HTTPError as e:
            sys.exit(f"Jeton refusé ({e.code}) : {e.read()[:200]!r}")

    def espace(self, espace):
        if espace == "static" and self.version_static:
            return f"static-{self.version_static}-{self.jeu}-{self.region}"
        return f"{espace}-{self.jeu}-{self.region}"

    def get(self, chemin, espace, jeton=None):
        params = urllib.parse.urlencode({"namespace": self.espace(espace), "locale": LOCALE})
        return self.ouvrir(f"https://{self.region}.api.blizzard.com{urllib.parse.quote(chemin)}?{params}",
                           jeton)[:2]

    def ouvrir(self, url, jeton=None):
        """GET d'une URL complète (lien href de l'API, locale ajoutée) → (code, JSON ou None, texte brut)."""
        if "locale=" not in url:
            url += ("&" if "?" in url else "?") + f"locale={LOCALE}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {jeton or self.jeton}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                brut = r.read().decode("utf-8", "replace")
                return r.status, json.loads(brut), brut
        except urllib.error.HTTPError as e:
            return e.code, None, e.read().decode("utf-8", "replace")


def noms(api, type_):
    """{id: nom français} des races ou des classes jouables."""
    code, d = api.get(f"/data/wow/playable-{type_}/index", "static")
    if code != 200:
        print(f"✗ index playable-{type_} ({api.espace('static')}) : {code}"
              + (" — essaie --version-static" if code == 403 and not api.version_static else ""))
        return {}
    cle = "races" if type_ == "race" else "classes"
    res = {x["id"]: x["name"] for x in d[cle]}
    print(f"✓ {len(res)} {cle} : {', '.join(sorted(res.values()))}")
    return res


def version_lue(d):
    """Version statique citée dans les liens d'un roster ou d'un profil ("" si aucune)."""
    trouve = re.search(r"namespace=static-(\d[^\"&]*?)-[a-z0-9]+-[a-z]{2}\b", json.dumps(d))
    return trouve.group(1) if trouve else ""


def royaumes(api):
    code, d = api.get("/data/wow/realm/index", "dynamic")
    if code != 200:
        sys.exit(f"✗ liste des royaumes ({api.espace('dynamic')}) : {code}")
    print(f"✓ {len(d['realms'])} royaumes ({api.espace('dynamic')})")
    for r in sorted(d["realms"], key=lambda r: r["slug"]):
        print(f"  {r['slug']:<32} {r['name'] or '(sans nom)'}")


def guilde(api, royaume, nom, races, classes):
    # Forever : guilde sans royaume (/data/wow/guild/quartz-forever/roster), persos avec surname
    code, d = api.get("/data/wow/guild/" + (f"{royaume}/" if royaume else "") + f"{slug(nom)}/roster", "profile")
    if code != 200:
        print(f"✗ roster de {nom} sur {royaume} : {code}")
        return
    membres = d.get("members", [])
    print(f"✓ roster : {len(membres)} membres")
    version = version_lue(d)
    if version and version != api.version_static:
        print(f"  ! version statique du roster : {version} (utilisée : {api.version_static or 'aucune'})")
    persos = []
    for m in membres:
        c = m["character"]
        race = races.get(c.get("playable_race", {}).get("id"), "?")
        classe = classes.get(c.get("playable_class", {}).get("id"), "?")
        nom_perso = f"{c['name']}-{c['surname']}" if c.get("surname") else c["name"]  # comme identite()
        persos.append((nom_perso, race, classe, c.get("level", 0)))
    persos.sort(key=lambda p: -p[3])
    # Même forme que analyser_export() : ce que lire_api_blizzard() devra renvoyer.
    for p in persos[:15]:
        print("  " + ";".join(map(str, p)))
    if len(persos) > 15:
        print(f"  … et {len(persos) - 15} autres")
    print("  champs d'un membre :", json.dumps(membres[0], ensure_ascii=False)[:400] if membres else "—")


def perso(api, royaume, nom):
    # Forever : --perso gawel-zugzug (slug nom-surname), sans royaume
    code, d = api.get("/profile/wow/character/" + (f"{royaume}/" if royaume else "") + nom.lower(), "profile")
    if code != 200:
        print(f"✗ profil de {nom} : {code} (404 = inconnu, ou pas joué depuis longtemps)")
        return
    if version_lue(d):
        print(f"  version statique du profil : {version_lue(d)}")
    print(f"✓ {d['name']} — {d['race']['name']} {d['character_class']['name']} niveau {d['level']}"
          f", guilde : {d.get('guild', {}).get('name', '—')}"
          f", dernière connexion (ms) : {d.get('last_login_timestamp', '—')}")


def jeton_utilisateur(api, port):
    """OAuth « authorization code » (scope wow.profile) : ouvre le navigateur, attend le retour sur
    http://localhost:<port>/, échange le code. Le jeton reste en mémoire."""
    redirection = f"http://localhost:{port}/"
    etat = secrets.token_urlsafe(16)
    url = "https://oauth.battle.net/authorize?" + urllib.parse.urlencode({
        "client_id": api.cid, "redirect_uri": redirection, "response_type": "code",
        "scope": "wow.profile", "state": etat})
    recu = {}

    class Retour(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if "code" not in q and "error" not in q:
                self.send_response(404)  # favicon.ico, etc.
                self.end_headers()
                return
            recu.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>Connexion reçue, tu peux fermer cet onglet.</p>".encode())

        def log_message(self, *args):
            pass

    try:
        serveur = http.server.HTTPServer(("127.0.0.1", port), Retour)
    except OSError as e:
        sys.exit(f"✗ port {port} indisponible ({e}) : essaie --port")
    print(f"Connexion Battle.net dans le navigateur (sinon ouvre ce lien) :\n  {url}")
    print(f"  (adresse de retour attendue sur develop.battle.net : {redirection})")
    webbrowser.open(url)
    with serveur:
        while not recu:
            serveur.handle_request()
    if "error" in recu:
        sys.exit(f"✗ connexion refusée : {recu['error']} {recu.get('error_description', '')}"
                 " (adresse de retour non déclarée sur develop.battle.net ?)")
    if recu.get("state") != etat:
        sys.exit("✗ state inattendu : réponse ignorée")
    jeton = api.demander_jeton({"grant_type": "authorization_code", "code": recu["code"],
                                "redirect_uri": redirection})
    print("✓ jeton utilisateur obtenu (scope wow.profile)")
    return jeton


def compte(api, port, filtre, sortie):
    """Persos du compte (/profile/user/wow) et ce que répondent leurs liens."""
    jeton = jeton_utilisateur(api, port)
    brut = {}

    def suivre(url, avec_jeton_utilisateur=False):
        code, d, texte = api.ouvrir(url, jeton if avec_jeton_utilisateur else None)
        brut[url] = {"code": code, "reponse": d if d is not None else texte[:500]}
        return code, d, texte

    url = (f"https://{api.region}.api.blizzard.com/profile/user/wow?"
           + urllib.parse.urlencode({"namespace": api.espace("profile")}))
    code, d, texte = suivre(url, True)
    if code != 200:
        print(f"✗ /profile/user/wow ({api.espace('profile')}) : {code} {texte[:200]}")
    else:
        persos = [(c, a.get("id")) for a in d.get("wow_accounts", []) for c in a.get("characters", [])]
        print(f"✓ /profile/user/wow : {len(d.get('wow_accounts', []))} compte(s) WoW, {len(persos)} perso(s)")
        if version_lue(d):
            print(f"  version statique citée : {version_lue(d)}")
        for c, id_compte in persos:
            royaume = c.get("realm") or {}
            print(f"\n• {c.get('name')} {c.get('surname') or ''}".rstrip()
                  + f" — niveau {c.get('level')}, {c.get('playable_race', {}).get('name', '?')}"
                  f" {c.get('playable_class', {}).get('name', '?')}, {c.get('faction', {}).get('name', '?')}"
                  f", royaume : {royaume.get('slug') or royaume.get('name') or '—'}"
                  f" (id {royaume.get('id', '—')}), id perso {c.get('id')}, compte {id_compte}")
            if filtre and filtre.lower() not in f"{c.get('name')} {c.get('surname') or ''}".lower():
                continue
            for cle, utilisateur in (("character", False), ("protected_character", True)):
                lien = (c.get(cle) or {}).get("href")
                if not lien:
                    print(f"  {cle} : pas de lien")
                    continue
                code, p, texte = suivre(lien, utilisateur)
                print(f"  {cle} → {code} {lien}")
                if p is None:
                    print(f"    {texte[:200] or '(réponse vide)'}")
                    continue
                print("    champs :", ", ".join(sorted(p)))
                for sous in ("character", "realm", "guild"):
                    if isinstance(p.get(sous), dict):
                        print(f"    {sous} :", json.dumps(p[sous], ensure_ascii=False)[:300])
                g = (p.get("guild") or {}).get("key", {}).get("href")
                if g:
                    for lien_g in (g, g.replace("?", "/roster?", 1)):
                        code_g, dg, texte_g = suivre(lien_g)
                        print(f"  guilde → {code_g} {lien_g}")
                        if dg and "members" in dg:
                            print(f"    {len(dg['members'])} membres ; 1er :",
                                  json.dumps(dg["members"][0], ensure_ascii=False)[:300])
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump(brut, f, ensure_ascii=False, indent=2)
    print(f"\nRéponses brutes : {os.path.abspath(sortie)} (données personnelles, ne pas commiter)")


def main():
    p = argparse.ArgumentParser(description="Essais de l'API Blizzard (Classic Era par défaut).")
    p.add_argument("--region", default="eu")
    p.add_argument("--jeu", default="classic1x", help="classic1x = Classic Era, forever = WoW Forever")
    p.add_argument("--version-static", help="version de l'espace statique (défaut forever : "
                   f"{VERSIONS['forever']}) ; vide = static-<jeu>-<région>")
    p.add_argument("--royaume", help="slug du royaume (défaut : firemaw ; aucun pour forever)")
    p.add_argument("--guilde", help="nom de la guilde (converti en slug)")
    p.add_argument("--perso", help="nom d'un personnage")
    p.add_argument("--royaumes", action="store_true", help="liste les royaumes et s'arrête")
    p.add_argument("--compte", action="store_true",
                   help="connexion Battle.net (wow.profile) : persos du compte et leurs liens")
    p.add_argument("--port", type=int, default=8765, help="port de retour OAuth de --compte")
    a = p.parse_args()

    version = VERSIONS.get(a.jeu, "") if a.version_static is None else a.version_static
    if a.royaume is None:
        a.royaume = "" if a.jeu == "forever" else "firemaw"
    api = Api(a.region, a.jeu, version)
    if a.compte:  # --perso filtre alors les persos dont on suit les liens
        compte(api, a.port, a.perso, f"compte-{a.jeu}.json")
        return
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
