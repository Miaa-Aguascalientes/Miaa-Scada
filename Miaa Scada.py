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
from branca.element import Element, MacroElement

# 1---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2-----------------------------------------------------------------------------------2. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        .sidebar-logo { display: flex; justify-content: center; margin-top: -70px !important; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# 3--------------------------------------------------------------------------------3. FUNCIONES DE CONEXIÓN ----------------------------------------------------------------------------------------------------------
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

# 4-------------------------------------------------------------------------------- 4. CARGA DE DATOS ----------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                lat, lon = map(float, str(row['coord']).strip("()").split(','))
                nuevo_mapa[row['Pozos']] = {
                    "coord": (lat, lon), "bomba": row['bomba'], "caudal": row['caudal'],
                    "presion": row['presion'], "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                    "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
                }
            except: continue
        return nuevo_mapa
    except: return {}

def cargar_datos_scada(mapa_pozos):
    engine = get_mysql_scada_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos.values():
        for v in p.values():
            if isinstance(v, list): all_tags.extend([str(t) for t in v if t and str(t) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    if not all_tags: return {}
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except: return {}

# 5-------------------------------------------------------------------------------- 5. PROCESAMIENTO ----------------------------------------------------------------------------------------------------------
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

pozos_on, pozos_off = [], []
total_q = 0.0

for id_p, info in mapa_pozos_dict.items():
    val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
    if val_bba == 1:
        info.update({'status': 'ON', 'color': '#00FF00', 'blink': False})
        pozos_on.append(id_p)
        total_q += data_scada.get(info['caudal'], (0, 0))[0]
    else:
        info.update({'status': 'OFF', 'color': '#FF0000', 'blink': True})
        pozos_off.append(id_p)

# 6 ------------------------------------------------------------------------------- 6. SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.metric("Caudal Total", f"{total_q:.2f} L/s")

# 7--------------------------------------------------------------------------------- 7. MAPA -------------------------------------------------------------------------------------------------------------
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")

# --- SOLUCIÓN TÉCNICA DEFINITIVA ---
# Inyectamos el CSS y un Script que busca elementos con la clase 'parpadeo-rojo'
style_script = """
<style>
@keyframes latido {
    0% { opacity: 1; stroke-width: 2; }
    50% { opacity: 0.2; stroke-width: 10; }
    100% { opacity: 1; stroke-width: 2; }
}
.parpadeo-rojo {
    animation: latido 1.5s infinite !important;
}
</style>
<script>
setInterval(function(){
    var elements = document.querySelectorAll('.parpadeo-rojo');
    elements.forEach(function(el) {
        el.classList.add('parpadeo-rojo');
    });
}, 1000);
</script>
"""
m.get_root().header.add_child(folium.Element(style_script))

for id_p, info in mapa_pozos_dict.items():
    # Solo aplicamos la clase si está OFF
    clase = "parpadeo-rojo" if info['blink'] else ""
    
    folium.CircleMarker(
        location=info['coord'],
        radius=8,
        color=info['color'],
        fill=True,
        fill_color=info['color'],
        fill_opacity=0.8,
        class_name=clase, # ESTO ASIGNA LA CLASE AL ELEMENTO <path> DEL SVG
        popup=f"Pozo: {id_p} - {info['status']}"
    ).add_to(m)

    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(html=f'<div style="font-size:10px; color:{info["color"]}; font-weight:bold; transform:translate(10px,-10px);">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=1200, height=750)
