import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime, timedelta

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - Control de Pozos", layout="wide", initial_sidebar_state="collapsed")

# 2. ESTILO CSS PARA PANEL IZQUIERDO Y ESTÉTICA DARK
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        
        /* Contenedor principal para mover el panel a la izquierda */
        .main-container { display: flex; flex-direction: row-reverse; }
        
        /* Título superior */
        .header-miaa {
            text-align: center; padding: 10px; border-bottom: 2px solid #00d4ff;
            background: #0b1a29; margin-bottom: 10px;
        }
        
        /* Estilo de la tabla y métricas */
        .stTable { background-color: #111111; border-radius: 10px; }
        [data-testid="stMetric"] { background-color: #111111; border: 1px solid #333; border-radius: 8px; }
    </style>
    <div class="header-miaa">
        <h2 style="color: #00d4ff; margin:0; letter-spacing: 2px;">SISTEMA DE MONITOREO DE POZOS - MIAA</h2>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN
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

# 4. FUNCIONES DE DATOS
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}", pool_pre_ping=True)
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
ahora = datetime.now()

# --- LAYOUT: PANEL A LA IZQUIERDA ---
col_info, col_map = st.columns([1, 3])

with col_info:
    st.markdown("### 📊 Estado de Pozos")
    resumen_data = []
    
    # Pre-cálculo para el mapa y panel
    for id_p, info in mapa_pozos_dict.items():
        # 1. Obtener datos base
        bba_val, f_act = data_scada.get(info['corriente_bba'], (None, None))
        v_l1 = data_scada.get(info['voltajes_l'][0], (None, None))
        
        # 2. Lógica de Colores
        color_hex = "#808080"  # Gris por defecto (Sin telemetría)
        icon_color = "gray"
        status_label = "SIN TELEMETRÍA"
        emoji = "⚪"

        if bba_val is not None:
            # Verificar si es obsoleto (Voltaje L1 sin datos > 4 horas)
            if v_l1[1] and (ahora - v_l1[1]).total_seconds() > 14400: # 4 horas
                color_hex = "#FFFF00" # Amarillo
                icon_color = "orange"
                status_label = "OBSOLETO (+4h)"
                emoji = "🟡"
            elif bba_val == 1:
                color_hex = "#00FF00" # Verde
                icon_color = "green"
                status_label = "ENCENDIDO"
                emoji = "🟢"
            else:
                color_hex = "#FF0000" # Rojo
                icon_color = "red"
                status_label = "APAGADO"
                emoji = "🔴"

        # Guardar para el mapa
        info['color_final'] = color_hex
        info['icon_color'] = icon_color
        info['status_label'] = status_label
        
        resumen_data.append({
            " ": emoji,
            "ID": id_p,
            "Estado": status_label,
            "Q (L/s)": f"{data_scada.get(info['caudal'], (0,0))[0]:.1f}"
        })

    st.table(pd.DataFrame(resumen_data))
    st.caption("🟢 Encendido | 🔴 Apagado | 🟡 Obsoleto | ⚪ Sin Telemetría")

with col_map:
    m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    for id_p, info in mapa_pozos_dict.items():
        q_val = data_scada.get(info['caudal'], (0,0))[0]
        p_val = data_scada.get(info['presion'], (0,0))[0]
        s_val = data_scada.get(info['sumergencia'], (0,0))[0]
        f_act = data_scada.get(info['corriente_bba'], (0, "N/A"))[1]

        # POPUP ESTILO HMI
        html_popup = f"""
        <div style="background: #0b1a29; color: white; padding: 12px; border-radius: 10px; width: 260px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
            <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 5px; margin-bottom: 10px;">
                <b style="color: #00d4ff;">{id_p}</b>
                <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 1px 5px; border-radius: 3px; font-weight: bold;">{info['status_label']}</span>
            </div>
            <div style="font-size: 12px; margin-bottom: 5px;">💧 Caudal: <b>{q_val:.2f} L/s</b></div>
            <div style="font-size: 12px; margin-bottom: 5px;">🚀 Presión: <b>{p_val:.2f} kg</b></div>
            <div style="font-size: 12px; margin-bottom: 10px;">📉 Sumergencia: <b>{s_val:.1f} m</b></div>
            <div style="font-size: 9px; color: #666; text-align: right;">Sinc: {f_act}</div>
        </div>
        """

        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color=info['icon_color'], icon='tint', prefix='fa'),
            popup=folium.Popup(folium.IFrame(html_popup, width=280, height=180), max_width=300),
            tooltip=f"{id_p}: {info['status_label']}"
        ).add_to(m)

    folium_static(m, width=1000, height=700)
