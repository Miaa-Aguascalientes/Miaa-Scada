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
    page_title="MIAA - Sistema de Monitoreo Integral",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS PARA PANEL DE CONTROL (DARK MODE)
st.markdown("""
    <style>
        /* Fondo General */
        .stApp { background-color: #000000 !important; color: white; }
        
        /* Título Superior */
        .main-title {
            text-align: center;
            color: #00d4ff;
            font-size: 1.8rem;
            font-weight: bold;
            margin-top: -50px;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }

        /* Contenedores de Métricas */
        [data-testid="stMetric"] {
            background-color: #111111;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 10px !important;
        }
        [data-testid="stMetricValue"] { color: #00d4ff !important; font-size: 1.6rem !important; }
        
        /* Ajuste de Mapa */
        iframe { border: 1px solid #444 !important; border-radius: 15px; }
        
        /* Tabla Lateral */
        .stTable { background-color: #111111; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE POZOS Y TAGS (Tu configuración)
mapa_pozos_dict = {
    "P002": {
        "coord": (21.88229, -102.31542), 
        "corriente": "PZ_002_TRC_BBA_CRUDO", 
        "caudal": "PZ_002_TRC_CAU_INS", 
        "presion": "PZ_002_TRC_PRES_INS", 
        "sumergencia": "PZ_002_TRC_SUMERG",
        "nivel_estatico": "PZ_002_TRC_NIV_EST"
    },
    "P003": {
        "coord": (21.88603, -102.26653), 
        "corriente": "PZ_003_BBA_CRUDO", 
        "caudal": "PZ_003_CAU_INS", 
        "presion": "PZ_003_PRES_INS", 
        "sumergencia": "PZ_003_SUMERG",
        "nivel_estatico": "PZ_003_NIV_EST"
    }
}

# 4. CONEXIONES A BASES DE DATOS
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}", pool_pre_ping=True)
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 5. CARGA DE DATOS (SCADA Y SECTORES)
def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}
    
    # Extraemos todos los tags únicos del diccionario
    all_tags = []
    for p in mapa_pozos_dict.values():
        all_tags.extend([v for v in p.values() if isinstance(v, str) and v.startswith("PZ_")])
    
    if not all_tags: return {}
    
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ('{tags_str}')
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

@st.cache_data(ttl=3600)
def cargar_sectores_pg():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- PROCESAMIENTO DE DATOS ---
dict_valores = cargar_datos_scada()
sectores = cargar_sectores_pg()

# --- INTERFAZ DE USUARIO ---
st.markdown('<p class="main-title">Sistema de Monitoreo de Pozos y Sectores - MIAA</p>', unsafe_allow_html=True)

# FILA 1: MÉTRICAS GENERALES
m1, m2, m3, m4 = st.columns(4)
total_q = sum([dict_valores.get(v['caudal'], (0,0))[0] for v in mapa_pozos_dict.values()])
avg_p = sum([dict_valores.get(v['presion'], (0,0))[0] for v in mapa_pozos_dict.values()]) / len(mapa_pozos_dict)

m1.metric("Pozos Monitoreados", len(mapa_pozos_dict))
m2.metric("Caudal Total", f"{total_q:.1f} L/s")
m3.metric("Presión Promedio", f"{avg_p:.2f} kg/cm²")
m4.metric("Estado de Sistema", "ESTABLE", delta="Normal")

# FILA 2: CUERPO PRINCIPAL (Mapa e Información)
col_mapa, col_info = st.columns([3, 1])

with col_mapa:
    m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    # Dibujar Polígonos de Sectores (Postgres)
    for s in sectores:
        folium.GeoJson(json.loads(s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.15},
            tooltip=f"Sector: {s['sector']}").add_to(m)

    # Dibujar Pozos con POPUP Personalizado (MySQL)
    for id_p, info in mapa_pozos_dict.items():
        q_val, q_f = dict_valores.get(info['caudal'], (0, "N/A"))
        p_val, _ = dict_valores.get(info['presion'], (0, "N/A"))
        s_val, _ = dict_valores.get(info['sumergencia'], (0, "N/A"))
        a_val, _ = dict_valores.get(info['corriente'], (0, "N/A"))

        # HTML para el Popup (Fiel a tu imagen de referencia)
        html_content = f"""
        <div style="background-color: #1e1e1e; color: white; padding: 12px; border-radius: 10px; width: 220px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; border: 1px solid #444;">
            <div style="text-align: center; font-weight: bold; border-bottom: 1px solid #00d4ff; padding-bottom: 8px; margin-bottom: 12px; font-size: 14px; color: #00d4ff;">
                POZO {id_p}
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
                <span>💧 <b>Caudal:</b></span> <span style="color: #00d4ff;">{q_val:.2f} L/s</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
                <span>🚀 <b>Presión:</b></span> <span style="color: #00ff00;">{p_val:.2f} kg</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
                <span>📉 <b>Sumergencia:</b></span> <span style="color: #ffaa00;">{s_val:.2f} m</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px;">
                <span>⚡ <b>Corriente:</b></span> <span style="color: #ff5555;">{a_val:.1f} A</span>
            </div>
            <div style="font-size: 9px; color: #888; text-align: right; margin-top: 12px; border-top: 1px solid #333; padding-top: 5px;">
                Actualizado: {q_f}
            </div>
        </div>
        """
        
        # El color del icono cambia si el pozo no tiene caudal (rojo)
        status_color = "blue" if q_val > 0 else "red"
        
        iframe = folium.IFrame(html_content, width=250, height=190)
        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color=status_color, icon='tint', prefix='fa'),
            popup=folium.Popup(iframe, max_width=260),
            tooltip=f"Pozo {id_p}"
        ).add_to(m)

    folium_static(m, width=1050, height=650)

with col_info:
    st.markdown("### 📋 Resumen de Pozos")
    
    # Tabla lateral con los datos principales
    resumen_data = []
    for id_p, info in mapa_pozos_dict.items():
        resumen_data.append({
            "ID": id_p,
            "Q (L/s)": f"{dict_valores.get(info['caudal'], (0,0))[0]:.1f}",
            "P (kg)": f"{dict_valores.get(info['presion'], (0,0))[0]:.1f}"
        })
    
    st.table(pd.DataFrame(resumen_data))
    
    st.divider()
    st.write("🔔 **Alertas de Presión**")
    # Alerta automática si un pozo baja de 1.0 kg
    for id_p, info in mapa_pozos_dict.items():
        p_val = dict_valores.get(info['presion'], (0,0))[0]
        if p_val < 1.0 and p_val > 0:
            st.warning(f"Baja presión en {id_p}: {p_val:.2f} kg")
