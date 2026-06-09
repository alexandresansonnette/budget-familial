"""
Budget Familial AS — Module calculs
Source unique de vérité pour tous les calculs financiers.

Règles fondamentales :
- Solde = solde_debut + Σ TX réelles du mois
- MC : dépenses affectées à un mois, déduites du CA en fin de mois
- Pas de TX récurrentes : les récurrentes servent uniquement au prévisionnel
- Une seule fonction pour chaque calcul MC
"""
import calendar
from datetime import datetime, date
from collections import defaultdict
from modules.data import mc_aff_from_date, CATS_NEUTRES, CATS_REVENUS


# ── Clé d'affectation d'une transaction ──────────────────────────────────────
def aff_key(t):
    """Retourne (year, month_0indexed) du mois auquel la TX est affectée."""
    if t.get("compte") == "mc":
        return (int(t["affY"]), int(t["affM"]))
    d = datetime.strptime(t["date"], "%Y-%m-%d")
    return (d.year, d.month - 1)


def month_add(m, y, n):
    """Ajoute n mois à (m, y) 0-indexed."""
    total = y * 12 + m + n
    return total % 12, total // 12


# ── MC : fonctions centralisées ───────────────────────────────────────────────
def mc_depenses_mois(tx, m, y, jusqu_au=None):
    """
    Total des dépenses MC affectées au mois (m, y).
    jusqu_au : datetime optionnel — filtre sur la date réelle de la TX.
    """
    txs = [t for t in tx
           if t["compte"] == "mc"
           and t["type"] == "depense"
           and aff_key(t) == (y, m)]
    if jusqu_au is not None:
        txs = [t for t in txs
               if datetime.strptime(t["date"], "%Y-%m-%d") <= jusqu_au]
    return sum(t["montant"] for t in txs)


def mc_rec_total(rec):
    """Total mensuel des récurrentes MC dépenses."""
    return sum(r["mnt"] for r in rec
               if r["compte"] == "mc" and r["type"] == "depense")


# ── Soldes ───────────────────────────────────────────────────────────────────
def get_sol(sol_dict, cpt, m, y):
    v = sol_dict.get(f"{cpt}_{y}_{m}")
    return float(v) if v is not None else None


def set_sol(sol_dict, cpt, m, y, v):
    k = f"{cpt}_{y}_{m}"
    if v is not None:
        sol_dict[k] = v
    else:
        sol_dict.pop(k, None)


def resolve_sol(D, cpt_id, target_m, target_y):
    """
    Retourne (solde_debut_mois, source) en cherchant le solde saisi
    le plus proche et en propageant via les TX réelles.
    """
    v = get_sol(D["sol"], cpt_id, target_m, target_y)
    if v is not None:
        return v, "saisi"

    target_abs = target_y * 12 + target_m
    candidates = []
    for key, val in D["sol"].items():
        parts = key.split("_")
        if len(parts) == 3 and parts[0] == cpt_id:
            try:
                ky, km = int(parts[1]), int(parts[2])
                candidates.append((ky * 12 + km, km, ky, float(val)))
            except ValueError:
                pass

    if not candidates:
        return None, None

    past = [(a, m, y, v) for a, m, y, v in candidates if a <= target_abs]
    future = [(a, m, y, v) for a, m, y, v in candidates if a > target_abs]

    if past:
        src_abs, src_m, src_y, src_val = max(past, key=lambda x: x[0])
    elif future:
        src_abs, src_m, src_y, src_val = min(future, key=lambda x: x[0])
    else:
        return None, None

    sol = src_val
    step = 1 if src_abs <= target_abs else -1
    cur_abs = src_abs
    while cur_abs != target_abs:
        if step == 1:
            cur_m, cur_y = cur_abs % 12, cur_abs // 12
            mvt = _mvt_net(D, cpt_id, cur_m, cur_y)
            sol += mvt
        else:
            prev_abs = cur_abs - 1
            prev_m, prev_y = prev_abs % 12, prev_abs // 12
            mvt = _mvt_net(D, cpt_id, prev_m, prev_y)
            sol -= mvt
        cur_abs += step

    return sol, "calculé"


def _mvt_net(D, cpt_id, m, y):
    """Mouvement net réel d'un compte sur un mois (revenus - dépenses - MC si CA)."""
    tx_m = [t for t in D["tx"]
            if t["compte"] == cpt_id and aff_key(t) == (y, m)]
    mvt = sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
              for t in tx_m)
    if cpt_id == "ca":
        mvt -= mc_depenses_mois(D["tx"], m, y)
    return mvt


def solde_a_date(D, cpt_id):
    """Solde réel du compte à l'instant présent (MC déduite pour CA)."""
    now = datetime.now()
    m, y = now.month - 1, now.year
    deb = get_sol(D["sol"], cpt_id, m, y)
    if deb is None:
        return None
    txs = [t for t in D["tx"]
           if t["compte"] == cpt_id
           and aff_key(t) == (y, m)
           and datetime.strptime(t["date"], "%Y-%m-%d") <= now]
    sol = deb + sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
                    for t in txs)
    if cpt_id == "ca":
        sol -= mc_depenses_mois(D["tx"], m, y, jusqu_au=now)
    return sol


