"""
FICHIER contenant la logique metier gerant l'automatisation PM : 

# BUT :
- automatisation pour trouver les PM et les mettres sur un excel

#LISTES FONCTIONS :
    - identifier_PM_llm() :
    # ROLE : Envoyer le nom de la ville au LLM et récupérer la liste
              des lieux importants (PM) structurée en JSON
    # ARGUMENTS : "ville" de type str (ex: "Garches")
    # REPONSE : list[dict] avec les clés "nom" et "type"
 
- geocoder_lieu() :
    # ROLE : Récupérer les coordonnées GPS d'un lieu via l'API Adresse
              du gouvernement français (gratuite, pas de clé nécessaire)
    # ARGUMENTS : "nom" de type str, "ville" de type str
    # REPONSE : dict avec les clés "latitude", "longitude", "adresse"
                ou None si le lieu n'est pas trouvé
 
- construire_dataframe_PM() :
    # ROLE : Assembler les résultats du LLM et du géocodage en un DataFrame
              propre et exportable en Excel
    # ARGUMENTS : "ville" de type str
    # REPONSE : pd.DataFrame avec les colonnes :
                nom | type | adresse | latitude | longitude | coordonnees

"""