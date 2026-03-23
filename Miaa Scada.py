import streamlit as st
import pandas as pd
import pydeck as pdk
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime
import datetime as dt

# 1---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
st.set_page_config(
    page_title="MIAA - Estado de Pozos 3D Relieve", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2-----------------------------------------------------------------------------------2. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed;
            top: 15px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999999;
            color: #00d4ff;
            font-size: 1.5rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff, 0 0 10px #00d4ff; transform: translateX(-50%) scale(1); }
            to { text-shadow: 0 0 15px #00d4ff, 0 0 25px #0077ff; transform: translateX(-50%) scale(1.02); }
        }
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        [data-testid="stSidebarContent"] { padding-top: 0rem !important; }
        .sidebar-logo { display: flex; justify-content: center; padding: 0px !important; margin-top: -70px !important; margin-bottom: 10px; }
        .sidebar-logo img { max-width: 85%; height: auto; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# 3--------------------------------------------------------------------------------3. FUNCIONES DE CONEXIÓN ----------------------------------------------------------------------------------------------------------
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4-------------------------------------------------------------------------------- 4. CARGA DE DATOS ----------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_pozos_dataframe():
    engine = get_mysql_telemetria_engine()
    if not engine: return pd.DataFrame()
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine)
        def extraer_coords(c):
            try:
                parts = str(c).replace('(', '').replace(')', '').split(',')
                return float(parts[0]), float(parts[1])
            except: return None, None
        df['lat'], df['lon'] = zip(*df['coord'].apply(extraer_coords))
        return df.dropna(subset=['lat', 'lon'])
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def cargar_sectores_geojson():
    conn = get_postgres_conn()
    if not conn: return None
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        features = []
        for _, row in df.iterrows():
            features.append({
                "type": "Feature",
                "geometry": json.loads(row['geo']),
                "properties": {"sector": row['sector']}
            })
        return {"type": "FeatureCollection", "features": features}
    except: return None

def cargar_datos_scada_df(df_pozos):
    engine = get_mysql_scada_engine()
    if not engine or df_pozos.empty: return {}
    tags = []
    for col in ['bomba', 'caudal', 'presion', 'voltaje_L1']:
        tags.extend(df_pozos[col].astype(str).tolist())
    tags = list(set([t for t in tags if t and t not in ['0', 'Sin telemetria', 'None']]))
    try:
        tags_str = "', '".join(tags)
        query = f"SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_str}')"
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except: return {}

# 5-------------------------------------------------------------------------------- 5. PROCESAMIENTO ----------------------------------------------------------------------------------------------------------
df_p = cargar_pozos_dataframe()
sectores_geo = cargar_sectores_geojson()
scada_dict = cargar_datos_scada_df(df_p)
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

def calcular_estado(row):
    bomba_tag = str(row['bomba'])
    l1_tag = str(row['voltaje_L1'])
    if bomba_tag == "Sin telemetria": return [128, 128, 128], "SIN TELEMETRÍA" 
    val_l1, fecha_l1 = scada_dict.get(l1_tag, (0, None))
    if not fecha_l1 or (ahora - fecha_l1).total_seconds() / 3600 > 4: return [255, 165, 0], "FALLA COM." 
    val_bba, _ = scada_dict.get(bomba_tag, (0, None))
    if val_bba == 1: return [0, 255, 0], "OPERANDO" 
    else: return [255, 0, 0], "APAGADO" 

if not df_p.empty:
    res = df_p.apply(lambda r: pd.Series(calcular_estado(r)), axis=1)
    df_p['color_rgb'] = res[0]
    df_p['status_label'] = res[1]

# 6 ------------------------------------------------------------------------------- 6. SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 7--------------------------------------------------------------------------------- 7. MAPA 3D CON RELIEVE Y CALLES -------------------------------------------------------------------------------------------------------------
st.markdown('<div class="titulo-superior">Sistema MIAA - Relieve 3D</div>', unsafe_allow_html=True)

# Vista inicial con inclinación pronunciada para apreciar el relieve
view_state = pdk.ViewState(
    latitude=21.8820,
    longitude=-102.2800,
    zoom=12,
    pitch=60, # Mayor inclinación para ver el terreno
    bearing=0
)

capas = []

# CAPA DE TERRENO (Relieve 3D) - Usa datos de elevación RGB de Mapbox
capa_relieve = pdk.Layer(
    "TerrainLayer",
    elevation_decoder={"rScaler": 1, "gScaler": 0, "bScaler": 0, "offset": 0},
    texture="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", # Textura del mapa
    elevation_data="https://assets.mapbox.com/raster-terrain-rgb/{z}/{x}/{y}.pngraw?access_token=" + st.secrets.get("mapbox_token", ""),
)
# Nota: Si no tienes mapbox_token en secrets, Pydeck usará el relieve por defecto del estilo del mapa.

# CAPA DE SECTORES (Transparente para ver calles)
if sectores_geo:
    capas.append(pdk.Layer(
        "GeoJsonLayer",
        sectores_geo,
        opacity=0.1,
        stroked=True,
        filled=True,
        get_fill_color=[0, 212, 255],
        get_line_color=[0, 212, 255],
        get_line_width=2,
    ))

# CAPA DE PUNTOS DE LOS POZOS (Scatterplot) - Cambian de color según operación
capas.append(pdk.Layer(
    "ScatterplotLayer",
    df_p,
    get_position=['lon', 'lat'],
    get_color='color_rgb',
    get_radius=60,
    pickable=True,
    opacity=0.9,
    stroked=True,
    line_width_min_pixels=1,
    get_line_color=[255, 255, 255]
))

# CAPA DE ETIQUETAS (Nombres)
capas.append(pdk.Layer(
    "TextLayer",
    df_p,
    get_position=['lon', 'lat'],
    get_text='Pozos',
    get_size=15,
    get_color=[255, 255, 255],
    get_alignment_baseline="'bottom'",
    offset_y=-10
))

# MAPA FINAL CON ESTILO SATELITAL HÍBRIDO PARA VER CALLES Y RELIEVE
st.pydeck_chart(pdk.Deck(
    map_style='mapbox://styles/mapbox/satellite-streets-v11', # Satélite + Calles + Nombres
    initial_view_state=view_state,
    layers=capas,
    tooltip={
        "html": "<b>Pozo:</b> {Pozos}<br><b>Estado:</b> {status_label}",
        "style": {"backgroundColor": "#050505", "color": "white"}
    }
))
