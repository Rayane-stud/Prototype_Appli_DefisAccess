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

# FONCTION:  duplication_lignes ------------------------------------------------


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

    # ETAPE 3 : on duplique chaque ligne selon le nb de passage pieton(nb_traversees)
            
    repeat_idxs = df.index.repeat(df["nb_traversees"])
    df_developpe = df.loc[repeat_idxs].reset_index(drop=True)
            
            #df.index va cherhcer la liste des numeros des lignes fais lors de la trad en pandas
            # le .repeat() va faire repeter le numero d'index autant de fois que nb_traverses sur chaque ligne 
            #df.loc[repeat_idx] va chercher dans le tab les lignes correspondant a repeat_indxs
            #le probleme est que ce sont les index qui sont dupliqués donc .reset_index(drop=True) les remets proprements selon l'ordre des lignes, le drop=True jette les anciens indexs
    
    
    # ETAPE 4 : on numerote chaque passage pieton pour un meme croisement
    
    df_developpe["traversee"] = (
        df_developpe.groupby("Intersection", sort=False).cumcount() + 1
    )
            #df_developpe["traversee"] = (df_developpe.groupby("Intersection", sort=False) regroupe toutes les lignes qui ont le meme nom d'InterruptedError
            #sort=False permet que pandas ne retrie pas par ordre alphabetique
            #.cumcount numerote les lignes en partant de 0
            # le +1 car python commence a 0 alors que stata commence a 1

    # ETAPE 5 : on supprime nb_traversees qui ne sert plus
    df_developpe = df_developpe[["Equipe", "coordonnees", "Intersection", "Ordre", "traversee"]]
            # et on reordonne les colonnes comme dans le Stata et jette la colonne nb_traversees



    # ETAPE 6 : on trie comme dans le Stata
    
    df_developpe = df_developpe.sort_values(
        ["Ordre", "Intersection", "traversee"]
    ).reset_index(drop=True)

    return df_developpe
     
            #.sort_values(["Ordre", "Intersection", "traversee"]) pandas trie par ordre puis par intersection puis par traversee 
            #.reset_index(drop=True) apres le tri il remet les indexs dans l'ordre



#FONCTION : ajouter_colonnes_terrain() ------------------------------------------------------------------------------

def ajouter_col_notation_terrain(df):
    #ETAPE 1 : fais une copie du tableau pour ne pas modif l'original
    df_terrain = df.copy()

    # ETAPE 2 : on ajoute les 4 colonnes de saisie avec None comme valeur par defaut
    df_terrain["bande_de_guidage"] = None
    df_terrain["bande_eveil"] = None
    df_terrain["feu_parlant"] = None
    df_terrain["commentaire"] = None
    
    return df_terrain


#FONCTION : vers_xlsx() ----------------------------------------------------------------------------------------------

def vers_xlsx(df, id_equipe, dossier_sortie) :
    # ETAPE 1 : on construit le nom du fichier comme dans le Stata
    nom_fichier = f"Garches_Equipe_{id_equipe}_feuille.xlsx"
             # "Garches_Equipe_`i'_feuille.xlsx"

    # ETAPE 2 : on construit le chemin complet du fichier (nom+adresse)
    
    chemin_fichier = os.path.join(dossier_sortie, nom_fichier)
            # os.path.join : fonction Python qui colle un dossier et un nom de fichier ensemble pour former un chemin complet.
    
    
    # ETAPE 3 : on exporte le tableau en fichier XLSX
    
    df.to_excel(chemin_fichier, index=False)
            #df.to_excel(chemin_fichier) fonction qui exporte le tableau en fichier XLSX 
            # index=False : on n'exporte pas les numeros de lignes pandas (index)

          
    return chemin_fichier
    
    
#FONCTION : exporter_toutes_equipes() ----------------------------------------------------------------------------------------------------------


def exporter_toutes_equipes(dict_equipes, dossier_sortie):


    # ETAPE 1 : on cree une liste vide qui va accumuler les chemins de chaque fichier genere
    liste_chemins = []

    # ETAPE 2 : on boucle sur chaque equipe du dictionnaire

    for id_equipe, df_equipe in dict_equipes.items():
            #dict_equipes nom du dictionnaire
            #chaque equipe a une clé (1,2,3,...) et la veleur c'est le nom de l'equipe qui est dans le tab df_equipe1,dfequipe2
            # .items() permet de recup en meme temps la clé et la valeur


    # ETAPE 3 : on appelle vers_xlsx() pour chaque equipe
        chemin = vers_xlsx(df_equipe, id_equipe, dossier_sortie)
             # on cree un fichier XLSX pour chauqe et retourne son chemin


    # ETAPE 4 : on ajoute le chemin du fichier genere a la liste
        liste_chemins.append(chemin)

    # ETAPE 5 : on retourne la liste de tous les chemins
        # utile pour creer le ZIP Streamlit avec tous les fichiers
    return liste_chemins



#---- TESTS ------------------------------------------------------------------
# Lancer ce fichier directement pour tester : python export.py
 
if __name__ == "__main__":
 
    df_test = pd.DataFrame({
        "Equipe":        [1, 1, 2],
        "coordonnees":   ["48.838 2.186", "48.839 2.187", "48.840 2.188"],
        "Intersection":  ["Rue de la Paix / Rue du General", "Avenue Foch / Rue Victor Hugo", "Rue Pasteur / Avenue de la Gare"],
        "Ordre":         [1, 2, 1],
        "nb_traversees": [3, 2, 4]
    })
 
    print("=== TEST 1 : duplication_lignes ===")
    df_dup = duplication_lignes(df_test)
    print(df_dup)
    print(f"\n→ {len(df_test)} lignes au départ → {len(df_dup)} lignes après duplication")
 
    print("\n=== TEST 2 : ajouter_col_notation_terrain ===")
    df_terrain = ajouter_col_notation_terrain(df_dup)
    print(df_terrain.columns.tolist())
    print(f"→ {len(df_terrain.columns)} colonnes au total")
 
    print("\n=== TEST 3 : vers_xlsx + exporter_toutes_equipes ===")
    os.makedirs("test_export", exist_ok=True)
    dict_equipes = {
        1: df_terrain[df_terrain["Equipe"] == 1],
        2: df_terrain[df_terrain["Equipe"] == 2]
    }
    chemins = exporter_toutes_equipes(dict_equipes, "test_export")
    for c in chemins:
        print(f"→ Fichier généré : {c}")
 
    print("\n✅ Tous les tests passent !")