# Génère les clés personnelles des membres dans cles.txt (format Pseudo:clé).
# Usage : python tools/generer_cles.py cles.txt Pseudo1 Pseudo2 ...
#         python tools/generer_cles.py cles.txt --renouveler Pseudo   (clé perdue / vue)
# Les pseudos déjà présents sont ignorés ; seules les nouvelles clés sont affichées,
# prêtes à être envoyées en MP.
import secrets
import sys
from pathlib import Path


def generer(fichier, pseudos, renouveler=False):
    """Ajoute (ou remplace si renouveler) une clé par pseudo. Renvoie {pseudo: clé} des clés créées."""
    fichier = Path(fichier)
    lignes = fichier.read_text(encoding="utf-8").splitlines() if fichier.exists() else []
    connus = {l.split(":", 1)[0].strip().lower(): i for i, l in enumerate(lignes)
              if l.strip() and not l.lstrip().startswith("#") and ":" in l}
    cles_prises = {l.split(":", 1)[1].strip() for l in lignes if ":" in l}
    nouvelles, deja_vus = {}, set()
    for pseudo in pseudos:
        pseudo = pseudo.strip()
        if not pseudo or ":" in pseudo or pseudo.lower() in deja_vus:
            continue
        deja_vus.add(pseudo.lower())
        i = connus.get(pseudo.lower())
        if i is not None and not renouveler:
            continue
        cle = secrets.token_urlsafe(18)
        while cle in cles_prises:
            cle = secrets.token_urlsafe(18)
        cles_prises.add(cle)
        if i is None:
            connus[pseudo.lower()] = len(lignes)
            lignes.append(f"{pseudo}:{cle}")
        else:
            lignes[i] = f"{pseudo}:{cle}"
        nouvelles[pseudo] = cle
    if not lignes or not lignes[0].startswith("#"):
        lignes.insert(0, "# Pseudo:clé — une ligne par membre, relu à chaque envoi")
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return nouvelles


if __name__ == "__main__":
    args = sys.argv[1:]
    renouveler = "--renouveler" in args
    args = [a for a in args if a != "--renouveler"]
    if len(args) < 2:
        sys.exit("Usage : python tools/generer_cles.py cles.txt Pseudo1 Pseudo2 ... [--renouveler]")
    for pseudo, cle in generer(args[0], args[1:], renouveler).items():
        print(f"{pseudo}:{cle}")
