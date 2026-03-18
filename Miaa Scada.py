import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import plotly.graph_objects as go
import urllib.parse
from datetime import datetime, timedelta # IMPORTACIÓN CORREGIDA PARA EVITAR NAMEERROR

# 1. CONFIGURACIÓN DE PÁGINA (PANTALLA COMPLETA)
st.set_page_config(page_title="MIAA - SCADA", layout="wide", initial_sidebar_state="expanded")

# 2. ESTILO CSS PARA PANEL LATERAL OSCURO Y MAPA FULL
st.markdown("""
    <style>
        /* Fondo general negro */
        .stApp { background-color: #000000 !important; }
        
        /* Estilo del Panel Lateral (Sidebar) */
        [data-testid="stSidebar"] {
            background-color: #0b1a29 !important;
            min-width: 350px !important;
        }
        
        /* Tarjetas del Panel Lateral */
        .card-sidebar {
            background-color: #162636;
            border: 1px solid #333;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 10px;
        }
        
        /* Quitar espacios blancos innecesarios */
        .block-container { padding: 0rem !important; }
        iframe { background-color: #000 !important; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN (BOMBA ACTUALIZADO)
mapa_pozos_dict = {
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_estatico": "PZ_006_TRC_NIV_EST",
        "voltajes": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    }
}

# 4. FUNCIONES DE APOYO (GRÁFICO POPUP)
def generar_grafico_html():
    fechas = [datetime.now() - timedelta(hours=i) for i in range(24)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fechas, y=[11.8]*24, name="Caudal", line=dict(color='#00d4ff', width=2)))
    fig.add_trace(go.Scatter(x=fechas, y=[0.6]*24, name="Presión", line=dict(color='#00ff00', width=2)))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=0), height=200, showlegend=False,
        xaxis=dict(showgrid=True, gridcolor='#333'), yaxis=dict(showgrid=True, gridcolor='#333')
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn', config={'displayModeBar': False})

# --- PANEL LATERAL (SIDEBAR) ---
with st.sidebar:
    st.markdown("<h2 style='color:white;'>Estado de Pozos</h2>", unsafe_allow_html=True)
    
    # Resumen Global
    st.markdown(f"""
        <div class="card-sidebar">
            <h4 style='color:#00d4ff; margin:0;'>RESUMEN GLOBAL</h4>
            <p style='color:#00ff00; margin:10px 0 0 0;'>Caudal Total: <b>1409.22 l/s</b></p>
            <p style='color:#00ff00; margin:5px 0;'>Presión Prom: <b>2.15 Kg/cm²</b></p>
            <p style='color:#ffcc00; margin:5px 0;'>Nivel Estático Prom: <b>292.76 mts.</b></p>
            <p style='color:#00d4ff; margin:5px 0;'>Consumo Macros (Mes): <b>540.59 m³</b></p>
        </div>
    """, unsafe_allow_html=True)
    
    # Listado de Pozos
    st.success("Bombas ON (107)")
    st.code("P006\nP009\nP013\nP014A\nP016", language="text")
    
    st.error("Bombas OFF (16)")
    st.code("P003\nP005A\nP011\nP017A\nP020A", language="text")
    
    st.warning("Obsoletos (20)")
    st.code("P002\nP004\nP008\nP012", language="text")

    # Métrica de Sincronización (CORREGIDA)
    st.metric("Sincronización", datetime.now().strftime("%H:%M:%S"))

# --- ÁREA PRINCIPAL (MAPA) ---
st.markdown("<h3 style='color:white; text-align:center; padding:10px;'>MONITOREO ESTRATÉGICO MIAA</h3>", unsafe_allow_html=True)

# Creamos el mapa con Folium
m = folium.Map(location=[21.88, -102.28], zoom_start=12, tiles="CartoDB dark_matter", control_scale=True)
Fullscreen().add_to(m)

for id_p, info in mapa_pozos_dict.items():
    estado_bba = "ON" # Ejemplo
    dot_color = "#00ff00"
    graf_html = generar_grafico_html()
    
    # Popup exacto según la imagenimage_5bf406.jpg
    popup_content = f"""
    <div style="background-color: #0b1a29; color: white; padding: 15px; width: 700px; border-radius: 8px; font-family: sans-serif;">
        <h3 style="color: #00ff00; margin:0;">Pozo: {id_p} - {estado_bba}</h3>
        <hr style="border: 0.1px solid #333;">
        <div style="display: flex; justify-content: space-between;">
            <div style="width: 48%;">
                <p style="margin:4px 0;"><b style="color:#00d4ff;">Caudal: 11.87 l/s</b> <span style="color:#00ff00; font-size:10px;">--- 18/03/2026 11:50</span></p>
                <p style="margin:4px 0;"><b style="color:#00ff00;">Presión: 0.64 Kg/cm²</b> <span style="color:#00ff00; font-size:10px;">--- 18/03/2026 11:50</span></p>
                <p style="margin:4px 0;"><b style="color:#ffcc00;">Nivel Estático: 0.00 mts.</b> <span style="color:#ff0066; font-size:10px;">--- 16/02/2026 08:27</span></p>
            </div>
            <div style="width: 48%; font-size:12px;">
                <b style="color:#00d4ff;">Voltajes (V):</b> L1-L2: 431V | L2-L3: 432V<br>
                <b style="color:#00ff00;">Corrientes (A):</b> Total Avg: 67.99A
            </div>
        </div>
        <div style="margin-top:10px; border:1px solid #333;">{graf_html}</div>
        <div style="text-align:center; margin-top:10px;">
            <button style="background:#00d4ff; color:black; border:none; padding:8px 20px; border-radius:4px; font-weight:bold;">📊 ABRIR GRÁFICO FULL</button>
        </div>
    </div>
    """
    
    # Dibujar el punto
    folium.CircleMarker(
        location=info['coord'],
        radius=8,
        color=dot_color,
        fill=True,
        fill_color=dot_color,
        fill_opacity=1,
        popup=folium.Popup(popup_content, max_width=750)
    ).add_to(m)
    
    # Dibujar la etiqueta del pozo al lado
    folium.Marker(
        location=info['coord'],
        icon=folium.DivIcon(
            icon_size=(150,36),
            icon_anchor=(-10, 18),
            html=f'<div style="font-size: 13pt; color: {dot_color}; font-weight: bold;">{id_p}</div>',
        )
    ).add_to(m)

# Renderizado final del mapa
folium_static(m, width=1300, height=850)
