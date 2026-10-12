"""
Étape 2 du Jour 5 : extraction des données d'Odoo vers des fichiers CSV.

Le script lit, via l'API XML-RPC, toutes les données utiles au calcul des indicateurs :
articles, clients, commandes clients et fournisseurs, mouvements de stock, factures
et paiements. Il les enregistre dans le dossier « donnees ».

Équivalent SAP : une extraction des tables VBAK/VBAP (ventes), LIKP/LIPS (livraisons),
EKKO/EKPO (achats), MSEG (mouvements de stock) et BSID/BSAD (postes clients),
ou une extraction via les API OData de S/4HANA.

Utilisation :
    python extraire_donnees.py                                  (base « distrielec », dossier « donnees »)
    python extraire_donnees.py distrielec_avant donnees_avant   (base, dossier de sortie)
"""

import csv
import os
import getpass
import sys
import xmlrpc.client

URL = "http://localhost:8069"
DB = "distrielec"
# Identifiants lus dans les variables d'environnement, jamais écrits dans le code :
#   set ODOO_USER=ton.email@exemple.com
#   set ODOO_PASSWORD=ton_mot_de_passe
# Sans variable, le script demande le mot de passe au lancement.
USER = os.environ.get("ODOO_USER") or input("E-mail Odoo : ")
PASSWORD = os.environ.get("ODOO_PASSWORD") or getpass.getpass("Mot de passe Odoo : ")

OUT_DIR = "donnees"
if len(sys.argv) > 1:
    DB = sys.argv[1]
if len(sys.argv) > 2:
    OUT_DIR = sys.argv[2]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    sys.exit("Échec de connexion : vérifie DB, USER et PASSWORD.")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)


def call(model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PASSWORD, model, method, list(args), kwargs)


_fields_cache = {}


def available_fields(model):
    if model not in _fields_cache:
        _fields_cache[model] = call(model, "fields_get", attributes=["type"])
    return _fields_cache[model]


def first_field(model, candidates):
    """Renvoie le premier champ existant (les noms changent parfois entre versions d'Odoo)."""
    for name in candidates:
        if name in available_fields(model):
            return name
    return None


def read_all(model, domain, wanted):
    """Lit tous les enregistrements ; un champ many2one devient deux colonnes : id et nom."""
    fields = [f for f in wanted if f in available_fields(model)]
    missing = [f for f in wanted if f not in fields]
    if missing:
        print(f"  (champs absents de {model}, ignorés : {', '.join(missing)})")
    ids = call(model, "search", domain)
    rows = []
    for i in range(0, len(ids), 500):
        for rec in call(model, "read", ids[i:i + 500], fields=fields):
            row = {"id": rec["id"]}
            for f in fields:
                value = rec.get(f)
                ftype = available_fields(model)[f]["type"]
                if ftype == "many2one":
                    row[f] = value[0] if value else ""
                    row[f + "_name"] = value[1] if value else ""
                elif ftype in ("one2many", "many2many"):
                    row[f] = "|".join(str(v) for v in value) if value else ""
                else:
                    row[f] = "" if value is False else value
            rows.append(row)
    return rows


def save(name, rows):
    path = os.path.join(OUT_DIR, f"{name}.csv")
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns or ["id"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{path} : {len(rows)} lignes")


os.makedirs(OUT_DIR, exist_ok=True)

# 1. Articles
save("produits", read_all("product.product", [("default_code", "!=", False)],
                          ["default_code", "name", "standard_price", "qty_available"]))

# 2. Clients et leur canal de distribution (étiquette)
tags = {t["id"]: t["name"] for t in call("res.partner.category", "search_read", [], fields=["name"])}
channels = {"Grossiste", "Installateur", "Détail"}
partners = read_all("res.partner", [("category_id", "!=", False)], ["name", "category_id"])
for p in partners:
    names = [tags.get(int(t)) for t in str(p.pop("category_id")).split("|") if t]
    p["canal"] = next((n for n in names if n in channels), "")
save("clients", partners)

# 3. Ventes
save("ventes", read_all("sale.order", [("state", "=", "sale")],
                        ["name", "partner_id", "date_order", "commitment_date", "amount_untaxed"]))
save("ventes_lignes", read_all("sale.order.line", [("order_id.state", "=", "sale"), ("product_id", "!=", False)],
                               ["order_id", "product_id", "product_uom_qty", "price_subtotal"]))

# 4. Achats
save("achats", read_all("purchase.order", [("state", "in", ["purchase", "done"])],
                        ["name", "partner_id", "date_order", "date_approve", "date_planned", "amount_untaxed"]))
save("achats_lignes", read_all("purchase.order.line", [("order_id.state", "in", ["purchase", "done"])],
                               ["order_id", "product_id", "product_qty", "qty_received"]))

# 5. Mouvements de stock terminés, avec le type des emplacements d'origine et de destination
usage = {loc["id"]: loc["usage"] for loc in call("stock.location", "search_read",
                                                    [("active", "in", [True, False])], fields=["usage"])}
qty_field = first_field("stock.move", ["quantity", "quantity_done", "product_uom_qty"])
moves = read_all("stock.move", [("state", "=", "done")],
                 ["product_id", qty_field, "date", "location_id", "location_dest_id",
                  "sale_line_id", "purchase_line_id", "reference"])
for m in moves:
    m["quantite"] = m.pop(qty_field)
    m["src_usage"] = usage.get(m["location_id"], "")
    m["dest_usage"] = usage.get(m["location_dest_id"], "")
save("mouvements", moves)

# 6. Factures clients et fournisseurs comptabilisées
save("factures", read_all("account.move",
                          [("state", "=", "posted"),
                           ("move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"])],
                          ["name", "move_type", "commercial_partner_id", "invoice_date", "invoice_date_due",
                           "amount_untaxed", "amount_total", "amount_residual"]))

# 7. Paiements : dates de lettrage entre factures et règlements
partials = call("account.partial.reconcile", "search_read", [],
                fields=["debit_move_id", "credit_move_id", "amount", "max_date"])
line_ids = {p["debit_move_id"][0] for p in partials} | {p["credit_move_id"][0] for p in partials}
line_to_move = {}
ids = list(line_ids)
for i in range(0, len(ids), 500):
    for line in call("account.move.line", "read", ids[i:i + 500], fields=["move_id"]):
        line_to_move[line["id"]] = line["move_id"][0]
payments = []
for p in partials:
    for side in ("debit_move_id", "credit_move_id"):
        payments.append({"move_id": line_to_move.get(p[side][0], ""), "date": p["max_date"], "montant": p["amount"]})
save("lettrages", payments)

print(f"\nExtraction terminée dans « {OUT_DIR} ».")
