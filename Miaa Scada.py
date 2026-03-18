import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse

# 1. CONFIGURACIÓN
st.set_page_config(page_title="MIAA - SCADA Completo", page_icon="https://www.miaa.mx/favicon.ico", layout="wide")

# Estilo MIAA
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stMetric"] { background-color: #111111; border: 1px solid #333; border-radius: 10px; padding: 10px !important; }
        [data-testid="stMetricValue"] { color: #00d4ff !important; font-size: 1.5rem !important; }
        .titulo-superior { text-align: center; color: white; font-size: 1.6rem; font-weight: bold; margin-bottom: 20px; }
    </style>
""", unsafe_allow_html=True)

# 2. TU DICCIONARIO DE CONFIGURACIÓN
mapa_pozos_dict = {
    "P002": {
        "coord": (21.88229, -102.31542), "corriente": "PZ_002_TRC_BBA_CRUDO", "caudal": "PZ_002_TRC_CAU_INS", 
        "corrientes_l": ["PZ_002_TRC_CORR_L1", "PZ_002_TRC_CORR_L2", "PZ_002_TRC_CORR_L3"], 
        "presion": "PZ_002_TRC_PRES_INS", 
        "voltajes_l": ["PZ_002_TRC_VOL_L1_L2", "PZ_002_TRC_VOL_L2_L3", "PZ_002_TRC_VOL_L1_L3"], 
        "nivel_estatico": "PZ_002_TRC_NIV_EST", "sumergencia": "PZ_002_TRC_SUMERG", "nivel_tanque": "0", 
    },
    "P003": {
        "coord": (21.88603, -102.26653), "corriente": "PZ_003_BBA_CRUDO", "caudal": "PZ_003_CAU_INS", 
        "corrientes_l": ["PZ_003_CORR_L1", "PZ_003_CORR_L2", "PZ_003_CORR_L3"], 
        "presion": "PZ_003_PRES_INS", 
        "voltajes_l": ["PZ_003_VOL_L1_L2", "PZ_003_VOL_L2_L3", "PZ_003_VOL_L1_L3"], 
        "nivel_estatico": "PZ_003_NIV_EST", "sumergencia": "PZ_003_SUMERG", "nivel_tanque": "PZ_159_NIV_TQ", 
    }
}

# 3. CONEXIONES
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
    except Exception as e:
        st.error(f"Error MySQL: {e}"); return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e: st.error(f"Error Postgres: {e}"); return None

# 4. CARGA DE DATOS OPTIMIZADA
def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}

    # Extraer todos los tags únicos del diccionario para una sola consulta
    all_tags = []
    for info in mapa_pozos_dict.values():
        for key, val in info.items():
            if isinstance(val, list): all_tags.extend(val)
            elif isinstance(val, str) and val != "0": all_tags.append(val)
    
    all_tags = list(set(all_tags)) # Eliminar duplicados
    
    try:
        # Consulta masiva para obtener el último valor de cada tag
        query = f"""
            SELECT r.NAME, h.VALUE 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ({str(all_tags)[1:-1]})
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return dict(zip(df['NAME'], df['VALUE']))
    except Exception as e:
        st.error(f"Error al traer tags: {e}"); return {}

@st.cache_data(ttl=600)
def cargar_sectores():
    conn = get_postgres_conn()
    if not conn: return []
    query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
    df = pd.read_sql(query, conn)
    conn.close()
    return df.to_dict('records')

# --- LÓGICA DE INTERFAZ ---
st.markdown('<div class="titulo-superior">MONITOREO TÉCNICO DE POZOS - MIAA</div>', unsafe_allow_html=True)

dict_valores = cargar_datos_scada()
sectores = cargar_sectores()

# Mapa
m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Dibujar Sectores
for s in sectores:
    folium.GeoJson(json.loads(s['geo']),
        style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1},
        tooltip=f"Sector: {s['sector']}").add_to(m)

# Dibujar Pozos con Popups Detallados
for id_pozo, info in mapa_pozos_dict.items():
    p_val = dict_valores.get(info['presion'], 0)
    c_val = dict_valores.get(info['caudal'], 0)
    
    # Construcción del HTML para el Popup (estilo técnico)
    html_popup = f"""
    <div style="font-family: Arial; width: 200px;">
        <h4 style="margin:0; color:#0056b3;">{id_pozo}</h4>
        <hr style="margin:5px 0;">
        <b>Caudal:</b> {c_val:.2f} L/s<br>
        <b>Presión:</b> {p_val:.2f} kg/cm²<br>
        <b>Sumergencia:</b> {dict_valores.get(info['sumergencia'], 0):.2f} m<br>
        <hr style="margin:5px 0;">
        <small>Corriente: {dict_valores.get(info['corriente'], 0):.1f} A</small>
    </div>
    """
    
    color = "green" if c_val > 0 else "red"
    folium.Marker(
        location=info['coord'],
        icon=folium.Icon(color=color, icon='tint', prefix='fa'),
        popup=folium.Popup(html_popup, max_width=250),
        tooltip=f"{id_pozo}: {p_val:.1f} kg/cm²"
    ).add_to(m)

folium_static(m, width=1300, height=600)

# Tabla de Resumen Técnica
st.subheader("Estado de Variables Críticas")
resumen = []
for id_p, info in mapa_pozos_dict.items():
    resumen.append({
        "Pozo": id_p,
        "Caudal (L/s)": dict_valores.get(info['caudal'], 0),
        "Presión (kg/cm²)": dict_valores.get(info['presion'], 0),
        "Sumergencia (m)": dict_valores.get(info['sumergencia'], 0),
        "Nivel Estático": dict_valores.get(info['nivel_estatico'], 0)
    })
st.dataframe(pd.DataFrame(resumen), use_container_width=True, hide_index=True)
