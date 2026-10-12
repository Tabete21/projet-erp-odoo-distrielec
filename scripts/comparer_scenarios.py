"""
Comparaison des deux scénarios de réapprovisionnement (avant / après correction).

Lit indicateurs_avant.csv et indicateurs_apres.csv (produits par analyse_kpi.py)
et crée comparaison.html : un tableau des écarts et deux graphiques avant / après.

Utilisation :
    python comparer_scenarios.py
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

avant = pd.read_csv("indicateurs_avant.csv").set_index("indicateur")["valeur"]
apres = pd.read_csv("indicateurs_apres.csv").set_index("indicateur")["valeur"]
comp = pd.DataFrame({"Avant": avant, "Après": apres})
comp["Écart"] = comp["Après"] - comp["Avant"]
comp["Écart (%)"] = (comp["Écart"] / comp["Avant"].abs() * 100).round(1)
print(comp.to_string())


def fmt(x):
    if pd.isna(x):
        return "–"
    return f"{x:,.0f}".replace(",", " ") if abs(x) >= 1000 else f"{x:.1f}".replace(".", ",")


def bar_pair(title, rows, suffix):
    rows = [r for r in rows if r in comp.index]
    labels = [r.split(" (")[0] for r in rows]
    fig = go.Figure()
    for col, color in [("Avant", BLUE), ("Après", ORANGE)]:
        fig.add_bar(x=labels, y=comp.loc[rows, col], name=col, marker_color=color,
                    text=[fmt(v) + suffix for v in comp.loc[rows, col]], textposition="outside",
                    textfont=dict(color=INK_2), hovertemplate=col + "<br>%{x} : %{y:.1f}" + suffix + "<extra></extra>")
    fig.update_layout(title=dict(text=title, font=dict(size=15, color=INK), x=0),
                      font=dict(family=FONT, size=12, color=INK_2), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                      height=360, margin=dict(l=48, r=20, t=56, b=60), bargap=0.3, bargroupgap=0.08,
                      legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=AXIS, tickfont=dict(color=MUTED), ticksuffix=suffix)
    return fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                       config={"displaylogo": False, "responsive": True})


service = bar_pair("Service client", ["Taux de service OTIF (%)", "Taux de service des lignes (%)",
                                      "Commandes livrées en plusieurs fois (%)"], " %")
stock = bar_pair("Stock", ["Couverture de stock (jours)", "Délai moyen commande → livraison complète (jours)"], " j")

rows = "".join(
    f"<tr><td>{i}</td><td>{fmt(r['Avant'])}</td><td>{fmt(r['Après'])}</td>"
    f"<td>{'+' if r['Écart'] > 0 else ''}{fmt(r['Écart'])}</td></tr>"
    for i, r in comp.iterrows())

html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avant et après</title>
<script src="https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js" charset="utf-8"></script>
<style>
body {{ margin:0; background:#f9f9f7; color:{INK}; font-family:{FONT}; }}
main {{ max-width:1100px; margin:0 auto; padding:32px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
p {{ color:{INK_2}; margin:0 0 24px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(440px, 1fr)); gap:16px; margin-bottom:24px; }}
.card {{ background:{SURFACE}; border:1px solid rgba(11,11,11,.10); border-radius:12px; padding:8px; overflow:hidden; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th, td {{ padding:10px 12px; border-bottom:1px solid {GRID}; text-align:right; font-variant-numeric:tabular-nums; }}
th:first-child, td:first-child {{ text-align:left; }}
th {{ color:{INK_2}; font-weight:600; }}
@media (max-width:520px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>Politique de réapprovisionnement : avant et après</h1>
<p>Même demande client dans les deux scénarios · après : révision quotidienne, stock de sécurité et délai de sécurité</p>
<div class="grid"><div class="card">{service}</div><div class="card">{stock}</div></div>
<div class="card"><table><thead><tr><th>Indicateur</th><th>Avant</th><th>Après</th><th>Écart</th></tr></thead>
<tbody>{rows}</tbody></table></div>
</main></body></html>"""
with open("comparaison.html", "w", encoding="utf-8") as fh:
    fh.write(html)
print("\nComparaison créée : comparaison.html")
