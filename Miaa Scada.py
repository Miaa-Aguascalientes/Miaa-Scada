import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import urllib.parse

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Monitoreo SCADA y Pozos",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide"
)

# 2. ESTILO CSS (Fiel a MIAA: Negro y Azul)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        section[data-testid="stSidebar"] { background-color: #111111 !important; }
        .titulo-superior {
            text-align: center; color: white; font-size: 1.5rem;
            font-weight: bold; margin-bottom: 20px;
        }
        [data-testid="stMetric"] {
            background-color: #111111; border: 1px solid #333;
            border-radius: 10px; padding: 10px !important;
            display: flex; flex-direction: column; align-items: center;
        }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; color: #00d4ff !important; }
        iframe { border: 2px solid #444 !important; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# 3. CONEXIONES A BASES DE DATOS
@st.cache_resource
def get_mysql_engine():
    try:
        creds = st.secrets["mysql"]
        pwd = urllib.parse.quote_plus(creds["password"])
        conn_str = f"mysql+mysqlconnector://{creds['user']}:{pwd}@{creds['host']}/{creds['database']}"
        return create_engine(conn_str)
    except Exception as e:
        st.error(f"Error MySQL: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e:
        st.error(f"Error Postgres: {e}")
        return None

# 4. CARGA DE DATOS
def cargar_datos_unificados():
    engine_mysql = get_mysql_engine()
    conn_pg = get_postgres_conn()
    
    if not engine_mysql or not conn_pg:
        return pd.DataFrame()

    try:
        # 1. Datos de SCADA (MySQL)
        # Ajusta el nombre de la tabla según tu base 'miaamx_telemetria'
        df_scada = pd.read_sql("SELECT * FROM historico_scada ORDER BY fecha DESC LIMIT 500", engine_mysql)
        
        # 2. Datos Geográficos (Postgres)
        query_pg = 'SELECT * FROM "Agua_potable"."Pozos"'
        df_pozos = pd.read_sql(query_pg, conn_pg)
        
        # 3. Cruce de datos (Si el nombre del pozo coincide en ambas)
        # Si no hay columna para cruzar, los manejamos por separado
        return df_scada, df_pozos
    except Exception as e:
        st.error(f"Error al unificar datos: {e}")
        return pd.DataFrame(), pd.DataFrame()

def obtener_icono_pozo(estado):
    estado = str(estado).upper()
    iconos = {
        "FUNCIONANDO": {"color": "green", "icon": "tint"},
        "FUERA DE SERVICIO": {"color": "red", "icon": "exclamation-triangle"},
        "MANTENIMIENTO": {"color": "orange", "icon": "wrench"}
    }
    return iconos.get(estado, {"color": "blue", "icon": "info-circle"})

# --- INTERFAZ DASHBOARD ---
st.markdown('<div class="titulo-superior">TELEMETRÍA SCADA - MONITOREO DE POZOS MIAA</div>', unsafe_allow_html=True)

df_scada, df_pozos = cargar_datos_unificados()

# Sidebar
with st.sidebar:
    st.image("https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/main/LogoMIAA-BpcVaQaq.svg", use_container_width=True)
    if st.button("♻️ Actualizar Telemetría"):
        st.cache_resource.clear()
        st.rerun()

if df_pozos.empty:
    st.warning("No se detectaron datos geográficos de pozos.")
    st.stop()

# MÉTRICAS RÁPIDAS
m1, m2, m3, m4 = st.columns(4)
m1.metric("Pozos Totales", len(df_pozos))
m2.metric("En Operación", len(df_pozos[df_pozos['estado'] == 'FUNCIONANDO']))
if not df_scada.empty:
    # Ejemplo: Último valor de presión registrado en SCADA
    ultima_p = df_scada['presion'].iloc[0] if 'presion' in df_scada.columns else 0
    m3.metric("Presión Promedio", f"{ultima_p} kg/cm²")
m4.metric("Alertas Activas", len(df_pozos[df_pozos['estado'] != 'FUNCIONANDO']))

# MAPA Y TABLA SCADA
col_left, col_right = st.columns([2, 1])

with col_left:
    st.write("📍 **Ubicación y Estado en Tiempo Real**")
    m = folium.Map(location=[21.8853, -102.2916], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    for _, row in df_pozos.iterrows():
        if pd.notnull(row['latitud']) and pd.notnull(row['longitud']):
            estilo = obtener_icono_pozo(row['estado'])
            folium.Marker(
                location=[row['latitud'], row['longitud']],
                icon=folium.Icon(color=estilo['color'], icon=estilo['icon'], prefix='fa'),
                tooltip=f"Pozo: {row['nombre']} | Estado: {row['estado']}"
            ).add_to(m)
    
    folium_static(m, width=850, height=550)

with col_right:
    st.write("📊 **Últimas Lecturas SCADA**")
    if not df_scada.empty:
        # Mostramos los datos crudos del SCADA como pediste anteriormente
        st.dataframe(
            df_scada[['nombre_pozo', 'valor', 'fecha']].head(20), 
            hide_index=True, 
            use_container_width=True
        )
    else:
        st.info("Esperando datos de miaamx_telemetria...")

# TABLA GENERAL
st.divider()
st.subheader("Inventario de Infraestructura (Postgres)")
st.dataframe(df_pozos, use_container_width=True)
