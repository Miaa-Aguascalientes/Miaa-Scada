import streamlit as st
import pandas as pd
import pydeck as pdk
import json
import datetime as dt

# --- TÍTULO AZUL ANIMADO ---
st.markdown("""
    <style>
        .titulo-3d {
            text-align: center;
            color: #00d4ff;
            font-size: 2rem;
            font-weight: bold;
            text-transform: uppercase;
            animation: pulse 2s infinite alternate;
        }
        @keyframes pulse {
            from { text-shadow: 0 0 10px #00d4ff; transform: scale(1); }
            to { text-shadow: 0 0 30px #0077ff; transform: scale(1.03); }
        }
    </style>
    <div class="titulo-3d">🚀 MONITOREO MIAA - PERSPECTIVA 3D</div>
""", unsafe_allow_html=True)

# --- PROCESAMIENTO DE DATOS (Simulado con tu lógica de MIAA) ---
# Nota: Aquí usarías tus funciones de cargar_mapa_pozos() y cargar_scada()
def preparar_datos_3d():
    # Simulamos los datos que ya obtienes de tus DBs
    data = [
        {"name": "P022", "lat": 21.885, "lon": -102.285, "status": "OPERANDO", "h": 100, "color": [0, 255, 0]},
        {"name": "P021", "lat": 21.881, "lon": -102.270, "status": "FALLA COM.", "h": 300, "color": [255, 165, 0]},
        {"name": "P016", "lat": 21.875, "lon": -102.280, "status": "APAGADO", "h": 50, "color": [255, 0, 0]}
    ]
    return pd.DataFrame(data)

df = preparar_datos_3d()

# --- CONFIGURACIÓN DE LA VISTA 3D ---
view_state = pdk.ViewState(
    latitude=21.8820,
    longitude=-102.2800,
    zoom=13,
    pitch=50,   # ESTO DA LA INCLINACIÓN 3D
    bearing=-20 # ESTO DA LA ROTACIÓN
)

# --- CAPAS ---

# 1. Capa de Pozos (Cilindros 3D)
pozos_layer = pdk.Layer(
    "ColumnLayer",
    df,
    get_position="[lon, lat]",
    get_elevation="h", # La altura varía según el estado o caudal
    elevation_scale=2,
    radius=30,
    get_fill_color="color",
    pickable=True,
    auto_highlight=True,
)

# 2. Capa de Texto (ID Pozos)
text_layer = pdk.Layer(
    "TextLayer",
    df,
    get_position="[lon, lat]",
    get_text="name",
    get_size=16,
    get_color="color",
    get_alignment_baseline="'bottom'",
    get_pixel_offset=[0, -20]
)

# --- RENDERIZADO FINAL ---
r = pdk.Deck(
    layers=[pozos_layer, text_layer],
    initial_view_state=view_state,
    map_style="mapbox://styles/mapbox/satellite-v9", # SATÉLITE REAL
    tooltip={"text": "Pozo: {name}\nEstado: {status}"}
)

st.pydeck_chart(r)

st.info("💡 Usa el CLIC DERECHO para rotar e inclinar el mapa como en Google Earth.")
