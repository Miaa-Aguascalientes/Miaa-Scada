import streamlit as st
import pandas as pd
import pydeck as pdk
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime, timedelta

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="MIAA - Monitoreo 3D", layout="wide")

# 2. TÍTULO AZUL VIVO Y ANIMADO (CSS)
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 9999;
            color: #00d4ff; font-size: 1.8rem; font-weight: bold; text-transform: uppercase;
            text-shadow: 0 0 15px rgba(0, 212, 255, 0.7);
            animation: pulse-blue 2s infinite alternate;
        }
        @keyframes pulse-blue {
            from { transform: translateX(-50%) scale(1); text-shadow: 0 0 10px #00d4ff; }
            to { transform: translateX(-50%) scale(1.05); text-shadow: 0 0 25px #0077ff; }
        }
        .stApp { background-color: #000000; }
    </style>
    <div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>
""", unsafe_allow_html=True)

# 3. CONEXIONES A BASES DE DATA (MIAA)
@st.cache_resource
def get_mysql_engine(key):
    try:
        c = st.secrets[key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

# 4. CARGA DE DATOS COMPLETA
@st.cache_data(ttl=300)
def cargar_datos_sistema():
    # Cargar todos los pozos (MySQL)
    eng_tele = get_mysql_engine("mysql_telemetria")
    df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", eng_tele)
    
    # Cargar Sectores (PostgreSQL)
    conn_pg = psycopg2.connect(**st.secrets["postgres"])
    df_sectores = pd.read_sql('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"', conn_pg)
    conn_pg.close()
    
    # Cargar SCADA
    eng_scada = get_mysql_engine("mysql_scada")
    df_scada = pd.read_sql("SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID", eng_scada)
    scada_data = {r['NAME']: (r['VALUE'], r['FECHA']) for _, r in df_scada.iterrows()}
    
    return df_pozos, df_sectores, scada_data

df_p, df_s, scada = cargar_datos_sistema()

# 5. PROCESAMIENTO PARA 3D
ahora = datetime.utcnow() - timedelta(hours=6)
lista_pozos_3d = []

for _, row in df_p.iterrows():
    try:
        coords = str(row['coord']).strip("()").split(',')
        lat, lon = float(coords[0]), float(coords[1])
        
        # Lógica de estado y color
        val_bba, _ = scada.get(row['bomba'], (0, None))
        _, f_l1 = scada.get(row['voltaje_L1'], (0, None))
        
        color = [0, 255, 0, 200] # Verde (Operando)
        elevacion = 50
        
        if f_l1 and (ahora - f_l1).total_seconds() / 3600 > 4:
            color = [255, 165, 0, 255] # Naranja (Falla Com)
            elevacion = 150 # Más alto para resaltar falla
        elif val_bba == 0:
            color = [255, 0, 0, 255] # Rojo (Apagado)
            elevacion = 20
            
        lista_pozos_3d.append({
            "name": row['Pozos'], "lat": lat, "lon": lon,
            "color": color, "elev": elevacion,
            "info": f"Pozo: {row['Pozos']} | Bomba: {val_bba}"
        })
    except: continue

df_final_pozos = pd.DataFrame(lista_pozos_3d)

# 6. RENDERIZADO DEL MAPA 3D (PYDECK)
# Convertir sectores a formato GeoJSON para Pydeck
geojson_sectores = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": json.loads(s['geo']), "properties": {"name": s['sector']}} 
    for _, s in df_s.iterrows()
]}

# Capa de Sectores (Planos en el suelo)
capa_sectores = pdk.Layer(
    "GeoJsonLayer",
    geojson_sectores,
    get_fill_color=[0, 212, 255, 30], # Azul MIAA transparente
    get_line_color=[0, 212, 255, 100],
    line_width_min_pixels=1,
)

# Capa de Pozos (Columnas 3D)
capa_pozos = pdk.Layer(
    "ColumnLayer",
    df_final_pozos,
    get_position="[lon, lat]",
    get_elevation="elev",
    elevation_scale=1,
    radius=25,
    get_fill_color="color",
    pickable=True,
)

# Capa de Etiquetas (Nombres de Pozos)
capa_nombres = pdk.Layer(
    "TextLayer",
    df_final_pozos,
    get_position="[lon, lat]",
    get_text="name",
    get_color="color",
    get_size=12,
    get_alignment_baseline="'bottom'",
    get_pixel_offset=[0, -10]
)

# Configuración de cámara inicial (INCLINADA 3D)
view_state = pdk.ViewState(
    latitude=21.8820, longitude=-102.2800,
    zoom=12, pitch=50, bearing=-10
)

# El Mapa Final
r = pdk.Deck(
    layers=[capa_sectores, capa_pozos, capa_nombres],
    initial_view_state=view_state,
    map_style="mapbox://styles/mapbox/satellite-v9", # SATÉLITE REAL
    tooltip={"text": "{info}"}
)

st.pydeck_chart(r)

st.sidebar.image("https://www.miaa.mx/logo.png", width=150)
st.sidebar.write("### Instrucciones 3D")
st.sidebar.info("Manten presionado CLICK DERECHO para rotar e inclinar la cámara.")
