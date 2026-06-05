"""
Onglet Paramètres — récurrentes, catégories, prêts, découverts, soldes début de mois.
"""
import streamlit as st
from datetime import datetime
from modules.data import COMPTES, visible_cats, all_cats
from modules.calculs import get_sol, set_sol
from modules.fmt import fmt2, fmt

MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin',
        'Juillet','Août','Septembre','Octobre','Novembre','Décembre']


def render(D, persist, cur_m, cur_y):
    st.subheader("⚙️ Paramètres")

    tab_sol, tab_rec, tab_cats, tab_prets, tab_od = st.tabs([
        "💰 Soldes", "🔄 Récurrentes", "🏷️ Catégories", "🏦 Prêts", "⚠️ Découverts"
    ])

    with tab_sol:
        _render_soldes(D, persist, cur_m, cur_y)

    with tab_rec:
        _render_recurrentes(D, persist)

    with tab_cats:
        _render_categories(D, persist)

    with tab_prets:
        _render_prets(D, persist)

    with tab_od:
        _render_overdrafts(D, persist)


def _render_soldes(D, persist, cur_m, cur_y):
    st.markdown("**Soldes de début de mois**")
    st.caption("Saisissez le solde réel au 1er de chaque mois. "
               "Ces valeurs ancrent le calcul des soldes pour toute l'app.")

    cols = st.columns(len([k for k in COMPTES if k != "mc"]))
    cpts = [(k, v) for k, v in COMPTES.items() if k != "mc"]

    for i, (cpt_id, cpt) in enumerate(cpts):
        with cols[i]:
            deb = get_sol(D["sol"], cpt_id, cur_m, cur_y)
            tx_m = [t for t in D["tx"]
                    if t.get("compte") == cpt_id]
            from modules.calculs import aff_key, mc_depenses_mois
            mvt = sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
                      for t in D["tx"]
                      if t["compte"] == cpt_id
                      and aff_key(t) == (cur_y, cur_m))
            if cpt_id == "ca":
                mvt -= mc_depenses_mois(D["tx"], cur_m, cur_y)
            fin = (deb + mvt) if deb is not None else None

            st.markdown(f"**{cpt['label']}** — {MOIS[cur_m]} {cur_y}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Début", fmt2(deb) if deb is not None else "—")
            c2.metric("Mouvements TX", fmt2(mvt))
            c3.metric("Fin estimée", fmt2(fin) if fin is not None else "—")

            new_sol = st.number_input(
                "Solde au 1er (€)",
                value=float(deb) if deb is not None else 0.0,
                step=10.0, format="%.2f",
                key=f"sol_{cpt_id}_{cur_m}_{cur_y}"
            )
            if st.button("💾 Enregistrer", key=f"sav_sol_{cpt_id}_{cur_m}_{cur_y}"):
                set_sol(D["sol"], cpt_id, cur_m, cur_y, new_sol)
                persist()
                st.success("✓")
                st.rerun()


