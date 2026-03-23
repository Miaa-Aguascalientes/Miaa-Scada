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
import datetime as dt

# --- DETECCIÓN DE PARÁMETROS DE URL (NUEVA PÁGINA) ---
query_params = st.query_params
sector_filtrado = query_params.get("sector")

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title=f"MIAA - {sector_filtrado if sector_filtrado else 'Estado de Pozos'}", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="collapsed" if sector_filtrado else "expanded"
)

# 2. ESTILO CSS (Tu estilo original completo)
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed; top: 15px; left: 50%; transform: translateX(-50%);
            z-index: 9999999; color: #00d4ff; font-size: 1.5rem; font-weight: bold;
            text-transform: uppercase; letter-spacing: 2px; white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5); animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff, 0 0 10px #00d4ff; transform: translateX(-50%) scale(1); }
            to { text-shadow: 0 0 15px #00d4ff, 0 0 25px #0077ff; transform: translateX(-50%) scale(1.02); }
        }
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN (Tus funciones originales)
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. CARGA DE DATOS
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
    nuevo_mapa = {}
    for _, row in df_pozos.iterrows():
        try:
            coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
            lat, lon = map(float, coords_str.split(','))
            nuevo_mapa[row['Pozos']] = {
                "coord": (lat, lon), "bomba": row['bomba'], "caudal": row['caudal'],
                "presion": row['presion'], "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'], "nivel_tanque": row['nivel_tanque'],
                "columna": row['columna'], "h_arranque": row['H_arranque'], "h_paro": row['H_paro'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']],
                "sector": row.get('sector_hidrometrico', 'Sin Sector') # Asegúrate que este campo existe
            }
        except: continue
    return nuevo_mapa

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
    return pd.read_sql(query, conn).to_dict('records')

# 5. PROCESAMIENTO Y FILTRADO
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
# (Aquí iría tu lógica de cargar_datos_scada y el bucle de estados de pozo idéntico al tuyo)

# --- VISTA DE PÁGINA NUEVA (DETALLE DE SECTOR) ---
if sector_filtrado:
    st.markdown(f'<div class="titulo-superior">DETALLE SECTOR: {sector_filtrado}</div>', unsafe_allow_html=True)
    
    # 1. Filtrar polígono
    geo_sector = [s for s in sectores if s['sector'] == sector_filtrado]
    # 2. Filtrar pozos que pertenecen a ese sector
    pozos_del_sector = {id_p: info for id_p, info in mapa_pozos_dict.items() if str(info.get('sector')) == sector_filtrado}
    
    if geo_sector:
        m = folium.Map(location=json.loads(geo_sector[0]['geo'])['coordinates'][0][0][::-1], zoom_start=14, tiles="CartoDB dark_matter")
        folium.GeoJson(json.loads(geo_sector[0]['geo']), style_function=lambda x: {'color': '#00d4ff', 'fillOpacity': 0.2}).add_to(m)
        
        # Renderizar solo los pozos de este sector (con tu popup de 500 líneas)
        for id_p, info in pozos_del_sector.items():
            # ... (Aquí pegas todo tu bloque de HTML_POPUP detallado) ...
            folium.Marker(location=info['coord'], popup=folium.Popup("Tu HTML Detallado", max_width=450)).add_to(m)
            
        folium_static(m, width=None, height=800)
    else:
        st.error("Sector no encontrado.")
    st.stop() # Detiene la ejecución aquí para que no cargue el resto de la web

# --- VISTA PRINCIPAL (EL DASHBOARD COMPLETO) ---
st.markdown('<div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["🗺️ Mapa", "📊 Información de Sectores"])

with tab2:
    st.write("### Seleccione un sector para abrir en pestaña nueva")
    if sectores:
        df_sec = pd.DataFrame(sectores)[['sector']]
        # Creamos una columna con el enlace a la "Página nueva"
        # Usamos st.Page_link o un simple HTML
        for s_name in df_sec['sector']:
            col_a, col_b = st.columns([0.8, 0.2])
            col_a.write(f"Sector: **{s_name}**")
            # El enlace abre la misma URL de tu app pero con el parámetro ?sector=...
            url_detalle = f"/?sector={urllib.parse.quote(s_name)}"
            col_b.markdown(f'<a href="{url_detalle}" target="_blank" style="background:#00d4ff; color:black; padding:5px 10px; border-radius:5px; text-decoration:none; font-weight:bold;">Abrir Detalle ↗️</a>', unsafe_allow_html=True)

with tab1:
    # (Aquí va tu mapa general con todos los pozos y sectores como lo tenías)
    pass
