import streamlit as st
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine
import psycopg2
import json
import urllib.parse
from datetime import datetime

# 1. CONFIGURACIÓN DE PÁGINA (Favicon oficial)
st.set_page_config(
    page_title="MIAA - Control Maestro de Pozos", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# 2. ESTILO CSS PARA LOGOTIPO Y TABLERO
st.markdown("""
    <style>
        .stApp { background-color: #000000 !important; color: white; }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        .header-miaa {
            text-align: center; padding: 10px; border-bottom: 2px solid #00d4ff;
            background: #0b1a29; margin-bottom: 10px;
        }
        .stTable { background-color: #111111; border-radius: 10px; }
    </style>
    <div class="header-miaa">
        <h2 style="color: #00d4ff; margin:0; letter-spacing: 2px;">SISTEMA DE MONITOREO Y SECTORIZACIÓN - MIAA</h2>
    </div>
""", unsafe_allow_html=True)

# 3. DICCIONARIO DE POZOS COMPLETO (Se mantiene intacto)
mapa_pozos_dict = {
    "P005A": {
        "coord": (21.89147, -102.23195), 
        "bomba": "PZ_RP_005_TRHDAS_BBA_CRUDO", 
        "caudal": "PZ_RP_005_TRHDAS_CAU_INS", 
        "presion": "PZ_RP_005_TRHDAS_PRES_INS", 
        "sumergencia": "PZ_RP_005_TRHDAS_SUMERG", 
        "nivel_dinamico": "PZ_RP_005_TRHDAS_NIV_EST", 
        "nivel_tanque": "RB_241_NIV_TQ_R", 
        "voltajes_l": ["PZ_RP_005_TRHDAS_VOL_L1_L2", "PZ_RP_005_TRHDAS_VOL_L2_L3", "PZ_RP_005_TRHDAS_VOL_L1_L3"],
        "amperajes_l": ["PZ_RP_005_TRHDAS_CORR_L1", "PZ_RP_005_TRHDAS_CORR_L2", "PZ_RP_005_TRHDAS_CORR_L3"]
    },
    "P006": {
        "coord": (21.91504, -102.281668), 
        "bomba": "PZ_006_TRC_BBA_CRUDO", 
        "caudal": "PZ_006_TRC_CAU_INS", 
        "presion": "PZ_006_TRC_PRES_INS", 
        "sumergencia": "PZ_006_TRC_SUMERG", 
        "nivel_dinamico": "PZ_006_TRC_NIV_EST",
        "nivel_tanque": "0", 
        "voltajes_l": ["PZ_006_TRC_VOL_L1_L2", "PZ_006_TRC_VOL_L2_L3", "PZ_006_TRC_VOL_L1_L3"],
        "amperajes_l": ["PZ_006_TRC_CORR_L1", "PZ_006_TRC_CORR_L2", "PZ_006_TRC_CORR_L3"]
    }
}

# 4. FUNCIONES DE CARGA SIMPLIFICADAS
@st.cache_resource
def get_postgres_conn():
    try: return psycopg2.connect(**st.secrets["postgres"])
    except: return None

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        query = 'SELECT sector, ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo FROM "Sectorizacion"."Sectores_hidr"'
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except: return []

# --- 5. PROCESAMIENTO (Demostración de estados) ---
sectores = cargar_sectores_poligonos()
ahora = datetime.now()

# Mantenemos estados fijos: P005A es ON (Verde), P006 es OFF (Rojo parpadeante)
status_demo = {
    "P005A": {'txt_status': 'OPERANDO', 'color_hex': '#00FF00', 'blink': False}, 
    "P006": {'txt_status': 'APAGADO', 'color_hex': '#FF0000', 'blink': True}    
}

# --- 6. INTERFAZ: PANEL IZQUIERDO Y MAPA PRINCIPAL ---
col_info, col_map = st.columns([1, 3])

with col_info:
    st.markdown("### 📊 Estado de Pozos")
    resumen_lista = []
    resumen_lista.append({" ": "🟢", "ID": "P005A", "Estado": "OPERANDO"})
    resumen_lista.append({" ": "🔴", "ID": "P006", "Estado": "APAGADO (Blink)"})
    st.table(pd.DataFrame(resumen_lista))

# --- 7. DISEÑO DEL MAPA CON ANIMACIÓN DE PARPADEO ---
with col_map:
    m = folium.Map(location=[21.8900, -102.2500], zoom_start=12, tiles="CartoDB dark_matter")
    Fullscreen().add_to(m)

    # GRUPO 1: SECTORES HIDRÁULICOS
    fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos", show=True)
    for s in sectores:
        folium.GeoJson(
            json.loads(s['geo']),
            style_function=lambda x: {
                'fillColor': '#00d4ff', 'color': '#00d4ff', 'weight': 1, 'fillOpacity': 0.1
            },
            tooltip=f"Sector: {s['sector']}"
        ).add_to(fg_sectores)
    fg_sectores.add_to(m)

    # GRUPO 2: POZOS (Minimalistas)
    fg_pozos = folium.FeatureGroup(name="Pozos", show=True)
    for id_p, coord in [(p, info['coord']) for p, info in mapa_pozos_dict.items()]:
        
        estado = status_demo.get(id_p, {'color_hex': '#FFFF00', 'blink': False})
        
        # Determinar clase CSS condicionalmente
        popup_class_name = 'leaflet-interactive' # Clase base predeterminada de Leaflet
        if estado['blink']:
             popup_class_name += ' blink_me' # Añadir clase personalizada si debe parpadear

        # 2a. PUNTO CIRCULAR SÓLIDO (CircleMarker condicionalmente animado)
        # Aplicamos la clase CSS blink_me solo si estado['blink'] es True
        folium.CircleMarker(
            location=coord,
            radius=6, 
            color=estado['color_hex'], 
            weight=0, 
            fill=True,
            fill_color=estado['color_hex'],
            fill_opacity=1, 
            tooltip=f"Pozo: {id_p} ({estado['txt_status']})",
            class_name=popup_class_name # AQUÍ APLICAMOS LA CLASE DE PARPADEO CONDICIONAL
        ).add_to(fg_pozos)

        # 2b. ETIQUETA DE TEXTO FLOTANTE (Se mantiene igual, sin parpadeo)
        html_label = f"""
        <div style="
            font-family: Arial, sans-serif; font-size: 14px; font-weight: bold;
            color: {estado['color_hex']}; background-color: transparent; white-space: nowrap;
            position: absolute; left: 10px; top: -10px;
        ">
            {id_p}
        </div>
        """
        
        folium.map.Marker(
            location=coord,
            icon=folium.DivIcon(icon_size=(150, 36), icon_anchor=(0, 0), html=html_label)
        ).add_to(fg_pozos)

    fg_pozos.add_to(m)
    
    # Control de capas
    folium.LayerControl(position='topright', collapsed=False).add_to(m)
    
    # --- INYECCIÓN DE CSS PERSONALIZADO PARA EL PARPADEO ---
    # Creamos la animación blink y la clase blink_me
    blink_css = """
    <style>
    @keyframes blink {
        0% { opacity: 1; }
        50% { opacity: 0; }
        100% { opacity: 1; }
    }
    .blink_me {
        animation: blink 1.2s infinite; /* Parpadeo infinito cada 1.2 segundos */
    }
    </style>
    """
    # Insertamos el bloque style directamente en el HTML del mapa
    m.get_root().header.add_child(folium.Element(blink_css))
    
    # Renderizar el mapa
    folium_static(m, width=1050, height=750)
