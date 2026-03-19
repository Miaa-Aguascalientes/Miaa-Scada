import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - Monitoreo en Tiempo Real", layout="wide")

# 2. ESTILO CSS (Diseño persistente y animaciones)
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)

# 3. MOTORES DE CONEXIÓN (Doble persistencia)
@st.cache_resource
def get_engine(db_name):
    """Crea una conexión dinámica según el nombre de la base de datos"""
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{db_name}", 
                              pool_recycle=3600, pool_pre_ping=True)
    except Exception as e:
        st.error(f"Error conectando a {db_name}: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    """Conexión para capas de QGIS / Sectores"""
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. EXTRACCIÓN DE DATOS CRUZADA
def cargar_sistema_dinamico():
    # Paso A: Leer nombres de variables desde 'miaamx_telemetria2'
    engine_config = get_engine("miaamx_telemetria2")
    if not engine_config: return {}, {}
    
    try:
        df_dict = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine_config)
        pozos_config = {}
        all_tags = []
        
        for _, row in df_dict.iterrows():
            coords = tuple(map(float, row['coord'].split(',')))
            # Recolectamos todos los nombres de variables (tags)
            tags_pozo = [
                row['bomba'], row['caudal'], row['presion'], 
                row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3'],
                row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3'],
                row['sumergencia'], row['nivel_dinamico'], row['nivel_tanque']
            ]
            all_tags.extend([str(t) for t in tags_pozo if t and t != '0'])
            
            pozos_config[row['Pozos']] = {
                "coord": coords,
                "vars": row.to_dict()
            }
            
        # Paso B: Leer valores reales desde 'miaamx_telemetria'
        engine_scada = get_engine("miaamx_telemetria")
        if not engine_scada: return pozos_config, {}
        
        tags_query = "', '".join(list(set(all_tags)))
        query_valores = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_query}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df_val = pd.read_sql(query_valores, engine_scada)
        valores_realtime = {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%H:%M')) for _, row in df_val.iterrows()}
        
        return pozos_config, valores_realtime
    except Exception as e:
        st.error(f"Error en cruce de datos: {e}")
        return {}, {}

# 5. EJECUCIÓN
pozos, lecturas = cargar_sistema_dinamico()

# 6. INTERFAZ Y MAPA
with st.sidebar:
    st.image("https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/main/LogoMIAA-BpcVaQaq.svg")
    st.markdown("### Estado de Red")
    if st.button("🔄 ACTUALIZAR TODO", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

m = folium.Map(location=[21.881, -102.291], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

for id_p, info in pozos.items():
    v = info['vars']
    
    # Función para obtener valor con validación (Si SCADA <= 0, podrías poner lógica de respaldo aquí)
    def get_val(tag): return lecturas.get(tag, (0.0, "N/A"))
    
    val_bba = get_val(v['bomba'])[0]
    color = "#00FF00" if val_bba == 1 else "#FF0000"
    
    # Popup con el diseño completo que manejas
    html = f"""
    <div style="background:#000; color:white; padding:12px; border:1px solid {color}; border-radius:10px; width:280px; font-family:sans-serif;">
        <b style="color:#00d4ff; font-size:14px;">POZO {id_p}</b><br>
        <div style="margin-top:8px; font-size:12px;">
            💧 Caudal: <b>{get_val(v['caudal'])[0]:.2f} L/s</b> <br>
            🚀 Presión: <b>{get_val(v['presion'])[0]:.2f} kg</b> <br>
            📉 Nivel Tanque: <b>{get_val(v['nivel_tanque'])[0]:.1f}%</b>
        </div>
        <hr style="border:0.5px solid #333">
        <div style="font-size:10px; color:yellow;">Sincronizado: {get_val(v['bomba'])[1]}</div>
    </div>
    """
    
    folium.CircleMarker(
        location=info['coord'],
        radius=7,
        color=color,
        fill=True,
        fill_opacity=1,
        class_name="blink_me" if val_bba != 1 else "",
        popup=folium.Popup(html, max_width=300)
    ).add_to(m)
    
    folium.Marker(
        location=info['coord'],
        icon=folium.DivIcon(html=f'<div style="font-size:12px; font-weight:bold; color:{color}; margin-left:12px; text-shadow: 1px 1px #000;">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=1280, height=720)
