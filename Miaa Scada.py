import streamlit as st
import pandas as pd
import pydeck as pdk
from sqlalchemy import create_engine
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Monitoreo 3D", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide"
)

# 2. ESTILO CSS PARA EL TÍTULO ANIMADO
st.markdown("""
    <style>
        .titulo-superior {
            text-align: center;
            color: #00d4ff;
            font-size: 1.8rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 20px;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            animation: glow 2s ease-in-out infinite alternate;
        }
        @keyframes glow {
            from { text-shadow: 0 0 5px #00d4ff; transform: scale(1); }
            to { text-shadow: 0 0 20px #0077ff; transform: scale(1.02); }
        }
        .stApp { background-color: #000000; }
    </style>
    <div class="titulo-superior">📡 SISTEMA DE MONITOREO 3D - AGUASCALIENTES</div>
""", unsafe_allow_html=True)

# 3. FUNCIONES DE CONEXIÓN (Basadas en tus credenciales)
@st.cache_resource
def get_engine(secret_key):
    try:
        c = st.secrets[secret_key]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except: return None

# 4. CARGA Y PROCESAMIENTO DE DATOS
def obtener_datos_procesados():
    engine_tele = get_engine("mysql_telemetria")
    engine_scada = get_engine("mysql_scada")
    
    if not engine_tele or not engine_scada:
        st.error("Error de conexión a las bases de datos.")
        return pd.DataFrame()

    # Cargar Diccionario
    df_pozos = pd.read_sql("SELECT * FROM Diccionario_de_pozos", engine_tele)
    
    # Obtener últimos valores de SCADA
    query_scada = "SELECT r.NAME, h.VALUE, h.FECHA FROM VfiTagNumHistory_Ultimo h JOIN VfiTagRef r ON h.GATEID = r.GATEID"
    df_scada = pd.read_sql(query_scada, engine_scada)
    scada_dict = dict(zip(df_scada['NAME'], zip(df_scada['VALUE'], df_scada['FECHA'])))

    procesados = []
    ahora = dt.datetime.utcnow() - dt.timedelta(hours=6)

    for _, row in df_pozos.iterrows():
        try:
            coords = str(row['coord']).replace('(', '').replace(')', '').split(',')
            lat, lon = float(coords[0]), float(coords[1])
        except: continue

        # Lógica de Estado (Tu regla de negocio)
        status = "OPERANDO"
        color = [0, 255, 0, 200] # Verde
        
        tag_bomba = row['bomba']
        tag_l1 = row['voltaje_L1']
        
        val_bba, fecha_scada = scada_dict.get(tag_bomba, (0, None))
        _, fecha_l1 = scada_dict.get(tag_l1, (0, None))

        # Validación Falla Com (+4h)
        if fecha_l1:
            diff = (ahora - fecha_l1).total_seconds() / 3600
            if diff > 4:
                status, color = "FALLA COM.", [255, 165, 0, 255] # Naranja
        elif tag_bomba == "Sin telemetria":
            status, color = "SIN TELEMETRÍA", [128, 128, 128, 200] # Gris
        
        if status == "OPERANDO" and val_bba == 0:
            status, color = "APAGADO", [255, 0, 0, 255] # Rojo

        procesados.append({
            "name": row['Pozos'],
            "lat": lat, "lon": lon,
            "status": status,
            "color": color,
            "caudal": scada_dict.get(row['caudal'], (0, ""))[0],
            "presion": scada_dict.get(row['presion'], (0, ""))[0]
        })
    
    return pd.DataFrame(procesados)

data = obtener_datos_procesados()

# 5. RENDERIZADO DEL MAPA 3D (PYDECK)
if not data.empty:
    # Capa de puntos 3D (Cilindros)
    layer_pozos = pdk.Layer(
        "ScatterplotLayer",
        data,
        get_position="[lon, lat]",
        get_color="color",
        get_radius=40,
        pickable=True,
        opacity=0.8,
    )

    # Capa de etiquetas (Texto)
    layer_text = pdk.Layer(
        "TextLayer",
        data,
        get_position="[lon, lat]",
        get_text="name",
        get_color="color",
        get_size=15,
        get_alignment_baseline="'bottom'",
        get_pixel_offset=[0, -15]
    )

    # Configuración de la vista inicial (Inclinada para efecto 3D)
    view_state = pdk.ViewState(
        latitude=21.882,
        longitude=-102.28,
        zoom=12,
        pitch=45, # Inclinación
        bearing=0  # Rotación
    )

    # Render del mapa con estilo Satélite
    r = pdk.Deck(
        layers=[layer_pozos, layer_text],
        initial_view_state=view_state,
        map_style="mapbox://styles/mapbox/satellite-v9", # Vista Satélite
        tooltip={"text": "Pozo: {name}\nEstado: {status}\nCaudal: {caudal} L/s"}
    )

    st.pydeck_chart(r)

# 6. SIDEBAR RESUMEN
with st.sidebar:
    st.image("https://www.miaa.mx/logo.png", width=150)
    st.header("Resumen de Pozos")
    st.metric("Total Operando", len(data[data['status'] == "OPERANDO"]))
    st.metric("Fallas de Com.", len(data[data['status'] == "FALLA COM."]))
    
    if st.button("♻️ Actualizar"):
        st.rerun()
