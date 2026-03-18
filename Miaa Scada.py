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
st.set_page_config(
    page_title="MIAA - SCADA & Sectores",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide"
)

# Estilo visual MIAA (Negro y Azul)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        section[data-testid="stSidebar"] { background-color: #111111 !important; }
        .titulo-superior {
            text-align: center; color: white; font-size: 1.6rem;
            font-weight: bold; margin-bottom: 20px;
        }
        [data-testid="stMetric"] {
            background-color: #111111; border: 1px solid #333;
            border-radius: 10px; padding: 10px !important;
        }
        [data-testid="stMetricValue"] { color: #00d4ff !important; font-size: 1.6rem !important; }
        iframe { border: 2px solid #444 !important; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# 2. MOTORES DE CONEXIÓN
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}", pool_pre_ping=True)
    except Exception as e:
        st.error(f"Error MySQL: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e:
        st.error(f"Error Postgres: {e}")
        return None

# 3. CARGA DE DATOS
@st.cache_data(ttl=600)
def cargar_sectores_pg():
    conn = get_postgres_conn()
    if not conn: return pd.DataFrame()
    try:
        # Solo polígonos desde Postgres
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson_data FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def cargar_scada_realtime():
    """
    Obtiene los últimos datos de la tabla vfitagnumhistory
    """
    engine = get_mysql_engine()
    if not engine: return pd.DataFrame()
    
    try:
        # 1. Obtener los GATEID de los pozos (Filtramos por prefijo PZ_ como ejemplo)
        query_ref = "SELECT GATEID, NAME FROM VfiTagRef WHERE NAME LIKE 'PZ_%'" 
        df_ref = pd.read_sql(query_ref, engine)
        
        if df_ref.empty: return pd.DataFrame()

        # 2. Obtener el ÚLTIMO valor registrado para cada GATEID en vfitagnumhistory
        # Usamos una subconsulta para traer solo el registro más reciente por ID
        gateids = tuple(df_ref['GATEID'].tolist())
        query_data = f"""
            SELECT h.GATEID, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h
            INNER JOIN (
                SELECT GATEID, MAX(FECHA) as MaxFecha
                FROM vfitagnumhistory
                WHERE GATEID IN {gateids}
                GROUP BY GATEID
            ) sub ON h.GATEID = sub.GATEID AND h.FECHA = sub.MaxFecha
        """
        df_vals = pd.read_sql(query_data, engine)
        
        # Unimos nombres con valores
        return pd.merge(df_ref, df_vals, on='GATEID')
    except Exception as e:
        st.error(f"Error en SCADA: {e}")
        return pd.DataFrame()

# 4. MAPEO DE UBICACIONES (Asegúrate de que los nombres coincidan con VfiTagRef)
MAPEO_POZOS = {
    'PZ_001': {'lat': 21.8818, 'lon': -102.2917, 'nombre': 'Pozo 01'},
    'PZ_002': {'lat': 21.8920, 'lon': -102.3010, 'nombre': 'Pozo 02'},
    # Añadir aquí las coordenadas del resto de los pozos
}

# --- INTERFAZ ---
st.markdown('<div class="titulo-superior">MONITOREO SCADA - SECTORES Y POZOS MIAA</div>', unsafe_allow_html=True)

df_sec = cargar_sectores_pg()
df_scada = cargar_scada_realtime()

# Procesar para el mapa
datos_mapa = []
if not df_scada.empty:
    for _, row in df_scada.iterrows():
        if row['NAME'] in MAPEO_POZOS:
            pos = MAPEO_POZOS[row['NAME']]
            datos_mapa.append({
                **pos,
                'tag': row['NAME'],
                'valor': row['VALUE'],
                'fecha': row['FECHA']
            })

# MÉTRICAS
m1, m2, m3 = st.columns(3)
m1.metric("Tags Monitoreados", len(df_scada))
m2.metric("Pozos Localizados", len(datos_mapa))
m3.metric("Última Lectura", df_scada['FECHA'].max() if not df_scada.empty else "---")

# MAPA Y LISTA
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    # Dibujar Sectores (Postgres)
    if not df_sec.empty:
        for _, row in df_sec.iterrows():
            folium.GeoJson(
                json.loads(row['geojson_data']),
                style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1},
                tooltip=f"Sector: {row['sector']}"
            ).add_to(m)

    # Dibujar Pozos (SCADA MySQL)
    for p in datos_mapa:
        color = "green" if p['valor'] > 0 else "red"
        folium.CircleMarker(
            location=[p['lat'], p['lon']],
            radius=8, color=color, fill=True, fill_opacity=0.7,
            tooltip=f"{p['nombre']} ({p['tag']}): {p['valor']} | {p['fecha']}"
        ).add_to(m)

    folium_static(m, width=950, height=600)

with c2:
    st.write("### Listado SCADA")
    if datos_mapa:
        df_view = pd.DataFrame(datos_mapa)[['nombre', 'valor', 'fecha']]
        st.dataframe(df_view, hide_index=True, use_container_width=True)
    else:
        st.warning("No hay pozos mapeados. Revisa el diccionario MAPEO_POZOS.")

# Detalle de la tabla vfitagnumhistory
st.divider()
st.subheader("Datos Crudos de Telemetría")
st.dataframe(df_scada, use_container_width=True)
