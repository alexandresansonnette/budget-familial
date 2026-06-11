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

# Mots-clés pour détecter le prélèvement Mastercard sur un relevé CA.
# Cette ligne ne doit JAMAIS être importée : la MC est déjà déduite
# automatiquement du solde CA par le modèle (mc_depenses_mois).
MC_RELEVE_KEYWORDS = [
    "mastercard", "master card", "debit differe", "débit différé",
    "releve carte", "relevé carte", "retrait differe", "retrait différé",
]


def _is_releve_mc(libelle):
    lib = libelle.lower()
    return any(kw in lib for kw in MC_RELEVE_KEYWORDS)


def render(D, persist, cur_m=None, cur_y=None):
    st.subheader("📋 Transactions")

    now = datetime.now()
    # Utiliser la navigation globale si fournie
    default_m = cur_m if cur_m is not None else now.month - 1
    default_y = cur_y if cur_y is not None else now.year

    # ── Filtres ───────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        cpt_opts = {"all": "Tous les comptes", **{k: v["label"] for k, v in COMPTES.items()}}
        filt_cpt = st.selectbox("Compte", list(cpt_opts.keys()),
                                format_func=lambda x: cpt_opts[x], key="tx_filt_cpt")
    with f2:
        annees = sorted({datetime.strptime(t["date"], "%Y-%m-%d").year
                         for t in D["tx"]}, reverse=True) or [default_y]
        filt_y = st.selectbox("Année", annees,
                              index=annees.index(default_y) if default_y in annees else 0,
                              key="tx_filt_y")
    with f3:
        filt_m = st.selectbox("Mois", range(12), index=default_m,
                              format_func=lambda x: MOIS[x], key="tx_filt_m")
    with f4:
        show_exc = st.checkbox("⭐ Excep.", value=False, key="tx_show_exc",
                               help="Afficher uniquement les exceptionnelles")

    # Filtrage
    def match(t):
        if filt_cpt != "all" and t["compte"] != filt_cpt:
            return False
        ak = aff_key(t)
        if ak != (filt_y, filt_m):
            return False
        return True

    # Filtre par mois d'affectation (aff_key)
    # Tri par date réelle décroissante.
    # Pour MC : les TX du 25/12 au 31/12 sont les premières du mois
    # d'affectation suivant → elles apparaissent en bas (les plus anciennes).
    tx_filtered = [t for t in D["tx"] if match(t)]
    if show_exc:
        tx_filtered = [t for t in tx_filtered if t.get("exceptionnel", False)]
    tx_show = sorted(tx_filtered, key=lambda t: t["date"], reverse=True)

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

    # ── Détection des doublons ────────────────────────────────────────────
    with st.expander("🔍 Détecter les doublons", expanded=False):
        st.caption(f"Analyse sur **{MOIS[filt_m]} {filt_y}** — {cpt_opts.get(filt_cpt, filt_cpt)}")
        from collections import defaultdict
        groupes = defaultdict(list)
        for t in D["tx"]:
            if filt_cpt != "all" and t["compte"] != filt_cpt:
                continue
            if aff_key(t) != (filt_y, filt_m):
                continue
            key = (
                t["compte"],
                round(t["montant"], 2),
                t.get("note", "").strip().lower(),
                t["date"]
            )
            groupes[key].append(t)
        doublons = {k: v for k, v in groupes.items() if len(v) > 1}
        if not doublons:
            st.success(f"✅ Aucun doublon sur {MOIS[filt_m]} {filt_y}.")
        else:
            st.warning(f"⚠️ **{len(doublons)} groupe(s) de doublons détectés** — vérifiez et supprimez les entrées en trop.")
            for key, txs in doublons.items():
                cpt, mnt, note, date_d = key
                cpt_lbl = COMPTES.get(cpt, {"label": cpt})["label"]
                st.markdown(
                    f"**{date_d} — {cpt_lbl} — {fmt2(mnt)} — {note or '(sans note)'}**"
                    f" → {len(txs)} occurrences"
                )
                for i, t in enumerate(txs):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    aff = ""
                    if t["compte"] == "mc":
                        aff = f" → affecté {MOIS[int(t['affM'])]} {int(t['affY'])}"
                    c1.caption(f"#{i+1} — {t['id']}{aff}")
                    c2.caption(f"Catégorie : {t['categorie']}")
                    if i > 0:  # Proposer suppression sur les doublons (pas le premier)
                        if c3.button("🗑 Supprimer", key=f"dup_del_{t['id']}",
                                     help="Garder le premier, supprimer celui-ci"):
                            D["tx"] = [x for x in D["tx"] if x["id"] != t["id"]]
                            persist()
                            st.success(f"✓ Supprimé.")
                            st.rerun()
                    else:
                        c3.caption("✓ garder")
                st.divider()

    st.divider()

    # ── Tableau principal ─────────────────────────────────────────────────
    if not tx_show:
        st.info("Aucune transaction pour ce filtre.")
        return

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
                    # Lire l'affectation MC depuis session_state (valeur du selectbox au moment du submit)
                    final_aff_m = st.session_state.get(f"eaff_m_{t['id']}", aff_m_val)
                    final_aff_y = st.session_state.get(f"eaff_y_{t['id']}", aff_y_val)
                    # Sécurité : une TX MC doit toujours avoir une affectation
                    if new_cpt == "mc" and (final_aff_m is None or final_aff_y is None):
                        final_aff_m, final_aff_y = mc_aff_from_date(date_str)
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
                        "affM": final_aff_m,
                        "affY": final_aff_y,
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
        if tx_cpt == "mc":
            auto_m, auto_y = mc_aff_from_date(tx_date.strftime("%Y-%m-%d"))
            st.caption(f"💳 Affectation calculée : **{MOIS[auto_m]} {auto_y}**  *(modifiable ci-dessous si nécessaire)*")
            ov1, ov2 = st.columns(2)
            # Clé dépend de la date → Streamlit réinitialise le selectbox si la date change
            date_key = tx_date.strftime("%Y%m%d")
            ov1.selectbox("Mois affectation", range(12),
                          index=auto_m, format_func=lambda x: MOIS[x],
                          key=f"saisie_aff_m_{date_key}")
            ov2.selectbox("Année", list(range(2024, 2029)),
                          index=list(range(2024, 2029)).index(auto_y) if auto_y in range(2024, 2029) else 0,
                          key=f"saisie_aff_y_{date_key}")

        if st.form_submit_button("✅ Ajouter", type="primary", use_container_width=True):
            date_str = tx_date.strftime("%Y-%m-%d")
            st.session_state.saisie_last_date = tx_date  # mémoriser la date
            aff_m, aff_y = (None, None)
            if tx_cpt == "mc":
                # FIX v2.1 : lire les VRAIES clés des selectbox d'override
                # (avant : clés "saisie_sel_m"/"saisie_sel_y" inexistantes
                #  → l'override manuel était silencieusement ignoré)
                date_key = tx_date.strftime("%Y%m%d")
                aff_m = st.session_state.get(f"saisie_aff_m_{date_key}", auto_m)
                aff_y = st.session_state.get(f"saisie_aff_y_{date_key}", auto_y)

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

    if cpt_import == "ca":
        st.warning("💳 Les lignes « prélèvement Mastercard » du relevé CA seront "
                   "**décochées automatiquement** : la MC est déjà déduite du "
                   "solde CA par l'app. Les importer créerait un double comptage.")

    uploaded = st.file_uploader("Relevé bancaire (CSV ou PDF)",
                                type=["csv", "pdf"], key="import_csv")
    if not uploaded:
        return

    cats = visible_cats(D)
    pending = []

    # ── v2.5 étape 4 : RELEVÉ PDF ─────────────────────────────────────────
    if uploaded.name.lower().endswith(".pdf"):
        from modules.extraction_pdf import extraire_releve_pdf
        annee_pdf = st.number_input(
            "Année du relevé (si les dates du PDF sont en JJ/MM)",
            min_value=2020, max_value=2035, value=datetime.now().year,
            key="import_pdf_annee")
        try:
            pending, n_carte = extraire_releve_pdf(uploaded,
                                                   annee_defaut=int(annee_pdf))
        except Exception as e:
            st.error(f"Erreur extraction PDF : {e}")
            return
        if n_carte:
            st.info(f"💳 {n_carte} ligne(s) de récapitulatif carte ignorée(s) "
                    f"(déjà déduites par l'app).")
        if not pending:
            st.warning("Aucune opération détectée dans ce PDF — "
                       "le format du relevé n'est peut-être pas tabulaire.")
            return
        st.info(f"{len(pending)} opérations extraites du PDF.")

    # ── CSV ───────────────────────────────────────────────────────────────
    else:
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

    # ══ v2.7 (B+C) : RAPPROCHEMENT BANCAIRE ═══════════════════════════════
    # Compare le relevé aux TX déjà saisies (même compte, même montant,
    # date exacte ou ±3 j pour les décalages date valeur/opération).
    certains, probables, pending, tx_absentes = _rapprocher_releve(
        pending, D, cpt_import)
    doublons_forces = []

    n_anomalies = len(probables) + len(tx_absentes)
    with st.expander(
        f"🔍 Rapprochement bancaire — {len(certains)} déjà saisie(s), "
        f"{len(probables)} probable(s), {len(tx_absentes)} TX appli "
        f"absente(s) du relevé",
        expanded=n_anomalies > 0
    ):
        # ⛔ Doublons certains : exclus d'office
        if certains:
            st.markdown("**⛔ Déjà présentes dans l'appli (montant + date "
                        "identiques) — exclues d'office :**")
            for di, (row, t, _) in enumerate(certains):
                c1, c2 = st.columns([4, 1])
                c1.caption(
                    f"{row['date']} · {row['libelle'][:35]} · "
                    f"{fmt2(row['montant'])} ↔ déjà saisi : "
                    f"« {t.get('note') or t['categorie']} » ({t['categorie']})")
                if c2.checkbox("Forcer", value=False, key=f"rap_force_{di}",
                               help="Importer quand même (vraie double dépense)"):
                    doublons_forces.append({**row, "categorie": t["categorie"]})

        # ⚠️ Doublons probables : à trancher
        if probables:
            st.markdown("**⚠️ Doublons probables (même montant, ±3 jours) — "
                        "décochés par défaut :**")
            for pi, (row, t, delta) in enumerate(probables):
                c1, c2 = st.columns([4, 1])
                c1.caption(
                    f"{row['date']} · {row['libelle'][:35]} · "
                    f"{fmt2(row['montant'])} ↔ "
                    f"« {t.get('note') or t['categorie']} » du {t['date']} "
                    f"(écart {delta} j)")
                if c2.checkbox("Importer", value=False, key=f"rap_prob_{pi}",
                               help="Cochez si ce sont bien 2 opérations distinctes"):
                    doublons_forces.append({**row, "categorie": t["categorie"]})

        # 🔎 TX de l'appli absentes du relevé : incohérence à vérifier
        if tx_absentes:
            st.markdown("**🔎 Saisies dans l'appli mais ABSENTES du relevé** "
                        "— montant ou date erronés ? mauvais compte ?")
            for t in sorted(tx_absentes, key=lambda x: x["date"]):
                sign = "+" if t["type"] == "revenu" else "−"
                st.caption(f"{t['date']} · {t.get('note') or t['categorie']} · "
                           f"{sign}{fmt2(t['montant'])} ({t['categorie']})")
            st.info("💡 Ouvrez ces TX dans la liste pour corriger montant/"
                    "date/compte — c'est la clé de la cohérence relevé ↔ appli.")

        if not certains and not probables and not tx_absentes:
            st.success("✓ Relevé et appli parfaitement cohérents sur la période.")

    if not pending and not doublons_forces:
        st.success("✓ Toutes les lignes du relevé sont déjà dans l'appli — "
                   "rien à importer.")
        return

    # ── v2.5 étape 2 : GROUPEMENT PAR LIBELLÉ + APPRENTISSAGE ────────────
    # Un libellé = une validation (15 passages Leclerc → 1 seul choix).
    # Libellé reconnu par le registre → catégorie pré-remplie.
    # Libellé inconnu → choix + mot-clé (tronc pré-extrait) MÉMORISÉ
    # dans D['cat_keywords'] à l'import → automatique la fois suivante.
    from modules.categorisation import (extraire_tronc, guess_cat,
                                        memoriser_mot_cle, est_op_opaque,
                                        cle_op, memoriser_op)
    from collections import defaultdict

    groupes_lib = defaultdict(list)
    for row in pending:
        groupes_lib[row["libelle"]].append(row)

    connus, inconnus, mc_releves, opaques = [], [], [], []
    for lib, rows_g in groupes_lib.items():
        if cpt_import == "ca" and _is_releve_mc(lib):
            mc_releves.append((lib, rows_g))
            continue
        # v2.5 ét.3 : chèques / P2P / virements opaques → traitement individuel
        if est_op_opaque(lib):
            opaques += rows_g
            continue
        proposed = guess_cat(D, lib, cats)
        if proposed and proposed in cats:
            connus.append((lib, rows_g, proposed))
        else:
            inconnus.append((lib, rows_g))

    n_tx_ok = sum(len(r) for _, r, _ in connus)
    st.markdown(f"**{len(pending)} lignes → {len(groupes_lib)} libellés distincts** : "
                f"{len(connus)} reconnus ({n_tx_ok} TX), "
                f"{len(inconnus)} à catégoriser, "
                f"{len(opaques)} opaque(s), "
                f"{len(mc_releves)} prélèvement(s) MC ignoré(s).")
    if mc_releves:
        st.info("💳 Prélèvements Mastercard exclus (déjà déduits par l'app) : "
                + " · ".join(lib[:35] for lib, _ in mc_releves))

    validated = list(doublons_forces)  # doublons forcés au rapprochement
    a_memoriser = []      # [(cat, mot_cle)] → registre de mots-clés
    a_memoriser_ops = []  # [(date, libelle, cat)] → ops_connues

    # ── Opérations OPAQUES : chèques, P2P, virements sans tronc ──────────
    # Une par une (le destinataire change), mémoire par (date, libellé).
    if opaques:
        st.markdown("**✍️ Opérations opaques — à catégoriser une par une "
                    "(chèque, Wero/Lydia, virement sans détail) :**")
        st.caption("Mémorisées individuellement par date+libellé — "
                   "jamais transformées en mot-clé général.")
        ops_connues = D.get("ops_connues", {})
        for oi, row in enumerate(sorted(opaques, key=lambda r: r["date"])):
            cle = cle_op(row["date"], row["libelle"])
            deja = ops_connues.get(cle)
            c1, c2, c3 = st.columns([3, 2, 1])
            sign = "+" if row["type"] == "revenu" else "−"
            c1.write(f"{row['date']} · **{row['libelle'][:38]}**")
            c1.caption(f"{sign}{fmt2(row['montant'])}"
                       + (" · 🧠 déjà connue" if deja else ""))
            opts = ["— Choisir —"] + cats
            idx = opts.index(deja) if deja in opts else 0
            cat_sel = c2.selectbox("Cat.", opts, index=idx,
                                   key=f"imp_op_cat_{oi}",
                                   label_visibility="collapsed")
            incl = c3.checkbox("✓", value=True, key=f"imp_op_ok_{oi}")
            if incl and cat_sel != "— Choisir —":
                validated.append({**row, "categorie": cat_sel})
                if cat_sel != deja:
                    a_memoriser_ops.append((row["date"], row["libelle"], cat_sel))

    # ── Libellés INCONNUS : choix + mot-clé mémorisé ──────────────────────
    if inconnus:
        st.markdown("**🆕 À catégoriser (sera mémorisé) :**")
        for gi, (lib, rows_g) in enumerate(sorted(inconnus)):
            tot = sum(r["montant"] if r["type"] == "revenu" else -r["montant"]
                      for r in rows_g)
            with st.container(border=True):
                c1, c2 = st.columns([3, 3])
                with c1:
                    st.write(f"**{lib[:45]}**")
                    st.caption(f"{len(rows_g)} occurrence(s) · net {fmt2(tot)}")
                with c2:
                    cat_sel = st.selectbox(
                        "Catégorie", ["— Choisir —"] + cats,
                        key=f"imp_inc_cat_{gi}", label_visibility="collapsed")
                    mot = st.text_input(
                        "🔑 Mot-clé mémorisé", value=extraire_tronc(lib),
                        key=f"imp_inc_mot_{gi}",
                        help="Raccourcissez si besoin (ex : NETFLIX)")
                incl = st.checkbox("Importer ces transactions", value=True,
                                   key=f"imp_inc_ok_{gi}")
                if incl and cat_sel != "— Choisir —":
                    validated += [{**r, "categorie": cat_sel} for r in rows_g]
                    if mot.strip():
                        a_memoriser.append((cat_sel, mot))
        non_choisis = sum(1 for gi, (lib, _) in enumerate(sorted(inconnus))
                          if st.session_state.get(f"imp_inc_cat_{gi}",
                                                  "— Choisir —") == "— Choisir —"
                          and st.session_state.get(f"imp_inc_ok_{gi}", True))
        if non_choisis:
            st.warning(f"⚠️ {non_choisis} libellé(s) sans catégorie — "
                       f"ils ne seront pas importés.")

    # ── Libellés RECONNUS : compact, modifiable ───────────────────────────
    if connus:
        with st.expander(f"✅ Reconnus automatiquement ({len(connus)} libellés) "
                         f"— vérifier / ajuster", expanded=False):
            for gi, (lib, rows_g, proposed) in enumerate(sorted(connus)):
                c1, c2, c3 = st.columns([3, 2, 1])
                tot = sum(r["montant"] if r["type"] == "revenu" else -r["montant"]
                          for r in rows_g)
                c1.write(f"{lib[:40]}")
                c1.caption(f"{len(rows_g)} TX · net {fmt2(tot)}")
                cat_sel = c2.selectbox(
                    "Cat.", cats, index=cats.index(proposed),
                    key=f"imp_con_cat_{gi}", label_visibility="collapsed")
                incl = c3.checkbox("✓", value=True, key=f"imp_con_ok_{gi}")
                if incl:
                    validated += [{**r, "categorie": cat_sel} for r in rows_g]
                    # Correction d'un reconnu = ré-apprentissage
                    if cat_sel != proposed:
                        a_memoriser.append((cat_sel, extraire_tronc(lib)))

    if st.button(f"✅ Importer {len(validated)} transactions", type="primary",
                 disabled=not validated):
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
        n_appris = sum(1 for cat, mot in a_memoriser
                       if memoriser_mot_cle(D, cat, mot))
        for d_op, lib_op, cat_op in a_memoriser_ops:
            memoriser_op(D, d_op, lib_op, cat_op)
        persist()
        msg = f"✓ {added} transactions importées."
        if n_appris:
            msg += f" 🧠 {n_appris} mot(s)-clé(s) mémorisé(s)."
        if a_memoriser_ops:
            msg += f" ✍️ {len(a_memoriser_ops)} opération(s) opaque(s) mémorisée(s)."
        st.success(msg)
        st.rerun()


