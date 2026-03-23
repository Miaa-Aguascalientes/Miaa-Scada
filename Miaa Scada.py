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
    page_title="MIAA - Estado de Pozos 3D", 
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
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; font-weight: bold; }
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
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
        # Convertir a formato GeoJSON FeatureCollection para Pydeck
        features = []
        for _, row in df.iterrows():
            feature = {
                "type": "Feature",
                "geometry": json.loads(row['geo']),
                "properties": {"sector": row['sector']}
            }
            features.append(feature)
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
    if bomba_tag == "Sin telemetria": return "#808080", "SIN TELEMETRÍA", 0
    val_l1, fecha_l1 = scada_dict.get(l1_tag, (0, None))
    if not fecha_l1 or (ahora - fecha_l1).total_seconds() / 3600 > 4: return "#FFA500", "FALLA COM.", 1
    val_bba, _ = scada_dict.get(bomba_tag, (0, None))
    if val_bba == 1: return "#00FF00", "OPERANDO", 2
    else: return "#FF0000", "APAGADO", 3

if not df_p.empty:
    df_p[['color_hex', 'status_label', 'status_code']] = df_p.apply(lambda r: pd.Series(calcular_estado(r)), axis=1)
    df_p['color_rgb'] = df_p['color_hex'].apply(lambda x: [int(x[i:i+2], 16) for i in (1, 3, 5)] + [255])
    # Altura basada en caudal para el efecto 3D
    df_p['altura_3d'] = df_p['Pozos'].apply(lambda x: scada_dict.get(df_p.loc[df_p['Pozos']==x, 'caudal'].values[0], (0,0))[0] * 30)

# 6 ------------------------------------------------------------------------------- 6. SIDEBAR ------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("### RESUMEN")
    if not df_p.empty:
        st.write(f"🟢 Operando: {len(df_p[df_p['status_code']==2])}")
        st.write(f"🔴 Apagados: {len(df_p[df_p['status_code']==3])}")
        st.write(f"🟠 Falla Com: {len(df_p[df_p['status_code']==1])}")

# 7--------------------------------------------------------------------------------- 7. MAPA 3D REAL (CALLES Y SECTORES) -------------------------------------------------------------------------------------------------------------
st.markdown('<div class="titulo-superior">Monitoreo MIAA 3D</div>', unsafe_allow_html=True)

# Estado de la vista (Inclinada y con zoom para ver calles)
view_state = pdk.ViewState(
    latitude=21.8820,
    longitude=-102.2800,
    zoom=13,
    pitch=50,
    bearing=-10
)

capas = []

# Capa 1: Sectores (GeoJSON)
if sectores_geo:
    capas.append(pdk.Layer(
        "GeoJsonLayer",
        sectores_geo,
        opacity=0.1,
        stroked=True,
        filled=True,
        get_fill_color=[0, 212, 255, 100],
        get_line_color=[0, 212, 255, 255],
        get_line_width=2,
    ))

# Capa 2: Pozos en 3D (Columnas)
capas.append(pdk.Layer(
    "ColumnLayer",
    df_p,
    get_position=['lon', 'lat'],
    get_elevation='altura_3d',
    elevation_scale=1,
    radius=35,
    get_fill_color='color_rgb',
    pickable=True,
    auto_highlight=True,
))

# Capa 3: Etiquetas de Pozos
capas.append(pdk.Layer(
    "TextLayer",
    df_p,
    get_position=['lon', 'lat'],
    get_text='Pozos',
    get_size=14,
    get_color=[255, 255, 255],
    get_alignment_baseline="'bottom'",
    offset_y=-15
))

# Renderizado del mapa
# El estilo 'mapbox://styles/mapbox/dark-v10' muestra las calles claramente en gris oscuro.
st.pydeck_chart(pdk.Deck(
    map_style='mapbox://styles/mapbox/dark-v10', 
    initial_view_state=view_state,
    layers=capas,
    tooltip={
        "html": "<b>Pozo:</b> {Pozos}<br><b>Estado:</b> {status_label}",
        "style": {"backgroundColor": "#050505", "color": "white", "fontSize": "12px"}
    }
))

if df_p.empty:
    st.error("Error al cargar datos. Verifica la conexión a la base de datos.")
