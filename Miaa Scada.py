import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import plotly.graph_objects as go
import urllib.parse
from datetime import datetime, timedelta  # IMPORTACIÓN CRÍTICA CORREGIDA

# 1. CONFIGURACIÓN DE PÁGINA Y ESTILO MIAA
st.set_page_config(page_title="MIAA - SCADA", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        .css-1d391kg { background-color: #0b1a29; } /* Sidebar color */
        .resumen-card {
            background-color: #0b1a29; border: 1px solid #00d4ff;
            padding: 10px; border-radius: 5px; margin-bottom: 10px;
        }
    </style>
""", unsafe_allow_html=True)

# 2. DICCIONARIO DE CONFIGURACIÓN (MAPEO DE POZOS)
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
    }
}

# 3. GENERACIÓN DE GRÁFICO PARA POPUP (ESTILO image_6a83a3.png)
def generar_grafico_popup():
    fechas = [datetime.now() - timedelta(hours=i) for i in range(24)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fechas, y=[11.8]*24, name="Caudal", line=dict(color='#00d4ff', width=2)))
    fig.add_trace(go.Scatter(x=fechas, y=[0.6]*24, name="Presión", line=dict(color='#00ff00', width=2)))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=0), height=200, showlegend=False,
        xaxis=dict(showgrid=True, gridcolor='#333'), yaxis=dict(showgrid=True, gridcolor='#333')
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

# 4. INTERFAZ: PANEL LATERAL Y MAPA
col_sid, col_map = st.columns([1, 4])

with col_sid:
    st.markdown("<h3 style='color:white;'>Estado de Pozos</h3>", unsafe_allow_html=True)
    st.markdown("""
        <div class="resumen-card">
            <h4 style='color:#00d4ff; margin:0;'>RESUMEN GLOBAL</h4>
            <p style='color:#00ff00; margin:5px 0;'>Caudal Total: 1409.22 l/s</p>
            <p style='color:#00ff00; margin:5px 0;'>Presión Prom: 2.15 Kg/cm²</p>
            <p style='color:#ffcc00; margin:5px 0;'>Nivel Estático Prom: 292.76 mts.</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Listas de Bombas (Ejemplo visual image_5c0e0e.png)
    st.success("Bombas ON (107)")
    st.code("P006\nP009\nP013")
    st.error("Bombas OFF (16)")
    st.code("P003\nP005A")

with col_map:
    m = folium.Map(location=[21.88, -102.28], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    for id_p, info in mapa_pozos_dict.items():
        estado = "ON" # Esto vendría de tu lógica de DB
        color = "#00ff00" if estado == "ON" else "#ff0000"
        graf_html = generar_grafico_popup()
        
        # HTML DEL POPUP EXCLUSIVO (image_6a83a3.png)
        popup_html = f"""
        <div style="background-color: #0b1a29; color: white; padding: 15px; width: 700px; border-radius: 10px; font-family: sans-serif; border: 1px solid #333;">
            <h2 style="color: #00ff00; margin: 0 0 10px 0;">Pozo: {id_p} - {estado}</h2>
            <div style="display: flex; justify-content: space-between;">
                <div>
                    <p style="color:#00d4ff; margin:2px 0;"><b>Caudal: 11.87 l/s</b> <small style="color:#00ff00;">--- 18/03/2026</small></p>
                    <p style="color:#00ff00; margin:2px 0;"><b>Presión: 0.64 Kg/cm²</b> <small style="color:#00ff00;">--- 18/03/2026</small></p>
                    <p style="color:#ffcc00; margin:2px 0;"><b>Nivel Estático: 0.00 mts.</b> <small style="color:#ff0066;">--- 16/02/2026</small></p>
                </div>
                <div style="font-size: 11px;">
                    <b style="color:#00d4ff;">Voltajes (V):</b><br>L1-L2: 431V | L2-L3: 432V<br>
                    <b style="color:#00ff00;">Corrientes (A):</b><br>Total: 67.99 A
                </div>
            </div>
            <div style="margin-top:10px; background:#000; border:1px solid #333;">{graf_html}</div>
            <div style="text-align:center; margin-top:10px;">
                <button style="background:#00d4ff; color:black; border:none; padding:8px 20px; border-radius:5px; font-weight:bold;">📊 ABRIR GRÁFICO FULL</button>
            </div>
        </div>
        """
        
        folium.CircleMarker(
            location=info['coord'], radius=7, color=color, fill=True, fill_color=color, fill_opacity=1,
            popup=folium.Popup(popup_html, max_width=750)
        ).add_to(m)
        
        folium.Marker(
            location=info['coord'],
            icon=folium.DivIcon(html=f'<div style="font-size:12pt; color:{color}; font-weight:bold; margin-left:10px;">{id_p}</div>')
        ).add_to(m)

    folium_static(m, width=1200, height=750)

# Sincronización (Corrigiendo el error de la captura)
st.sidebar.metric("Sincronización", datetime.now().strftime("%H:%M:%S"))
