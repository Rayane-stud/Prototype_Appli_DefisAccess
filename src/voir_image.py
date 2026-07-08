"""
Script pour retrouver et afficher l'image d'une intersection analysée.
Lancer avec : python voir_image.py
"""

import os
from pathlib import Path

DOSSIER_OUTPUT = Path(__file__).parent.parent / "data" / "raw" / "images_pp"


def trouver_image(lat: float, lon: float, dossier: str | None = None) -> list[str]:
    """Cherche l'image annotée d'une intersection par ses coordonnées.

    Par défaut, cherche dans tous les dossiers "images_*/" jamais générés
    (utile en usage autonome, en ligne de commande). Si `dossier` est fourni,
    ne cherche QUE dedans — utile pour ne retrouver que l'image de la
    génération en cours, sans faire remonter les exécutions précédentes
    (une même intersection ré-analysée plusieurs fois par le passé aurait
    sinon une image par ancienne exécution).
    """
    pattern = f"{lat:.5f}_{lon:.5f}.jpg"
    dossiers = [Path(dossier)] if dossier else DOSSIER_OUTPUT.glob("images_*/")
    resultats = []
    for d in dossiers:
        d = Path(d)
        if not d.is_dir():
            continue
        for img in d.iterdir():
            if pattern in img.name:
                resultats.append(str(img))
    return resultats


def parser_coordonnees(saisie: str) -> tuple[float, float]:
    """Découpe une saisie du type '48.85820,2.19257' (aussi accepté avec un
    ';' ou juste un espace comme séparateur, ex: colonne 'coordonnees' des
    fiches Excel exportées) en (latitude, longitude)."""
    separateur = next((s for s in (",", ";") if s in saisie), None)
    morceaux = saisie.split(separateur) if separateur else saisie.split()
    if len(morceaux) != 2:
        raise ValueError(f"Format inattendu : '{saisie}' (attendu : 'latitude,longitude')")
    return float(morceaux[0].strip()), float(morceaux[1].strip())


if __name__ == "__main__":
    print("=== Recherche d'image d'intersection ===\n")
    print("Comment voulez-vous saisir la position ?")
    print("  1. Coordonnées combinées (ex: 48.85820,2.19257 — colonne 'coordonnees' de la fiche Excel)")
    print("  2. Latitude puis longitude séparément")

    mode = input("Choix (1/2) : ").strip()

    try:
        if mode == "1":
            lat, lon = parser_coordonnees(input("Coordonnées : ").strip())
        else:
            lat = float(input("Latitude  : ").strip())
            lon = float(input("Longitude : ").strip())
    except ValueError as e:
        print(f"Coordonnées invalides ({e}), entrez des nombres (ex: 48.85820)")
        exit(1)

    images = trouver_image(lat, lon)

    if not images:
        print(f"\nAucune image trouvée pour ({lat:.5f}, {lon:.5f}).")
        print(
            "Rappel : seule la méthode IA (YOLO) capture une image par intersection — "
            "les méthodes OSM, Accidents (CSV) ou OSM + Accidents n'en génèrent aucune. "
            "Si votre fiche vient de l'une de ces méthodes, c'est normal qu'il n'y ait rien ici."
        )
        exit(0)

    print(f"\n{len(images)} image(s) trouvée(s) :")
    for i, chemin in enumerate(images, 1):
        print(f"  {i}. {chemin}")

    # Si plusieurs images, demander laquelle ouvrir
    if len(images) == 1:
        choix = 1
    else:
        try:
            choix = int(input("\nQuelle image ouvrir ? (numéro) : ").strip())
        except ValueError:
            choix = 1

    chemin_choisi = images[choix - 1]
    print(f"\nOuverture de : {chemin_choisi}")
    os.startfile(chemin_choisi)
