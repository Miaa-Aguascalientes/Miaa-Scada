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
st.set_page_config(page_title="MIAA - SCADA Realtime", layout="wide", initial_sidebar_state="collapsed")

# 2. ESTILO CSS PARA REPLICAR LA INTERFAZ DE LA IMAGEN
st.markdown("""
    <style>
        .stApp { background-color: #050505 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        
        /* Contenedor del Título */
        .title-container {
            text-align: center;
            padding: 20px;
            background: linear-gradient(90deg, rgba(0,212,255,0) 0%, rgba(0,212,255,0.2) 50%, rgba(0,212,255,0) 100%);
            border-bottom: 1px solid #00d4ff;
            margin-bottom: 20px;
        }
        
        iframe { border: none !important; border-radius: 20px; box-shadow: 0px 0px 20px rgba(0,212,255,0.2); }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE POZOS (Nuevos Pozos P005A y P006)
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

# 4. CONEXIONES (MySQL y Postgres)
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

def cargar_datos():
    engine = get_mysql_engine()
    if not engine: return {}
    all_tags = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, list): all_tags.extend(v)
            elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): all_tags.append(v)
    
    try:
        tags_str = "', '".join(list(set(all_tags)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ('{tags_str}')
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

# --- PROCESO ---
data = cargar_datos()

# --- INTERFAZ ---
st.markdown('<div class="title-container"><h1>MONITOREO ESTRATÉGICO MIAA</h1></div>', unsafe_allow_html=True)

m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for id_p, info in mapa_pozos_dict.items():
    # Datos SCADA
    bba_val, f_act = data.get(info['corriente_bba'], (0, "N/A"))
    q_val = data.get(info['caudal'], (0,0))[0]
    p_val = data.get(info['presion'], (0,0))[0]
    s_val = data.get(info['sumergencia'], (0,0))[0]
    tq_val = data.get(info['nivel_tanque'], (0,0))[0] if info['nivel_tanque'] != "0" else 0
    
    # Lógica de colores (1=Verde, 0=Rojo)
    color_neon = "#00ff00" if bba_val == 1 else "#ff0000"
    status_text = "ENCENDIDO" if bba_val == 1 else "APAGADO"

    # HTML DEL POPUP (REPLICANDO TU IMAGEN)
    html_popup = f"""
    <div style="background: linear-gradient(135deg, #0b1a29 0%, #050505 100%); 
                color: white; padding: 15px; border-radius: 15px; width: 280px; 
                font-family: 'Arial'; border: 1px solid {color_neon}; box-shadow: 0 0 15px {color_neon}55;">
        
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 10px;">
            <span style="font-size: 18px; font-weight: bold; color: #00d4ff;">{id_p}</span>
            <span style="background: {color_neon}; color: black; padding: 2px 8px; border-radius: 5px; font-size: 10px; font-weight: bold;">{status_text}</span>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px;">
            <div style="text-align: center; background: rgba(255,255,255,0.05); padding: 5px; border-radius: 8px;">
                <div style="font-size: 10px; color: #888;">CAUDAL</div>
                <div style="font-size: 16px; color: #00d4ff; font-weight: bold;">{q_val:.1f} <small>L/s</small></div>
            </div>
            <div style="text-align: center; background: rgba(255,255,255,0.05); padding: 5px; border-radius: 8px;">
                <div style="font-size: 10px; color: #888;">PRESIÓN</div>
                <div style="font-size: 16px; color: #00ff00; font-weight: bold;">{p_val:.2f} <small>kg</small></div>
            </div>
        </div>

        <div style="margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 3px;">
                <span>Nivel Sumergencia</span><span>{s_val:.1f}m</span>
            </div>
            <div style="width: 100%; bg: #333; height: 8px; border-radius: 4px; background: #222; overflow: hidden;">
                <div style="width: {min(s_val*2, 100)}%; height: 100%; background: linear-gradient(90deg, #00d4ff, #00ff00);"></div>
            </div>
        </div>

        <div style="margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 3px;">
                <span>Nivel Tanque</span><span>{tq_val:.1f}%</span>
            </div>
            <div style="width: 100%; bg: #333; height: 8px; border-radius: 4px; background: #222; overflow: hidden;">
                <div style="width: {tq_val}%; height: 100%; background: linear-gradient(90deg, #ffa500, #ff4500);"></div>
            </div>
        </div>

        <div style="font-size: 9px; color: #555; text-align: right; margin-top: 10px;">
            DATOS ACTUALIZADOS: {f_act}
        </div>
    </div>
    """
    
    # Icono personalizado con el logo de MIAA (o similar)
    folium.Marker(
        location=info['coord'],
        icon=folium.Icon(color="green" if bba_val == 1 else "red", icon="tint", prefix="fa"),
        popup=folium.Popup(folium.IFrame(html_popup, width=310, height=290), max_width=320),
        tooltip=f"Pozo {id_p}"
    ).add_to(m)

folium_static(m, width=1300, height=750)
