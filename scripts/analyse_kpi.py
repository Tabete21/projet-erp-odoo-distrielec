"""
Étape 3 du Jour 5 : calcul des indicateurs de performance et tableau de bord.

Lit les fichiers CSV du dossier « donnees » et produit :
  - indicateurs.csv       : la valeur de chaque indicateur ;
  - tableau_de_bord.html  : le tableau de bord interactif (à ouvrir dans un navigateur).

Indicateurs calculés, sur la période simulée :
  Ventes / SD   : taux de service OTIF, taux de service des lignes, délai de livraison,
                  part des commandes livrées en plusieurs fois, chiffre d'affaires par canal.
  Stock / MM    : rotation des stocks, couverture en jours, valeur du stock dans le temps.
  Achats / MM   : ponctualité des fournisseurs (OTD) et délai réel d'approvisionnement.
  Finance / FI  : DSO, délai de paiement réel par canal, balance âgée des créances.

Utilisation :
    pip install pandas plotly
    python analyse_kpi.py                          (dossier « donnees »)
    python analyse_kpi.py donnees_avant avant      (dossier de données, nom du scénario)
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version

DATA = sys.argv[1] if len(sys.argv) > 1 else "donnees"
SUFFIX = f"_{sys.argv[2]}" if len(sys.argv) > 2 else ""
START = pd.Timestamp("2026-06-01")
END = pd.Timestamp("2026-10-09")
DAYS = (END - START).days + 1
OTIF_TARGET = 95.0

# Palette (catégorielle, dans un ordre fixe) et encres du tableau de bord
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
CHANNEL_COLORS = {"Grossiste": BLUE, "Installateur": ORANGE, "Détail": AQUA}
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def load(name, dates=()):
    df = pd.read_csv(os.path.join(DATA, f"{name}.csv"))
    for col in dates:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


produits = load("produits")
clients = load("clients")
ventes = load("ventes", ["date_order", "commitment_date"])
lignes = load("ventes_lignes")
achats = load("achats", ["date_order", "date_approve", "date_planned"])
achats_lignes = load("achats_lignes")
mvts = load("mouvements", ["date"])
factures = load("factures", ["invoice_date", "invoice_date_due"])
lettrages = load("lettrages", ["date"])

canal = clients.set_index("id")["canal"].to_dict()
cost = produits.set_index("id")["standard_price"].to_dict()
code = produits.set_index("id")["default_code"].to_dict()
mvts["jour"] = mvts["date"].dt.normalize()

# ---------------------------------------------------------------------------
# 1. Ventes : OTIF, taux de service, délai de livraison, livraisons fractionnées
# ---------------------------------------------------------------------------
v = ventes[(ventes["date_order"] >= START) & (ventes["date_order"] <= END + pd.Timedelta(days=1))].copy()
v["canal"] = v["partner_id"].map(canal).fillna("Autre")
v["promis"] = v["commitment_date"].dt.normalize()

livr = mvts[(mvts["dest_usage"] == "customer") & (mvts["src_usage"] == "internal") & mvts["sale_line_id"].notna()]
livr = livr.merge(lignes[["id", "order_id"]], left_on="sale_line_id", right_on="id", suffixes=("", "_l"))

l = lignes[lignes["order_id"].isin(v["id"])].merge(v[["id", "promis"]], left_on="order_id", right_on="id",
                                                    suffixes=("", "_v"))
dated = livr.merge(l[["id", "promis"]], left_on="sale_line_id", right_on="id", suffixes=("", "_ligne"))
a_temps = dated[dated["jour"] <= dated["promis"]].groupby("sale_line_id")["quantite"].sum()
l["livre_a_temps"] = l["id"].map(a_temps).fillna(0)
l["complete_a_temps"] = l["livre_a_temps"] >= l["product_uom_qty"] - 1e-6

# On ne juge que les commandes dont la date promise est passée à la fin de la période
eval_orders = v[v["promis"] <= END]
l_eval = l[l["order_id"].isin(eval_orders["id"])]
otif_by_order = l_eval.groupby("order_id")["complete_a_temps"].all()
eval_orders = eval_orders.assign(otif=eval_orders["id"].map(otif_by_order).fillna(False))

otif = 100 * eval_orders["otif"].mean()
taux_lignes = 100 * l_eval["complete_a_temps"].mean()

par_cmd = livr[livr["order_id"].isin(v["id"])].groupby("order_id")["jour"].agg(["max", "nunique"])
v = v.join(par_cmd, on="id")
tout_livre = l.groupby("order_id").apply(
    lambda g: (livr[livr["sale_line_id"].isin(g["id"])]["quantite"].sum() >= g["product_uom_qty"].sum() - 1e-6),
    include_groups=False)
v["livree"] = v["id"].map(tout_livre).fillna(False)
livrees = v[v["livree"]]
delai_livraison = (livrees["max"] - livrees["date_order"].dt.normalize()).dt.days.mean()
fractionnees = 100 * (livrees["nunique"] > 1).mean()

eval_orders["mois"] = eval_orders["promis"].dt.to_period("M")
otif_mensuel = eval_orders.groupby("mois")["otif"].mean().mul(100)
otif_canal = eval_orders.groupby("canal")["otif"].mean().mul(100)

# ---------------------------------------------------------------------------
# 2. Stock : valeur dans le temps, rotation, couverture
# ---------------------------------------------------------------------------
# Les opérations saisies à la main (Jours 1 à 4) sont datées du 11 octobre mais ont eu
# lieu avant la simulation : on les ramène au début de la période.
m = mvts.copy()
m.loc[m["jour"] > END, "jour"] = START
entree = (m["dest_usage"] == "internal") & (m["src_usage"] != "internal")
sortie = (m["src_usage"] == "internal") & (m["dest_usage"] != "internal")
m["delta"] = 0.0
m.loc[entree, "delta"] = m["quantite"]
m.loc[sortie, "delta"] = -m["quantite"]
m["valeur"] = m["delta"] * m["product_id"].map(cost)

jours = pd.date_range(START, END, freq="D")
avant = m[m["jour"] < START]["valeur"].sum()
flux = m[(m["jour"] >= START) & (m["jour"] <= END)].groupby("jour")["valeur"].sum().reindex(jours, fill_value=0)
stock_valeur = avant + flux.cumsum()
stock_moyen = stock_valeur.mean()

ventes_sorties = m[sortie & (m["dest_usage"] == "customer") & (m["jour"] >= START) & (m["jour"] <= END)]
cogs = -ventes_sorties["valeur"].sum()
rotation = cogs / stock_moyen * 365 / DAYS if stock_moyen else float("nan")
couverture = stock_moyen / (cogs / DAYS) if cogs else float("nan")

# Rotation par article
par_article = []
for pid, g in m.groupby("product_id"):
    if pid not in code:
        continue
    avant_q = g[g["jour"] < START]["delta"].sum()
    q = avant_q + g[(g["jour"] >= START) & (g["jour"] <= END)].groupby("jour")["delta"].sum() \
        .reindex(jours, fill_value=0).cumsum()
    vendu = -g[sortie.loc[g.index] & (g["dest_usage"] == "customer") & (g["jour"] >= START)]["delta"].sum()
    moy = q.mean()
    par_article.append({"article": code[pid], "rotation": vendu / moy * 365 / DAYS if moy > 0 else 0,
                        "couverture": moy / (vendu / DAYS) if vendu else float("nan"),
                        "jours_rupture": int((q <= 0).sum())})
par_article = pd.DataFrame(par_article).sort_values("rotation")

# ---------------------------------------------------------------------------
# 3. Achats : ponctualité et délai réel des fournisseurs
# ---------------------------------------------------------------------------
a = achats[(achats["date_order"] >= START) & (achats["date_order"] <= END + pd.Timedelta(days=1))].copy()
recep = mvts[(mvts["src_usage"] == "supplier") & mvts["purchase_line_id"].notna()]
recep = recep.merge(achats_lignes[["id", "order_id"]], left_on="purchase_line_id", right_on="id",
                    suffixes=("", "_l"))
premiere = recep.groupby("order_id")["jour"].min()
a["reception"] = a["id"].map(premiere)
a = a[a["reception"].notna()]
a["a_lheure"] = a["reception"] <= a["date_planned"].dt.normalize()
a["delai"] = (a["reception"] - a["date_approve"].dt.normalize()).dt.days
otd = 100 * a["a_lheure"].mean()
fournisseurs = a.groupby("partner_id_name").agg(otd=("a_lheure", "mean"), delai=("delai", "mean"),
                                                 commandes=("id", "count"))
fournisseurs["otd"] *= 100

# ---------------------------------------------------------------------------
# 4. Finance : chiffre d'affaires, DSO, délais de paiement, balance âgée
# ---------------------------------------------------------------------------
f = factures[(factures["invoice_date"] >= START) & (factures["invoice_date"] <= END)].copy()
f["canal"] = f["commercial_partner_id"].map(canal).fillna("Autre")
fc = f[f["move_type"] == "out_invoice"].copy()

fc["mois"] = fc["invoice_date"].dt.to_period("M")
ca = fc.pivot_table(index="mois", columns="canal", values="amount_untaxed", aggfunc="sum").fillna(0)
ca_total = fc["amount_untaxed"].sum()

paye_le = lettrages.groupby("move_id")["date"].max()
fc["paye_le"] = fc["id"].map(paye_le)
payees = fc[(fc["amount_residual"] <= 0.01) & fc["paye_le"].notna()].copy()
payees["delai_reel"] = (payees["paye_le"] - payees["invoice_date"]).dt.days
payees["delai_contrat"] = (payees["invoice_date_due"] - payees["invoice_date"]).dt.days
payees["retard"] = payees["paye_le"] > payees["invoice_date_due"]
delais_canal = payees.groupby("canal")[["delai_contrat", "delai_reel"]].mean()
retard_pct = 100 * payees["retard"].mean()

encours = fc[fc["amount_residual"] > 0.01].copy()
dso = encours["amount_residual"].sum() / fc["amount_total"].sum() * DAYS if len(fc) else float("nan")
encours["jours_retard"] = (END - encours["invoice_date_due"]).dt.days
tranches = ["Non échu", "1 à 30 j", "31 à 60 j", "Plus de 60 j"]
encours["tranche"] = pd.cut(encours["jours_retard"], [-10_000, 0, 30, 60, 10_000], labels=tranches)
balance_agee = encours.groupby("tranche", observed=False)["amount_residual"].sum().reindex(tranches)

# ---------------------------------------------------------------------------
# 5. Enregistrement des indicateurs
# ---------------------------------------------------------------------------
indicateurs = pd.DataFrame([
    ("Chiffre d'affaires HT (DH)", ca_total),
    ("Taux de service OTIF (%)", otif),
    ("Taux de service des lignes (%)", taux_lignes),
    ("Délai moyen commande → livraison complète (jours)", delai_livraison),
    ("Commandes livrées en plusieurs fois (%)", fractionnees),
    ("Valeur moyenne du stock (DH)", stock_moyen),
    ("Rotation des stocks (fois par an)", rotation),
    ("Couverture de stock (jours)", couverture),
    ("Ponctualité fournisseurs OTD (%)", otd),
    ("DSO (jours)", dso),
    ("Factures clients payées en retard (%)", retard_pct),
    ("Encours clients au " + END.strftime("%d/%m/%Y") + " (DH)", encours["amount_residual"].sum()),
], columns=["indicateur", "valeur"])
indicateurs["valeur"] = indicateurs["valeur"].round(1)
indicateurs.to_csv(f"indicateurs{SUFFIX}.csv", index=False, encoding="utf-8-sig")
print(indicateurs.to_string(index=False))

# ---------------------------------------------------------------------------
# 6. Tableau de bord
# ---------------------------------------------------------------------------
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def style(fig, title, y_title="", y_suffix=""):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=INK), x=0, xanchor="left"),
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, height=340,
        margin=dict(l=56, r=20, t=56, b=44), bargap=0.35, bargroupgap=0.08,
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom", title=None),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, color=INK)),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor=AXIS, tickfont=dict(color=MUTED),
                     title=dict(text=y_title, font=dict(color=MUTED)), ticksuffix=y_suffix)
    return fig


def mois_fr(periods):
    noms = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    return [f"{noms[p.month - 1]} {p.year}" for p in periods]


figs = []

# OTIF mensuel
fig = go.Figure(go.Scatter(x=mois_fr(otif_mensuel.index), y=otif_mensuel.values, mode="lines+markers",
                           line=dict(color=BLUE, width=2), marker=dict(size=8),
                           hovertemplate="%{x}<br>OTIF : %{y:.1f} %<extra></extra>", name="OTIF"))
fig.add_hline(y=OTIF_TARGET, line=dict(color=MUTED, dash="dash", width=1),
              annotation_text=f"Objectif {OTIF_TARGET:.0f} %", annotation_font_color=INK_2)
figs.append(style(fig, "Taux de service OTIF par mois", y_suffix=" %").update_yaxes(range=[0, 105]))

# OTIF par canal
order = [c for c in CHANNEL_COLORS if c in otif_canal.index]
fig = go.Figure(go.Bar(x=order, y=[otif_canal[c] for c in order], marker_color=BLUE,
                       text=[f"{otif_canal[c]:.0f} %" for c in order], textposition="outside",
                       textfont=dict(color=INK_2), hovertemplate="%{x}<br>OTIF : %{y:.1f} %<extra></extra>"))
figs.append(style(fig, "Taux de service OTIF par canal", y_suffix=" %").update_yaxes(range=[0, 110]))

# Chiffre d'affaires par canal
fig = go.Figure()
for c in [c for c in CHANNEL_COLORS if c in ca.columns]:
    fig.add_bar(x=mois_fr(ca.index), y=ca[c], name=c, marker_color=CHANNEL_COLORS[c],
                hovertemplate=c + "<br>%{x} : %{y:,.0f} DH<extra></extra>")
figs.append(style(fig, "Chiffre d'affaires HT par mois et par canal", "DH"))

# Valeur du stock
fig = go.Figure(go.Scatter(x=stock_valeur.index, y=stock_valeur.values, mode="lines",
                           line=dict(color=BLUE, width=2), name="Stock",
                           hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} DH<extra></extra>"))
fig.update_layout(hovermode="x unified")
figs.append(style(fig, "Valeur du stock (au coût)", "DH"))

# Rotation par article
fig = go.Figure(go.Bar(y=par_article["article"], x=par_article["rotation"], orientation="h", marker_color=BLUE,
                       customdata=par_article[["couverture", "jours_rupture"]].values,
                       hovertemplate="%{y}<br>Rotation : %{x:.1f} fois/an<br>Couverture : %{customdata[0]:.0f} j"
                                     "<br>Jours en rupture : %{customdata[1]}<extra></extra>"))
figs.append(style(fig, "Rotation annualisée des stocks par article").update_xaxes(
    title=dict(text="fois par an", font=dict(color=MUTED)), showgrid=True, gridcolor=GRID))

# Fournisseurs
fig = go.Figure(go.Bar(x=fournisseurs.index, y=fournisseurs["otd"], marker_color=BLUE,
                       text=[f"{x:.0f} %" for x in fournisseurs["otd"]], textposition="outside",
                       textfont=dict(color=INK_2), customdata=fournisseurs[["delai", "commandes"]].values,
                       hovertemplate="%{x}<br>À l'heure : %{y:.1f} %<br>Délai réel moyen : %{customdata[0]:.1f} j"
                                     "<br>Commandes : %{customdata[1]}<extra></extra>"))
figs.append(style(fig, "Ponctualité des fournisseurs (OTD)", y_suffix=" %").update_yaxes(range=[0, 110]))

# Délais de paiement
fig = go.Figure()
for col, name, color in [("delai_contrat", "Délai contractuel", BLUE), ("delai_reel", "Délai réel", ORANGE)]:
    fig.add_bar(x=delais_canal.index, y=delais_canal[col], name=name, marker_color=color,
                hovertemplate=name + "<br>%{x} : %{y:.0f} jours<extra></extra>")
figs.append(style(fig, "Délai de paiement des clients : contrat et réalité", "jours"))

# Balance âgée
fig = go.Figure(go.Bar(x=tranches, y=balance_agee.values, marker_color=BLUE,
                       text=[f"{x:,.0f} DH".replace(",", " ") for x in balance_agee.values], textposition="outside",
                       textfont=dict(color=INK_2), hovertemplate="%{x}<br>%{y:,.0f} DH<extra></extra>"))
figs.append(style(fig, f"Balance âgée des créances au {END:%d/%m/%Y}", "DH"))


def fmt(x, suffix=""):
    return (f"{x:,.0f}".replace(",", " ") if abs(x) >= 1000 else f"{x:.1f}".replace(".", ",")) + suffix


tuiles = [
    ("Chiffre d'affaires HT", fmt(ca_total, " DH"), f"{len(v)} commandes"),
    ("Taux de service OTIF", fmt(otif, " %"), f"objectif {OTIF_TARGET:.0f} %"),
    ("Livraisons fractionnées", fmt(fractionnees, " %"), "des commandes livrées"),
    ("Rotation des stocks", fmt(rotation, " / an"), f"couverture {couverture:.0f} jours"),
    ("Ponctualité fournisseurs", fmt(otd, " %"), f"{len(a)} réceptions"),
    ("DSO", fmt(dso, " jours"), f"{retard_pct:.0f} % de paiements en retard"),
]

html_tuiles = "".join(f'<div class="tile"><div class="label">{t}</div><div class="value">{val}</div>'
                      f'<div class="sub">{s}</div></div>' for t, val, s in tuiles)
# Plotly est chargé une seule fois dans l'en-tête ; chaque graphique s'adapte à la largeur de sa carte
html_figs = "".join(
    '<div class="card">' + fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                                       config={"displaylogo": False, "responsive": True}) + "</div>"
    for fig in figs)
html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pilotage DistriElec</title>
<script src="https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js" charset="utf-8"></script>
<style>
body {{ margin:0; background:#f9f9f7; color:{INK}; font-family:{FONT}; }}
main {{ max-width:1200px; margin:0 auto; padding:32px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
.intro {{ color:{INK_2}; margin:0 0 24px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-bottom:24px; }}
.tile, .card {{ background:{SURFACE}; border:1px solid rgba(11,11,11,.10); border-radius:12px; }}
.tile {{ padding:16px; }}
.label {{ color:{INK_2}; font-size:13px; }}
.value {{ font-size:26px; font-weight:600; margin:6px 0 2px; }}
.sub {{ color:{MUTED}; font-size:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(460px, 1fr)); gap:16px; }}
.card {{ padding:8px; overflow:hidden; }}
@media (max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>Tableau de bord supply chain – DistriElec Maroc</h1>
<p class="intro">Scénario : {SUFFIX[1:] or "unique"} · période du {START:%d/%m/%Y} au {END:%d/%m/%Y} · données extraites d'Odoo 19 · survolez les graphiques pour le détail</p>
<div class="tiles">{html_tuiles}</div>
<div class="grid">{html_figs}</div>
</main></body></html>"""
with open(f"tableau_de_bord{SUFFIX}.html", "w", encoding="utf-8") as fh:
    fh.write(html)
print(f"\nTableau de bord créé : tableau_de_bord{SUFFIX}.html (ouvre-le dans ton navigateur)")
