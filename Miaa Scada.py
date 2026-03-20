import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen, LayerControl
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

# 2. ESTILO CSS (Incluye personalización para el panel derecho)
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
                    "columna": row['columna']
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
            if isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): 
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
total_q = 0.0

for id_p, info in mapa_pozos_dict.items():
    if str(info['bomba']).strip() == "Sin telemetria":
        info.update({'status': 'SIN TELEMETRÍA', 'color': '#808080', 'blink': False})
        pozos_sin_telemetria.append(id_p)
    else:
        val_bba = data_scada.get(info['bomba'], (0, "N/A"))[0]
        q_val = data_scada.get(info['caudal'], (0, "N/A"))[0]
        if val_bba == 1:
            info.update({'status': 'OPERANDO', 'color': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += q_val
        else:
            info.update({'status': 'APAGADO', 'color': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# --- 6. LAYOUT: SIDEBAR IZQUIERDO Y PANEL DERECHO ---
col_mapa, col_ctrl = st.columns([0.85, 0.15])

with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="resumen-card"><h4>Caudal Total</h4><h2 style="color:#00FF00;">{total_q:.2f} L/s</h2></div>', unsafe_allow_html=True)
    
    st.markdown(f"<div class='section-header' style='background:#1b5e20;'>OPERANDO ({len(pozos_on)})</div>", unsafe_allow_html=True)
    for p in sorted(pozos_on): st.write(f"🟢 {p}")
    
    st.markdown(f"<div class='section-header' style='background:#b71c1c;'>APAGADOS ({len(pozos_off)})</div>", unsafe_allow_html=True)
    for p in sorted(pozos_off): st.write(f"🔴 {p}")

    st.markdown(f"<div class='section-header' style='background:#424242;'>SIN TELEMETRÍA ({len(pozos_sin_telemetria)})</div>", unsafe_allow_html=True)
    for p in sorted(pozos_sin_telemetria): st.write(f"⚪ {p}")

# --- 7. MAPA CON CONTROL DE CAPAS ---
with col_mapa:
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # Definición de capas (Feature Groups)
    fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos")
    fg_on = folium.FeatureGroup(name="Pozos Operando")
    fg_off = folium.FeatureGroup(name="Pozos Apagados")
    fg_st = folium.FeatureGroup(name="Pozos Sin Telemetría")

    # Añadir sectores a su capa
    for s in sectores:
        folium.GeoJson(
            json.loads(s['geo']), 
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}
        ).add_to(fg_sectores)

    # Añadir pozos a sus capas correspondientes
    for id_p, info in mapa_pozos_dict.items():
        d = lambda tag: data_scada.get(tag, (0, "N/A"))
        q = d(info['caudal'])[0]
        p = d(info['presion'])[0]
        
        html_popup = f"<div style='color:white; background:black; padding:10px;'><b>POZO {id_p}</b><br>Caudal: {q:.2f} L/s<br>Presión: {p:.2f} kg</div>"
        
        marker = folium.CircleMarker(
            location=info['coord'],
            radius=8,
            color=info['color'],
            fill=True,
            fill_opacity=1,
            class_name="blink_me" if info['blink'] else "",
            popup=folium.Popup(html_popup, max_width=300)
        )
        
        # Clasificación por capa
        if info['status'] == 'OPERANDO': marker.add_to(fg_on)
        elif info['status'] == 'APAGADO': marker.add_to(fg_off)
        else: marker.add_to(fg_st)

    # Añadir todas las capas al mapa
    fg_sectores.add_to(m)
    fg_on.add_to(m)
    fg_off.add_to(m)
    fg_st.add_to(m)

    # ACTIVADOR DE CAPAS (Aparece en la esquina superior derecha del mapa)
    LayerControl(collapsed=False).add_to(m)
    
    folium_static(m, width=1100, height=800)

# --- 8. PANEL DE CONTROL DERECHO (ST.COLUMNS) ---
with col_ctrl:
    st.markdown("### 🛠️ Capas")
    st.info("Usa el control en la esquina superior derecha del mapa para activar/desactivar las capas visuales.")
    st.divider()
    if st.button("♻️ Refrescar SCADA", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
