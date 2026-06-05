"""
Onglet Transactions — tableau Excel-like
Saisie rapide, modification inline, filtres par compte/mois/catégorie.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from modules.data import COMPTES, mc_aff_from_date, visible_cats
from modules.calculs import aff_key
from modules.fmt import fmt2

MOIS = ['Janvier','Février','Mars','Avril','Mai','Juin',
        'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']


def render(D, persist):
    st.subheader("📋 Transactions")

    now = datetime.now()

    # ── Filtres ───────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        cpt_opts = {"all": "Tous les comptes", **{k: v["label"] for k, v in COMPTES.items()}}
        filt_cpt = st.selectbox("Compte", list(cpt_opts.keys()),
                                format_func=lambda x: cpt_opts[x], key="tx_filt_cpt")
    with f2:
        annees = sorted({datetime.strptime(t["date"], "%Y-%m-%d").year
                         for t in D["tx"]}, reverse=True) or [now.year]
        filt_y = st.selectbox("Année", annees, key="tx_filt_y")
    with f3:
        filt_m = st.selectbox("Mois", range(12), index=now.month - 1,
                              format_func=lambda x: MOIS[x], key="tx_filt_m",
                              label_visibility="collapsed" if False else "visible")
    with f4:
        show_exc = st.checkbox("⭐ Excep.", value=False, key="tx_show_exc",
                               help="Afficher aussi les exceptionnelles")

    # Filtrage
    def match(t):
        if filt_cpt != "all" and t["compte"] != filt_cpt:
            return False
        ak = aff_key(t)
        if ak != (filt_y, filt_m):
            return False
        if not show_exc and t.get("exceptionnel", False):
            return False
        return True

    tx_show = sorted([t for t in D["tx"] if match(t)],
                     key=lambda t: t["date"], reverse=True)

    # ── Statistiques rapides ──────────────────────────────────────────────
    tx_all_month = [t for t in D["tx"] if aff_key(t) == (filt_y, filt_m)
                    and (filt_cpt == "all" or t["compte"] == filt_cpt)]
    rev = sum(t["montant"] for t in tx_all_month if t["type"] == "revenu")
    dep = sum(t["montant"] for t in tx_all_month if t["type"] == "depense")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Transactions", len(tx_show))
    s2.metric("Entrées", fmt2(rev))
    s3.metric("Sorties", fmt2(dep))
    s4.metric("Net", fmt2(rev - dep))

    if filt_cpt == "mc":
        st.caption("💳 Les transactions MC sont affichées selon leur **mois d'affectation** (pas leur date réelle).")
    st.divider()

    # ── Saisie rapide ─────────────────────────────────────────────────────
    with st.expander("➕ Saisie rapide", expanded=False):
        _render_saisie(D, persist, filt_cpt, filt_m, filt_y)

    st.divider()

    # ── Import CSV ────────────────────────────────────────────────────────
    with st.expander("📥 Import CSV banque", expanded=False):
        _render_import_csv(D, persist)

    st.divider()

    # ── Tableau principal ─────────────────────────────────────────────────
    if not tx_show:
        st.info("Aucune transaction pour ce filtre.")
        return

    # Construction du DataFrame d'affichage
    rows = []
    for t in tx_show:
        d = datetime.strptime(t["date"], "%Y-%m-%d")
        cpt_lbl = COMPTES.get(t["compte"], {"label": t["compte"]})["label"].split()[0]
        sign = "+" if t["type"] == "revenu" else "−"
        aff = ""
        if t["compte"] == "mc":
            aff = f"→ {MOIS_COURT[t['affM']]} {t['affY']}"
        rows.append({
            "_id": t["id"],
            "Date": d.strftime("%d/%m/%Y"),
            "Compte": cpt_lbl,
            "Catégorie": t["categorie"],
            "Note": t.get("note", ""),
            "Montant": f"{sign}{fmt2(t['montant'])}",
            "Affectation MC": aff,
            "⭐": "⭐" if t.get("exceptionnel") else "",
        })

    df = pd.DataFrame(rows)

    # Affichage avec expanders pour édition
    for t in tx_show:
        d = datetime.strptime(t["date"], "%Y-%m-%d")
        is_exc = t.get("exceptionnel", False)
        sign = "+" if t["type"] == "revenu" else "−"
        exc_badge = " ⭐" if is_exc else ""
        label = (f"{sign}{fmt2(t['montant'])} — "
                 f"{t.get('note') or t['categorie']} — "
                 f"{COMPTES.get(t['compte'],{'label':t['compte']})['label'].split()[0]} — "
                 f"{d.strftime('%d/%m/%Y')}{exc_badge}")

        with st.expander(label, expanded=False):
            # Bouton rapide exceptionnel
            btn_lbl = "⭐ Retirer exceptionnel" if is_exc else "⭐ Marquer exceptionnel"
            c_exc, c_del = st.columns([2, 1])
            with c_exc:
                if st.button(btn_lbl, key=f"exc_{t['id']}"):
                    idx = next(i for i, x in enumerate(D["tx"]) if x["id"] == t["id"])
                    D["tx"][idx]["exceptionnel"] = not is_exc
                    persist()
                    st.rerun()
            with c_del:
                if st.button("🗑 Supprimer", key=f"del_{t['id']}", type="secondary"):
                    D["tx"] = [x for x in D["tx"] if x["id"] != t["id"]]
                    persist()
                    st.rerun()

            # Formulaire d'édition
            with st.form(key=f"edit_{t['id']}"):
                e1, e2 = st.columns(2)
                with e1:
                    new_date = st.date_input("Date", value=d.date(), key=f"ed_{t['id']}")
                    new_cpt = st.selectbox("Compte", list(COMPTES.keys()),
                                           index=list(COMPTES.keys()).index(t["compte"]),
                                           format_func=lambda x: COMPTES[x]["label"],
                                           key=f"ec_{t['id']}")
                    new_type = st.radio("Type", ["depense", "revenu"],
                                        index=0 if t["type"] == "depense" else 1,
                                        format_func=lambda x: "💸 Dépense" if x == "depense" else "💰 Revenu",
                                        horizontal=True, key=f"et_{t['id']}")
                with e2:
                    cats = visible_cats(D)
                    cat_idx = cats.index(t["categorie"]) if t["categorie"] in cats else 0
                    new_cat = st.selectbox("Catégorie", cats, index=cat_idx, key=f"ecat_{t['id']}")
                    new_mnt = st.number_input("Montant €", value=float(t["montant"]),
                                              step=0.01, format="%.2f", key=f"em_{t['id']}")
                    new_note = st.text_input("Note", value=t.get("note", ""), key=f"en_{t['id']}")
                    new_exc = st.checkbox("⭐ Exceptionnelle", value=is_exc, key=f"eexc_{t['id']}")

                # Affectation MC : modifiable manuellement
                aff_m_val, aff_y_val = t.get("affM"), t.get("affY")
                if new_cpt == "mc":
                    auto_m, auto_y = mc_aff_from_date(new_date.strftime("%Y-%m-%d"))
                    cur_aff_m = int(aff_m_val) if aff_m_val is not None else auto_m
                    cur_aff_y = int(aff_y_val) if aff_y_val is not None else auto_y
                    st.caption("💳 Mois d'affectation MC (modifiable si besoin) :")
                    ma1, ma2 = st.columns(2)
                    aff_m_val = ma1.selectbox("Mois affectation", range(12),
                                              index=cur_aff_m,
                                              format_func=lambda x: MOIS[x],
                                              key=f"eaff_m_{t['id']}")
                    aff_y_val = ma2.selectbox("Année affectation",
                                              list(range(2024, 2029)),
                                              index=list(range(2024, 2029)).index(cur_aff_y) if cur_aff_y in range(2024, 2029) else 0,
                                              key=f"eaff_y_{t['id']}")

                if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                    date_str = new_date.strftime("%Y-%m-%d")
                    idx = next(i for i, x in enumerate(D["tx"]) if x["id"] == t["id"])
                    D["tx"][idx] = {
                        **t,
                        "date": date_str,
                        "compte": new_cpt,
                        "categorie": new_cat,
                        "montant": float(new_mnt),
                        "type": new_type,
                        "note": new_note,
                        "exceptionnel": new_exc,
                        "affM": aff_m_val,
                        "affY": aff_y_val,
                    }
                    persist()
                    st.success("✓")
                    st.rerun()


def _render_saisie(D, persist, default_cpt, default_m, default_y):
    """Formulaire de saisie rapide."""
    # Sélection compte hors formulaire (persiste entre saisies)
    if "saisie_cpt" not in st.session_state:
        st.session_state.saisie_cpt = default_cpt if default_cpt != "all" else "ca"
    if "saisie_last_date" not in st.session_state:
        st.session_state.saisie_last_date = date.today()

    cpt_keys = list(COMPTES.keys())
    tx_cpt = st.selectbox(
        "Compte",
        cpt_keys,
        index=cpt_keys.index(st.session_state.saisie_cpt),
        format_func=lambda x: COMPTES[x]["label"],
        key="saisie_cpt_sel"
    )
    if tx_cpt != st.session_state.saisie_cpt:
        st.session_state.saisie_cpt = tx_cpt
        st.rerun()

    if tx_cpt == "mc":
        st.info("💳 Mastercard — l'affectation mensuelle est calculée automatiquement depuis la date.")

    with st.form("add_tx", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            tx_date = st.date_input("Date", value=st.session_state.saisie_last_date, format="DD/MM/YYYY")
            tx_type = st.radio("Type", ["depense", "revenu"],
                               format_func=lambda x: "💸 Dépense" if x == "depense" else "💰 Revenu",
                               horizontal=True)
        with c2:
            tx_cat = st.selectbox("Catégorie", visible_cats(D))
            tx_mnt = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f")
            tx_note = st.text_input("Note", placeholder="Description…")
            tx_exc = st.checkbox("⭐ Exceptionnelle (exclue du prévisionnel)", value=False)

        # Affectation MC : auto depuis date + override manuel possible
        override_aff_m = override_aff_y = None
        if tx_cpt == "mc":
            auto_m, auto_y = mc_aff_from_date(tx_date.strftime("%Y-%m-%d"))
            st.caption(f"💳 Affectation calculée : **{MOIS[auto_m]} {auto_y}**  *(modifiable ci-dessous si nécessaire)*")
            ov1, ov2 = st.columns(2)
            override_aff_m = ov1.selectbox("Mois affectation", range(12),
                                            index=auto_m, format_func=lambda x: MOIS[x],
                                            key="saisie_aff_m")
            override_aff_y = ov2.selectbox("Année", list(range(2024, 2029)),
                                            index=list(range(2024, 2029)).index(auto_y) if auto_y in range(2024, 2029) else 0,
                                            key="saisie_aff_y")

        if st.form_submit_button("✅ Ajouter", type="primary", use_container_width=True):
            date_str = tx_date.strftime("%Y-%m-%d")
            st.session_state.saisie_last_date = tx_date  # mémoriser la date
            aff_m, aff_y = (None, None)
            if tx_cpt == "mc":
                aff_m = override_aff_m
                aff_y = override_aff_y

            new_tx = {
                "id": f"tx_{int(datetime.now().timestamp()*1000)}",
                "date": date_str,
                "compte": tx_cpt,
                "categorie": tx_cat,
                "montant": float(tx_mnt),
                "type": tx_type,
                "note": tx_note,
                "exceptionnel": tx_exc,
                "affM": aff_m,
                "affY": aff_y,
            }
            D["tx"].append(new_tx)
            persist()
            st.success(f"✓ {COMPTES[tx_cpt]['label']} — {fmt2(tx_mnt)} — {tx_cat}")
            st.rerun()


def _render_import_csv(D, persist):
    """Import CSV avec pré-saisie et validation par catégorie."""
    st.markdown("**Import depuis relevé bancaire (CSV)**")
    st.caption("Format attendu : Date, Libellé, Montant (négatif = dépense). "
               "L'app propose une catégorie, tu valides avant import.")

    cpt_import = st.selectbox("Compte concerné", list(COMPTES.keys()),
                              format_func=lambda x: COMPTES[x]["label"],
                              key="import_cpt")

    uploaded = st.file_uploader("Fichier CSV", type=["csv"], key="import_csv")
    if not uploaded:
        return

    import csv, io
    try:
        content = uploaded.read().decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content), delimiter=";")
        rows = list(reader)
    except Exception as e:
        st.error(f"Erreur lecture CSV : {e}")
        return

    if not rows:
        st.warning("Fichier vide.")
        return

    # Détecter header
    start = 1 if any(c.lower() in ["date", "libellé", "montant"] for c in rows[0]) else 0
    st.info(f"{len(rows) - start} lignes détectées. Vérifiez les catégories avant d'importer.")

    cats = visible_cats(D)
    pending = []

    for row in rows[start:]:
        if len(row) < 3:
            continue
        try:
            # Essayer différents formats de date
            date_str = row[0].strip()
            for fmt_d in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                try:
                    d_obj = datetime.strptime(date_str, fmt_d)
                    date_str = d_obj.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

            libelle = row[1].strip()
            # Montant : gérer virgule décimale et négatif
            mnt_raw = row[2].strip().replace(" ", "").replace(",", ".")
            mnt = float(mnt_raw)
            tx_type = "revenu" if mnt > 0 else "depense"
            mnt = abs(mnt)

            pending.append({
                "date": date_str,
                "libelle": libelle,
                "montant": mnt,
                "type": tx_type,
            })
        except (ValueError, IndexError):
            continue

    if not pending:
        st.warning("Aucune ligne valide détectée.")
        return

    # Tableau de validation
    st.markdown(f"**{len(pending)} transactions à valider :**")
    validated = []
    for i, row in enumerate(pending):
        c1, c2, c3, c4 = st.columns([2, 3, 2, 1])
        c1.text(row["date"])
        c2.text(row["libelle"][:40])
        # Catégorie proposée
        proposed = _guess_cat(row["libelle"], cats)
        cat_sel = c3.selectbox(
            "Cat.",
            cats,
            index=cats.index(proposed) if proposed in cats else 0,
            key=f"imp_cat_{i}",
            label_visibility="collapsed"
        )
        incl = c4.checkbox("✓", value=True, key=f"imp_incl_{i}")
        if incl:
            validated.append({**row, "categorie": cat_sel})

    if st.button(f"✅ Importer {len(validated)} transactions", type="primary"):
        added = 0
        for row in validated:
            aff_m, aff_y = (None, None)
            if cpt_import == "mc":
                aff_m, aff_y = mc_aff_from_date(row["date"])
            D["tx"].append({
                "id": f"tx_import_{int(datetime.now().timestamp()*1000)}_{added}",
                "date": row["date"],
                "compte": cpt_import,
                "categorie": row["categorie"],
                "montant": row["montant"],
                "type": row["type"],
                "note": row["libelle"],
                "exceptionnel": False,
                "affM": aff_m,
                "affY": aff_y,
            })
            added += 1
        persist()
        st.success(f"✓ {added} transactions importées.")
        st.rerun()


def _guess_cat(libelle, cats):
    """Devine la catégorie depuis le libellé bancaire."""
    lib = libelle.lower()
    rules = [
        (["salaire", "are ", "allocation", "caf ", "prime"], "ARE / Salaire"),
        (["courses", "carrefour", "leclerc", "lidl", "aldi", "monop", "supermarché", "nourriture"], "Nourriture"),
        (["loyer", "prêt", "credit", "crédit", "sgfgas", "caisse epargne", "regroupement"], "Prêt / Assurance"),
        (["assurance", "groupama", "predica", "maaf", "axa"], "Prêt / Assurance"),
        (["sncf", "ratp", "essence", "total", "bp ", "shell", "péage", "autoroute"], "Voiture"),
        (["netflix", "spotify", "canal", "sfr", "free", "orange", "bouygues", "amazon prime", "apple", "google"], "Abonnement"),
        (["pharmacie", "médecin", "docteur", "hopital", "clinique", "mutuelle"], "Santé"),
        (["école", "scolaire", "cantine", "clae", "périscolaire"], "CLAE / École"),
        (["sénégal", "senegal", "western union", "transfert"], "Sénégal"),
        (["virement", "transfer"], "Virement interne"),
        (["zara", "h&m", "primark", "coiffeur", "beauté"], "Habit / Beauté"),
        (["restaurant", "cinéma", "loisir", "vacances", "voyage", "hotel"], "Loisirs / Vacances"),
    ]
    for keywords, cat in rules:
        if any(kw in lib for kw in keywords):
            if cat in cats:
                return cat
    return cats[0] if cats else "Divers"