def solde_bancaire(D, cpt_id):
    """
    Solde tel qu'affiché sur le relevé bancaire.
    Pour CA : sans déduire l'encours MC (la MC n'est pas encore prélevée).
    """
    now = datetime.now()
    m, y = now.month - 1, now.year
    deb = get_sol(D["sol"], cpt_id, m, y)
    if deb is None:
        return None
    txs = [t for t in D["tx"]
           if t["compte"] == cpt_id
           and aff_key(t) == (y, m)
           and datetime.strptime(t["date"], "%Y-%m-%d") <= now]
    return deb + sum(t["montant"] if t["type"] == "revenu" else -t["montant"]
                     for t in txs)


# ── Transactions filtrées ────────────────────────────────────────────────────
def tx_of_month(D, m, y, cpt_filter=None):
    txs = [t for t in D["tx"] if aff_key(t) == (y, m)]
    if cpt_filter:
        txs = [t for t in txs if t["compte"] == cpt_filter]
    return txs


def tx_mc_period(D, m, y):
    cal_m = m + 1
    cal_y = y
    if cal_m == 1:
        start = date(cal_y - 1, 12, 25)
    else:
        start = date(cal_y, cal_m - 1, 25)
    end = date(cal_y, cal_m, 24)
    return [t for t in D["tx"]
            if t["compte"] == "mc"
            and start <= datetime.strptime(t["date"], "%Y-%m-%d").date() <= end]


# ── Alertes ───────────────────────────────────────────────────────────────────
def alertes(D, cpt_id):
    od = D["overdraft"].get(cpt_id, 0)
    solde = solde_a_date(D, cpt_id)
    if solde is None:
        return []
    alts = []
    if solde < -od:
        alts.append(("danger", "Solde dans le rouge"))
    elif solde < (-od + 300):
        alts.append(("warn", "Solde proche de la limite"))
    return alts


def rec_futures(D, cpt_id):
    now = datetime.now()
    m, y = now.month - 1, now.year
    tx_noms = {t.get("note", "").strip().lower()
               for t in D["tx"] if aff_key(t) == (y, m) and t["compte"] == cpt_id}
    result = []
    for r in D["rec"]:
        if r["compte"] != cpt_id:
            continue
        if r["jour"] <= now.day:
            continue
        if r["nom"].strip().lower() in tx_noms:
            continue
        result.append(r)
    return sorted(result, key=lambda r: r["jour"])


# ── Matching récurrentes robuste ──────────────────────────────────────────────
def _rec_deja_couverte(r, tx_mois):
    """
    True si une TX réelle couvre déjà cette récurrente.
    Matching par type + montant à ±2% — indépendant du nom.
    """
    for t in tx_mois:
        if t["type"] != r["type"]:
            continue
        if abs(t["montant"] - r["mnt"]) / max(r["mnt"], 0.01) <= 0.02:
            return True
    return False


