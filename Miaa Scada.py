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
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. ESTILO CSS
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .sidebar-logo { display: flex; justify-content: center; padding: 10px 0 20px 0; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
        .section-header { padding: 10px; border-radius: 3px; font-weight: bold; margin-bottom: 5px; color: white; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        # Usamos el nombre de base de datos correcto según tu imagen
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/miaamx_telemetria2")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# NUEVA FUNCIÓN: Carga el diccionario de pozos desde MySQL
def cargar_diccionario_pozos():
    engine = get_mysql_engine()
    if not engine: return {}
    try:
        # Nota: Ajusté el nombre de la tabla a 'Diccionario_de_pozos' según tu imagen de DB
        query = "SELECT * FROM Diccionario_de_pozos"
        df = pd.read_sql(query, engine)
        
        diccionario_dinamico = {}
        for _, row in df.iterrows():
            # Convertimos la cadena de coordenadas "lat, lon" a tupla de floats
            coords = tuple(map(float, row['coord'].split(',')))
            
            diccionario_dinamico[row['Pozos']] = {
                "coord": coords,
                "bomba": row['bomba'],
                "caudal": row['caudal'],
                "presion": row['presion'],
                "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'],
                "nivel_tanque": row['nivel_tanque'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
            }
        return diccionario_dinamico
    except Exception as e:
        st.error(f"Error cargando diccionario de pozos: {e}")
        return {}

def cargar_datos_scada(mapa_dict):
    engine = get_mysql_engine()
    if not engine or not mapa_dict: return {}
    all_tags = []
    for p in mapa_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}') AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
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

# --- 4. PROCESAMIENTO DINÁMICO ---
mapa_pozos_dict = cargar_diccionario_pozos()
data_scada = cargar_datos_scada(mapa_pozos_dict)
sectores = cargar_sectores_poligonos()

pozos_on, pozos_off = [], []
total_q, total_p = 0.0, 0.0

for id_p, info in mapa_pozos_dict.items():
    val_bba, f_bba = data_scada.get(info['bomba'], (0, "N/A"))
    q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
    p_val = data_scada.get(info['presion'], (0, "N/A"))[0]
    
    if val_bba == 1:
        info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
        pozos_on.append(id_p)
        total_q += float(q_val)
        total_p += float(p_val)
    else:
        info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
        pozos_off.append(id_p)

# --- 5. SIDEBAR ---
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    st.markdown("<h2 style='color:#00d4ff; text-align:center;'>Estado de Pozos</h2>", unsafe_allow_html=True)

    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    
    st.divider() 
    
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

# --- 6. MAPA ---
m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Dibujar Sectores
for s in sectores:
    try:
        folium.GeoJson(json.loads(s['geo']), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)
    except: continue

# Dibujar Pozos Dinámicos
for id_p, info in mapa_pozos_dict.items():
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    q, f_q = d(info['caudal'])
    p, f_p = d(info['presion'])
    
    # ... (Se mantiene el diseño del popup exactamente como estaba)
    html_popup = f"""<div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 320px; border: 1px solid {info['color_final']};">
        <b>POZO {id_p}</b> - {info['status_label']}<br>
        💧 Caudal: {q:.2f} L/s <br>
        🚀 Presión: {p:.2f} kg
    </div>"""

    folium.CircleMarker(
        location=info['coord'],
        radius=6,
        color=info['color_final'],
        fill=True,
        fill_color=info['color_final'],
        fill_opacity=1,
        weight=0,
        class_name="blink_me" if info['blink'] else "",
        popup=folium.Popup(html_popup, max_width=450)
    ).add_to(m)

    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(0,0),
            html=f'<div style="font-size: 14px; font-weight: bold; color: {info["color_final"]}; position: absolute; left: 12px; top: -10px; white-space: nowrap;">{id_p}</div>'
        )
    ).add_to(m)

folium_static(m, width=1300, height=800)
