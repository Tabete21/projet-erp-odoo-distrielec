"""
Génération d'un historique d'activité réaliste pour DistriElec Maroc SARL (Odoo 19).

Le script simule, jour après jour, l'activité de l'entreprise sur une période donnée :
  - des commandes clients (avec une date de livraison promise) ;
  - les livraisons (prélèvement, emballage, expédition), parfois en retard ou partielles ;
  - les factures clients et leurs paiements (avec des retards de paiement réalistes) ;
  - les achats de réapprovisionnement (politique point de commande / niveau de recomplètement) ;
  - les réceptions fournisseurs (parfois en retard), les factures fournisseurs et leurs paiements.

Toutes les opérations passent par l'API XML-RPC d'Odoo, exactement comme si un utilisateur
les faisait dans l'interface. Les dates sont ensuite réécrites pour reconstituer l'historique.

AVANT DE LANCER : faire une sauvegarde de la base (Database manager -> Backup).

Utilisation :
    1. Définir ODOO_USER et ODOO_PASSWORD (voir plus bas), ou les saisir au lancement.
    2. Test sur une semaine : laisser START = 2026-06-01 et END = 2026-06-07, puis lancer
           python generer_historique.py
    3. Si tout est correct : restaurer la sauvegarde faite avant le test, mettre
       END = 2026-10-09, puis relancer sur la période complète.
"""

import datetime as dt
import random
import getpass
import os
import sys
import xmlrpc.client

# ---------------------------------------------------------------------------
# 1. Paramètres de connexion et de simulation
# ---------------------------------------------------------------------------
URL = "http://localhost:8069"
DB = "distrielec"            # remplacé par le 2e argument de la ligne de commande
# Identifiants lus dans les variables d'environnement, jamais écrits dans le code :
#   set ODOO_USER=ton.email@exemple.com
#   set ODOO_PASSWORD=ton_mot_de_passe
# Sans variable, le script demande le mot de passe au lancement.
USER = os.environ.get("ODOO_USER") or input("E-mail Odoo : ")
PASSWORD = os.environ.get("ODOO_PASSWORD") or getpass.getpass("Mot de passe Odoo : ")

START = dt.date(2026, 6, 1)   # premier jour simulé
END = dt.date(2026, 10, 9)    # dernier jour simulé (inclus)
SEED = 42                     # graine aléatoire : même résultat à chaque exécution

# Article : (fournisseur, délai fournisseur en jours, quantité min par ligne, quantité max par ligne)
PRODUCTS = {
    "CAB-001": ("MaghrebCâbles SA", 7, 3, 12),
    "CAB-002": ("MaghrebCâbles SA", 7, 5, 25),
    "ECL-001": ("LumiTech Import SARL", 14, 10, 40),
    "ECL-002": ("LumiTech Import SARL", 14, 2, 10),
    "APP-001": ("LumiTech Import SARL", 14, 10, 60),
    "APP-002": ("LumiTech Import SARL", 14, 10, 40),
}

# Conditions de paiement fournisseurs (jours)
SUPPLIER_TERMS = {"MaghrebCâbles SA": 30, "LumiTech Import SARL": 45}

# Canal de distribution : (client modèle, multiplicateur de quantité, délai de paiement contractuel)
CHANNELS = {
    "Grossiste": ("Électro Atlas SARL", 1.5, 60),
    "Installateur": ("BTP Horizon SA", 1.0, 30),
    "Détail": ("Client comptoir", 0.2, 0),
}

# Nouveaux clients créés pour enrichir l'historique : (nom, ville, canal)
NEW_CUSTOMERS = [
    ("Sud Électricité SARL", "Agadir", "Grossiste"),
    ("Nord Distribution Électrique", "Tanger", "Grossiste"),
    ("Atlas Installations", "Marrakech", "Installateur"),
    ("ElecPro Services", "Casablanca", "Installateur"),
    ("Bâtir Plus SA", "Kénitra", "Installateur"),
]

# Scénario de réapprovisionnement : "avant" (politique initiale) ou "apres" (politique corrigée)
# Lancement : python generer_historique.py <scenario> <base>
SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "avant"
if len(sys.argv) > 2:
    DB = sys.argv[2]
