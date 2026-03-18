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

# 1. CONFIGURACIÓN ESTRUCTURAL (Sin márgenes para ocupar toda la pantalla)
st.set_page_config(
    page_title="MIAA - SCADA DASHBOARD",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS PARA CALCAR TU IMAGEN (Fondo oscuro, sidebar simulado y Popups)
st.markdown("""
    <style>
        /* Fondo total negro */
        .stApp {
            background-color: #000000 !important;
        }
        
        /* Ocultar elementos innecesarios de Streamlit */
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}

        /* Contenedor de la barra de navegación lateral izquierda (Simulación) */
        .nav-sidebar {
            background-color: #0b1a29;
            height: 100vh;
            width: 70px;
            position: fixed;
            left: 0;
            top: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding-top: 20px;
            border-right: 1px solid #00d4ff33;
            z-index: 100;
        }

        /* Título superior estilo MIAA */
        .header-miaa {
            background: linear-gradient(180deg, #0b1a29 0%, #000000 100%);
            padding: 15px;
            text-align: center;
            border-bottom: 2px solid #00d4ff;
            margin-left: 70px;
        }
        
        .header-miaa h1 {
            color: #00d4ff;
            font-size: 1.5rem;
            letter-spacing: 3px;
            margin: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }

        /* Estilo del Mapa */
        .map-container {
            margin-left: 70px;
        }
        
        iframe {
            border: none !important;
        }
    </style>
    
    <div class="nav-sidebar">
        <div style="color: #00d4ff; font-size: 24px; margin-bottom: 30px;">Ⓜ️</div>
        <div style="color: #444; font-size: 20px; margin-bottom: 25px;">📊</div>
        <div style="color: #00d4ff; font-size: 20px; margin-bottom: 25px;">📍</div>
        <div style="color: #444; font-size: 20px; margin-bottom: 25px;">⚙️</div>
    </div>
    
    <div class="header-miaa">
        <h1>SISTEMA DE MONITOREO ESTRATÉGICO - MIAA</h1>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE POZOS (Tus datos exactos)
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "corriente_bba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes_l": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"]
    },
    "P006": {
        "coord": (21.91504, -102.281668), 
        "corriente_bba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_tanque": "0", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"]
    }
}

# 4. FUNCIONES DE CARGA (Sin cambios, pero necesarias para el código completo)
@st.cache_resource
def get_engine():
    c = st.secrets["mysql"]
    p = urllib.parse.quote_plus(c["password"])
    return create_engine(f"mysql+mysqlconnector://{c['user']}:{p}@{c['host']}/{c['database']}")

def cargar_datos_scada():
    try:
        engine = get_engine()
        tags = []
        for p in mapa_pozos_dict.values():
            for k, v in p.items():
                if isinstance(v, list): tags.extend(v)
                elif isinstance(v, str) and (v.startswith("PZ_") or v.startswith("RB_")): tags.append(v)
        
        tags_str = "', '".join(list(set(tags)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ('{tags_str}')
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

# --- PROCESAMIENTO ---
data_scada = cargar_datos_scada()

# --- MAPA ---
st.markdown('<div class="map-container">', unsafe_allow_html=True)

m = folium.Map(location=[21.8900, -102.2500], zoom_start=13, tiles="CartoDB dark_matter", zoom_control=False)
Fullscreen().add_to(m)

for id_p, info in mapa_pozos_dict.items():
    val_bba, f_act = data_scada.get(info['corriente_bba'], (0, "N/A"))
    q_val = data_scada.get(info['caudal'], (0,0))[0]
    p_val = data_scada.get(info['presion'], (0,0))[0]
    s_val = data_scada.get(info['sumergencia'], (0,0))[0]
    tq_val = data_scada.get(info['nivel_tanque'], (0,0))[0] if info['nivel_tanque'] != "0" else 0
    
    # Lógica de Color Neón
    color_neon = "#00ff00" if val_bba == 1 else "#ff0000"
    status_label = "OPERATIVO" if val_bba == 1 else "FUERA DE SERVICIO"

    # HTML DEL POPUP CALCADO A TU IMAGEN
    html_popup = f"""
    <div style="background: rgba(10, 25, 41, 0.95); color: white; padding: 15px; border-radius: 12px; 
                width: 290px; border: 1px solid {color_neon}; box-shadow: 0 0 20px {color_neon}44; 
                font-family: 'Segoe UI', Arial, sans-serif;">
        
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #00d4ff44; padding-bottom: 8px; margin-bottom: 12px;">
            <span style="font-size: 18px; font-weight: bold; color: #00d4ff;">{id_p}</span>
            <span style="background: {color_neon}; color: black; padding: 2px 10px; border-radius: 4px; font-size: 10px; font-weight: 900;">{status_label}</span>
        </div>

        <div style="display: flex; gap: 10px; margin-bottom: 15px;">
            <div style="flex: 1; background: rgba(255,255,255,0.03); padding: 8px; border-radius: 6px; text-align: center; border: 0.5px solid #333;">
                <div style="font-size: 9px; color: #888; margin-bottom: 4px;">CAUDAL ACTUAL</div>
                <div style="font-size: 18px; color: #00d4ff; font-weight: bold;">{q_val:.1f} <small style="font-size: 10px;">L/s</small></div>
            </div>
            <div style="flex: 1; background: rgba(255,255,255,0.03); padding: 8px; border-radius: 6px; text-align: center; border: 0.5px solid #333;">
                <div style="font-size: 9px; color: #888; margin-bottom: 4px;">PRESIÓN RED</div>
                <div style="font-size: 18px; color: #00ff00; font-weight: bold;">{p_val:.2f} <small style="font-size: 10px;">kg</small></div>
            </div>
        </div>

        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; color: #aaa; margin-bottom: 4px;">
                <span>NIVEL SUMERGENCIA</span><span>{s_val:.1f}m</span>
            </div>
            <div style="width: 100%; height: 6px; background: #111; border-radius: 3px; overflow: hidden; border: 1px solid #333;">
                <div style="width: {min(s_val*1.5, 100)}%; height: 100%; background: linear-gradient(90deg, #005f73, #00d4ff);"></div>
            </div>
        </div>

        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; color: #aaa; margin-bottom: 4px;">
                <span>NIVEL TANQUE RESERVA</span><span>{tq_val:.1f}%</span>
            </div>
            <div style="width: 100%; height: 6px; background: #111; border-radius: 3px; overflow: hidden; border: 1px solid #333;">
                <div style="width: {tq_val}%; height: 100%; background: linear-gradient(90deg, #9b2226, #ae2012);"></div>
            </div>
        </div>

        <div style="font-size: 9px; color: #444; text-align: right; margin-top: 10px; font-style: italic;">
            Sincronización: {f_act}
        </div>
    </div>
    """
    
    # Marcador en el mapa con estilo de punto de control
    folium.CircleMarker(
        location=info['coord'],
        radius=8,
        color=color_neon,
        fill=True,
        fill_color=color_neon,
        fill_opacity=0.7,
        popup=folium.Popup(folium.IFrame(html_popup, width=320, height=295), max_width=330),
        tooltip=f"Pozo {id_p}"
    ).add_to(m)

folium_static(m, width=1450, height=800)
st.markdown('</div>', unsafe_allow_html=True)
