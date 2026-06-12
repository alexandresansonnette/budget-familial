"""
Mocks des dépendances externes — les tests tournent sans connexion,
sans secrets Google, sans Streamlit. `pytest` depuis la racine du repo.
"""
import sys
import types
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Streamlit minimal
_st = types.ModuleType("streamlit")
_st.cache_resource = lambda f: f
_st.secrets = {}
_st.session_state = {}
sys.modules.setdefault("streamlit", _st)

# gspread minimal
_gs = types.ModuleType("gspread")
_gs.WorksheetNotFound = type("WorksheetNotFound", (Exception,), {})
_gs.authorize = lambda *a, **k: None
sys.modules.setdefault("gspread", _gs)

# google.oauth2.service_account minimal
_g = types.ModuleType("google")
_g_oauth2 = types.ModuleType("google.oauth2")
_g_sa = types.ModuleType("google.oauth2.service_account")
_g_sa.Credentials = type("Credentials", (), {
    "from_service_account_info": staticmethod(lambda *a, **k: None)})
_g.oauth2 = _g_oauth2
_g_oauth2.service_account = _g_sa
sys.modules.setdefault("google", _g)
sys.modules.setdefault("google.oauth2", _g_oauth2)
sys.modules.setdefault("google.oauth2.service_account", _g_sa)
