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
from streamlit_autorefresh import st_autorefresh
import hashlib
import bcrypt
import time # Necesario para controlar la duración del intro
import urllib.parse


st.set_page_config(
    page_title="Sistema Scada", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)


# 1  SECCION---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
params = st.query_params
sector_seleccionado = params.get("sector", None)

if sector_seleccionado:
    titulo_pestaña = f"MIAA - Estado de Sector: {sector_seleccionado}"
else:
    titulo_pestaña = "MIAA - Estado de Pozos"

st.set_page_config(
    page_title=titulo_pestaña, 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide", 
    initial_sidebar_state="expanded"
)
count = st_autorefresh(interval=300000, limit=1000, key="scada_refresh")

# 2  SECCION------------------------------------------------------------------------------2. FUNCIONES DE CONEXIÓN ------------------------------------------------------------------------------------------------------
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        conn.close() 
        return psycopg2.connect(**st.secrets["postgres"])
    except: 
        return None

def cargar_datos_scada(lista_tags):
    engine = get_mysql_scada_engine()
    if not engine or not lista_tags: return {}
    try:
        # Convertimos la lista a un string separado por comas para el SQL
        tags_str = "', '".join(lista_tags)
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM VfiTagNumHistory_Ultimo h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        # Retornamos un diccionario con el nombre del tag como llave
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except Exception as e:
        # st.error(f"Error en consulta SCADA: {e}") # Opcional para debug
        return {}

