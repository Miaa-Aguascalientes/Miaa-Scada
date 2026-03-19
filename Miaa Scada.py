import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Monitoreo Crítico", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide"
)

# 2. ESTILO CSS (Diseño persistente)
st.markdown("""
    <style>
        .stApp { background-color: #000000; color: white; }
        [data-testid="stSidebar"] { background-color: #0b1a29; }
        .resumen-card { background: #050505; border: 1px solid #1f4068; border-radius: 5px; padding: 15px; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)

# 3. GESTIÓN DE CONEXIONES (SEGURIDAD TOTAL)
@st.cache_resource
def get_mysql_engine():
    """Conexión a MySQL para Diccionario y SCADA"""
    try:
        c = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(c["password"])
        # Se conecta a la base de datos específica detectada
        return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/miaamx_telemetria2", 
                              pool_recycle=3600, pool_pre_ping=True)
    except Exception as e:
        st.error(f"Error Crítico MySQL: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    """Conexión a PostgreSQL para Cartografía (Sectores)"""
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e:
        st.sidebar.error(f"Error Crítico PostgreSQL: {e}")
        return None

# 4. EXTRACCIÓN DE DATOS
def cargar_configuracion_pozos():
    """Lee los 5 pozos y sus tags desde la tabla Diccionario_de_pozos"""
    engine = get_mysql_engine()
    if engine is None: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df = pd.read_sql(query, engine)
        
        diccionario = {}
        for _, row in df.iterrows():
            # Limpieza y conversión de coordenadas
            coords = tuple(map(float, row['coord'].replace(' ', '').split(',')))
            
            diccionario[row['Pozos']] = {
                "coord": coords,
                "tags": {
                    "bomba": row['bomba'],
                    "caudal": row['caudal'],
                    "presion": row['presion'],
                    "sumergencia": row['sumergencia'],
                    "nivel_dinamico": row['nivel_dinamico'],
                    "nivel_tanque": row['nivel_tanque'],
                    "v": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                    "a": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
                }
            }
        return diccionario
    except Exception as e:
        st.error(f"Error al leer Diccionario: {e}")
        return {}

def obtener_lecturas_scada(diccionario):
    """Obtiene los valores en tiempo real desde el historial de tags"""
    engine = get_mysql_engine()
    if not engine or not diccionario: return {}
    
    # Extraer todos los tags únicos para una sola consulta
    tags = []
    for p in diccionario.values():
        t = p['tags']
        tags.extend([t['bomba'], t['caudal'], t['presion'], t['sumergencia'], t['nivel_dinamico'], t['nivel_tanque']] + t['v'] + t['a'])
    
    try:
        tags_filt = "', '".join(list(set([str(x) for x in tags if x and x != '0'])))
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM vfitagnumhistory h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_filt}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM vfitagnumhistory WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%H:%M')) for _, row in df.iterrows()}
    except:
        return {}

@st.cache_data(ttl=600)
def cargar_capa_sectores():
    """Carga polígonos desde PostgreSQL (Esquema Sectorizacion)"""
    conn = get_postgres_conn()
    if not conn: return []
    try:
        with conn.cursor() as cur:
            # Transformación a 4326 para Folium
            cur.execute('SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) FROM "Sectorizacion"."Sectores_hidr"')
            return cur.fetchall()
    except:
        return []
    finally:
        if conn: conn.close()

# 5. LÓGICA DE NEGOCIO
pozos_config = cargar_configuracion_pozos()
lecturas = obtener_lecturas_scada(pozos_config)
sectores_geometria = cargar_capa_sectores()

# 6. INTERFAZ Y MAPA
with st.sidebar:
    st.image("https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/main/LogoMIAA-BpcVaQaq.svg")
    if st.button("🔄 REFRESCAR SISTEMA", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

m = folium.Map(location=[21.885, -102.29], zoom_start=12, tiles="CartoDB dark_matter")
Fullscreen().add_to(m)

# Dibujar sectores primero (fondo)
for nombre, geo_json in sectores_geometria:
    folium.GeoJson(json.loads(geo_json), style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)

# Dibujar todos los pozos detectados en la base de datos
for id_p, p_data in pozos_config.items():
    t = p_data['tags']
    
    # Función auxiliar para lectura con validación
    def get_v(tag): return lecturas.get(tag, (0, "N/A"))
    
    st_bomba = get_v(t['bomba'])[0]
    color = "#00FF00" if st_bomba == 1 else "#FF0000"
    
    # Construcción de Popup (Diseño persistente)
    pop_html = f"""
    <div style="background:#000; color:white; padding:10px; border:1px solid {color}; border-radius:8px; width:250px;">
        <b style="color:#00d4ff;">POZO {id_p}</b><br>
        Caudal: {get_v(t['caudal'])[0]:.2f} L/s<br>
        Presión: {get_v(t['presion'])[0]:.2f} kg<br>
        <hr style="border:0.5px solid #333">
        <small style="color:yellow;">Última act: {get_v(t['bomba'])[1]}</small>
    </div>
    """
    
    folium.CircleMarker(
        location=p_data['coord'],
        radius=7,
        color=color,
        fill=True,
        fill_opacity=1,
        class_name="blink_me" if st_bomba != 1 else "",
        popup=folium.Popup(pop_html, max_width=300)
    ).add_to(m)
    
    folium.Marker(
        location=p_data['coord'],
        icon=folium.DivIcon(html=f'<div style="font-size:12px; font-weight:bold; color:{color}; margin-left:10px;">{id_p}</div>')
    ).add_to(m)

folium_static(m, width=1200, height=700)
