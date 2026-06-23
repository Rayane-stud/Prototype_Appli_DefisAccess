"""
Méthodologie :
    Récuperations des coordonnées GPS des intersections selectioner par l'algorithme.

    Récuperer les informations de la présence de passage piétons :
     - Premiere étape : Utiliser l'API overpass avec OpenStreetMap pour récupérer les passages piétons référencés
     - les attribués à leur intersection respective

     - Deuxieme étape : Récuperer les passages piétons des bases de données publiques disponibles
     - les attribués à leur intersection respective

     - Troisieme étape : Detecter a l'aide d'images (par exemple de 
                l'institut national de l'information géographique et forestiere) les passages piétons
                - ou alors les orthophotos disponibles 
            - pour cela : utiliser probablement DETECTRON2 pour detecter les passages piétons sur les images
     
     - Quatrieme étape :
     - Comparer ce que detecte DETECTRON2 et les recuperations de OpenStreetMap
     - Fusinoner les resultat pour avoir un resultat fiable pour chaque intersections
"""
"""
Avec BASE DE DONNEES Accidents :
Se mettre a jour 1 fois tout les mois pour ne pas avoir a repasser la liste a chaque fois.
Donc se creer une base traitée, des lieux de passages pietons a reutiliser (qui est donc mise a jour 1 fois par mois)

"""