if SCENARIO not in ("avant", "apres"):
    sys.exit('Scénario inconnu : utilise "avant" ou "apres".')
print(f"Scénario : {SCENARIO} - base : {DB}")

# Trois générateurs aléatoires indépendants : la demande des clients reste IDENTIQUE
# dans les deux scénarios, quelle que soit la politique d'achat. La comparaison est équitable.
rng_demand = random.Random(SEED)       # commandes clients et dates de livraison
rng_supply = random.Random(SEED + 1)   # retards des fournisseurs
rng_pay = random.Random(SEED + 2)      # retards de paiement

# Paramètres de la politique corrigée
Z = 1.65            # facteur de sécurité pour un taux de service visé de 95 %
CV_WEEKLY = 0.6     # coefficient de variation de la demande hebdomadaire (hypothèse)
LEAD_MARGIN = 2     # délai de sécurité en jours (les fournisseurs livrent parfois en retard)

# ---------------------------------------------------------------------------
# 2. Connexion et fonctions utilitaires
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USER, PASSWORD, {})
if not uid:
    sys.exit("Échec de connexion : vérifie USER et PASSWORD.")
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

errors = []
FAILED = object()   # valeur renvoyée par safe() en cas d'erreur


def call(model, method, *args, **kwargs):
    """Appelle une méthode Odoo. Certaines méthodes renvoient None : on l'ignore."""
    try:
        return models.execute_kw(DB, uid, PASSWORD, model, method, list(args), kwargs)
    except xmlrpc.client.Fault as e:
        if "cannot marshal None" in e.faultString:
            return None
        raise


def safe(label, func, *args, **kwargs):
    """Exécute une étape ; en cas d'erreur, la note sans arrêter la simulation."""
    try:
        return func(*args, **kwargs)
    except xmlrpc.client.Fault as e:
        msg = e.faultString.strip().splitlines()[-1][:200]
        errors.append(f"{label} : {msg}")
        return FAILED


def ts(day, hour=10):
    return f"{day.isoformat()} {hour:02d}:00:00"


def one(model, domain):
    ids = call(model, "search", domain, limit=1)
    if not ids:
        sys.exit(f"Introuvable dans Odoo : {model} {domain}")
    return ids[0]


def m2o_id(value):
    return value[0] if value else False


# ---------------------------------------------------------------------------
# 3. Lecture des données de base
# ---------------------------------------------------------------------------
wh_casa = one("stock.warehouse", [("code", "=", "CASA")])
# Zone de réception (CASA/Entrée) : point de départ des transferts de rangement
input_loc = m2o_id(call("stock.warehouse", "read", [wh_casa], fields=["wh_input_stock_loc_id"])[0]["wh_input_stock_loc_id"])
product_ids = {code: one("product.product", [("default_code", "=", code)]) for code in PRODUCTS}
supplier_ids = {name: one("res.partner", [("name", "=", name)]) for name in SUPPLIER_TERMS}

# Clients par canal : on copie liste de prix, conditions de paiement et étiquettes du client modèle
customers = {channel: [] for channel in CHANNELS}
templates = {}
for channel, (template_name, _, _) in CHANNELS.items():
    tid = one("res.partner", [("name", "=", template_name)])
    templates[channel] = call(
        "res.partner", "read", [tid],
        fields=["property_product_pricelist", "property_payment_term_id", "category_id", "country_id"],
    )[0]
    customers[channel].append(tid)

for name, city, channel in NEW_CUSTOMERS:
    existing = call("res.partner", "search", [("name", "=", name)], limit=1)
    if existing:
        customers[channel].append(existing[0])
        continue
    t = templates[channel]
    cid = call("res.partner", "create", {
        "name": name,
        "is_company": True,
        "city": city,
        "country_id": m2o_id(t["country_id"]),
        "category_id": [[6, 0, t["category_id"]]],
        "property_product_pricelist": m2o_id(t["property_product_pricelist"]),
        "property_payment_term_id": m2o_id(t["property_payment_term_id"]),
    })
    customers[channel].append(cid)
    print(f"Client créé : {name} ({channel})")

