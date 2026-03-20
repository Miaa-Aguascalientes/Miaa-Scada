import streamlit as st
import pandas as pd
import folium
from folium import LayerControl  # Corrección de la importación
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
    try: 
        return psycopg2.connect(**st.secrets["postgres"])
    except: 
        return None

# 4. CARGA DE DATOS
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df_pozos = pd.read_sql(query, engine)
        
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                nuevo_mapa[row['Pozos']] = {
                    "coord": (lat, lon),
                    "bomba": row['bomba'],
                    "caudal": row['caudal'],
                    "presion": row['presion'],
                    "sumergencia": row['sumergencia'],
                    "nivel_dinamico": row['nivel_dinamico'],
                    "nivel_tanque": row['nivel_tanque'],
                    "columna": row['columna'],
                    "h_arranque": row['H_arranque'],
                    "h_paro": row['H_paro'],
                    "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
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
        for k, v in p.items():
            if isinstance(v, list): 
                all_tags.extend([str(tag) for tag in v if tag and str(tag) not in ['0', 'Sin telemetria']])
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): 
                all_tags.append(v)
    if not all_tags: return {}
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

# --- 5. PROCESAMIENTO ---
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
data_scada = cargar_datos_scada(mapa_pozos_dict)

pozos_on, pozos_off, pozos_sin_telemetria = [], [], []
total_q, total_p = 0.0, 0.0

for id_p, info in mapa_pozos_dict.items():
    if str(info['bomba']).strip() == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
        pozos_sin_telemetria.append(id_p)
    else:
        val_bba = data_scada.get(info['bomba'], (0, "N/A"))[0]
        q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
        p_val = data_scada.get(info['presion'], (0, "N/A"))[0]
        
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += q_val
            total_p += p_val
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# --- 6. SIDEBAR IZQUIERDO ---
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"""
    <div class="resumen-card">
        <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
        <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
        <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"<div class='section-header' style='background:#1b5e20;'>Bombas ON ({len(pozos_on)})</div>", unsafe_allow_html=True)
    for p in sorted(pozos_on): st.write(f"🟢 {p}")
    
    st.markdown(f"<div class='section-header' style='background:#b71c1c;'>Bombas OFF ({len(pozos_off)})</div>", unsafe_allow_html=True)
    for p in sorted(pozos_off): st.write(f"🔴 {p}")

    if pozos_sin_telemetria:
        st.markdown(f"<div class='section-header' style='background:#424242;'>Sin Telemetría ({len(pozos_sin_telemetria)})</div>", unsafe_allow_html=True)
        for p in sorted(pozos_sin_telemetria): st.write(f"⚪ {p}")

# --- 7. MAPA CON PANEL DE CAPAS ---
m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Creación de Grupos de Capas
fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos")
fg_on = folium.FeatureGroup(name="Pozos Operando")
fg_off = folium.FeatureGroup(name="Pozos Apagados")
fg_st = folium.FeatureGroup(name="Pozos Sin Telemetría (Gris)")

# RENDERIZADO DE SECTORES (Capa base)
for s in sectores:
    folium.GeoJson(
        json.loads(s['geo']), 
        style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}
    ).add_to(fg_sectores)

# RENDERIZADO DE POZOS
for id_p, info in mapa_pozos_dict.items():
    is_st = (info['status_label'] == 'SIN TELEMETRÍA')
    d = lambda tag: data_scada.get(tag, (0, "N/A"))
    q = d(info['caudal'])[0]
    p = d(info['presion'])[0]

    html_popup = f"""
    <div style="background: #050505; color: white; padding: 10px; border-radius: 8px; width: 250px; border: 1px solid {info['color_final']};">
        <b style="color: #00d4ff;">POZO {id_p}</b><br>
        Status: {info['status_label']}<br>
        💧 Caudal: {q:.2f} L/s<br>
        🚀 Presión: {p:.2f} kg
    </div>
    """

    marker = folium.CircleMarker(
        location=info['coord'],
        radius=7,
        color=info['color_final'],
        fill=True,
        fill_color=info['color_final'],
        fill_opacity=1,
        weight=0,
        class_name="blink_me" if info['blink'] else "",
        popup=folium.Popup(html_popup, max_width=300)
    )

    # Añadir al grupo correspondiente
    if info['status_label'] == 'OPERANDO':
        marker.add_to(fg_on)
    elif info['status_label'] == 'APAGADO':
        marker.add_to(fg_off)
    else:
        marker.add_to(fg_st)

    # Etiqueta de texto (Nombre del pozo siempre visible)
    folium.map.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(0,0),
            html=f'<div style="font-size: 13px; font-weight: bold; color: {info["color_final"]}; position: absolute; left: 10px; top: -10px;">{id_p}</div>'
        )
    ).add_to(m)

# Añadir grupos al mapa
fg_sectores.add_to(m)
fg_on.add_to(m)
fg_off.add_to(m)
fg_st.add_to(m)

# ACTIVADOR DE CAPAS (Panel a la derecha)
LayerControl(position='topright', collapsed=False).add_to(m)

folium_static(m, width=1300, height=800)
