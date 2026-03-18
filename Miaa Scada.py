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
    page_title="MIAA - Monitoreo SCADA Pozos",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS (INTERFAZ DARK PROFESIONAL)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        .main-title {
            text-align: center; color: #00d4ff; font-size: 1.8rem;
            font-weight: bold; margin-top: -50px; margin-bottom: 20px;
            text-transform: uppercase; letter-spacing: 2px;
        }
        [data-testid="stMetric"] {
            background-color: #111111; border: 1px solid #333;
            border-radius: 10px; padding: 10px !important;
        }
        [data-testid="stMetricValue"] { color: #00d4ff !important; font-size: 1.6rem !important; }
        iframe { border: 1px solid #444 !important; border-radius: 15px; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN (MAPEO TÉCNICO)
mapa_pozos_dict = {
    "P002": {
        "coord": (21.88229, -102.31542), 
        "bomba": "PZ_002_TRC_BBA_CRUDO", 
        "caudal": "PZ_002_TRC_CAU_INS", 
        "presion": "PZ_002_TRC_PRES_INS",
        "sumergencia": "PZ_002_TRC_SUMERG",
        "corrientes_l": ["PZ_002_TRC_CORR_L1", "PZ_002_TRC_CORR_L2", "PZ_002_TRC_CORR_L3"],
        "voltajes_l": ["PZ_002_TRC_VOL_L1_L2", "PZ_002_TRC_VOL_L2_L3", "PZ_002_TRC_VOL_L1_L3"]
    },
    "P003": {
        "coord": (21.88603, -102.26653), 
        "bomba": "PZ_003_BBA_CRUDO", 
        "caudal": "PZ_003_CAU_INS", 
        "presion": "PZ_003_PRES_INS",
        "sumergencia": "PZ_003_SUMERG",
        "corrientes_l": ["PZ_003_CORR_L1", "PZ_003_CORR_L2", "PZ_003_CORR_L3"],
        "voltajes_l": ["PZ_003_VOL_L1_L2", "PZ_003_VOL_L2_L3", "PZ_003_VOL_L1_L3"]
    }
}

# 4. FUNCIONES DE BASE DE DATOS
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

def cargar_scada_history():
    engine = get_mysql_engine()
    if not engine: return {}
    
    # Extraer todos los tags para una sola consulta masiva
    tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): tags.extend(v)
            elif isinstance(v, str) and v.startswith("PZ_"): tags.append(v)
    
    try:
        tags_str = "', '".join(list(set(tags)))
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
def cargar_sectores():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- LÓGICA ---
data_scada = cargar_scada_history()
sectores = cargar_sectores()

st.markdown('<p class="main-title">Sistema de Monitoreo en Tiempo Real - MIAA</p>', unsafe_allow_html=True)

# METRICAS SUPERIORES
m1, m2, m3, m4 = st.columns(4)
p_on = sum([1 for p in mapa_pozos_dict.values() if data_scada.get(p['bomba'], (0,0))[0] == 1])
m1.metric("Pozos Encendidos", f"{p_on} / {len(mapa_pozos_dict)}")
m2.metric("Caudal Total", f"{sum([data_scada.get(p['caudal'], (0,0))[0] for p in mapa_pozos_dict.values()]):.1f} L/s")
m3.metric("Presión Promedio", f"{sum([data_scada.get(p['presion'], (0,0))[0] for p in mapa_pozos_dict.values()])/len(mapa_pozos_dict):.2f} kg")
m4.metric("Última Actualización", datetime.now().strftime("%H:%M:%S"))

# CUERPO DASHBOARD
col_map, col_list = st.columns([3, 1])

with col_map:
    m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    # Dibujar Sectores
    for s in sectores:
        folium.GeoJson(json.loads(s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

    # Dibujar Marcadores
    for id_p, info in mapa_pozos_dict.items():
        val_bba, f_act = data_scada.get(info['bomba'], (0, "N/A"))
        color_status = "green" if val_bba == 1 else "red"
        txt_status = "OPERANDO" if val_bba == 1 else "FUERA DE SERVICIO"

        # Obtener Voltajes y Corrientes
        v_l = [data_scada.get(tag, (0,0))[0] for tag in info['voltajes_l']]
        c_l = [data_scada.get(tag, (0,0))[0] for tag in info['corrientes_l']]

        html_popup = f"""
        <div style="background-color: #1e1e1e; color: white; padding: 12px; border-radius: 10px; width: 250px; font-family: sans-serif; border: 1px solid #444;">
            <div style="text-align: center; font-weight: bold; border-bottom: 1px solid #00d4ff; padding-bottom: 8px; margin-bottom: 10px; color: #00d4ff;">
                {id_p} - {txt_status}
            </div>
            <div style="font-size: 13px; margin-bottom: 4px;">💧 <b>Caudal:</b> <span style="color:#00d4ff">{data_scada.get(info['caudal'], (0,0))[0]:.2f} L/s</span></div>
            <div style="font-size: 13px; margin-bottom: 4px;">🚀 <b>Presión:</b> <span style="color:#00ff00">{data_scada.get(info['presion'], (0,0))[0]:.2f} kg</span></div>
            <div style="font-size: 13px; margin-bottom: 8px;">📉 <b>Sumergencia:</b> <span>{data_scada.get(info['sumergencia'], (0,0))[0]:.2f} m</span></div>
            
            <table style="width: 100%; font-size: 11px; text-align: center; border-top: 1px solid #333; padding-top: 5px;">
                <tr><th>Fase</th><th>Voltaje (V)</th><th>Corr (A)</th></tr>
                <tr><td>L1</td><td>{v_l[0]:.1f}</td><td>{c_l[0]:.1f}</td></tr>
                <tr><td>L2</td><td>{v_l[1]:.1f}</td><td>{c_l[1]:.1f}</td></tr>
                <tr><td>L3</td><td>{v_l[2]:.1f}</td><td>{c_l[2]:.1f}</td></tr>
            </table>
            <div style="font-size: 9px; color: #888; text-align: right; margin-top: 10px; border-top: 1px solid #333; padding-top: 5px;">
                Actualizado: {f_act}
            </div>
        </div>
        """
        
        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color=color_status, icon='flash' if val_bba == 1 else 'power-off', prefix='fa'),
            popup=folium.Popup(folium.IFrame(html_popup, width=270, height=240), max_width=280)
        ).add_to(m)

    folium_static(m, width=1050, height=650)

with col_list:
    st.markdown("### 📋 Resumen Pozos")
    resumen = []
    for k, v in mapa_pozos_dict.items():
        est = "🟢" if data_scada.get(v['bomba'], (0,0))[0] == 1 else "🔴"
        resumen.append({" ": est, "ID": k, "Q": f"{data_scada.get(v['caudal'], (0,0))[0]:.1f}"})
    st.dataframe(pd.DataFrame(resumen), hide_index=True)