# Politique de réapprovisionnement : demande hebdomadaire estimée par article
# (environ 3 lignes de commande par article et par semaine)
weekly_demand = {code: 3 * (p[2] + p[3]) / 2 for code, p in PRODUCTS.items()}

# ---------------------------------------------------------------------------
# 4. Briques de simulation
# ---------------------------------------------------------------------------
def set_picking_date(pid, day):
    call("stock.picking", "write", [pid], {"date_done": ts(day, 15)})
    move_ids = call("stock.move", "search", [("picking_id", "=", pid)])
    if move_ids:
        call("stock.move", "write", move_ids, {"date": ts(day, 15)})
    line_ids = call("stock.move.line", "search", [("picking_id", "=", pid)])
    if line_ids:
        call("stock.move.line", "write", line_ids, {"date": ts(day, 15)})


def process_pickings(model, record_id, day):
    """Valide tous les transferts prêts d'une commande (plusieurs étapes possibles).
    Renvoie True si tout est livré/reçu."""
    for _ in range(6):
        picking_ids = call(model, "read", [record_id], fields=["picking_ids"])[0]["picking_ids"]
        pickings = call("stock.picking", "read", picking_ids, fields=["state", "name"])
        open_pickings = [p for p in pickings if p["state"] not in ("done", "cancel")]
        if not open_pickings:
            return True
        progressed = False
        for p in open_pickings:
            if p["state"] in ("confirmed", "waiting"):
                safe(f"Réservation {p['name']}", call, "stock.picking", "action_assign", [p["id"]])
                p["state"] = call("stock.picking", "read", [p["id"]], fields=["state"])[0]["state"]
            if p["state"] == "assigned":
                res = safe(f"Validation {p['name']}", call, "stock.picking", "button_validate",
                           [p["id"]], context={"skip_backorder": True})
                state = call("stock.picking", "read", [p["id"]], fields=["state"])[0]["state"]
                if state == "done":
                    safe(f"Date {p['name']}", set_picking_date, p["id"], day)
                    progressed = True
                elif res is not FAILED:
                    errors.append(f"{p['name']} non validé ({state})")
        if not progressed:
            return False
    return False


def process_putaways(day):
    """Valide les rangements en attente (CASA/Entrée -> emplacements de stock).
    Avec la réception en 2 étapes, ces transferts ne sont pas rattachés à la commande d'achat."""
    if not input_loc:
        return
    picking_ids = call("stock.picking", "search", [
        ("location_id", "child_of", input_loc),
        ("state", "in", ["confirmed", "waiting", "assigned"]),
    ])
    for p in call("stock.picking", "read", picking_ids, fields=["state", "name"]):
        if p["state"] != "assigned":
            safe(f"Réservation {p['name']}", call, "stock.picking", "action_assign", [p["id"]])
        if call("stock.picking", "read", [p["id"]], fields=["state"])[0]["state"] == "assigned":
            safe(f"Rangement {p['name']}", call, "stock.picking", "button_validate",
                 [p["id"]], context={"skip_backorder": True})
            if call("stock.picking", "read", [p["id"]], fields=["state"])[0]["state"] == "done":
                safe(f"Date {p['name']}", set_picking_date, p["id"], day)


def post_invoices(model, record_id, day, ref_prefix):
    """Date et valide les factures brouillon liées à une commande. Renvoie les ids validés."""
    invoice_ids = call(model, "read", [record_id], fields=["invoice_ids"])[0]["invoice_ids"]
    drafts = call("account.move", "read", invoice_ids, fields=["state"]) if invoice_ids else []
    posted = []
    for inv in drafts:
        if inv["state"] != "draft":
            continue
        values = {"invoice_date": day.isoformat()}
        if ref_prefix:
            values["ref"] = f"{ref_prefix}-{inv['id']}"
        call("account.move", "write", [inv["id"]], values)
        safe(f"Validation facture {inv['id']}", call, "account.move", "action_post", [inv["id"]])
        if call("account.move", "read", [inv["id"]], fields=["state"])[0]["state"] == "posted":
            posted.append(inv["id"])
    return posted