def obtener_historia_7_dias(tag_name):
    engine = get_mysql_scada_engine()
    if not engine or not tag_name: return pd.DataFrame()
    try:
        query = f"""
            SELECT h.FECHA, h.VALUE 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME = '{tag_name}'
            AND h.FECHA >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY h.FECHA ASC
        """
        df = pd.read_sql(query, engine)
        # Forzamos a que sea datetime para que Streamlit detecte la hora
        df['FECHA'] = pd.to_datetime(df['FECHA']) 
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    conn = get_postgres_conn()
    if not conn: return []
    try:
        # Añadimos los campos numéricos solicitados en la consulta
        query = """
            SELECT sector, "Pozos_Sector", 
                   "Superficie", "Long_Red", "Vol_Prod", "U_Domesticos", 
                   "U_NoDom", "U_Tot", "Poblacion", "Cons_m3", 
                   "Faltas_Agua", "Fugas_Tot", "FTC", "FTA", 
                   "Vol_Medid", "Vol_Fact", "Kwh", "costoKw-hr", 
                   "Recaudacion", "Dotacion", "Balance_Estimado",
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) as geo 
            FROM "Sectorizacion"."Sectores_hidr"
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df.to_dict('records')
    except Exception as e:
        st.error(f"Error al cargar sectores: {e}")
        return []

def formato_hora(decimal):
    try:
        if decimal == "N/A" or decimal is None: return "00:00"
        horas = int(float(decimal))
        minutos = int((float(decimal) - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except:
        return "00:00"

def get_blink_icon(color):
    return f"""
    <div style="
        width: 8px; height: 8px; 
        background-color: {color}; 
        border-radius: 50%; 
        box-shadow: 0 0 8px {color};
        animation: blinker 1s linear infinite;">
    </div>
    <style>
    @keyframes blinker {{ 50% {{ opacity: 0.2; }} }}
    </style>
    """

# 3 SECCION -------------------------------------------------------------------------------- 3. CARGA DE DATOS DE DICCIONARIOS -------------------------------------------------------------------------------------------
# DICCIONARIO POZOS
@st.cache_data(ttl=600)
def cargar_mapa_pozos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_pozos"
        df_pozos = pd.read_sql(query, engine)
        
        nuevo_mapa = {}
        for _, row in df_pozos.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                coords = (lat, lon)
            except: continue

            nuevo_mapa[row['Pozos']] = {
                "coord": coords,
                "bomba": row['bomba'],
                "caudal": row['caudal'],
                "presion": row['presion'],
                "sumergencia": row['sumergencia'],
                "nivel_dinamico": row['nivel_dinamico'],
                "nivel_tanque": row['nivel_tanque'],
                "columna": row['columna'],
                "h_arranque": row['H_arranque'],
                "h_paro": row['H_paro'],
                "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
            }
        return nuevo_mapa
    except:
        return {}

# DICCIONARIO DE TANQUES
@st.cache_data(ttl=600)
def cargar_tanques_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_tanques"
        df_tq = pd.read_sql(query, engine)
        
        nuevo_mapa_tq = {}
        for _, row in df_tq.iterrows():
            try:
                # Limpiar y separar coordenadas
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                # Validación de Nivel Máximo para evitar división por cero o error
                n_max = float(row['Nivel_max']) if row.get('Nivel_max') is not None else 1.0
                if n_max <= 0: n_max = 1.0

                nuevo_mapa_tq[row['TQ']] = {
                    "nombre": row['Nombre_tq'],
                    "coord": (lat, lon),
                    "tag_nivel": row['nivel_tanque'], # Usamos el campo nivel_tanque
                    "nivel_max": n_max,
                    "sitios": row['Sitios']
                }
            except: continue
        return nuevo_mapa_tq
    except: return {}
        
# DICCIONARIO DE REBOMBEOS
@st.cache_data(ttl=600)
def cargar_rebombeos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_rebombeos"
        df_rb = pd.read_sql(query, engine)
        
        nuevo_mapa_rb = {}
        for _, row in df_rb.iterrows():
            try:
                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                nuevo_mapa_rb[row['Rebombeo']] = {
                    "nombre": row['Nombre_rebombeo'],
                    "coord": (lat, lon),
                    "telemetria": row['Telemetria'],
                    "presion": row['presion'],
                    "nivel_tanque": row['nivel_tanque'],
                    "voltajes_l": [row['voltaje_L1'], row['voltaje_L2'], row['voltaje_L3']],
                    "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']]
                }
            except: continue
        return nuevo_mapa_rb
    except: return {}


# 4 SECCION -------------------------------------------------------------------------------- 4. GRAFICAR LOS TANQUES EN EL POPUP --------------------------------------------------------------------
params = st.query_params
tag_a_graficar = params.get("graficar_tanque", None)
nombre_tq = params.get("nombre", "Tanque")

if tag_a_graficar:
    import datetime
    import plotly.express as px
    import pandas as pd
    import plotly.graph_objects as go
    
    st.title(f"📊 Análisis de Nivel: {nombre_tq}")
    
    # --- FILTROS DE FECHA ---
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Selecciona un rango:",
            ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"],
            index=2, # <--- CAMBIO: Ahora selecciona 'Últimos 14 días' por defecto
            key="pop_selector_final_v8"
        )

    hoy = datetime.date.today()
    
    # Lógica de selección de fechas
    if opcion_fecha == "Hoy":
        fecha_inicio = hoy
        fecha_fin = hoy
    elif opcion_fecha == "Esta Semana":
        fecha_inicio = hoy - datetime.timedelta(days=hoy.weekday())
        fecha_fin = hoy
    elif opcion_fecha == "Últimos 14 días":
        fecha_inicio = hoy - datetime.timedelta(days=14)
        fecha_fin = hoy
    elif opcion_fecha == "Este Mes":
        fecha_inicio = hoy.replace(day=1)
        fecha_fin = hoy
    else: 
        with col_f2:
            rango = st.date_input("Periodo:", value=(hoy - datetime.timedelta(days=7), hoy), max_value=hoy, key="pop_cal_v8")
            fecha_inicio, fecha_fin = rango if isinstance(rango, tuple) and len(rango)==2 else (hoy, hoy)

    # --- CONSULTA A LA BASE DE DATOS ---
    try:
        engine = get_mysql_scada_engine()
        f_desde = f"{fecha_inicio} 00:00:00"
        f_hasta = f"{fecha_fin} 23:59:59"
        
        query = f"""
            SELECT h.FECHA, h.VALUE 
            FROM vfitagnumhistory h
            JOIN VfiTagRef r ON h.GATEID = r.GATEID
            WHERE r.NAME = '{tag_a_graficar}'
            AND h.FECHA BETWEEN '{f_desde}' AND '{f_hasta}'
            ORDER BY h.FECHA ASC
        """
        
        df_hist = pd.read_sql(query, engine)

        if not df_hist.empty:
            df_hist['FECHA'] = pd.to_datetime(df_hist['FECHA'])
            df_hist['VALUE'] = df_hist['VALUE'].round(2)
            
            # --- CREACIÓN DEL GRÁFICO DE ÁREA DESVANECIDA ---
            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=df_hist['FECHA'],
                y=df_hist['VALUE'],
                mode='lines+markers',
                line=dict(color='#00d4ff', width=2),
                marker=dict(size=4, color='#00d4ff'),
                fill='tozeroy',
                fillcolor='rgba(0, 212, 255, 0.2)', # Efecto desvanecido
                hovertemplate="<b>%{y:.2f} m</b><extra></extra>"
            ))
            
            # --- CONFIGURACIÓN DE LA LÍNEA GUÍA (PUNTEADA GRIS) ---
            fig.update_xaxes(
                showspikes=True, 
                spikecolor="gray", 
                spikethickness=1, 
                spikemode="across", 
                spikesnap="cursor",
                spikedash="dash", 
                showgrid=False
            )
            
            fig.update_layout(
                template="plotly_dark",
                hovermode="x unified",
                xaxis_title="Fecha y Hora",
                yaxis_title="Nivel (m)",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                yaxis=dict(
                    tickformat=".2f",
                    showgrid=True,
                    gridcolor='#333'
                ),
                hoverlabel=dict(
                    bgcolor="#1f2c38",
                    font_size=12
                )
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("Ver tabla de datos detallada"):
                st.dataframe(
                    df_hist[['FECHA', 'VALUE']].sort_values(by='FECHA', ascending=False), 
                    use_container_width=True
                )
        else:
            st.warning(f"No hay datos registrados desde el {f_desde} hasta el {f_hasta}")
            
    except Exception as e:
        st.error(f"Error en la consulta: {e}")
    
    st.stop()
# 5  SECCION-----------------------------------------------------------------------------------5. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        /* 1. BLOQUEO TOTAL DE SIDEBAR Y ELIMINACIÓN DE FLECHAS */
        [data-testid="collapsedControl"], 
        button[kind="headerNoPadding"], 
        [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }

        [data-testid="stSidebar"] {
            min-width: 320px !important; 
            max-width: 320px !important;
            width: 320px !important;
        }

        /* 2. LIMPIEZA DE INTERFAZ Y MODO ADMINISTRADOR */
        [data-testid="stNotification"], .stAlert, [data-testid="stStatusWidget"] {
            display: none !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        #MainMenu { visibility: hidden !important; }
        footer { visibility: hidden !important; }

        /* 3. LOGO EN LO MÁS ALTO */
        .sidebar-logo { 
            position: fixed;
            top: 0px;
            left: 0px;
            width: 320px;
            height: 100px;
            z-index: 999999;
            display: flex; 
            justify-content: center; 
            align-items: center;
            background-color: #0b1a29; 
            border-bottom: 1px solid #1f4068;
        }
        .sidebar-logo img { width: 80%; height: auto; }

        /* 4. CONTENEDOR PRINCIPAL - ELIMINAR EL HUECO ENTRE TÍTULO Y MAPA */
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0rem !important;    /* Elimina el espacio muerto arriba */
            padding-bottom: 0rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            margin-top: 100px !important;    /* Sube todo el contenido para cubrir el hueco del header */
        }

        /* QUITAMOS CUALQUIER MARGEN EXTRA DEL COMPONENTE DEL MAPA */
        iframe {
            margin-top: -110px !important; /* Margen negativo para succionar el mapa hacia arriba */
        }

        /* 5. TÍTULO SUPERIOR (BARRA FIJA) */
        .titulo-superior {
            position: fixed;
            top: 0px; 
            left: calc(50% + 160px); 
            transform: translateX(-50%);
            z-index: 1000;
            color: #00d4ff; 
            font-size: 1.5rem;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 2px;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            background-color: #000000; /* Fondo sólido para que no haya transparencias feas */
            width: 100%;
            text-align: center;
            padding: 10px 0;
            border-bottom: 1px solid #1f4068;
        }

        /* 6. SIDEBAR - CONTENIDO PEGADO AL LOGO */
        [data-testid="stSidebarContent"] {
            padding-top: 110px !important; 
        }

        [data-testid="stSidebar"] { 
            background-color: #0b1a29 !important; 
            border-right: 2px solid #1f4068; 
        }

                /* --- COMPONENTES DEL DASHBOARD --- */
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 auto !important;
        }
        
        .resumen-card { 
            background: #050505; 
            border: 1px solid #1f4068; 
            border-radius: 5px; 
            padding: 15px; 
            margin-bottom: 15px; 
        }
        
        .status-tag { 
            font-size: 10px; 
            padding: 2px 6px; 
            border-radius: 4px; 
            margin-left: 5px; 
            font-weight: bold; 
        }
        
        .status-ok { background-color: #1b5e20; color: #a5d6a7; }
        .status-err { background-color: #b71c1c; color: #ef9a9a; }
        
        .section-header { 
            padding: 10px; 
            border-radius: 3px; 
            font-weight: bold; 
            margin-bottom: 5px; 
            color: white; 
        }

        /* ANIMACIÓN DE PARPADEO */
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } 100% { opacity: 1; } }
        .blink_me { animation: blink 1.2s infinite; }
    </style>
""", unsafe_allow_html=True)
# 6 SECCION------------------------------------------------------- 6. PROCESAMIENTO (MODIFICADO) -----------------------------------------------------------------