def _guess_cat(libelle, cats, D=None):
    """
    Devine la catégorie depuis le libellé bancaire.
    v2.5 : utilise le registre APPRIS D['cat_keywords'] (persisté dans
    Sheets, enrichi à chaque validation manuelle). Les anciennes règles
    codées en dur servent d'amorçage via la migration.
    """
    if D is not None:
        from modules.categorisation import guess_cat
        cat = guess_cat(D, libelle, cats)
        if cat and cat in cats:
            return cat
    return cats[0] if cats else "Divers"


# ══ v2.7 (B+C) : Rapprochement bancaire ═════════════════════════════════════
def _rapprocher_releve(pending, D, cpt_import):
    """
    Rapproche les lignes du relevé des TX déjà saisies sur le même compte.
    Matching : même type + même montant (au centime) + écart de date :
      0 jour  → doublon CERTAIN (exclu d'office)
      ≤ 3 j   → doublon PROBABLE (date valeur vs date opération)
    Chaque TX existante ne peut matcher qu'UNE ligne du relevé
    (affectation gloutonne par écart croissant).

    Retourne (certains, probables, restants, tx_absentes) :
      certains/probables : [(ligne_releve, tx_existante, delta_jours)]
      restants           : lignes du relevé sans correspondance → import normal
      tx_absentes        : TX de l'appli sur la période, absentes du relevé
                           → incohérence à vérifier (rapprochement bancaire)
    """
    from datetime import timedelta
    if not pending:
        return [], [], pending, []

    dates_rel = [datetime.strptime(r["date"], "%Y-%m-%d") for r in pending]
    dmin = min(dates_rel) - timedelta(days=3)
    dmax = max(dates_rel) + timedelta(days=3)

    exist = []
    for t in D["tx"]:
        if t["compte"] != cpt_import:
            continue
        dt = datetime.strptime(t["date"], "%Y-%m-%d")
        if dmin <= dt <= dmax:
            exist.append(t)

    # Paires candidates triées par écart de date croissant
    paires = []
    for i, r in enumerate(pending):
        dr = datetime.strptime(r["date"], "%Y-%m-%d")
        for t in exist:
            if t["type"] != r["type"]:
                continue
            if abs(float(t["montant"]) - float(r["montant"])) > 0.005:
                continue
            delta = abs((datetime.strptime(t["date"], "%Y-%m-%d") - dr).days)
            if delta <= 3:
                paires.append((delta, i, t["id"], t))
    paires.sort(key=lambda p: p[0])

    used_rel, used_tx = set(), set()
    certains, probables = [], []
    for delta, i, tid, t in paires:
        if i in used_rel or tid in used_tx:
            continue
        used_rel.add(i)
        used_tx.add(tid)
        if delta == 0:
            certains.append((pending[i], t, delta))
        else:
            probables.append((pending[i], t, delta))

    restants = [r for i, r in enumerate(pending) if i not in used_rel]
    tx_absentes = [t for t in exist if t["id"] not in used_tx]
    return certains, probables, restants, tx_absentes
