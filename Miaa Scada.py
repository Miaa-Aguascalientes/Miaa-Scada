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

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - Estado de Pozos", layout="wide", initial_sidebar_state="expanded")

# 2. ESTILO CSS PARA LA ESTÉTICA DE LA IMAGEN
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .section-header { padding: 10px; border-radius: 3px; font-weight: bold; margin-bottom: 5px; color: white; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "bomba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_dinamico": "PZ_RP_005_TRHDAS_NIV_EST", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes_l": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"],
        "amperajes_l": ["PZ_RP_005_TRHDAS_CORR_L1", "PZ_RP_005_TRHDAS_CORR_L2", "PZ_RP_005_TRHDAS_CORR_L3"]
    },
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_dinamico": "PZ_006_TRC_NIV_EST",
        "nivel_tanque": "0", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes_l": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    }
}

# 4. FUNCIONES DE CARGA
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- 5. PROCESAMIENTO ---
data_scada = cargar_datos_scada()
sectores = cargar_sectores_poligonos()
ahora = datetime.now()

pozos_on, pozos_off, pozos_obs = [], [], []
total_q, total_p = 0.0, 0.0

for id_p, info in mapa_pozos_dict.items():
    val_bba, f_bba = data_scada.get(info['bomba'], (0, None))
    q_val = data_scada.get(info['caudal'], (0, 0))[0]
    p_val = data_scada.get(info['presion'], (0, 0))[0]
    
    if f_bba and (ahora - f_bba).total_seconds() > 14400:
        info.update({'status': 'OBSOLETO', 'color': 'orange'})
        pozos_obs.append(id_p)
    elif val_bba == 1:
        info.update({'status': 'ENCENDIDO', 'color': 'green'})
        pozos_on.append(id_p)
        total_q += q_val
        total_p += p_val
    else:
        info.update({'status': 'APAGADO', 'color': 'red'})
        pozos_off.append(id_p)

# --- 6. SIDEBAR ---
with st.sidebar:
    st.markdown("<h2 style='color:#00d4ff;'>📊 Estado de Pozos</h2>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="resumen-card">
        <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
        <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
        <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"<div class='section-header' style='background:#1b5e20;'>Bombas ON ({len(pozos_on)})</div>", unsafe_allow_html=True)
    for p in pozos_on: st.write(f"🟢 {p}")
    st.markdown(f"<div class='section-header' style='background:#b71c1c;'>Bombas OFF ({len(pozos_off)})</div>", unsafe_allow_html=True)
    for p in pozos_off: st.write(f"🔴 {p}")
    st.markdown(f"<div class='section-header' style='background:#4a148c;'>Obsoletos ({len(pozos_obs)})</div>", unsafe_allow_html=True)
    for p in pozos_obs: st.write(f"🟡 {p}")

# --- 7. MAPA CON CONTROL DE CAPAS ---
m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles=None)

# Mapas Base
folium.TileLayer("CartoDB dark_matter", name="CartoDB Dark (Default)").add_to(m)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap (Claro)").add_to(m)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Esri Satellite'
).add_to(m)

# Grupos de Capas (Permiten activar/desactivar en el control de la derecha)
fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos (Polígonos)", show=True)
fg_pozos = folium.FeatureGroup(name="Pozos", show=True)

# Dibujar Sectores en su grupo
for s in sectores:
    folium.GeoJson(
        json.loads(s['geo']),
        style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1.5, 'fillOpacity': 0.1},
        tooltip=f"Sector: {s['sector']}"
    ).add_to(fg_sectores)

# Dibujar Pozos en su grupo
for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    q, p = d(info['caudal'])[0], d(info['presion'])[0]
    
    html_popup = f"""
    <div style="background:#111; color:white; padding:15px; border-radius:10px; width:280px; border:2px solid {info['color']}; font-family:sans-serif;">
        <h4 style="margin:0; color:#00d4ff;">POZO {id_p}</h4>
        <hr style="border:0.5px solid #333;">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>ESTADO:</span> <b style="color:{info['color']};">{info['status']}</b></div>
        <div style="display:flex; justify-content:space-between; margin-bottom:5px;"><span>💧 CAUDAL:</span> <b>{q:.2f} L/s</b></div>
        <div style="display:flex; justify-content:space-between;"><span>🚀 PRESIÓN:</span> <b>{p:.2f} kg</b></div>
    </div>
    """
    folium.Marker(
        location=info['coord'],
        icon=folium.Icon(color=info['color'], icon='tint', prefix='fa'),
        popup=folium.Popup(html_popup, max_width=300)
    ).add_to(fg_pozos)

# Añadir grupos y control al mapa
fg_sectores.add_to(m)
fg_pozos.add_to(m)
Fullscreen().add_to(m)
folium.LayerControl(position='topright', collapsed=False).add_to(m)

folium_static(m, width=1300, height=800)