# 1. Carga de datos base
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
mapa_tanques_dict = cargar_tanques_desde_db()
mapa_rebombeos_dict = cargar_rebombeos_desde_db()

# 2. Recolección de tags para la consulta masiva
tags_a_consultar = []

for p in mapa_pozos_dict.values():
    # Añadimos los campos que te faltaban: nivel_dinamico, sumergencia y columna
    tags_a_consultar.extend([
        p['bomba'], 
        p['caudal'], 
        p['presion'], 
        p['nivel_tanque'],
        p['nivel_dinamico'], # <-- AGREGADO
        p['sumergencia'],     # <-- AGREGADO
        p['columna']          # <-- AGREGADO
    ])
    # Voltajes y amperajes
    tags_a_consultar.extend(p['voltajes_l'] + p['amperajes_l'])

# Tags de Tanques
for t in mapa_tanques_dict.values():
    if t['tag_nivel']: tags_a_consultar.append(t['tag_nivel'])

# Tags de Rebombeos
for r in mapa_rebombeos_dict.values():
    tags_a_consultar.extend([r['presion'], r['nivel_tanque']])
    tags_a_consultar.extend(r['voltajes_l'] + r['amperajes_l'])

# Limpieza de la lista
tags_finales = list(set([str(t).strip() for t in tags_a_consultar if t and str(t) not in ['0', 'Sin telemetria', 'None']]))

# 3. Consulta al SCADA pasando la LISTA corregida
data_scada = cargar_datos_scada(tags_finales)

# 4. Inicialización de contadores
pozos_on, pozos_off, pozos_sin_telemetria, pozos_falla_com = [], [], [], []
total_q, total_p = 0.0, 0.0

import datetime as dt
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6) 

# --- LÓGICA DE POZOS ---
for id_p, info in mapa_pozos_dict.items():
    bomba_val = str(info['bomba']).strip()
    if bomba_val == "Sin telemetria":
        info.update({'status_label': 'SIN TELEMETRÍA', 'color_final': '#808080', 'blink': False})
        pozos_sin_telemetria.append(id_p)
        continue

    tag_l1 = info['voltajes_l'][0]
    _, fecha_str = data_scada.get(tag_l1, (0, "N/A"))
    
    es_falla_com = False
    if fecha_str != "N/A":
        try:
            fecha_dt = dt.datetime.strptime(f"{ahora.year}/{fecha_str}", "%Y/%d/%m %H:%M")
            if (ahora - fecha_dt).total_seconds() / 3600 > 4: es_falla_com = True
        except: es_falla_com = True
    else: es_falla_com = True

    if es_falla_com:
        info.update({'status_label': 'FALLA COM.', 'color_final': '#FFA500', 'blink': True})
        pozos_falla_com.append(id_p)
    else:
        val_bba, _ = data_scada.get(info['bomba'], (0, "N/A"))
        if val_bba == 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, ""))[0]
            total_p += data_scada.get(info['presion'], (0, ""))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# --- LÓGICA DE REBOMBEOS (CORREGIDA) ---