def register_payment(move_id, day):
    ctx = {"active_model": "account.move", "active_ids": [move_id], "active_id": move_id}
    wizard = call("account.payment.register", "create", {"payment_date": day.isoformat()}, context=ctx)
    call("account.payment.register", "action_create_payments", [wizard], context=ctx)


def add_working_days(day, n):
    while n > 0:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


# ---------------------------------------------------------------------------
# 5. Simulation jour par jour
# ---------------------------------------------------------------------------
deliveries, receipts, payments = [], [], []   # listes d'événements (date, id, ...)
stats = {"ventes": 0, "achats": 0, "factures clients": 0, "factures fournisseurs": 0, "paiements": 0}

day = START
while day <= END:
    weekday = day.weekday()

    # 5.1 Réceptions fournisseurs prévues ce jour
    for event in [e for e in receipts if e[0] == day]:
        receipts.remove(event)
        _, po_id, supplier = event
        done = process_pickings("purchase.order", po_id, day)
        # Facture fournisseur sur les quantités reçues (contrôle à trois voies)
        safe("Facture fournisseur", call, "purchase.order", "action_create_invoice", [po_id])
        for bill_id in post_invoices("purchase.order", po_id, day, "FRS"):
            stats["factures fournisseurs"] += 1
            pay_day = day + dt.timedelta(days=SUPPLIER_TERMS[supplier] + rng_pay.randint(-3, 5))
            payments.append((pay_day, bill_id))
        if not done:
            receipts.append((day + dt.timedelta(days=3), po_id, supplier))
    # Deuxième étape de la réception : ranger la marchandise dans CASA/Stock
    process_putaways(day)

    # 5.2 Calcul des besoins et commandes fournisseurs
    #   avant : révision le lundi seulement, point de commande = demande pendant le délai, sans sécurité
    #   apres : révision chaque jour ouvré, avec stock de sécurité et délai de sécurité
    if (SCENARIO == "avant" and weekday == 0) or (SCENARIO == "apres" and weekday < 5):
        ctx = {"warehouse": wh_casa, "warehouse_id": wh_casa}
        forecast = {
            r["id"]: r["virtual_available"]
            for r in call("product.product", "read", list(product_ids.values()),
                          fields=["virtual_available"], context=ctx)
        }
        orders = {}
        for code, (supplier, lead, _, _) in PRODUCTS.items():
            if SCENARIO == "avant":
                weeks = lead / 7
                reorder_point = weekly_demand[code] * weeks
                order_up_to = weekly_demand[code] * (weeks + 1.5)
            else:
                # Stock de sécurité : SS = z x sigma_semaine x racine(délai protégé en semaines)
                protected_weeks = (lead + LEAD_MARGIN + 1) / 7      # délai + marge + 1 jour de révision
                safety_stock = Z * CV_WEEKLY * weekly_demand[code] * protected_weeks ** 0.5
                reorder_point = weekly_demand[code] * protected_weeks + safety_stock
                order_up_to = reorder_point + weekly_demand[code]   # environ une semaine de ventes par commande
            stock = forecast[product_ids[code]]
            if stock < reorder_point:
                qty = max(1, round(order_up_to - stock))
                orders.setdefault(supplier, []).append((code, qty))
        for supplier, lines in orders.items():
            lead = PRODUCTS[lines[0][0]][1]
            po_id = call("purchase.order", "create", {
                "partner_id": supplier_ids[supplier],
                "date_order": ts(day, 8),
                "date_planned": ts(day + dt.timedelta(days=lead), 12),
                "order_line": [[0, 0, {"product_id": product_ids[c], "product_qty": q}] for c, q in lines],
            })
            call("purchase.order", "button_confirm", [po_id])
            call("purchase.order", "write", [po_id], {
                "date_order": ts(day, 8), "date_approve": ts(day, 8),
                "date_planned": ts(day + dt.timedelta(days=lead), 12),
            })
            stats["achats"] += 1
            # Délai réel : parfois en avance, souvent à l'heure, parfois en retard
            actual = lead + rng_supply.choice([-1, 0, 0, 0, 0, 1, 2, 4])
            receipts.append((day + dt.timedelta(days=actual), po_id, supplier))

    # 5.3 Commandes clients (jours ouvrés)
    if weekday < 5:
        for _ in range(rng_demand.choices([0, 1, 2, 3], weights=[2, 4, 3, 1])[0]):
            channel = rng_demand.choices(list(CHANNELS), weights=[3, 5, 2])[0]
            customer = rng_demand.choice(customers[channel])
            multiplier = CHANNELS[channel][1]
            codes = rng_demand.sample(list(PRODUCTS), rng_demand.randint(1, 2) if channel == "Détail" else rng_demand.randint(2, 4))
            lines = []
            for code in codes:
                _, _, qmin, qmax = PRODUCTS[code]
                qty = max(1, round(rng_demand.randint(qmin, qmax) * multiplier))
                lines.append([0, 0, {"product_id": product_ids[code], "product_uom_qty": qty}])
            promised = add_working_days(day, 2)
            so_id = call("sale.order", "create", {
                "partner_id": customer,
                "date_order": ts(day, 9),
                "commitment_date": ts(promised, 17),
                "order_line": lines,
            })
            call("sale.order", "action_confirm", [so_id])
            call("sale.order", "write", [so_id], {"date_order": ts(day, 9)})
            stats["ventes"] += 1
            # Jour de la tentative de livraison : souvent à temps, parfois en retard
            attempt = add_working_days(day, rng_demand.choice([1, 1, 2, 2, 2, 3, 4]))
            deliveries.append((attempt, so_id, channel))

    # 5.4 Livraisons prévues ce jour, puis facturation des quantités livrées
    for event in [e for e in deliveries if e[0] == day]:
        deliveries.remove(event)
        _, so_id, channel = event
        done = process_pickings("sale.order", so_id, day)
        status = call("sale.order", "read", [so_id], fields=["invoice_status"])[0]["invoice_status"]
        if status != "to invoice":
            # Rien de livré depuis la dernière facture : on retentera dans 2 jours
            if not done:
                deliveries.append((add_working_days(day, 2), so_id, channel))
            continue
        ctx = {"active_model": "sale.order", "active_ids": [so_id], "active_id": so_id}
        wizard = safe("Assistant facture", call, "sale.advance.payment.inv", "create",
                      {"advance_payment_method": "delivered"}, context=ctx)
        if wizard and wizard is not FAILED:
            safe("Création facture", call, "sale.advance.payment.inv", "create_invoices", [wizard], context=ctx)
            for inv_id in post_invoices("sale.order", so_id, day, None):
                stats["factures clients"] += 1
                terms = CHANNELS[channel][2]
                delay = 0 if terms == 0 else max(0, terms + int(rng_pay.gauss(5, 12)))
                payments.append((day + dt.timedelta(days=delay), inv_id))
        if not done:
            deliveries.append((add_working_days(day, 2), so_id, channel))

    # 5.5 Paiements (clients et fournisseurs) prévus ce jour
    for event in [e for e in payments if e[0] == day]:
        payments.remove(event)
        if safe(f"Paiement {event[1]}", register_payment, event[1], day) is not FAILED:
            stats["paiements"] += 1

    if weekday == 4:
        print(f"Semaine du {day - dt.timedelta(days=4)} terminée : {stats}")
    day += dt.timedelta(days=1)

# ---------------------------------------------------------------------------
# 6. Bilan
# ---------------------------------------------------------------------------
print("\n=== Simulation terminée ===")
for key, value in stats.items():
    print(f"  {key} : {value}")
print(f"  livraisons encore en attente : {len(deliveries)}")
print(f"  réceptions encore en attente : {len(receipts)}")
print(f"  paiements non encore échus (factures ouvertes) : {len(payments)}")
if errors:
    print(f"\n{len(errors)} erreur(s) rencontrée(s) (les 15 premières) :")
    for e in errors[:15]:
        print("  -", e)
