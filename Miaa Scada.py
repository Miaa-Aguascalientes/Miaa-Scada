import streamlit as st
import pandas as pd
import pydeck as pdk
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN
st.set_page_config(page_title="MIAA - Ciudad 3D", layout="wide")

# 2. CARGA DE DATOS (Usando tu lógica de respaldo)
@st.cache_resource
def get_engines():
    c_tele = st.secrets["mysql_telemetria"]
    pwd_tele = urllib.parse.quote_plus(c_tele["password"])
    engine_tele = create_engine(f"mysql+mysqlconnector://{c_tele['user']}:{pwd_tele}@{c_tele['host']}/{c_tele['database']}")
    
    c_scada = st.secrets["mysql_scada"]
    pwd_scada = urllib.parse.quote_plus(c_scada["password"])
    engine_scada = create_engine(f"mysql+mysqlconnector://{c_scada['user']}:{pwd_scada}@{c_scada['host']}/{c_scada['database']}")
    return engine_tele, engine_scada

@st.cache_data(ttl=600)
def cargar_datos_completos():
    eng_tele, eng_scada = get_engines()
    # Pozos
    df = pd.read_sql("SELECT * FROM Diccionario_de_pozos", eng_tele)
    def extraer_coords(c):
        try:
            parts = str(c).replace('(','').replace(')','').split(',')
            return float(parts[0]), float(parts[1])
        except: return None, None
    df['lat'], df['lon'] = zip(*df['coord'].apply(extraer_coords))
    df = df.dropna(subset=['lat', 'lon'])
    
    # SCADA (Últimos valores)
    query_scada = "SELECT r.NAME, h.VALUE FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID"
    df_scada = pd.read_sql(query_scada, eng_scada)
    scada_map = dict(zip(df_scada['NAME'], df_scada['VALUE']))
    return df, scada_map

df_p, scada_values = cargar_datos_completos()

# 3. PROCESAMIENTO DE COLORES (OPERANDO/APAGADO)
def definir_estilo(row):
    val = scada_values.get(str(row['bomba']), 0)
    if val == 1: return [0, 255, 0, 255] # Verde
    return [255, 0, 0, 255] # Rojo

df_p['color'] = df_p.apply(definir_estilo, axis=1)

# 4. CARGA DE SECTORES (PostgreSQL)
@st.cache_data
def cargar_sectores():
    try:
        conn = psycopg2.connect(**st.secrets["postgres"])
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df_s = pd.read_sql(query, conn)
        conn.close()
        return [{"type": "Feature", "geometry": json.loads(r['geo'])} for _, r in df_s.iterrows()]
    except: return []

sectores_features = cargar_sectores()

# 5. RENDERIZADO DEL MAPA 3D CON CIUDAD VISIBLE
st.markdown('<h2 style="text-align:center; color:#00d4ff;">VISOR URBANO MIAA 3D</h2>', unsafe_allow_html=True)

view_state = pdk.ViewState(
    latitude=21.8820,
    longitude=-102.2800,
    zoom=13,
    pitch=60, # Inclinación para ver relieve
    bearing=-10
)

capas = [
    # CAPA DE CIUDAD / SECTORES (Muy transparente para no tapar calles)
    pdk.Layer(
        "GeoJsonLayer",
        sectores_features,
        opacity=0.05,
        stroked=True,
        filled=True,
        get_fill_color=[0, 212, 255],
        get_line_color=[0, 212, 255],
        line_width_min_pixels=1,
    ),
    # CAPA DE POZOS (Puntos de operación)
    pdk.Layer(
        "ScatterplotLayer",
        df_p,
        get_position=['lon', 'lat'],
        get_color='color',
        get_radius=40,
        pickable=True,
    ),
    # CAPA DE ETIQUETAS (Nombres de los pozos)
    pdk.Layer(
        "TextLayer",
        df_p,
        get_position=['lon', 'lat'],
        get_text='Pozos',
        get_size=12,
        get_color=[255, 255, 255],
        offset_y=-10
    )
]

# EL DECK QUE FUERZA LA VISIBILIDAD DE LA CIUDAD
st.pydeck_chart(pdk.Deck(
    # Estilo de mapa que muestra calles, edificios y nombres detallados
    map_style='mapbox://styles/mapbox/navigation-night-v1', 
    initial_view_state=view_state,
    layers=capas,
    tooltip={"text": "Pozo: {Pozos}"}
))
