import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine, text
import plotly.graph_objects as go
import urllib.parse
from datetime import datetime, timedelta

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - SCADA REAL-TIME", layout="wide", initial_sidebar_state="expanded")

# 2. CONEXIONES A BASES DE DATOS (USANDO st.secrets)
@st.cache_resource
def get_mysql_engine():
    # Base de datos de Telemetría (MySQL)
    c = st.secrets["mysql"]
    pwd = urllib.parse.quote_plus(c["password"])
    return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")

@st.cache_resource
def get_postgre_engine():
    # Base de datos de QGIS/Sectores (PostgreSQL)
    c = st.secrets["postgres"]
    pwd = urllib.parse.quote_plus(c["password"])
    return create_engine(f"postgresql://{c['user']}:{pwd}@{c['host']}:{c['port']}/{c['database']}")

# 3. FUNCIONES DE EXTRACCIÓN DE DATOS REALES
def obtener_ultimo_dato_scada(tag):
    engine = get_mysql_engine()
    query = text(f"SELECT valor, fecha FROM lecturas_hes WHERE tag = :tag ORDER BY fecha DESC LIMIT 1")
    with engine.connect() as conn:
        result = conn.execute(query, {"tag": tag}).fetchone()
    return result if result else (0, "---")

def obtener_historial_grafico(tag_caudal, tag_presion):
    engine = get_mysql_engine()
    query = text(f"""
        SELECT fecha, 
               MAX(CASE WHEN tag = :tc THEN valor END) as caudal,
               MAX(CASE WHEN tag = :tp THEN valor END) as presion
        FROM lecturas_hes 
        WHERE tag IN (:tc, :tp) 
        AND fecha >= NOW() - INTERVAL 7 DAY
        GROUP BY fecha ORDER BY fecha ASC
    """)
    return pd.read_sql(query, engine, params={"tc": tag_caudal, "tp": tag_presion})

# 4. DICCIONARIO DE CONFIGURACIÓN (Mapeos corregidos)
# Aquí debes incluir todos los tags reales de tu base miaamx_telemetria
mapa_pozos_dict = {
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_estatico": "PZ_006_TRC_NIV_EST",
        "voltajes": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"]
    }
}

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; }
        [data-testid="stSidebar"] { background-color: #0b1a29 !important; }
        .block-container { padding: 0rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- PANEL LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("<h2 style='color:white;'>Estado de Pozos</h2>", unsafe_allow_html=True)
    # Aquí podrías calcular el "Resumen Global" con un query SUM() a la tabla de pozos
    st.metric("Sincronización", datetime.now().strftime("%H:%M:%S"))

# --- MAPA PRINCIPAL ---
m = folium.Map(location=[21.88, -102.28], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for id_p, info in mapa_pozos_dict.items():
    # CONSULTA DE DATOS EN TIEMPO REAL
    val_bba, f_bba = obtener_ultimo_dato_scada(info['bomba'])
    val_cau, f_cau = obtener_ultimo_dato_scada(info['caudal'])
    val_pre, f_pre = obtener_ultimo_dato_scada(info['presion'])
    val_sum, f_sum = obtener_ultimo_dato_scada(info['sumergencia'])
    
    estado = "ON" if val_bba > 0 else "OFF"
    color = "#00ff00" if estado == "ON" else "#ff0000"
    
    # GENERACIÓN DE GRÁFICO CON DATOS DE LA DB
    df_hist = obtener_historial_grafico(info['caudal'], info['presion'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_hist['fecha'], y=df_hist['caudal'], name="Caudal", line=dict(color='#00d4ff')))
    fig.add_trace(go.Scatter(x=df_hist['fecha'], y=df_hist['presion'], name="Presión", line=dict(color='#00ff00')))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=200, margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
    graf_html = fig.to_html(full_html=False, include_plotlyjs='cdn')

    # POPUP (DISEÑO image_5bf406.jpg)
    popup_html = f"""
    <div style="background-color: #0b1a29; color: white; padding: 15px; width: 700px; border-radius: 8px; font-family: sans-serif;">
        <h3 style="color: {color}; margin:0;">Pozo: {id_p} - {estado}</h3>
        <hr style="border: 0.1px solid #333;">
        <div style="display: flex; justify-content: space-between;">
            <div style="width: 55%;">
                <p style="margin:4px 0;"><b style="color:#00d4ff;">Caudal: {val_cau:.2f} l/s</b> <span style="color:#00ff00; font-size:10px;">--- {f_cau}</span></p>
                <p style="margin:4px 0;"><b style="color:#00ff00;">Presión: {val_pre:.2f} Kg/cm²</b> <span style="color:#00ff00; font-size:10px;">--- {f_pre}</span></p>
                <p style="margin:4px 0;"><b style="color:#ff6666;">Sumergencia: {val_sum:.2f} mts.</b> <span style="color:#ff0066; font-size:10px;">--- {f_sum}</span></p>
            </div>
            <div style="width: 40%; font-size:12px;">
                <b style="color:#00d4ff;">INFO SISTEMA:</b><br>
                Última lectura: {f_bba}
            </div>
        </div>
        <div style="margin-top:10px; background:#000; border:1px solid #333;">{graf_html}</div>
    </div>
    """
    
    # MARCADORES
    folium.CircleMarker(
        location=info['coord'], radius=8, color=color, fill=True, fill_color=color, fill_opacity=1,
        popup=folium.Popup(popup_html, max_width=750)
    ).add_to(m)
    
    folium.Marker(
        location=info['coord'],
        icon=folium.DivIcon(html=f'<div style="font-size:13pt; color:{color}; font-weight:bold; margin-left:12px;">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=1300, height=800)
