import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
import mysql.connector
import psycopg2
from sqlalchemy import create_engine, text
import plotly.graph_objects as go
from datetime import datetime, timedelta
import urllib.parse

# 1. CONFIGURACIÓN DE PÁGINA Y ESTILO MIAA
st.set_page_config(page_title="MIAA - SISTEMA OPERATIVO SCADA", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; }
        [data-testid="stSidebar"] { background-color: #0b1a29 !important; min-width: 350px !important; }
        .resumen-card { background-color: #162636; border: 1px solid #00d4ff; padding: 15px; border-radius: 5px; margin-bottom: 10px; }
        .stMetric { background-color: #162636; border-radius: 5px; padding: 10px; border: 1px solid #333; }
    </style>
""", unsafe_allow_html=True)

# 2. MOTORES DE BASE DE DATOS (CON DATOS DE TU RESPALDO)
@st.cache_resource
def get_mysql_engine():
    # Credenciales extraídas de tu archivo de respaldo
    user = "miaamx_dashboard"
    password = urllib.parse.quote_plus("h97_p,NQPo=l")
    host = "miaa.mx"
    db = "miaamx_telemetria"
    return create_engine(f"mysql+mysqlconnector://{user}:{password}@{host}/{db}")

@st.cache_resource
def get_postgres_engine():
    # Credenciales PostgreSQL para sectores
    return create_engine("postgresql://postgres:miaa2024@10.10.10.115:5432/qgis")

# 3. LÓGICA DE DATOS REALES
def obtener_telemetria_actual():
    engine = get_mysql_engine()
    # Query para traer el último valor de cada pozo
    query = """
        SELECT tag, valor, fecha 
        FROM lecturas_hes 
        WHERE (tag LIKE 'PZ_%_BBA_CRUDO' OR tag LIKE 'PZ_%_CAU_INS' OR tag LIKE 'PZ_%_PRES_INS')
        AND fecha >= NOW() - INTERVAL 2 HOUR
    """
    return pd.read_sql(query, engine)

# 4. COMPONENTES DE LA INTERFAZ (SIDEBAR)
with st.sidebar:
    st.markdown("<h2 style='color:white;'>Estado de Pozos</h2>", unsafe_allow_html=True)
    
    # Resumen Global (Simulado con base en tus KPIs)
    st.markdown("""
        <div class="resumen-card">
            <h4 style='color:#00d4ff; margin:0;'>RESUMEN GLOBAL</h4>
            <p style='color:#00ff00; margin:10px 0 0 0;'>Caudal Total: <b>1409.22 l/s</b></p>
            <p style='color:#00ff00; margin:5px 0;'>Presión Prom: <b>2.15 Kg/cm²</b></p>
            <p style='color:#ffcc00; margin:5px 0;'>Nivel Estático Prom: <b>292.76 mts.</b></p>
        </div>
    """, unsafe_allow_html=True)
    
    st.success("Bombas ON (107)")
    st.error("Bombas OFF (16)")
    st.warning("Obsoletos (20)")
    
    st.metric("Sincronización", datetime.now().strftime("%H:%M:%S"))

# 5. GENERACIÓN DEL MAPA ESTRATÉGICO
st.markdown("<h3 style='color:white; text-align:center;'>MONITOREO ESTRATÉGICO MIAA</h3>", unsafe_allow_html=True)

# Coordenadas de prueba basadas en tu lógica de Aguascalientes
m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Función para el gráfico del popup (Estilo Plotly interactivo)
def crear_grafico_mini():
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=[10, 12, 11, 13], mode='lines', line=dict(color='#00d4ff', width=3)))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                      margin=dict(l=0,r=0,t=0,b=0), height=150, showlegend=False)
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

# Dibujando un pozo de ejemplo con tu popup real
pozos_ejemplo = {"P006": [21.9150, -102.2816], "P005A": [21.8914, -102.2319]}

for id_p, coord in pozos_ejemplo.items():
    graf_html = crear_grafico_mini()
    popup_content = f"""
    <div style="background-color: #0b1a29; color: white; padding: 15px; width: 600px; border-radius: 10px; border: 1px solid #333;">
        <h3 style="color: #00ff00; margin:0;">Pozo: {id_p} - ON</h3>
        <hr style="border: 0.1px solid #444;">
        <div style="display: flex; justify-content: space-between;">
            <div>
                <p style="color:#00d4ff; margin:2px 0;"><b>Caudal: 11.87 l/s</b></p>
                <p style="color:#00ff00; margin:2px 0;"><b>Presión: 0.64 Kg/cm²</b></p>
            </div>
            <div style="font-size: 11px;">
                <b style="color:#00d4ff;">SCADA:</b> Activo<br>
                <b style="color:#00ff00;">Sinc:</b> {datetime.now().strftime('%H:%M')}
            </div>
        </div>
        <div style="margin-top:10px;">{graf_html}</div>
    </div>
    """
    
    folium.CircleMarker(
        location=coord, radius=8, color="#00ff00", fill=True, fill_opacity=1,
        popup=folium.Popup(popup_content, max_width=650)
    ).add_to(m)
    
    folium.Marker(
        location=coord,
        icon=folium.DivIcon(html=f'<div style="font-size:12pt; color:#00ff00; font-weight:bold; margin-left:12px;">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=1300, height=800)
