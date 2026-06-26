"""
Script pour retrouver et afficher l'image d'une intersection analysée.
Lancer avec : python voir_image.py
"""

import os
from pathlib import Path

DOSSIER_OUTPUT = Path(__file__).parent / "data" / "output"


def trouver_image(lat: float, lon: float) -> list[str]:
    pattern = f"{lat:.5f}_{lon:.5f}.jpg"
    resultats = []
    for dossier in DOSSIER_OUTPUT.glob("images_*/"):
        for img in dossier.iterdir():
            if pattern in img.name:
                resultats.append(str(img))
    return resultats


if __name__ == "__main__":
    print("=== Recherche d'image d'intersection ===\n")

    try:
        lat = float(input("Latitude  : ").strip())
        lon = float(input("Longitude : ").strip())
    except ValueError:
        print("Coordonnées invalides, entrez des nombres (ex: 48.85820)")
        exit(1)

    images = trouver_image(lat, lon)

    if not images:
        print(f"\nAucune image trouvée pour ({lat:.5f}, {lon:.5f}).")
        print("Vérifiez que les coordonnées sont exactement celles du fichier Excel (5 décimales).")
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