def _render_recurrentes(D, persist):
    st.markdown("**Récurrentes mensuelles**")
    st.caption("Utilisées uniquement pour le prévisionnel — elles ne créent pas de transactions réelles.")

    # Filtre par compte
    fopts = {"all": "Tous", **{k: v["label"] for k, v in COMPTES.items()}}
    filt = st.selectbox("Compte", list(fopts.keys()),
                        format_func=lambda x: fopts[x], key="rec_filt")
    recs = [r for r in D["rec"] if filt == "all" or r["compte"] == filt]

    for r in recs:
        cpt = COMPTES.get(r["compte"], {"label": r["compte"]})
        sign = "+" if r["type"] == "revenu" else "−"
        with st.expander(
            f"{sign}{fmt2(r['mnt'])} — {r['nom']} — {cpt['label'].split()[0]} — j.{r['jour']}",
            expanded=False
        ):
            with st.form(f"edit_rec_{r['id']}"):
                c1, c2 = st.columns(2)
                with c1:
                    rn = st.text_input("Nom", value=r["nom"])
                    rc = st.selectbox("Compte", list(COMPTES.keys()),
                                      index=list(COMPTES.keys()).index(r["compte"]),
                                      format_func=lambda x: COMPTES[x]["label"])
                    rt = st.radio("Type", ["depense", "revenu"],
                                  index=0 if r["type"] == "depense" else 1,
                                  format_func=lambda x: "💸 Dépense" if x == "depense" else "💰 Revenu",
                                  horizontal=True, key=f"rt_{r['id']}")
                with c2:
                    cats = visible_cats(D)
                    rcat = st.selectbox("Catégorie", cats,
                                        index=cats.index(r["cat"]) if r["cat"] in cats else 0)
                    rmnt = st.number_input("Montant €", value=float(r["mnt"]),
                                           step=0.01, format="%.2f")
                    rjour = st.number_input("Jour du mois", value=min(int(r["jour"]), 28),
                                            min_value=1, max_value=28)
                if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                    idx = next(i for i, x in enumerate(D["rec"]) if x["id"] == r["id"])
                    D["rec"][idx] = {**r, "nom": rn, "compte": rc, "cat": rcat,
                                     "mnt": float(rmnt), "type": rt, "jour": int(rjour)}
                    persist(); st.success("✓"); st.rerun()
            if st.button("🗑 Supprimer", key=f"del_rec_{r['id']}"):
                D["rec"] = [x for x in D["rec"] if x["id"] != r["id"]]
                persist(); st.rerun()

    st.divider()
    st.markdown("**Ajouter une récurrente**")
    with st.form("add_rec", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            rn2 = st.text_input("Nom", key="ar_nom")
            rc2 = st.selectbox("Compte", list(COMPTES.keys()),
                                format_func=lambda x: COMPTES[x]["label"], key="ar_cpt")
            rt2 = st.radio("Type", ["depense", "revenu"],
                           format_func=lambda x: "💸 Dépense" if x == "depense" else "💰 Revenu",
                           horizontal=True, key="ar_type")
        with c2:
            rcat2 = st.selectbox("Catégorie", visible_cats(D), key="ar_cat")
            rmnt2 = st.number_input("Montant €", min_value=0.01, step=0.01,
                                    format="%.2f", key="ar_mnt")
            rjour2 = st.number_input("Jour du mois", min_value=1, max_value=28,
                                     value=5, key="ar_jour")
        if st.form_submit_button("✅ Ajouter", use_container_width=True):
            D["rec"].append({
                "id": f"r_{int(datetime.now().timestamp()*1000)}",
                "nom": rn2, "compte": rc2, "cat": rcat2,
                "mnt": float(rmnt2), "type": rt2, "jour": int(rjour2)
            })
            persist(); st.success("✓"); st.rerun()


def _render_categories(D, persist):
    st.markdown("**Catégories**")
    st.caption("Les catégories invisibles n'apparaissent plus dans les listes "
               "mais les transactions existantes sont conservées.")

    vis = sum(1 for c in D["cats"] if c.get("visible", True))
    st.info(f"**{vis}** visibles sur **{len(D['cats'])}** total")

    changed = False
    for cat in sorted(D["cats"], key=lambda c: c["nom"]):
        c1, c2 = st.columns([5, 1])
        c1.write(f"{'✅' if cat.get('visible', True) else '🚫'} {cat['nom']}")
        lbl = "🙈 Masquer" if cat.get("visible", True) else "👁 Afficher"
        if c2.button(lbl, key=f"vis_{cat['nom']}"):
            cat["visible"] = not cat.get("visible", True)
            changed = True
    if changed:
        persist(); st.rerun()

    st.divider()
    with st.form("add_cat", clear_on_submit=True):
        new_nom = st.text_input("Nouvelle catégorie")
        if st.form_submit_button("Ajouter"):
            if new_nom and not any(c["nom"] == new_nom for c in D["cats"]):
                D["cats"].append({"nom": new_nom, "visible": True})
                persist(); st.success(f"✓ « {new_nom} » ajoutée."); st.rerun()


def _render_prets(D, persist):
    st.markdown("**Prêts en cours** — indicatif")
    for p in D["prets"]:
        tot = p["nb"] * p["ech"] + p["cap"]
        pct = min(100, round((1 - p["cap"] / tot) * 100)) if tot > 0 else 0
        with st.expander(f"**{p['nom']}** — {fmt2(p['cap'])} restant"):
            with st.form(f"edit_pret_{p['id']}"):
                c1, c2 = st.columns(2)
                with c1:
                    pn = st.text_input("Nom", value=p["nom"])
                    pc = st.number_input("Capital restant €", value=float(p["cap"]),
                                         step=100.0, format="%.2f")
                with c2:
                    pe = st.number_input("Mensualité €", value=float(p["ech"]),
                                         step=10.0, format="%.2f")
                    pnb = st.number_input("Mensualités restantes", value=int(p["nb"]), step=1)
                st.progress(pct / 100, text=f"{pct}% remboursé")
                if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                    idx = next(i for i, x in enumerate(D["prets"]) if x["id"] == p["id"])
                    D["prets"][idx] = {"id": p["id"], "nom": pn, "cap": float(pc),
                                       "ech": float(pe), "nb": int(pnb)}
                    persist(); st.success("✓"); st.rerun()
            if st.button("🗑 Supprimer", key=f"del_p_{p['id']}"):
                D["prets"] = [x for x in D["prets"] if x["id"] != p["id"]]
                persist(); st.rerun()

    st.divider()
    st.markdown("**Ajouter un prêt**")
    with st.form("add_pret", clear_on_submit=True):
        c1, c2 = st.columns(2)
        pnom = c1.text_input("Nom")
        pcap = c1.number_input("Capital restant €", min_value=0.0, step=100.0)
        pech = c2.number_input("Mensualité €", min_value=0.0, step=10.0)
        pnb2 = c2.number_input("Mensualités restantes", min_value=0, step=1)
        if st.form_submit_button("✅ Ajouter", use_container_width=True):
            D["prets"].append({
                "id": f"p_{int(datetime.now().timestamp()*1000)}",
                "nom": pnom, "cap": float(pcap), "ech": float(pech), "nb": int(pnb2)
            })
            persist(); st.success("✓"); st.rerun()


def _render_overdrafts(D, persist):
    st.markdown("**Découverts autorisés**")
    changed = False
    for cpt_id, cpt in COMPTES.items():
        new_od = st.number_input(
            cpt["label"],
            value=float(D["overdraft"].get(cpt_id, 0)),
            step=50.0, key=f"od_{cpt_id}"
        )
        if new_od != D["overdraft"].get(cpt_id, 0):
            D["overdraft"][cpt_id] = new_od
            changed = True
    if changed:
        persist()
