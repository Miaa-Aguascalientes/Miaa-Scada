import streamlit as st
import pandas as pd
import pydeck as pdk
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Monitoreo 3D", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# 2. ESTILO CSS: TÍTULO AZUL ANIMADO Y APP
st.markdown("""
    <style>
        .titulo-superior {
            position: fixed; top: 15px; left: 50%; transform: translateX(-50%); z-index: 9999;
            color: #00d4ff; font-size: 1.6rem; font-weight: bold; text-transform: uppercase;
            letter-spacing: 2px; white-space: nowrap;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff; transform: translateX(-50%) scale(1); }
            to { text-shadow: 0 0 20px #0077ff; transform: translateX(-50%) scale(1.02); }
        }
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; border-right: 2px solid #333; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; }
    </style>
    <div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN (Mantenemos tus secrets)
@st.cache_resource
def get_mysql_engine(key):
    try:
        c = st.secrets[key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 4. CARGA Y PROCESAMIENTO DE DATOS
@st.cache_data(ttl=600)
def cargar_datos_completos():
    # A. Sectores de PostgreSQL
    sectores = []
    conn = get_postgres_conn()
    if conn:
        df_s = pd.read_sql('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"', conn)
        sectores = df_s.to_dict('records')
        conn.close()

    # B. Diccionario de Pozos (MySQL)
    eng_t = get_mysql_engine("mysql_telemetria")
    df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", eng_t) if eng_t is not None else pd.DataFrame()

    # C. Datos SCADA (MySQL)
    eng_s = get_mysql_engine("mysql_scada")
    scada_data = {}
    if eng_s:
        query = "SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID"
        df_sc = pd.read_sql(query, eng_s)
        scada_data = {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df_sc.iterrows()}

    return sectores, df_pozos, scada_data

sectores_raw, df_pozos_raw, data_scada = cargar_datos_completos()

# 5. LÓGICA DE ESTADOS Y RESUMEN
pozos_on, pozos_off, pozos_falla, total_q, total_p = [], [], [], 0.0, 0.0
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)
lista_pozos_3d = []

for _, row in df_pozos_raw.iterrows():
    try:
        lat, lon = map(float, str(row['coord']).strip("()").split(','))
        val_bba, f_bba = data_scada.get(row['bomba'], (0, None))
        val_l1, f_l1 = data_scada.get(row['voltaje_L1'], (0, None))
        q = data_scada.get(row['caudal'], (0, None))[0]
        p = data_scada.get(row['presion'], (0, None))[0]

        color, status, h_3d = [0, 255, 0, 200], "OPERANDO", 40 # Verde

        # Lógica Falla Com (+4h)
        if f_l1 and (ahora - f_l1).total_seconds() / 3600 > 4:
            color, status, h_3d = [255, 165, 0, 255], "FALLA COM.", 100 # Naranja
            pozos_falla.append(row['Pozos'])
        elif row['bomba'] == "Sin telemetria":
            color, status, h_3d = [128, 128, 128, 200], "SIN TELEMETRÍA", 10
        elif val_bba == 0:
            color, status, h_3d = [255, 0, 0, 255], "APAGADO", 30 # Rojo
            pozos_off.append(row['Pozos'])
        else:
            pozos_on.append(row['Pozos'])
            total_q += q
            total_p += p

        lista_pozos_3d.append({
            "name": row['Pozos'], "lat": lat, "lon": lon,
            "color": color, "h_3d": h_3d, "status": status,
            "tooltip": f"<b>{row['Pozos']}</b><br>Estado: {status}<br>Caudal: {q:.2f} L/s<br>Presión: {p:.2f} kg"
        })
    except: continue

df_final_3d = pd.DataFrame(lista_pozos_3d)

# 6. MAPA 3D (PYDECK)
# Capa de Sectores (GeoJSON)
geojson_sectores = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": json.loads(s['geo']), "properties": {"sector": s['sector']}} 
    for s in sectores_raw
]}

capa_sectores = pdk.Layer(
    "GeoJsonLayer", geojson_sectores,
    get_fill_color=[0, 212, 255, 30], get_line_color=[0, 212, 255, 120],
    line_width_min_pixels=1, pickable=True
)

# Capa de Pozos (Columnas 3D que "salen" del mapa)
capa_pozos = pdk.Layer(
    "ColumnLayer", df_final_3d,
    get_position="[lon, lat]", get_elevation="h_3d",
    elevation_scale=3, radius=35,
    get_fill_color="color", pickable=True, auto_highlight=True
)

# Capa de Etiquetas de ID
capa_texto = pdk.Layer(
    "TextLayer", df_final_3d,
    get_position="[lon, lat]", get_text="name",
    get_color="color", get_size=14,
    get_alignment_baseline="'bottom'", get_pixel_offset=[0, -15]
)

# Vista inicial inclinada estilo Google Earth
view_state = pdk.ViewState(
    latitude=21.8820, longitude=-102.2800,
    zoom=12.5, pitch=50, bearing=-15
)

# Renderizado
st.pydeck_chart(pdk.Deck(
    layers=[capa_sectores, capa_pozos, capa_texto],
    initial_view_state=view_state,
    map_style="mapbox://styles/mapbox/satellite-v9", # Vista Satélite Real
    tooltip={"html": "{tooltip}", "style": {"backgroundColor": "#050505", "color": "white", "border": "1px solid #00d4ff"}}
))

# 7. SIDEBAR (Tu diseño original)
with st.sidebar:
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="resumen-card"><h4 style="color:#00d4ff;">RESUMEN GLOBAL</h4>
        Caudal: <b style="color:#00FF00;">{total_q:.2f} l/s</b><br>
        Presión: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} kg</b></div>""", unsafe_allow_html=True)
    
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear(); st.rerun()

    with st.expander(f"🟢 Operando ({len(pozos_on)})"):
        for p in sorted(pozos_on): st.write(f"🟢 {p}")
    with st.expander(f"🔴 Apagados ({len(pozos_off)})"):
        for p in sorted(pozos_off): st.write(f"🔴 {p}")
    if pozos_falla:
        with st.expander(f"⚠️ Falla Com. ({len(pozos_falla)})"):
            for p in sorted(pozos_falla): st.write(f"🟠 {p}")

st.info("💡 TIP: Mantén presionado el **CLIC DERECHO** del mouse para rotar e inclinar el mapa.")
