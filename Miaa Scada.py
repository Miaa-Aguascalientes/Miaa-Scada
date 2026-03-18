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
    page_title="MIAA - Sistema de Monitoreo SCADA",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS (DARK MODE PROFESIONAL)
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
        .stTable { background-color: #111111; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN ACTUALIZADO
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "corriente_bba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "corrientes_l": ["PZ_RP_005_TRHDAS_CORR_L1", "PZ_RP_005_TRHDAS_CORR_L2", "PZ_RP_005_TRHDAS_CORR_L3"], 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "voltajes_l": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"], 
        "nivel_estatico": "PZ_RP_005_TRHDAS_NIV_EST", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
    },
    "P006": {
        "coord": (21.91504, -102.281668), 
        "corriente_bba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "corrientes_l": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"], 
        "presion": "PZ_006_TRC_PRES_INS", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"], 
        "nivel_estatico": "PZ_006_TRC_NIV_EST", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_tanque": "0", 
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

# 5. CARGA DE DATOS (SCADA HISTÓRICO Y SECTORES)
def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}
    
    all_tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and v.startswith("PZ_"): all_tags.append(v)
            elif isinstance(v, str) and v.startswith("RB_"): all_tags.append(v)
    
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

# --- PROCESAMIENTO ---
dict_valores = cargar_datos_scada()
sectores = cargar_sectores_pg()

# --- INTERFAZ ---
st.markdown('<p class="main-title">Panel de Control SCADA - MIAA</p>', unsafe_allow_html=True)

# FILA 1: MÉTRICAS
m1, m2, m3, m4 = st.columns(4)
pozos_on = sum([1 for p in mapa_pozos_dict.values() if dict_valores.get(p['corriente_bba'], (0,0))[0] == 1])
total_q = sum([dict_valores.get(p['caudal'], (0,0))[0] for p in mapa_pozos_dict.values()])

m1.metric("Bombas en Operación", f"{pozos_on} / {len(mapa_pozos_dict)}")
m2.metric("Caudal Total Red", f"{total_q:.1f} L/s")
m3.metric("Estado General", "ESTABLE", delta="Normal")
m4.metric("Sincronización", datetime.now().strftime("%H:%M:%S"))

# FILA 2: MAPA Y LISTADO
col_map, col_info = st.columns([3, 1])

with col_map:
    m = folium.Map(location=[21.9000, -102.2600], zoom_start=13, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    for s in sectores:
        folium.GeoJson(json.loads(s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

    for id_p, info in mapa_pozos_dict.items():
        # Lógica de Color (1=Verde, 0=Rojo)
        val_bba, f_act = dict_valores.get(info['corriente_bba'], (0, "N/A"))
        color_marker = "green" if val_bba == 1 else "red"
        txt_status = "OPERANDO" if val_bba == 1 else "APAGADO"
        
        q_val = dict_valores.get(info['caudal'], (0,0))[0]
        p_val = dict_valores.get(info['presion'], (0,0))[0]
        s_val = dict_valores.get(info['sumergencia'], (0,0))[0]
        
        # Voltajes y Corrientes para la tabla del Popup
        v_l = [dict_valores.get(tag, (0,0))[0] for tag in info['voltajes_l']]
        c_l = [dict_valores.get(tag, (0,0))[0] for tag in info['corrientes_l']]

        html_popup = f"""
        <div style="background-color: #1e1e1e; color: white; padding: 12px; border-radius: 10px; width: 250px; font-family: sans-serif; border: 1px solid #444;">
            <div style="text-align: center; font-weight: bold; border-bottom: 1px solid #00d4ff; padding-bottom: 8px; margin-bottom: 10px; color: #00d4ff;">
                {id_p} - {txt_status}
            </div>
            <div style="font-size: 13px; margin-bottom: 4px;">💧 <b>Caudal:</b> <span style="color:#00d4ff">{q_val:.2f} L/s</span></div>
            <div style="font-size: 13px; margin-bottom: 4px;">🚀 <b>Presión:</b> <span style="color:#00ff00">{p_val:.2f} kg</span></div>
            <div style="font-size: 13px; margin-bottom: 8px;">📉 <b>Sumergencia:</b> <span>{s_val:.2f} m</span></div>
            
            <table style="width: 100%; font-size: 11px; text-align: center; border-top: 1px solid #333; padding-top: 5px; color: #ccc;">
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
            icon=folium.Icon(color=color_marker, icon='flash' if val_bba == 1 else 'power-off', prefix='fa'),
            popup=folium.Popup(folium.IFrame(html_popup, width=270, height=245), max_width=280),
            tooltip=f"{id_p}: {txt_status}"
        ).add_to(m)

    folium_static(m, width=1050, height=650)

with col_info:
    st.markdown("### 📋 Resumen Pozos")
    resumen = []
    for k, v in mapa_pozos_dict.items():
        v_bba = dict_valores.get(v['corriente_bba'], (0,0))[0]
        resumen.append({
            " ": "🟢" if v_bba == 1 else "🔴",
            "ID": k,
            "Q (L/s)": f"{dict_valores.get(v['caudal'], (0,0))[0]:.1f}"
        })
    st.dataframe(pd.DataFrame(resumen), hide_index=True, use_container_width=True)