for id_rb, info in mapa_rebombeos_dict.items():
    # 1. Validar primero si el equipo está marcado como "Sin telemetria"
    # Convertimos a string y quitamos espacios para asegurar la comparación
    telemetria_status = str(info.get('telemetria', '')).strip().lower()
    
    if telemetria_status == "sin telemetria":
        info.update({
            'status_label': 'SIN TELEMETRÍA', 
            'color_final': '#808080',  # Color Gris
            'blink': False
        })
    else:
        # 2. Si tiene telemetría, aplicar la lógica de presión actual
        pres_val, _ = data_scada.get(info['presion'], (0, "N/A"))
        if pres_val < 0.10:
            info.update({
                'status_label': 'APAGADO', 
                'color_final': '#FF0000', 
                'blink': True
            })
        else:
            info.update({
                'status_label': 'OPERANDO', 
                'color_final': '#00FF00', 
                'blink': False
            })


# 7 SECCIÓN --------------------------------------------------------------7 VISTA DETALLE DEL SECTOR ---------------------------------------------------------------
if sector_seleccionado:
    # 1. Título superior fijo
    st.markdown(f'<div class="titulo-superior">Análisis de Sector: {sector_seleccionado}</div>', unsafe_allow_html=True)
    
    datos_s = next((s for s in sectores if s['sector'] == sector_seleccionado), None)
    
    if datos_s:
        st.markdown("""
            <style>
                /* Reducimos el espacio que Streamlit reserva arriba */
                .block-container { 
                    padding-top: 3.5rem !important; 
                    margin-top: 0px !important; 
                }
                
                /* Contenedor de métricas ultra-compacto */
                .metrics-container {
                    position: relative;
                    z-index: 9999;
                    margin-top: -700px; /* Subimos las métricas hacia el título */
                    margin-bottom: 5px;
                }

                .micro-card {
                    background: #0b1a29; 
                    border: 1px solid #1f4068;
                    border-radius: 5px; 
                    padding: 8px; /* Padding más pequeño */
                    text-align: center;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.5);
                }
                .micro-label { color: #888; font-size: 10px; text-transform: uppercase; margin-bottom: 2px; }
                .micro-value { color: #00d4ff; font-size: 15px; font-weight: bold; }
                
                /* Reducimos el espacio que ocupa el divisor */
                hr {
                    margin-top: 5px !important;
                    margin-bottom: 10px !important;
                    opacity: 0.3;
                }

                /* Ajuste del mapa para que no suba sobre las métricas pero no deje huecos */
                iframe {
                    margin-top: 0px !important;
                }
            </style>
        """, unsafe_allow_html=True)

        # Renderizado de métricas
        st.markdown('<div class="metrics-container">', unsafe_allow_html=True)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: st.markdown(f'<div class="micro-card"><div class="micro-label">Población</div><div class="micro-value">{datos_s.get("Poblacion", 0):,.0f}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="micro-card"><div class="micro-label">U. Totales</div><div class="micro-value">{datos_s.get("U_Tot", 0):,.0f}</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="micro-card"><div class="micro-label">U. Domésticos</div><div class="micro-value">{datos_s.get("U_Domesticos", 0):,.0f}</div></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="micro-card"><div class="micro-label">Consumo m³</div><div class="micro-value">{datos_s.get("Cons_m3", 0):,.1f}</div></div>', unsafe_allow_html=True)
        with c5: st.markdown(f'<div class="micro-card"><div class="micro-label">Dotación</div><div class="micro-value">{datos_s.get("Dotacion", 0):,.1f}</div></div>', unsafe_allow_html=True)
        with c6: st.markdown(f'<div class="micro-card"><div class="micro-label">Balance</div><div class="micro-value">{datos_s.get("Balance_Estimado", 0):,.1f}%</div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.divider() # Este divisor ahora es más delgado por el CSS de arriba

        # --- MAPA DEL SECTOR ---
        ids_pozos = [p.strip() for p in datos_s.get('Pozos_Sector', '').split(',')] if datos_s.get('Pozos_Sector') else []
        m_sec = folium.Map(location=[21.8820, -102.2800], zoom_start=14, tiles="CartoDB dark_matter")
        Fullscreen().add_to(m_sec)
        
        geojson_sector = folium.GeoJson(
            json.loads(datos_s['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 2, 'fillOpacity': 0.1}
        ).add_to(m_sec)

        for id_p in ids_pozos:
            if id_p in mapa_pozos_dict:
                info = mapa_pozos_dict[id_p]
                
                # --- EXTRACCIÓN DE DATOS PARA EL POPUP ---
                d = lambda tag: data_scada.get(tag, (0, "N/A"))
                is_st = (info['status_label'] == 'SIN TELEMETRÍA')
                
                q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
                p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
                sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
                dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
                tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
                col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
                
                h_arr_val, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
                h_par_val, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
                h_arr_fmt = formato_hora(h_arr_val)
                h_par_fmt = formato_hora(h_par_val)
                
                v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
                a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

                # Tu HTML personalizado integrado
                html_popup_sec = f"""
                <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
                    <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                        <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                        <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span>
                        </div>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>🔋 Nivel de Tanque:<b>{tanq:.2f} mts</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📉 Nivel Dinámico/Estatico: <b>{dinam:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📏 Sumergencia: <b>{sumer:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>🏗️ Longitud de Columna: <b>{col:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                    </div>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
                        <table style="width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 8px;">
                            <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                                <th style="padding: 4px;">Fase</th>
                                <th style="padding: 4px;">Voltaje / Act.</th>
                                <th style="padding: 4px;">Amp / Act.</th>
                            </tr>
                            <tr style="border-bottom: 1px solid #222;">
                                <td style="padding: 6px 4px;">L1-L2</td>
                                <td><b>{v[0][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[0][1]}</span></td>
                                <td><b>{a[0][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[0][1]}</span></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #222;">
                                <td style="padding: 6px 4px;">L2-L3</td>
                                <td><b>{v[1][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[1][1]}</span></td>
                                <td><b>{a[1][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[1][1]}</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 4px;">L1-L3</td>
                                <td><b>{v[2][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[2][1]}</span></td>
                                <td><b>{a[2][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[2][1]}</span></td>
                            </tr>
                        </table>
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px; border-top: 1px solid #222; padding-top: 5px;">HORARIOS</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>▶️ Arranque: <b>{h_arr_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_arr}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>⏹️ Paro: <b>{h_par_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_par}</span>
                        </div>
                    </div>
                </div>
                """

                # Marcador con lógica de parpadeo (Blink)
                if info.get('blink'):
                    folium.Marker(
                        location=info['coord'],
                        icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                        popup=folium.Popup(html_popup_sec, max_width=450)
                    ).add_to(m_sec)
                else:
                    folium.CircleMarker(
                        location=info['coord'], radius=5, color=info['color_final'], 
                        fill=True, fill_color=info['color_final'], fill_opacity=1,
                        popup=folium.Popup(html_popup_sec, max_width=450)
                    ).add_to(m_sec)
                
                # Etiqueta de ID
                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(
                        icon_anchor=(-12, 12),
                        html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; text-shadow: 1px 1px #000;">{id_p}</div>'
                    )
                ).add_to(m_sec)

        try:
            m_sec.fit_bounds(geojson_sector.get_bounds())
        except: pass

        folium_static(m_sec, width=None, height=750)
    else:
        st.error(f"No se encontró información para el sector {sector_seleccionado}")
    
    st.stop()
    
# 8 SECCION ------------------------------------------------------------------------------- 8. SIDEBAR BARRA LATERAL IZQUIERDA ------------------------------------------------------------------------------------------
with st.sidebar:
    # Contenedor del logo
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg"></div>', unsafe_allow_html=True)

    # 1. Inicializamos variables de estado (Solo si no existen)
    if 'centro_mapa' not in st.session_state:
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5

    # --- RESUMEN GLOBAL ---
    st.markdown(f"""
        <div class="resumen-card">
            <h4 style="color:#00d4ff; margin-top:0;">RESUMEN GLOBAL</h4>
            <p>Caudal Total: <b style="color:#00FF00;">{total_q:.2f} l/s</b></p>
            <p>Presión Prom: <b style="color:#FFFF00;">{total_p/max(len(pozos_on),1):.2f} Kg/cm²</b></p>
        </div>
    """, unsafe_allow_html=True)
    
    # --- ESTADO DE LAS CONEXIONES ---    
    with st.expander("🔌 Estado de las Conexiones", expanded=False):
        status_mysql_scada = "OK" if get_mysql_scada_engine() else "ERROR"
        status_mysql_tele = "OK" if get_mysql_telemetria_engine() else "ERROR"
        status_postgres = "OK" if get_postgres_conn() else "ERROR"

        def render_status_line(label, status):
            cls = "status-ok" if status == "OK" else "status-err"
            html = f"""
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                <span style="font-weight: bold; font-size: 13px;">{label}</span>
                <span class="status-tag {cls}">{status}</span>
            </div>
            """
            st.markdown(html, unsafe_allow_html=True)

        render_status_line("BD-Scada:", status_mysql_scada)
        render_status_line("BD-Diccionarios:", status_mysql_tele)
        render_status_line("BD-PostgreSQL:", status_postgres)
    
    # 2. Buscador de Pozos
    lista_pozos_nombres = sorted(list(mapa_pozos_dict.keys()))
    pozo_buscado = st.selectbox(
        "🔍 Localizar Sitio",
        options=[""] + lista_pozos_nombres,
        format_func=lambda x: "Seleccionar Sitio..." if x == "" else f" {x}"
    )

    # 3. Buscador de Sectores
    lista_sectores = sorted([s['sector'] for s in sectores])
    sector_buscado = st.selectbox(
        "🏘️ Localizar Sector",
        options=[""] + lista_sectores,
        format_func=lambda x: "Seleccionar Sector..." if x == "" else f" {x}",
        key="busqueda_sectores"
    )

    # 4. ASIGNACIÓN DE POSICIÓN Y PRIORIDAD
    datos_sector_resaltado = None

    if pozo_buscado:
        # Prioridad 1: Pozo seleccionado
        st.session_state.centro_mapa = mapa_pozos_dict[pozo_buscado]['coord']
        st.session_state.zoom_inicial = 18
    elif sector_buscado:
        # Prioridad 2: Sector seleccionado
        datos_s = next((s for s in sectores if s['sector'] == sector_buscado), None)
        if datos_s:
            datos_sector_resaltado = datos_s
            try:
                geom = json.loads(datos_s['geo'])
                coords_raw = geom['coordinates'][0][0][0] if geom['type'] == 'MultiPolygon' else geom['coordinates'][0][0]
                st.session_state.centro_mapa = [coords_raw[1], coords_raw[0]]
                st.session_state.zoom_inicial = 14.5
            except:
                pass
    else:
        # Prioridad 3: Si no hay nada seleccionado, mantener o resetear a vista general
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5
        
    # --- BOTON ACTUALIZAR ---
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
        
    # --- CONTROL DE CAPAS ---
    with st.expander("🗺️ Control de Capas", expanded=False):
        ver_sectores = st.checkbox("Mostrar Sectores", value=True)
        ver_pozos = st.checkbox("Mostrar Pozos", value=True)
        ver_tanques = st.checkbox("Mostrar Tanques", value=True)
        ver_rebombeos = st.checkbox("Mostrar Rebombeos", value=True)
    
    # --- LISTADO DE ESTADOS ---
    with st.expander(f"🟢 Bombas ON ({len(pozos_on)})", expanded=False):
        for p in sorted(pozos_on): 
            st.write(f"🟢 {p}")
    
    with st.expander(f"🔴 Bombas OFF ({len(pozos_off)})", expanded=False):
        for p in sorted(pozos_off): 
            st.write(f"🔴 {p}")

    if pozos_falla_com:
        with st.expander(f"⚠️ Falla de Com. ({len(pozos_falla_com)})", expanded=False):
            for p in sorted(pozos_falla_com):
                st.write(f"🟠 {p}")
    
    if pozos_sin_telemetria:
        with st.expander(f"⚪ Sin Telemetría ({len(pozos_sin_telemetria)})", expanded=False):
            for p in sorted(pozos_sin_telemetria): 
                st.write(f"⚪ {p}")
# 9  SECCION--------------------------------------------------------------------------------- 9. MAPA PRINCIPAL -----------------------------------------------------------------------------------------------------------
# DASHBOARD
st.markdown('<div class="titulo-superior">Sistema de monitoreo - Aguascalientes</div>', unsafe_allow_html=True)
# Proporción ultra-ancha para el mapa (90% mapa, 10% capas)
col_mapa, col_capas = st.columns([0.9, 0.1], gap="small")

with col_mapa:
    # Usamos las variables guardadas en el estado de la sesión
    m = folium.Map(
        location=st.session_state.centro_mapa, 
        zoom_start=st.session_state.zoom_inicial, 
        tiles="CartoDB dark_matter"
    )
    Fullscreen().add_to(m)

# Añadir el resaltado del sector si existe
    if datos_sector_resaltado:
        folium.GeoJson(
            json.loads(datos_sector_resaltado['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 3, 'fillOpacity': 0.4}
        ).add_to(m)

    # FUNCIÓN PARA HORARIO 00:00
    def formato_hora(decimal):
        try:
            if decimal == "N/A" or decimal is None: return "00:00"
            horas = int(float(decimal))
            minutos = int((float(decimal) - horas) * 60)
            return f"{horas:02d}:{minutos:02d}"
        except:
            return "00:00"

    # FUNCIÓN PARA ICONO PARPADEANTE PEQUEÑO (8px)
    def get_blink_icon(color):
        return f"""
        <div style="
            width: 8px; height: 8px; 
            background-color: {color}; 
            border-radius: 50%; 
            box-shadow: 0 0 8px {color};
            animation: blinker 1s linear infinite;">
        </div>
        <style>
        @keyframes blinker {{ 50% {{ opacity: 0.2; }} }}
        </style>
        """

# -------------------------------------------------------------------------------------- RENDERIZADO DE SECTORES (CON RESALTADO RESTAURADO) --------------------------------------------------------------------------

# 1. Definimos una función de estilo estática para evitar cálculos pesados en el loop
def get_sector_style(feature, visible):
    return {
        'fillColor': '#00d4ff',
        'color': '#00d4ff' if visible else 'transparent',
        'weight': 1.5 if visible else 0,
        'fillOpacity': 0.12 if visible else 0.01, # Nunca 0 para que el objeto exista en el DOM
    }

# 1. Cargamos los datos con tu función de caché
sectores_data = cargar_sectores_poligonos()

if sectores_data:
    fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos", z_index=1)
    
    for s in sectores_data:
        try:
            if not s.get('geo'): continue
            
            nombre_sec = s['sector']
            geo_dict = json.loads(s['geo'])
            
            # 2. Reconstrucción del enlace de acceso (Botón)
            # Usamos quote para manejar espacios o caracteres especiales en el nombre del sector
            sector_encoded = urllib.parse.quote(nombre_sec)
            url_acceso = f"/?sector={sector_encoded}&access=granted&role={st.session_state.rol}"
            
            # 3. Popup con diseño y botón restaurado
            html_popup = f"""
            <div style="font-family: 'Segoe UI', sans-serif; width: 220px; background-color: #0b1a29; color: white; padding: 12px; border-radius: 10px; border: 1px dashed #00d4ff;">
                <h4 style="margin:0 0 8px 0; color:#00d4ff; text-align:center;">{nombre_sec}</h4>
                <table style="width:100%; font-size: 11px; margin-bottom: 10px; border-collapse: collapse;">
                    <tr><td><b>Población:</b></td><td style="text-align:right;">{s.get('Poblacion', 0):,.0f}</td></tr>
                    <tr><td><b>Pozos:</b></td><td style="text-align:right;">{s.get('Pozos_Sector', 0)}</td></tr>
                    <tr><td><b>Fugas:</b></td><td style="text-align:right; color:#ff4b4b;">{s.get('Fugas_Tot', 0)}</td></tr>
                </table>
                
                <a href="{url_acceso}" target="_blank" 
                   style="display: block; text-align: center; background-color: #00d4ff; color: #0b1a29; 
                          text-decoration: none; font-weight: bold; font-size: 12px; padding: 8px; 
                          border-radius: 5px; transition: 0.3s;">
                   🚀 ABRIR SECTOR
                </a>
            </div>
            """

            # 4. Lógica de visibilidad (Siempre presentes en el código)
            estilo = {
                'fillColor': '#00d4ff',
                'color': '#00d4ff' if ver_sectores else 'transparent',
                'weight': 1.5 if ver_sectores else 0,
                'fillOpacity': 0.12 if ver_sectores else 0.0001 # Invisible pero "clicable"
            }

            folium.GeoJson(
                geo_dict,
                style_function=lambda x, stl=estilo: stl,
                highlight_function=lambda x: {
                    'fillColor': '#00d4ff', 
                    'color': '#ffffff', 
                    'weight': 3, 
                    'fillOpacity': 0.4
                },
                tooltip=f"Sector: {nombre_sec}",
                popup=folium.Popup(html_popup, max_width=260)
            ).add_to(fg_sectores)

        except Exception:
            continue

    fg_sectores.add_to(m)
    
    # ------------------------------------------------------------------------------ RENDERIZADO DE POZOS (UNIFICADO) ---------------------------------------------------------------------------------------------
    # Usamos solo 'ver_pozos' para controlar ambas cosas
    for id_p, info in mapa_pozos_dict.items():
        if ver_pozos:  # Si el checkbox está activo, dibujamos todo
            d = lambda tag: data_scada.get(tag, (0, "N/A"))
            is_st = (info['status_label'] == 'SIN TELEMETRÍA')
            
            # Extracción de datos
            q, f_q = d(info['caudal']) if not is_st else (0.0, "N/A")
            p, f_p = d(info['presion']) if not is_st else (0.0, "N/A")
            sumer, f_s = d(info['sumergencia']) if not is_st else (0.0, "N/A")
            dinam, f_d = d(info['nivel_dinamico']) if not is_st else (0.0, "N/A")
            tanq, f_t = d(info['nivel_tanque']) if not is_st else (0.0, "N/A")
            col, f_col = d(info['columna']) if not is_st else (0.0, "N/A")
            
            h_arr_val, f_h_arr = d(info['h_arranque']) if not is_st else (0.0, "N/A")
            h_par_val, f_h_par = d(info['h_paro']) if not is_st else (0.0, "N/A")
            h_arr_fmt = formato_hora(h_arr_val)
            h_par_fmt = formato_hora(h_par_val)

            v = [d(t) for t in info['voltajes_l']] if not is_st else [(0.0, "N/A")]*3
            a = [d(t) for t in info['amperajes_l']] if not is_st else [(0.0, "N/A")]*3

            html_popup = f"""
                <div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;">
                    <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;">
                        <b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b>
                        <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>💧 Caudal: <b>{q:.2f} L/s</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>🚀 Presión: <b>{p:.2f} kg</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span>
                        </div>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">NIVELES</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>🔋 Nivel de Tanque:<b>{tanq:.2f} mts</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_t}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📉 Nivel Dinámico/Estatico: <b>{dinam:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_d}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>📏 Sumergencia: <b>{sumer:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_s}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>🏗️ Longitud de Columna: <b>{col:.2f} m</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_col}</span>
                    </div>
                    </div>
                    <div style="margin-bottom: 12px;">
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div>
                        <table style="width: 100%; font-size: 10px; border-collapse: collapse; margin-bottom: 8px;">
                            <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                                <th style="padding: 4px;">Fase</th>
                                <th style="padding: 4px;">Voltaje / Act.</th>
                                <th style="padding: 4px;">Amp / Act.</th>
                            </tr>
                            <tr style="border-bottom: 1px solid #222;">
                                <td style="padding: 6px 4px;">L1-L2</td>
                                <td><b>{v[0][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[0][1]}</span></td>
                                <td><b>{a[0][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[0][1]}</span></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #222;">
                                <td style="padding: 6px 4px;">L2-L3</td>
                                <td><b>{v[1][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[1][1]}</span></td>
                                <td><b>{a[1][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[1][1]}</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 4px;">L1-L3</td>
                                <td><b>{v[2][0]:.1f}V</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{v[2][1]}</span></td>
                                <td><b>{a[2][0]:.1f}A</b> <span style="color:#FFFF00; font-size:8px; margin-left:4px;">{a[2][1]}</span></td>
                            </tr>
                        </table>
                        <div style="font-size: 10px; color: #888; margin-bottom: 4px; border-top: 1px solid #222; padding-top: 5px;">HORARIOS</div>
                        <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                            <span>▶️ Arranque: <b>{h_arr_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_arr}</span>
                        </div>
                        <div style="display: flex; align-items: baseline; font-size: 11px;">
                            <span>⏹️ Paro: <b>{h_par_fmt}</b></span>
                            <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_par}</span>
                        </div>
                    </div>
                </div>
                """

            # 1. Dibujar Etiqueta ID
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(
                    icon_size=(150,36),
                    icon_anchor=(-12, 10),
                    html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; white-space: nowrap; text-shadow: 1px 1px #000; pointer-events: none;">{id_p}</div>'
                )
            ).add_to(m)

            # 2. Dibujar Marcador (Punto o Blinker)
            if info.get('blink'):
                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                    popup=folium.Popup(html_popup, max_width=450)
                ).add_to(m)
            else:
                folium.CircleMarker(
                    location=info['coord'],
                    radius=4,
                    color=info['color_final'],
                    fill=True,
                    fill_color=info['color_final'],
                    fill_opacity=1,
                    popup=folium.Popup(html_popup, max_width=450)
                ).add_to(m)

# ------------------------------------------------------------------------------------------------- RENDERIZADO DE TANQUES ---------------------------------------------------------------------------------------
    if ver_tanques:
        for id_tq, info in mapa_tanques_dict.items():
            try:
                val_nivel, fecha_tq = data_scada.get(info['tag_nivel'], (0, "N/A"))
                n_max = info['nivel_max'] if info['nivel_max'] else 1.0
                porcentaje = (val_nivel / n_max) * 100
                
                # --- CAMBIO CLAVE: Pegamos la "llave" de acceso a la URL del gráfico ---
                # Esto permite que al abrir el histórico, la Sección 0 detecte el permiso y no pida login.
                url_grafico = (
                    f"?graficar_tanque={info['tag_nivel']}"
                    f"&nombre={info['nombre'].replace(' ', '%20')}"
                    f"&access=granted"
                    f"&role={st.session_state.get('rol', 'usuario')}"
                )

                html_popup_tq = f"""
                <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 250px; border: 2px solid #00d4ff; font-family: sans-serif;">
                    <b style="color: #00d4ff; font-size: 14px;">TANQUE: {info['nombre']}</b><br>
                    <hr style="border: 0.5px solid #333;">
                    <div style="font-size: 12px; margin-bottom: 10px;">
                        💧 Nivel Actual: <b>{val_nivel:.2f} m</b>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="{url_grafico}" target="_blank" 
                           style="background-color: #00d4ff; color: black; padding: 10px; 
                                  text-decoration: none; border-radius: 5px; font-weight: bold; 
                                  font-size: 11px; display: inline-block; width: 90%; border: 1px solid #00d4ff;">
                            📊 VER GRÁFICO HISTÓRICO
                        </a>
                    </div>
                    <div style="margin-top: 10px; font-size: 9px; color: #888; text-align: center;">ID: {id_tq}</div>
                </div>
                """
                
                folium.RegularPolygonMarker(
                    location=info['coord'],
                    number_of_sides=6, radius=5, color="#00d4ff", fill=True, fill_color="#00d4ff",
                    popup=folium.Popup(html_popup_tq, max_width=300),
                    tooltip=f"Tanque: {info['nombre']}"
                ).add_to(m)

                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(
                        icon_anchor=(20, -10),
                        html=f'<div style="font-size: 9px; font-weight: bold; color: #00d4ff; text-shadow: 1px 1px #000;">{id_tq}</div>'
                    )
                ).add_to(m)
            except: continue
            
    # ------------------------------------------------------------------------------- RENDERIZADO DE REBOMBEOS --------------------------------------------------------------------------------------
    if ver_rebombeos:
        for id_rb, info in mapa_rebombeos_dict.items():
            try:
                d = lambda tag: data_scada.get(tag, (0, "N/A"))
                pres, f_p = d(info['presion'])
                ntq, f_t = d(info['nivel_tanque'])
                v_rb = [d(t) for t in info['voltajes_l']]
                a_rb = [d(t) for t in info['amperajes_l']]

                html_popup_rb = f"""
                <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 300px; border: 2px solid {info['color_final']}; font-family: sans-serif;">
                    <div style="display: flex; justify-content: space-between;">
                        <b style="color: {info['color_final']}; font-size: 14px;">REBOMBEO: {id_rb}</b>
                        <span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span>
                    </div>
                    <hr style="border: 0.5px solid #333; margin: 8px 0;">
                    <div style="font-size: 11px; margin-bottom: 5px;">
                        🚀 Presión: <b>{pres:.2f} kg</b> <span style="color:#FFFF00; font-size:8px;">{f_p}</span><br>
                        🔋 Nivel Tanque: <b>{ntq:.2f} m</b> <span style="color:#FFFF00; font-size:8px;">{f_t}</span>
                    </div>
                    <table style="width: 100%; font-size: 9px; border-collapse: collapse; margin-top: 5px;">
                        <tr style="color: #00d4ff; border-bottom: 1px solid #333; text-align: left;">
                            <th>Fase</th><th>Voltaje</th><th>Amp</th>
                        </tr>
                        <tr><td>L1-L2</td><td>{v_rb[0][0]:.0f}V</td><td>{a_rb[0][0]:.1f}A</td></tr>
                        <tr><td>L2-L3</td><td>{v_rb[1][0]:.0f}V</td><td>{a_rb[1][0]:.1f}A</td></tr>
                        <tr><td>L1-L3</td><td>{v_rb[2][0]:.0f}V</td><td>{a_rb[2][0]:.1f}A</td></tr>
                    </table>
                </div>
                """
                if info.get('blink'):
                    folium.Marker(location=info['coord'], icon=folium.DivIcon(html=get_blink_icon(info['color_final'])), popup=folium.Popup(html_popup_rb, max_width=350)).add_to(m)
                else:
                    folium.RegularPolygonMarker(location=info['coord'], number_of_sides=4, radius=6, color=info['color_final'], fill=True, fill_color=info['color_final'], popup=folium.Popup(html_popup_rb, max_width=350)).add_to(m)
                
                folium.Marker(location=info['coord'], icon=folium.DivIcon(icon_anchor=(-15, 15), html=f'<div style="font-size: 10px; font-weight: bold; color: {info["color_final"]}; text-shadow: 1px 1px #000;">{id_rb}</div>')).add_to(m)
            except:
                continue

    # --- RENDERIZADO FINAL DEL MAPA (FUERA DE LOS IF) ---
    folium_static(m, width=None, height=750)
