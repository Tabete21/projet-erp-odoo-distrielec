# Implémentation d'un ERP intégré pour un distributeur (Odoo 19)

Projet personnel réalisé en octobre 2026 par **Aymane Tabete**, élève ingénieur en 3e année, filière Smart Supply Chain & Logistics, ENSIAS (Rabat).

**Résultat clé :** après diagnostic d'une politique de stock défaillante, le taux de service **OTIF passe de 17 % à 64 %** et les **livraisons fractionnées de 66 % à 8 %**, à demande client identique.

👉 **[Voir le tableau de bord interactif](https://Tabete21.github.io/projet-erp-odoo-distrielec/resultats/tableau_de_bord_apres.html)** · **[Voir la comparaison avant / après](https://Tabete21.github.io/projet-erp-odoo-distrielec/resultats/comparaison.html)**

![Tableau de bord](captures/tableau_de_bord.png)

---

## Le contexte

**DistriElec Maroc SARL** est un distributeur fictif de matériel électrique, modélisé de bout en bout dans Odoo 19 Community.

| Élément | Contenu |
| --- | --- |
| Sites | Entrepôt Casablanca (central) et Entrepôt Rabat (régional) |
| Articles | 6 articles en 3 familles : câbles, éclairage, appareillage |
| Clients | 8 clients répartis en 3 canaux : grossiste, installateur, détail |
| Fournisseurs | 2 fournisseurs, avec des délais de 7 et 14 jours |
| Modules Odoo | Ventes, Achats, Inventaire, Facturation |
| Outils | Docker, PostgreSQL, API XML-RPC, Python (pandas, Plotly) |

## Ce qui a été réalisé

1. **Fondations** : déploiement d'Odoo avec Docker, création de la société, des entrepôts et des emplacements de stockage, saisie des données de base (articles, clients, fournisseurs, conditions de paiement) et du stock initial.
2. **Ventes** : listes de prix par canal avec remises par quantité ; cycle complet devis → commande → livraison partielle → facture → paiement ; retour client et avoir.
3. **Achats** : réapprovisionnement automatique par règles min/max ; commande fournisseur, réception partielle, facture limitée aux quantités reçues (contrôle à trois voies).
4. **Entrepôt** : réception en 2 étapes (réception, rangement), livraison en 3 étapes (prélèvement, emballage, expédition), règles de rangement, zone de quarantaine, transfert entre entrepôts, inventaire tournant.
5. **Pilotage** : simulation de 4 mois d'activité via l'API d'Odoo, extraction des données, calcul de 12 indicateurs et tableau de bord interactif ; diagnostic et correction de la politique de réapprovisionnement.

![Livraison en 3 étapes](captures/livraison_3_etapes.png)

## Résultats : avant et après la nouvelle politique de stock

Les deux scénarios reçoivent **exactement les mêmes commandes clients** ; seule la politique d'achat change.

| Indicateur | Avant | Après |
| --- | --- | --- |
| Taux de service OTIF | 16,7 % | **63,6 %** |
| Taux de service des lignes | 41,6 % | 71,0 % |
| Commandes livrées en plusieurs fois | 66,1 % | **7,6 %** |
| Délai commande → livraison complète | 8,0 jours | 3,2 jours |
| Valeur moyenne du stock | 42 637 DH | 120 288 DH |
| Couverture de stock | 4,6 jours | 12,9 jours |

**Ce qui a changé :** révision des stocks chaque jour ouvré au lieu du lundi seulement, stock de sécurité calculé pour viser 95 % de service (z = 1,65), marge de 2 jours sur le délai fournisseur.

**Lecture :** les ruptures ont presque disparu. L'OTIF plafonne autour de 64 % à cause des retards de préparation simulés en entrepôt : le prochain levier n'est plus le stock, mais l'entrepôt ou une date promise plus réaliste. En contrepartie, le stock moyen est multiplié par 2,8 et le nombre de commandes fournisseurs passe de 32 à 78.

![Comparaison avant / après](captures/comparaison.png)

## Structure du dépôt

```
├── docker-compose.yml          Environnement Odoo 19 + PostgreSQL
├── requirements.txt            Bibliothèques Python
├── scripts/
│   ├── generer_historique.py   Simulation de l'activité via l'API XML-RPC
│   ├── extraire_donnees.py     Extraction des données d'Odoo en CSV
│   ├── analyse_kpi.py          Calcul des indicateurs et tableau de bord
│   └── comparer_scenarios.py   Comparaison des scénarios avant / après
├── resultats/                  Tableaux de bord HTML et indicateurs
└── captures/                   Captures d'écran d'Odoo
```

## Reproduire le projet

Prérequis : Docker Desktop et Python 3.10 ou plus.

```bash
docker compose up -d                      # Odoo sur http://localhost:8069
pip install -r requirements.txt

set ODOO_USER=ton.email@exemple.com       # sous Windows (export sous Linux / macOS)
set ODOO_PASSWORD=ton_mot_de_passe

python scripts/generer_historique.py apres distrielec_apres
python scripts/extraire_donnees.py distrielec_apres donnees_apres
python scripts/analyse_kpi.py donnees_apres apres
```

Les identifiants ne sont jamais écrits dans le code : ils sont lus dans les variables d'environnement, ou demandés au lancement.

## Limites

- Les données sont **simulées** : elles valident une démarche, pas une politique réelle.
- La variabilité de la demande est une hypothèse (coefficient de variation de 0,6) ; sur des données réelles, elle serait mesurée article par article.
- Le périmètre est volontairement réduit (une société, 6 articles) pour couvrir tous les processus de bout en bout.

## Contact

[LinkedIn](https://www.linkedin.com/in/AymaneTABETE)
