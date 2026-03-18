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
    page_title="MIAA - Monitoreo SCADA",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS (DARK MODE)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stMetric"] { background-color: #111111; border: 1px solid #333; border-radius: 10px; padding: 10px !important; }
        [data-testid="stMetricValue"] { color: #00d4ff !important; font-size: 1.5rem !important; }
        .main-title { text-align: center; color: #00d4ff; font-size: 1.8rem; font-weight: bold; margin-top: -50px; margin-bottom: 20px; text-transform: uppercase; }
        iframe { border: 1px solid #444 !important; border-radius: 15px; }
    </style>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE CONFIGURACIÓN (Asegúrate que estos nombres existan en VfiTagRef)
mapa_pozos_dict = {
    "P002": {
        "coord": (21.88229, -102.31542), 
        "corriente_bba": "PZ_002_TRC_BBA_CRUDO", 
        "caudal": "PZ_002_TRC_CAU_INS", 
        "presion": "PZ_002_TRC_PRES_INS", 
        "sumergencia": "PZ_002_TRC_SUMERG",
        "nivel_estatico": "PZ_002_TRC_NIV_EST"
    },
    "P003": {
        "coord": (21.88603, -102.26653), 
        "corriente_bba": "PZ_003_BBA_CRUDO", 
        "caudal": "PZ_003_CAU_INS", 
        "presion": "PZ_003_PRES_INS", 
        "sumergencia": "PZ_003_SUMERG",
        "nivel_estatico": "PZ_003_NIV_EST"
    }
}

# 4. CONEXIONES
@st.cache_resource
def get_mysql_engine():
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}", pool_pre_ping=True)
    except Exception as e:
        st.error(f"Error de conexión MySQL: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

# 5. CARGA DE DATOS OPTIMIZADA
def cargar_datos_scada():
    engine = get_mysql_engine()
    if not engine: return {}
    
    # Recolectar todos los tags del diccionario para buscarlos en la DB
    tags_a_buscar = []
    for p in mapa_pozos_dict.values():
        for k, v in p.items():
            if isinstance(v, str) and v.startswith("PZ_"):
                tags_a_buscar.append(v)
    
    if not tags_a_buscar:
        return {}

    try:
        # Buscamos los valores más recientes en vfitagnumhistory
        tags_str = "', '".join(list(set(tags_a_buscar)))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME IN ('{tags_str}')
            AND h.FECHA = (
                SELECT MAX(FECHA) 
                FROM vfitagnumhistory 
                WHERE GATEID = h.GATEID
            )
        """
        df = pd.read_sql(query, engine)
        # Convertimos a diccionario para fácil acceso: { 'TAG_NAME': (VALOR, FECHA) }
        return {row['NAME']: (row['VALUE'], row['FECHA']) for _, row in df.iterrows()}
    except Exception as e:
        st.error(f"Error al consultar vfitagnumhistory: {e}")
        return {}

@st.cache_data(ttl=3600)
def cargar_sectores_pg():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- EJECUCIÓN ---
dict_valores = cargar_datos_scada()
sectores = cargar_sectores_pg()

st.markdown('<p class="main-title">Panel de Control SCADA - MIAA</p>', unsafe_allow_html=True)

# FILA 1: MÉTRICAS
m1, m2, m3, m4 = st.columns(4)
pozos_on = 0
for p in mapa_pozos_dict.values():
    if dict_valores.get(p['corriente_bba'], (0,0))[0] == 1:
        pozos_on += 1

m1.metric("Bombas Encendidas", f"{pozos_on} / {len(mapa_pozos_dict)}")
m2.metric("Caudal Total", f"{sum([dict_valores.get(p['caudal'], (0,0))[0] for p in mapa_pozos_dict.values()]):.1f} L/s")
m3.metric("Presión Promedio", f"{sum([dict_valores.get(p['presion'], (0,0))[0] for p in mapa_pozos_dict.values()])/len(mapa_pozos_dict):.2f} kg")
m4.metric("Sistema", "OPERATIVO")

# FILA 2: MAPA Y PANEL LATERAL
col_map, col_info = st.columns([3, 1])

with col_map:
    m = folium.Map(location=[21.8818, -102.2917], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    for s in sectores:
        folium.GeoJson(json.loads(s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

    for id_p, info in mapa_pozos_dict.items():
        # Lógica de Estado (BBA_CRUDO)
        val_bba, fecha_act = dict_valores.get(info['corriente_bba'], (0, "N/A"))
        
        # Color: Verde si es 1, Rojo si es 0
        color_bba = "green" if val_bba == 1 else "red"
        txt_estado = "ENCENDIDA" if val_bba == 1 else "APAGADA"
        
        # Otros valores
        q_val = dict_valores.get(info['caudal'], (0,0))[0]
        p_val = dict_valores.get(info['presion'], (0,0))[0]
        s_val = dict_valores.get(info['sumergencia'], (0,0))[0]

        # POPUP ESTILO MIAA
        html_content = f"""
        <div style="background-color: #1e1e1e; color: white; padding: 12px; border-radius: 10px; width: 220px; font-family: sans-serif; border: 1px solid #444;">
            <div style="text-align: center; font-weight: bold; border-bottom: 1px solid #00d4ff; padding-bottom: 8px; margin-bottom: 12px; color: #00d4ff;">
                POZO {id_p} - {txt_estado}
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span>💧 <b>Caudal:</b></span> <span style="color: #00d4ff;">{q_val:.2f} L/s</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span>🚀 <b>Presión:</b></span> <span style="color: #00ff00;">{p_val:.2f} kg</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span>📉 <b>Sumergencia:</b></span> <span style="color: #ffaa00;">{s_val:.2f} m</span>
            </div>
            <div style="font-size: 10px; color: #888; text-align: right; margin-top: 10px; border-top: 1px solid #333; padding-top: 5px;">
                Actualizado: {fecha_act}
            </div>
        </div>
        """
        
        iframe = folium.IFrame(html_content, width=250, height=185)
        folium.Marker(
            location=info['coord'],
            icon=folium.Icon(color=color_bba, icon='tint', prefix='fa'),
            popup=folium.Popup(iframe, max_width=260),
            tooltip=f"{id_p}: {txt_estado}"
        ).add_to(m)

    folium_static(m, width=1050, height=650)

with col_info:
    st.markdown("### 📋 Resumen Operativo")
    resumen_lista = []
    for k, v in mapa_pozos_dict.items():
        v_bba = dict_valores.get(v['corriente_bba'], (0,0))[0]
        resumen_lista.append({
            "Estado": "🟢" if v_bba == 1 else "🔴",
            "Pozo": k,
            "Q (L/s)": f"{dict_valores.get(v['caudal'], (0,0))[0]:.1f}"
        })
    st.table(pd.DataFrame(resumen_lista))
