# Teste l'API Blizzard sur un personnage Classic Era.
# pip install requests ; identifiants à créer sur https://develop.battle.net
import os
import requests

CLIENT_ID = os.getenv("BNET_CLIENT_ID", "ton_client_id")
CLIENT_SECRET = os.getenv("BNET_CLIENT_SECRET", "ton_secret")
REGION = "eu"
NAMESPACE = "profile-classic1x-eu"   # Classic Era ; à remplacer par celui de Forever quand il existera
ROYAUME = "firemaw"                  # slug du royaume, en minuscules
PERSO = "nomdunperso"                # en minuscules

token = requests.post("https://oauth.battle.net/token",
                      data={"grant_type": "client_credentials"},
                      auth=(CLIENT_ID, CLIENT_SECRET)).json()["access_token"]

r = requests.get(
    f"https://{REGION}.api.blizzard.com/profile/wow/character/{ROYAUME}/{PERSO}",
    params={"namespace": NAMESPACE, "locale": "fr_FR"},
    headers={"Authorization": f"Bearer {token}"})

print(r.status_code)
if r.ok:
    d = r.json()
    print(d["name"], "-", d["race"]["name"], d["character_class"]["name"], "niveau", d["level"])
