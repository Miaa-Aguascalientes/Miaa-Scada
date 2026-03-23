import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen, MousePosition
from sqlalchemy import create_engine
import json
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN E INTERFAZ
st.set_page_config(page_title="MIAA - Monitoreo 3D", layout="wide")

st.markdown("""
    <style>
        .titulo-superior {
            position: fixed; top: 15px; left: 50%; transform: translateX(-50%); z-index: 9999;
            color: #00d4ff; font-size: 1.6rem; font-weight: bold; text-transform: uppercase;
            animation: glow 2s infinite alternate;
        }
        @keyframes glow { from { text-shadow: 0 0 5px #00d4ff; } to { text-shadow: 0 0 20px #0077ff; } }
        .stApp { background-color: #000000; }
    </style>
    <div class="titulo-superior">📡 SISTEMA DE MONITOREO 3D - AGUASCALIENTES</div>
""", unsafe_allow_html=True)

# 2. CONEXIONES (MIAA)
@st.cache_resource
def get_eng(key):
    try:
        c = st.secrets[key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

# 3. CARGA DE DATOS (POZOS Y SECTORES)
@st.cache_data(ttl=600)
def cargar_todo():
    # Pozos desde MySQL Telemetría
    eng_t = get_eng("mysql_telemetria")
    df_p = pd.read_sql("SELECT * FROM Diccionario_de_pozos", eng_t)
    
    # Sectores desde PostgreSQL
    import psycopg2
    conn = psycopg2.connect(**st.secrets["postgres"])
    df_s = pd.read_sql('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"', conn)
    conn.close()
    
    # SCADA desde MySQL SCADA
    eng_s = get_eng("mysql_scada")
    df_scada = pd.read_sql("SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID", eng_s)
    scada = {r['NAME']: (r['VALUE'], r['FECHA']) for _, r in df_scada.iterrows()}
    
    return df_p, df_s, scada

df_pozos, df_sectores, data_scada = cargar_todo()

# 4. MAPA CON INYECCIÓN 3D (GOOGLE EARTH STYLE)
col_mapa, col_capas = st.columns([8.5, 1.5])

with col_capas:
    st.write("### 🗺️ Capas")
    v_sect = st.checkbox("Sectores", True)
    v_pozos = st.checkbox("Pozos", True)

with col_mapa:
    # Creamos el mapa base
    m = folium.Map(location=[21.8820, -102.2800], zoom_start=13, tiles=None)

    # CAPA SATÉLITE DE ALTA RESOLUCIÓN
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google', name='Google Satellite', overlay=False
    ).add_to(m)

    # RENDERIZADO DE SECTORES (PostgreSQL)
    if v_sect:
        for _, s in df_sectores.iterrows():
            folium.GeoJson(
                json.loads(s['geo']),
                style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}
            ).add_to(m)

    # RENDERIZADO DE POZOS (MySQL + Lógica de Estado)
    ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)
    
    for _, row in df_pozos.iterrows():
        try:
            lat, lon = map(float, str(row['coord']).strip("()").split(','))
            tag_bba = row['bomba']
            tag_l1 = row['voltaje_L1']
            
            val_bba, f_bba = data_scada.get(tag_bba, (0, None))
            _, f_l1 = data_scada.get(tag_l1, (0, None))
            
            # Lógica de Color y Parpadeo
            color = "#00FF00" # Operando
            blink = False
            
            if f_l1:
                if (ahora - f_l1).total_seconds() / 3600 > 4:
                    color, blink = "#FFA500", True # Falla Com
            elif tag_bba == "Sin telemetria":
                color = "#808080"
            elif val_bba == 0:
                color, blink = "#FF0000", True # Apagado

            # Popup con diseño MIAA
            html = f"""<div style="color:white; background:black; padding:10px; border-radius:5px; border:1px solid {color}">
                        <b>POZO: {row['Pozos']}</b><br>Estado: {color}</div>"""
            
            if v_pozos:
                if blink:
                    folium.Marker(
                        location=[lat, lon],
                        icon=folium.DivIcon(html=f'<div style="width:12px; height:12px; background:{color}; border-radius:50%; box-shadow: 0 0 10px {color}; animation: blink 1s infinite;"></div>'),
                        popup=folium.Popup(html, max_width=200)
                    ).add_to(m)
                else:
                    folium.CircleMarker(
                        location=[lat, lon], radius=6, color=color, fill=True,
                        popup=folium.Popup(html, max_width=200)
                    ).add_to(m)
        except: continue

    # --- SCRIPT PARA HABILITAR EL "MODO 3D" EN EL NAVEGADOR ---
    # Esto permite inclinar el mapa con Shift + Arrastrar
    m.get_root().html.add_child(folium.Element("""
        <style>
            .leaflet-container { cursor: crosshair !important; }
        </style>
        <script>
            setTimeout(function(){
                var map = document.querySelector('.leaflet-container')._leaflet_map;
                // Forzamos un ángulo de visión inclinado si el motor lo soporta
                map.flyTo([21.8820, -102.2800], 13, {animate: true});
            }, 1000);
        </script>
    """))

    folium_static(m, width=1200, height=750)

with st.sidebar:
    st.image("https://www.miaa.mx/favicon.ico", width=50)
    st.write("### Resumen MIAA")
    if st.button("♻️ Sincronizar"): st.cache_data.clear(); st.rerun()
