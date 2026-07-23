import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import hashlib
import bcrypt
import time
import urllib.parse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from folium.plugins import MousePosition, LocateControl
from streamlit_folium import st_folium
import locale
from shapely import wkt
import geopandas as gpd
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError
import pytz

st.set_page_config(
    page_title="Sistema Scada", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 0. SECCION -------------------------------------------------------------------------------- 0. SISTEMA DE AUTENTICACIÓN HUD DEFINITIVO --------------------------------------------------------------------

# 0.1. INICIALIZACIÓN DE ESTADOS 
if 'autenticado' not in st.session_state:
    query_params = st.query_params
    if query_params.get("access") == "granted":
        st.session_state.autenticado = True
        st.session_state.rol = query_params.get("role", "usuario")
    else:
        st.session_state.autenticado = False

if 'fase_carga' not in st.session_state:
    st.session_state.fase_carga = False

# 0.2. FUNCIONES DE BASE DE DATOS (REFORZADAS) 
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(
            f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}",
            pool_recycle=3600,
            pool_pre_ping=True
        )
        return engine
    except Exception as e:
        st.error(f"⚠️ ERROR CRÍTICO DE CONEXIÓN: {e}")
        return None

def verificar_credenciales(usuario_input, password_input):
    try:
        engine = get_mysql_telemetria_engine()
        if engine is None: return None
        query = f"SELECT password, tipo_usuario FROM usuarios WHERE usuario = '{usuario_input}'"
        df_user = pd.read_sql(query, engine)
        if not df_user.empty and str(password_input) == str(df_user['password'].iloc[0]):
            return df_user['tipo_usuario'].iloc[0]
        return None
    except Exception as e:
        st.error(f"Error al consultar usuario: {e}")
        return None

# 0.3. ESTILO VISUAL HUD AJUSTADO
st.markdown("""
<style>
    /* Configuración base */
    .stApp { background-color: #050a10 !important; }
    .block-container { padding: 0 !important; max-width: 100% !important; }
    header, footer { visibility: hidden !important; }
    
    /* HUD Visual Elements */
    .visual-core { position: relative; width: 480px; height: 480px; margin: auto; }
    .ring { position: absolute; border-radius: 50%; border: 4px solid transparent; animation: spin var(--d) linear infinite; }
    .r1 { width: 100%; height: 100%; border-top: 8px solid #00d4ff; border-bottom: 8px solid #00d4ff; --d: 4s; }
    .r2 { width: 78%; height: 78%; top: 11%; left: 11%; border: 3px dashed #00d4ff; --d: 8s; animation-direction: reverse; }
    .center-logo { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; }
    .logo-miaa { width: 190px; filter: drop-shadow(0 0 15px #00d4ff); }
    
    /* Login Box */
    .login-box { 
        background: rgba(0, 212, 255, 0.05); 
        border-left: 8px solid #00d4ff; 
        padding: 30px; 
        margin-top: 50px;
        max-width: 320px;
        margin-left: 0;
    }
    
    @keyframes spin { 100% { transform: rotate(360deg); } }
    
    div[data-testid="stTextInputRootElement"] {
        background-color: #0d1b2a !important;
        border: 1px solid #1f4068 !important;
        border-radius: 0px !important;
        padding: 0px 10px !important; 
        height: 40px !important;
        box-shadow: none !important;
    }
    
    .stTextInput input { 
        background-color: transparent !important; 
        color: #00d4ff !important; 
        border: none !important;
        height: 100% !important;
        font-family: 'Courier New', monospace;
        font-size: 15px !important;
        padding: 0 !important;
    }
    
    div[data-testid="stTextInputRootElement"]:focus-within {
        border: 1px solid #00d4ff !important;
        box-shadow: none !important;
    }
    
    .stButton button { 
        background: #00d4ff !important; 
        color: #050a10 !important; 
        font-weight: bold !important; 
        width: 100%; 
        height: 45px; 
        border: none !important;
        border-radius: 0px !important;
    }
    
    div[data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# 0.4. LÓGICA DE INTERFAZ 
if not st.session_state.autenticado:
    col_esp1, col_vis, col_log, col_esp2 = st.columns([0.1, 1.8, 2, 1.1])
    
    with col_vis:
        st.markdown('<div style="height: 12vh;"></div>', unsafe_allow_html=True)
        st.markdown(f'''
        <div class="visual-core">
            <div class="ring r1"></div><div class="ring r2"></div>
            <div class="center-logo">
                <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" class="logo-miaa">
                <h2 style="color:#00d4ff; font-family:Orbitron; font-size:-400px; letter-spacing:5px; margin-top:-35px;"></h2>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    with col_log:
        st.markdown('<div style="height: 20vh;"></div>', unsafe_allow_html=True)
        
        if not st.session_state.fase_carga:
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            st.markdown('<h2 style="color:#00d4ff; font-size:18px;">// INGRESE SUS CREDENCIALES</h2>', unsafe_allow_html=True)
            
            with st.form("login_form", clear_on_submit=False):
                u = st.text_input("USUARIO", key="u_login")
                p = st.text_input("PASSWORD", type="password", key="p_login")
                
                submit_button = st.form_submit_button("ACCEDER AL SISTEMA")
                
                if submit_button:
                    rol = verificar_credenciales(u, p)
                    if rol:
                        st.session_state.temp_rol = rol
                        st.session_state.fase_carga = True
                        st.rerun()
                    else:
                        st.error("❌ ACCESO DENEGADO")
            st.markdown('</div>', unsafe_allow_html=True)
            
        else:
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            st.markdown('<h2 style="color:#00d4ff; font-size:18px;">// CARGANDO SCADA...</h2>', unsafe_allow_html=True)
            prog = st.progress(0)
            status = st.empty()
            
            tareas = [
                ("Conectando DB", "get_mysql_telemetria_engine"),
                ("Sectores", "cargar_sectores_poligonos"),
                ("Pozos", "cargar_mapa_pozos_desde_db"),
                ("Tanques", "cargar_tanques_desde_db"),
                ("Rebombeos", "cargar_rebombeos_desde_db")
            ]
            
            for i, (nombre, func) in enumerate(tareas):
                status.write(f"Cargando {nombre}...")
                if func in globals():
                    try:
                        globals()[func]()
                    except Exception as e:
                        st.warning(f"Error en {nombre}: {e}")
                prog.progress((i + 1) / len(tareas))
                time.sleep(0.4)

            st.cache_data.clear()
            st.cache_resource.clear()
            st.session_state.autenticado = True
            st.session_state.rol = st.session_state.temp_rol
            st.session_state.fase_carga = False
            st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
    st.stop()
