"""
FICHIER contenant la logique metier gerant l'etape 5 : 
# BUT :
- Génération des feuilles terrain XLSX pour que les benevoles puissent 
remplir les questionnaires

# LISTE DES FONCTIONS:
- duplication_lignes(): 
    #ROLE: Dupliquer les n- lignes (dans l'excel des benevoles) pour chaque intersection 
            par les n nb_traversees+ ajout d'une colonne traversées 
    #ARGUMENTS: "df" de type dataFrame
    #REPONSE: fichier pd.DataFrame avec duplication des lignes et avec une colonne qui indique le nombre de traversées

 - ajouter_colonnes_notation_terrain():
    # ROLE : Ajouter les colonnes de saisie vides que les benevoles 
              rempliront sur le terrain pour chaque passage
              (bande_de_guidage, bande_eveil, feu_parlant, commentaire)
    # ARGUMENTS : "df" de type DataFrame
    # REPONSE : pd.DataFrame avec 4 nouvelles colonnes vides de type NaN- 

- vers_xlsx():
    # ROLE : Exporter le DataFrame d'une equipe en fichier XLSX formate
              et lisible sur le terrain
    # ARGUMENTS : "df" de type DataFrame
                  "id_equipe" de type int (numero de l'equipe ex: 1, 2, 3...)
                  "dossier_sortie" de type str (chemin du dossier ou sauvegarder le fichier)
    # REPONSE : str (chemin complet du fichier XLSX genere)

- exporter_toutes_equipes():
    # ROLE : Appliquer vers_xlsx() pour chaque equipe du dictionnaire
              et recuperer la liste de tous les fichiers generes
              (utile pour creer le ZIP Streamlit)
    # ARGUMENTS : "dict_equipes" de type dict {int : DataFrame} 
                  (cle = id equipe, valeur = DataFrame de l equipe)
                  "dossier_sortie" de type str (chemin du dossier de sortie)
    # REPONSE : list[str] (liste des chemins de tous les fichiers XLSX generes)

"""
import os
import pandas as pd

# fonction duplication_lignes
def duplication_lignes(df):
    
        # ETAPE 1 : on verifie que la colonne nb_traversees existe
    if "nb_traversees" not in df.columns:
        raise ValueError("La colonne 'nb_traversees' est absente du DataFrame.")
    """
                    surement a supirmer
    # ETAPE 2 : on exclut les croisements avec la valeur aberrante 42
    # en Stata : "drop if nb_traversees==42"
    df_filtre = df[df["nb_traversees"] != 42].copy()
    """

    # ETAPE 3 : on duplique chaque ligne nb_traversees fois
    
    repeat_idxs = df.index.repeat(df["nb_traversees"])
    df_developpe = df.loc[repeat_idxs].reset_index(drop=True)

    # ETAPE 4 : on numerote chaque passage pour un meme croisement
    
    df_developpe["traversee"] = (
        df_developpe.groupby("Intersection", sort=False).cumcount() + 1
    )

    # ETAPE 5 : on supprime nb_traversees qui ne sert plus
    # et on reordonne les colonnes comme dans le Stata
    df_developpe = df_developpe[["Equipe", "coordonnees", "Intersection", "Ordre", "traversee"]]

    # ETAPE 6 : on trie comme dans le Stata
    # en Stata : "sort Ordre Intersection traversee"
    df_developpe = df_developpe.sort_values(
        ["Ordre", "Intersection", "traversee"]
    ).reset_index(drop=True)

    return df_developpe
     
    #vérifiction 
    import pandas as pd

# On cree un petit DataFrame qui simule ce que le vrai fichier contiendrait
df_test = pd.DataFrame({
    "Equipe":        [1, 1, 2],
    "coordonnees":   ["48.838 2.186", "48.839 2.187", "48.840 2.188"],
    "Intersection":  ["Rue de la Paix / Rue du General", "Avenue Foch / Rue Victor Hugo", "Rue Pasteur / Avenue de la Gare"],
    "Ordre":         [1, 2, 1],
    "nb_traversees": [4, 4, 4]
})

# On appelle la fonction
resultat = duplication_lignes(df_test)

# On affiche le resultat
print(resultat)


#fonction ajouter_colonnes_terrain():
def ajouter_colonnes_notation_terrain():
    return

#fonction vers_xlsx()
def vers_xlsx() :
    return

#fonction exporter_toutes_equipes()
def exporter_toutes_equipes():
    return 
