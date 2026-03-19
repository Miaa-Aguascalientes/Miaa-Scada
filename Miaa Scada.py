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

# 1. CONFIGURACIÓN DE PÁGINA Y FAVICON
st.set_page_config(
    page_title="MIAA - Estado de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS (DARK MODE, LOGO Y ANIMACIÓN BLINK)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        
        /* Contenedor del encabezado con Logo */
        .header-container {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px;
            background: #0b1a29;
            border-bottom: 2px solid #00d4ff;
            margin-bottom: 20px;
        }
        .header-container img {
            height: 50px;
            margin-right: 20px;
        }
        
        .stTable { background-color: #111111; border-radius: 10px; }
        
        /* Animación de parpadeo */
        @keyframes blinker {
            50% { opacity: 0; }
        }
        .blink_me {
            animation: blinker 1.2s linear infinite;
        }
    </style>
    
    <div class="header-container">
        <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg">
        <h2 style="color: #00d4ff; margin:0; letter-spacing: 2px;">SISTEMA DE MONITOREO Y SECTORIZACIÓN</h2>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN COMPLETO
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

# 4. FUNCIONES DE CONEXIÓN Y CARGA
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

# --- 5. PROCESAMIENTO DE DATOS ---
data_scada = cargar_datos_scada()
sectores = cargar_sectores_poligonos()
ahora = datetime.now()

# --- 6. INTERFAZ: PANEL IZQUIERDO Y MAPA ---
col_info, col_map = st.columns([1, 3])

with col_info:
    st.markdown("### 📊 Estado de Pozos")
    resumen_lista = []
    for id_p, info in mapa_pozos_dict.items():
        # Corrección del NameError: Usar 'bomba' en lugar de 'corriente_bba'
        val_bba, f_bba = data_scada.get(info['bomba'], (None, None))
        val_v1, f_v1 = data_scada.get(info['voltajes_l'][0], (None, None))
        
        color_hex, status_label, emoji, blink = "#808080", "SIN TELEMETRÍA", "⚪", False

        if val_bba is not None:
            if f_v1 and (ahora - f_v1).total_seconds() > 14400: # 4 horas
                color_hex, status_label, emoji, blink = "#FFFF00", "OBSOLETO (+4h)", "🟡", True
            elif val_bba == 1:
                color_hex, status_label, emoji, blink = "#00FF00", "ENCENDIDO", "🟢", False
            else:
                color_hex, status_label, emoji, blink = "#FF0000", "APAGADO", "🔴", True

        info['color_final'] = color_hex
        info['status_label'] = status_label
        info['blink'] = blink
        
        resumen_lista.append({
            " ": emoji, 
            "ID": id_p, 
            "Q (L/s)": f"{data_scada.get(info['caudal'], (0,0))[0]:.1f}"
        })

    st.table(pd.DataFrame(resumen_lista))

with col_map:
    m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # Inyección de CSS de parpadeo en el mapa
    m.get_root().header.add_child(folium.Element("""
        <style>
            @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
            .blink_me { animation: blink 1.2s infinite; }
        </style>
    """))

    # Sectores Hidráulicos
    for s in sectores:
        folium.GeoJson(
            json.loads(s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}
        ).add_to(m)

    # Marcadores de Pozos (Estilo Círculo Plano + Texto)
    for id_p, info in mapa_pozos_dict.items():
        # 1. Punto Circular
        folium.CircleMarker(
            location=info['coord'],
            radius=6,
            color=info['color_final'],
            fill=True,
            fill_color=info['color_final'],
            fill_opacity=1,
            weight=0,
            class_name="blink_me" if info['blink'] else ""
        ).add_to(m)

        # 2. Etiqueta de Texto ID
        folium.map.Marker(
            location=info['coord'],
            icon=folium.DivIcon(
                icon_size=(150,36),
                icon_anchor=(0,0),
                html=f'<div style="font-size: 14px; font-weight: bold; color: {info["color_final"]}; position: absolute; left: 12px; top: -10px; white-space: nowrap;">{id_p}</div>'
            )
        ).add_to(m)

    folium_static(m, width=1050, height=750)
