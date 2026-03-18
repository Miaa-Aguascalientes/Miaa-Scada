import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
import psycopg2
import json

# 1. CONFIGURACIÓN DE PÁGINA
st.set_page_config(
    page_title="MIAA - Monitoreo de Pozos",
    page_icon="https://www.miaa.mx/favicon.ico",
    layout="wide"
)

# 2. ESTILO CSS PERSONALIZADO (Fiel a tu diseño actual)
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        section[data-testid="stSidebar"] { background-color: #111111 !important; }
        .titulo-superior {
            text-align: center;
            color: white;
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 20px;
        }
        [data-testid="stMetric"] {
            background-color: #111111;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 10px !important;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; color: #00d4ff !important; }
        iframe { border: 2px solid #444 !important; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# 3. CONEXIÓN Y DATOS
@st.cache_resource
def get_postgres_conn():
    try:
        return psycopg2.connect(**st.secrets["postgres"])
    except Exception as e:
        st.error(f"Error en conexión: {e}")
        return None

def cargar_datos_pozos():
    conn = get_postgres_conn()
    if not conn: return pd.DataFrame()
    # Usando el esquema corregido según tu historial: Agua_potable."Pozos"
    query = 'SELECT * FROM "Agua_potable"."Pozos"'
    df = pd.read_sql(query, conn)
    conn.close()
    return df

# 4. LÓGICA DE ICONOS (Mapeo de tu archivo original)
def obtener_icono_pozo(estado):
    estado = str(estado).upper()
    # Mapeo extraído de tu lógica de Tkinter
    iconos = {
        "FUNCIONANDO": {"color": "green", "icon": "tint"},
        "FUERA DE SERVICIO": {"color": "red", "icon": "exclamation-triangle"},
        "MANTENIMIENTO": {"color": "orange", "icon": "wrench"},
        "DESCONECTADO": {"color": "gray", "icon": "plug"}
    }
    return iconos.get(estado, {"color": "blue", "icon": "info-circle"})

# --- INTERFAZ ---
st.markdown('<div class="titulo-superior">SISTEMA DE MONITOREO - POZOS AGUASCALIENTES</div>', unsafe_allow_html=True)

df_pozos = cargar_datos_pozos()

# Sidebar con filtros
with st.sidebar:
    st.image("https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/main/LogoMIAA-BpcVaQaq.svg", use_container_width=True)
    st.header("Filtros de Red")
    
    if not df_pozos.empty:
        # Filtro por estado del pozo
        estados = sorted(df_pozos['estado'].dropna().unique())
        estado_sel = st.multiselect("Estado del Pozo", options=estados, default=estados)
        
        # Filtro por zona/sector
        zonas = sorted(df_pozos['sector'].dropna().unique()) if 'sector' in df_pozos.columns else []
        zona_sel = st.multiselect("Sector Hidráulico", options=zonas)
        
        # Aplicar filtros
        df_filtrado = df_pozos[df_pozos['estado'].isin(estado_sel)]
        if zona_sel:
            df_filtrado = df_filtrado[df_filtrado['sector'].isin(zona_sel)]
    else:
        df_filtrado = pd.DataFrame()

# 5. MÉTRICAS (Diseño centrado)
m1, m2, m3 = st.columns(3)
total_pozos = len(df_filtrado)
activos = len(df_filtrado[df_filtrado['estado'] == 'FUNCIONANDO']) if not df_filtrado.empty else 0
fuera = total_pozos - activos

m1.metric("Total Pozos", total_pozos)
m2.metric("En Operación", activos)
m3.metric("Fuera de Servicio", fuera)

# 6. MAPA PRINCIPAL
col_mapa, col_info = st.columns([3, 1])

with col_mapa:
    # Coordenadas iniciales (Aguascalientes)
    m = folium.Map(location=[21.8853, -102.2916], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)
    
    if not df_filtrado.empty:
        for _, row in df_filtrado.iterrows():
            if pd.notnull(row['latitud']) and pd.notnull(row['longitud']):
                estilo = obtener_icono_pozo(row['estado'])
                
                # Popup detallado
                html_popup = f"""
                <div style="font-family: sans-serif; font-size: 12px;">
                    <b style="color:#00d4ff;">POZO: {row['nombre']}</b><br>
                    <b>Estado:</b> {row['estado']}<br>
                    <b>Caudal:</b> {row.get('caudal', 0)} L/s<br>
                    <b>Presión:</b> {row.get('presion', 0)} kg/cm²
                </div>
                """
                
                folium.Marker(
                    location=[row['latitud'], row['longitud']],
                    popup=folium.Popup(html_popup, max_width=200),
                    icon=folium.Icon(color=estilo['color'], icon=estilo['icon'], prefix='fa'),
                    tooltip=f"Pozo: {row['nombre']}"
                ).add_to(m)
    
    folium_static(m, width=1000, height=600)

with col_info:
    st.write("📋 **Detalle de Alarmas**")
    if not df_filtrado.empty:
        # Mostrar solo los que necesitan atención
        alarmas = df_filtrado[df_filtrado['estado'] != 'FUNCIONANDO'][['nombre', 'estado']]
        st.dataframe(alarmas, hide_index=True, use_container_width=True)
    else:
        st.info("No hay pozos que coincidan con el filtro.")

# 7. TABLA TOTAL (Al final, estilo Dashboard)
st.divider()
st.subheader("Registros de Telemetría en Tiempo Real")
st.dataframe(df_filtrado, use_container_width=True)