# ── Projection fin de mois ────────────────────────────────────────────────────
def projection_fin_mois(D, cpt_id):
    """
    Projette le solde jour par jour sur le mois courant.

    Principe d'ancrage :
    - Jours passés (< aujourd'hui) : recalculés depuis sol_debut + TX réelles
    - Jour courant : ANCRÉ sur solde_bancaire() — colle exactement au relevé
    - Jours futurs : projetés depuis l'ancrage via récurrentes manquantes + MC

    Format proj["jours"] : [(date_str, solde, [(nom, delta, cle, is_coche)])]
    """
    import streamlit as st

    now = datetime.now()
    m, y = now.month - 1, now.year
    last_day = calendar.monthrange(y, m + 1)[1]
    od = D["overdraft"].get(cpt_id, 0)
    limite = -od

    sol_debut, _ = resolve_sol(D, cpt_id, m, y)
    if sol_debut is None:
        return {"solde_actuel": None, "jours": [], "solde_fin": None,
                "point_bas": (None, None), "statut": "ok",
                "od": od, "marge": None, "limite": limite, "manque": 0}

    # Ancrage : solde bancaire réel à aujourd'hui
    sol_ancre = solde_bancaire(D, cpt_id)
    if sol_ancre is None:
        sol_ancre = sol_debut

    solde_act = solde_a_date(D, cpt_id)

    # Événements cochés et one-shot depuis session_state
    coches = st.session_state.get("evt_coches", {}).get(cpt_id, set())
    one_shots = st.session_state.get("evt_one_shot", {}).get(cpt_id, [])

    # ── Construire les deltas futurs (jours > aujourd'hui) ────────────────
    # Structure : jour → [(nom, delta, is_future, cle)]
    daily_future = defaultdict(list)

    # TX réelles futures (saisies en avance)
    for t in D["tx"]:
        if t["compte"] != cpt_id:
            continue
        if aff_key(t) != (y, m):
            continue
        d_obj = datetime.strptime(t["date"], "%Y-%m-%d")
        if d_obj.date() <= now.date():
            continue  # déjà dans l'ancrage
        delta = t["montant"] if t["type"] == "revenu" else -t["montant"]
        nom = t.get("note") or t["categorie"]
        cle = f"tx_{t.get('id', nom)}_{d_obj.day}"
        daily_future[d_obj.day].append((nom, delta, True, cle))

    # Récurrentes non encore couvertes (matching robuste type+montant ±2%)
    tx_mois = [t for t in D["tx"] if aff_key(t) == (y, m) and t["compte"] == cpt_id]
    for r in D["rec"]:
        if r["compte"] != cpt_id:
            continue
        if r["jour"] <= now.day:
            continue  # jour passé, déjà dans l'ancrage
        if _rec_deja_couverte(r, tx_mois):
            continue  # déjà une TX réelle qui couvre
        delta = r["mnt"] if r["type"] == "revenu" else -r["mnt"]
        cle = f"rec_{r['nom']}_{r['jour']}"
        daily_future[r["jour"]].append((r["nom"], delta, True, cle))

    # Prélèvement MC total sur CA en fin de mois
    if cpt_id == "ca":
        mc_tot = mc_depenses_mois(D["tx"], m, y)
        mc_rec_manquant = 0
        for r in D["rec"]:
            if r["compte"] != "mc" or r["type"] != "depense":
                continue
            deja = any(
                t["type"] == "depense"
                and abs(t["montant"] - r["mnt"]) / max(r["mnt"], 0.01) <= 0.02
                for t in D["tx"] if t["compte"] == "mc" and aff_key(t) == (y, m)
            )
            if not deja:
                mc_rec_manquant += r["mnt"]
        mc_a_prelever = mc_tot + mc_rec_manquant
        if mc_a_prelever > 0:
            cle = f"mc_prelevement_{last_day}"
            daily_future[last_day].append(("Prélèvement MC", -mc_a_prelever, True, cle))

    # Événements one-shot ajoutés manuellement
    for evt in one_shots:
        if evt["jour"] <= now.day:
            continue  # passé, ignoré
        delta = evt["montant"] if evt["type"] == "revenu" else -evt["montant"]
        cle = f"oneshot_{evt['jour']}_{evt['nom']}"
        daily_future[evt["jour"]].append((evt["nom"], delta, True, cle))

    # ── Construire les deltas passés (jours 1..aujourd'hui) ───────────────
    # Pour l'affichage du graphe passé uniquement — on repart de sol_debut
    daily_past = defaultdict(list)
    for t in D["tx"]:
        if t["compte"] != cpt_id:
            continue
        if aff_key(t) != (y, m):
            continue
        d_obj = datetime.strptime(t["date"], "%Y-%m-%d")
        if d_obj.date() > now.date():
            continue
        delta = t["montant"] if t["type"] == "revenu" else -t["montant"]
        nom = t.get("note") or t["categorie"]
        cle = f"tx_{t.get('id', nom)}_{d_obj.day}"
        daily_past[d_obj.day].append((nom, delta, False, cle))

    # ── Rejouer jour par jour ─────────────────────────────────────────────
    jours = []
    point_bas_sol = sol_ancre
    point_bas_jour = now.day

    # Passé : recalcul depuis sol_debut pour le graphe
    sol_passé = sol_debut
    for day in range(1, now.day):
        evts = daily_past.get(day, [])
        for nom, delta, _, cle in evts:
            sol_passé += delta
        date_str = f"{day:02d}/{m+1:02d}"
        jours.append((date_str, round(sol_passé, 2), []))
        if sol_passé < point_bas_sol:
            point_bas_sol = sol_passé
            point_bas_jour = day

    # Aujourd'hui : ancrage sur solde_bancaire réel
    date_str_today = f"{now.day:02d}/{m+1:02d}"
    jours.append((date_str_today, round(sol_ancre, 2), []))
    if sol_ancre < point_bas_sol:
        point_bas_sol = sol_ancre
        point_bas_jour = now.day

    # Futur : projection depuis l'ancrage
    sol = sol_ancre
    for day in range(now.day + 1, last_day + 1):
        evts = daily_future.get(day, [])
        evts_affich = []
        for nom, delta, is_future, cle in evts:
            if cle not in coches:
                sol += delta
            evts_affich.append((nom, delta, cle, (cle in coches)))
        date_str = f"{day:02d}/{m+1:02d}"
        jours.append((date_str, round(sol, 2), evts_affich))
        if sol < point_bas_sol:
            point_bas_sol = sol
            point_bas_jour = day

    sol_fin = jours[-1][1] if jours else sol_ancre
    marge = sol_fin - limite
    manque = max(0.0, -(min(point_bas_sol, sol_fin) - limite))

    if point_bas_sol < limite:
        statut = "danger"
    elif point_bas_sol < limite + 300:
        statut = "warn"
    else:
        statut = "ok"

    return {
        "solde_actuel": solde_act,
        "sol_debut": sol_debut,
        "jours": jours,
        "solde_fin": sol_fin,
        "point_bas": (f"{point_bas_jour:02d}/{m+1:02d}", round(point_bas_sol, 2)),
        "point_bas_jour": point_bas_jour,
        "manque": round(manque, 2),
        "statut": statut,
        "od": od,
        "marge": round(marge, 2),
        "limite": limite,
    }
