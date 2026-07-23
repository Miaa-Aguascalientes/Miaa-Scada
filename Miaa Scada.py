import streamlit as st
import pandas as pd
import folium
from sqlalchemy import create_engine
import psycopg2
import urllib.parse
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="MIAA - Mapa de Pozos y Sectores", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilo visual básico para fondo oscuro
st.markdown("""
<style>
    .stApp { background-color: #050a10 !important; color: white !important; }
    .block-container { padding: 1rem !important; max-width: 100% !important; }
    header, footer { visibility: hidden !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CONEXIONES A BASES DE DATOS
# ==========================================
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(
            f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}",
            pool_recycle=3600,
            pool_pre_ping=True
        )
        return engine
    except Exception as e:
        st.error(f"⚠️ Error de conexión MySQL Telemetría: {e}")
        return None

# ==========================================
# 3. CARGA DE DATOS (POZOS Y SECTORES)
# ==========================================
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    try:
        conn = psycopg2.connect(**st.secrets["postgres"])
        query = """
            SELECT sector, "Pozos_Sector", 
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Sectorizacion"."Sectores_hidr"
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        st.error(f"Error al cargar sectores: {e}")
        return []

@st.cache_data(ttl=3600) 
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df_pozos = pd.read_sql(query, engine)
        
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                coords = (lat, lon)
            except: 
                continue

            nuevo_mapa[row['Pozos']] = {
                "coord": coords,
                "caudal": row.get('caudal', 'N/A'),
                "presion": row.get('presion', 'N/A'),
                "nivel_dinamico": row.get('nivel_dinamico', 'N/A')
            }
        return nuevo_mapa
    except Exception as e:
        st.error(f"Error al cargar pozos: {e}")
        return {}

# ==========================================
# 4. INTERFAZ PRINCIPAL (MAPA)
# ==========================================
st.title("🗺️ MIAA - Monitoreo Geográfico de Pozos y Sectores")

# Cargar datos
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()

# Inicializar mapa centrado en Aguascalientes
m = folium.Map(
    location=[21.8853, -102.2916], 
    zoom_start=12, 
    tiles='CartoDB dark_matter'
)

# 4.1. Agregar Polígonos de Sectores
for sec in sectores:
    try:
        if sec.get('geo'):
            geo_json = eval(sec['geo']) if isinstance(sec['geo'], str) else sec['geo']
            folium.GeoJson(
                geo_json,
                style_function=lambda x: {
                    'fillColor': '#00d4ff',
                    'color': '#00d4ff',
                    'weight': 1,
                    'fillOpacity': 0.05
                },
                tooltip=f"Sector: {sec.get('sector')}"
            ).add_to(m)
    except Exception:
        pass

# 4.2. Agregar Marcadores de Pozos
for id_pozo, info in mapa_pozos_dict.items():
    coord = info.get("coord")
    if coord:
        folium.CircleMarker(
            location=coord,
            radius=6,
            color="#00ffcc",
            fill=True,
            fill_color="#00ffcc",
            fill_opacity=0.8,
            popup=folium.Popup(f"<b>Pozo:</b> {id_pozo}", max_width=250),
            tooltip=f"Pozo: {id_pozo}"
        ).add_to(m)

# Renderizar mapa usando HTML nativo para evitar errores de DOM en Streamlit
map_html = m._repr_html_()
st.components.v1.html(map_html, height=700, scrolling=True)
