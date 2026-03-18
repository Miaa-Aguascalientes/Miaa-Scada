import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import plotly.graph_objects as go
import urllib.parse
from datetime import datetime, timedelta

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - SCADA", layout="wide", initial_sidebar_state="collapsed")

# 2. ESTILO CSS PARA INTERFAZ TOTALMENTE OSCURA
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN (CON VARIABLE 'BOMBA')
mapa_pozos_dict = {
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_estatico": "PZ_006_TRC_NIV_EST",
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    },
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "bomba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_estatico": "PZ_RP_005_TRHDAS_NIV_EST", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"],
        "amperajes": ["PZ_RP_005_TRHDAS_CORR_L1", "PZ_RP_005_TRHDAS_CORR_L2", "PZ_RP_005_TRHDAS_CORR_L3"]
    }
}

# 4. CONEXIÓN Y CARGA DE DATOS
@st.cache_resource
def get_mysql_engine():
    c = st.secrets["mysql"]
    pwd = urllib.parse.quote_plus(c["password"])
    return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")

def generar_grafico_popup():
    # Simulación del gráfico de la imagen
    fechas = [datetime.now() - timedelta(hours=i) for i in range(168)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fechas, y=[12]*168, name="Caudal", line=dict(color='#00d4ff', width=2)))
    fig.add_trace(go.Scatter(x=fechas, y=[0.6]*168, name="Presión", line=dict(color='#00ff00', width=2)))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=0), showlegend=False, height=250,
        xaxis=dict(showgrid=True, gridcolor='#222', tickfont=dict(color='white')),
        yaxis=dict(showgrid=True, gridcolor='#222', tickfont=dict(color='white'))
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

# --- RENDERIZADO DEL MAPA ---
st.markdown("<h2 style='color:white; text-align:center;'>MONITOREO ESTRATÉGICO MIAA</h2>", unsafe_allow_html=True)

m = folium.Map(location=[21.88, -102.28], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for id_p, info in mapa_pozos_dict.items():
    # Aquí deberías obtener el valor real de la base de datos para info['bomba']
    estado_bba = "ON" # Ejemplo
    dot_color = "#00ff00" if estado_bba == "ON" else "#ff0000"
    
    grafico_html = generar_grafico_popup()
    
    # HTML FIEL A LA IMAGENimage_5bf406.jpg
    html_content = f"""
    <div style="background-color: #0b1a29; color: white; padding: 15px; width: 720px; border-radius: 8px; font-family: sans-serif;">
        <h3 style="color: #00ff00; margin-top: 0;">Pozo: {id_p} - {estado_bba}</h3>
        <hr style="border: 0.1px solid #333;">
        
        <div style="display: flex; justify-content: space-between;">
            <div style="width: 48%;">
                <p style="margin: 4px 0;"><b style="color: #00d4ff; font-size: 16px;">Caudal: 11.87 l/s</b> <span style="color: #00ff00; font-size: 10px;">---------- 18/03/2026 11:50</span></p>
                <p style="margin: 4px 0;"><b style="color: #00ff00; font-size: 16px;">Presión: 0.64 Kg/cm²</b> <span style="color: #00ff00; font-size: 10px;">---------- 18/03/2026 11:50</span></p>
                <p style="margin: 4px 0;"><b style="color: #ffcc00; font-size: 16px;">Nivel Estático: 0.00 mts.</b> <span style="color: #ff0066; font-size: 10px;">---------- 16/02/2026 08:27</span></p>
                <p style="margin: 4px 0;"><b style="color: #ff6666; font-size: 16px;">Sumergencia: 227.76 mts.</b> <span style="color: #ff0066; font-size: 10px;">---------- 16/02/2026 08:27</span></p>
                <p style="margin: 4px 0;"><b style="color: #ff9933; font-size: 16px;">Nivel Tanque Adj: 0.00 mts.</b> <span style="color: #888; font-size: 10px;">------</span></p>
            </div>
            <div style="width: 48%;">
                <p style="margin: 0; color: #00d4ff;"><b>Voltajes (V):</b></p>
                <div style="font-size: 12px; padding-left: 10px;">
                    L1-L2: 431 Volts <span style="color: #00ff00; font-size: 9px;">------------------------ 18/03/2026 11:50</span><br>
                    L2-L3: 432 Volts <span style="color: #00ff00; font-size: 9px;">------------------------ 18/03/2026 11:50</span><br>
                    L1-L3: 424 Volts <span style="color: #00ff00; font-size: 9px;">------------------------ 18/03/2026 11:50</span>
                </div>
                <p style="margin: 8px 0 0 0; color: #00ff00;"><b>Corrientes (A):</b></p>
                <div style="font-size: 12px; padding-left: 10px;">
                    Total (Avg): <b>67.99 A</b><br>
                    L1: 0.00 Amp <span style="color: #888; font-size: 9px;">--------------------------------------------</span><br>
                    L2: 0.00 Amp <span style="color: #888; font-size: 9px;">--------------------------------------------</span><br>
                    L3: 67.99 Amp <span style="color: #00ff00; font-size: 9px;">------------------------ 18/03/2026 11:41</span>
                </div>
            </div>
        </div>
        
        <div style="margin-top: 15px; border: 1px solid #333; background: #000;">
            {grafico_html}
        </div>
        
        <div style="text-align: center; margin-top: 10px;">
            <button style="background: #00d4ff; color: black; border: none; padding: 8px 25px; border-radius: 4px; font-weight: bold; cursor: pointer;">📊 ABRIR GRÁFICO FULL</button>
        </div>
    </div>
    """

    # PUNTO EN EL MAPA (ROJO O VERDE)
    folium.CircleMarker(
        location=info['coord'],
        radius=7,
        color=dot_color,
        fill=True,
        fill_color=dot_color,
        fill_opacity=1,
        popup=folium.Popup(html_content, max_width=750)
    ).add_to(m)
    
    # ETIQUETA CON EL NÚMERO DEL POZO AL LADO
    folium.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(-10, 18),
            html=f'<div style="font-size: 13pt; color: {dot_color}; font-weight: bold; text-shadow: 1px 1px #000;">{id_p}</div>',
        )
    ).add_to(m)

folium_static(m, width=1200, height=750)
