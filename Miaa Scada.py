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
import time
import urllib.parse
from datetime import datetime, timedelta
import plotly.graph_objects as go
from folium.plugins import MousePosition, LocateControl
from streamlit_folium import st_folium
import locale
from shapely import wkt
import geopandas as gpd
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError
import pytz
from datetime import datetime

st.set_page_config(
    page_title="Sistema Scada", 
    page_icon="https://www.miaa.mx/favicon.ico", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 0. SECCION -------------------------------------------------------------------------------- 0. SISTEMA DE AUTENTICACIÓN HUD DEFINITIVO --------------------------------------------------------------------


@st.cache_resource
def get_postgres_conn():
    try: 
        # Simplemente crea y retorna el objeto de conexión
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        st.error(f"Error de conexión Postgres: {e}")
        return None
# 0.2. FUNCIONES DE BASE DE DATOS (REFORZADAS) 
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        # pool_pre_ping=True es vital para evitar que el mapa se quede en blanco por conexión muerta
        engine = create_engine(
            f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}",
            pool_recycle=3600,
            pool_pre_ping=True
        )
        return engine
    except Exception as e:
        st.error(f"⚠️ ERROR CRÍTICO DE CONEXIÓN: {e}")
        return None

    with col_log:
        st.markdown('<div style="height: 20vh;"></div>', unsafe_allow_html=True)
        
        if not st.session_state.fase_carga:
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            st.markdown('<h2 style="color:#00d4ff; font-size:18px;">// INGRESE SUS CREDENCIALES</h2>', unsafe_allow_html=True)
            
            with st.form("login_form", clear_on_submit=False):
                u = st.text_input("USUARIO", key="u_login")
                p = st.text_input("PASSWORD", type="password", key="p_login")
                
                submit_button = st.form_submit_button("ACCEDER AL SISTEMA")
                
                if submit_button:
                    rol = verificar_credenciales(u, p)
                    if rol:
                        st.session_state.temp_rol = rol
                        st.session_state.fase_carga = True
                        st.rerun()
                    else:
                        st.error("❌ ACCESO DENEGADO")
            st.markdown('</div>', unsafe_allow_html=True)
            
        else:
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            st.markdown('<h2 style="color:#00d4ff; font-size:18px;">// CARGANDO SCADA...</h2>', unsafe_allow_html=True)
            prog = st.progress(0)
            status = st.empty()
            
            tareas = [
                ("Conectando DB", "get_mysql_telemetria_engine"),
                ("Sectores", "cargar_sectores_poligonos"),
                ("Pozos", "cargar_mapa_pozos_desde_db"),
                ("Tanques", "cargar_tanques_desde_db"),
                ("Rebombeos", "cargar_rebombeos_desde_db")
            ]
            
            for i, (nombre, func) in enumerate(tareas):
                status.write(f"Cargando {nombre}...")
                if func in globals():
                    try:
                        globals()[func]()
                    except Exception as e:
                        st.warning(f"Error en {nombre}: {e}")
                prog.progress((i + 1) / len(tareas))
                time.sleep(0.4)

            st.cache_data.clear()
            st.cache_resource.clear()
            st.session_state.autenticado = True
            st.session_state.rol = st.session_state.temp_rol
            st.session_state.fase_carga = False
            st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
    st.stop()

# 1.  SECCION---------------------------------------------------------------------------1. CONFIGURACIÓN DE PÁGINA ----------------------------------------------------------------------------------------------------------
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

# 2.  SECCION------------------------------------------------------------------------------2. FUNCIONES DE CONEXIÓN ------------------------------------------------------------------------------------------------------

from sqlalchemy import create_engine, event # Asegúrate de importar 'event' aquí

# 2.1. Secretos de la base de datos de SCADA
@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        
        # --- AÑADIR ESTE BLOQUE AQUÍ ---
        @event.listens_for(engine, "connect")
        def set_big_selects(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET SESSION SQL_BIG_SELECTS=1;")
            cursor.close()
        # -------------------------------
        
        with engine.connect() as conn: pass 
        return engine
    except Exception as e:
        st.error(f"Error al conectar a la BD: {e}")
        return None

# 2.2. Secretos de la base de datos de Telemetria 2
@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        with engine.connect() as conn: pass 
        return engine
    except: return None

# 2.3. Secretos de la base de datos de POSTGRES
@st.cache_resource
def get_postgres_conn():
    try: 
        # Simplemente crea y retorna el objeto de conexión
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        st.error(f"Error de conexión Postgres: {e}")
        return None
        
 # 2.4. Funcion para cargar el ultimo dato de SCADA
def cargar_datos_scada(lista_tags):
    engine = get_mysql_scada_engine()
    if not engine or not lista_tags: return {}
    try:
      
        tags_str = "', '".join(lista_tags)
        query = f"""
            SELECT r.NAME, h.VALUE, h.FECHA 
            FROM VfiTagNumHistory_Ultimo h 
            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
            WHERE r.NAME IN ('{tags_str}') 
            AND h.FECHA = (SELECT MAX(FECHA) FROM VfiTagNumHistory_Ultimo WHERE GATEID = h.GATEID)
        """
        df = pd.read_sql(query, engine)
        
        return {row['NAME']: (row['VALUE'], row['FECHA'].strftime('%d/%m %H:%M') if row['FECHA'] else "N/A") for _, row in df.iterrows()}
    except Exception as e:
        return {}

# 2.5. Funcion para optener los ultimos 7 dias de valores de SCADA
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
        df['FECHA'] = pd.to_datetime(df['FECHA']) 
        return df
    except:
        return pd.DataFrame()
        
# 2.6. Funcion para optener los poligonos de los sectores y sus demas campos
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
    # Obtenemos una conexión fresca
    conn = psycopg2.connect(**st.secrets["postgres"])
    if not conn: return []
    try:
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
        # Leemos los datos
        df = pd.read_sql(query, conn)
        return df.to_dict('records')
    except Exception as e:
        st.error(f"Error al cargar sectores: {e}")
        return []
    finally:
        # El bloque finally asegura que la conexión se cierre SIEMPRE
        # al terminar la función, exitosa o fallida.
        if conn:
            conn.close()

# Función corregida para leer el campo 'geom' directamente
@st.cache_data(ttl=3600)
def get_todas_las_colonias():
    query = """
        SELECT ST_AsText(geom) as geom_wkt, Pozos, Col_atl, Sector, Distrito, Supervisor,
               Pozo_1, Afectacion_1, Pozo_2, Afectacion_2, 
               Pozo_3, Afectacion_3, Pozo_4, Afectacion_4, 
               Pozo_5, Afectacion_5, Pozo_6, Afectacion_6, 
               Pozo_7, Afectacion_7, Pozo_8, Afectacion_8, 
               Pozo_9, Afectacion_9, Pozo_10, Afectacion_10 
        FROM Diccionario_colonias
    """
    try:
        df = pd.read_sql(query, get_mysql_telemetria_engine())
        if not df.empty and df['geom_wkt'].iloc[0] is not None:
            df['geometry'] = df['geom_wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs(epsg=32613, inplace=True)
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        st.error(f"Error cargando polígonos: {e}")
    return None

@st.cache_data(ttl=60)
def obtener_pozos_con_incidencias_hoy():
    engine = get_mysql_scada_engine()
    if engine is None:
        return {}
    try:
        query = """
            SELECT NUM_POZO, DIAGNOSTICO_FALLA, ESTATUS 
            FROM vw_incidencias_en_pozos 
            WHERE ESTATUS != 'CERRADA'
        """
        df_inc = pd.read_sql(query, engine)
        dic_incidencias = {}
        for _, row in df_inc.iterrows():
            val = row['NUM_POZO']
            if pd.notna(val):
                # CORRECCIÓN: Conservamos letras, números y guiones medios (ej. P-087A, R-087)
                id_limpio = str(val).strip().upper()
                if id_limpio:
                    diagnostico = row['DIAGNOSTICO_FALLA'] or 'Sin diagnóstico'
                    dic_incidencias[id_limpio] = diagnostico
        return dic_incidencias
    except Exception as e:
        return {}

def calcular_color_colonia(props, pozos_con_incidencia):
    suma_afectacion = 0.0
    tiene_incidencia_activa = False
    
    for i in range(1, 11):
        pozo_col = props.get(f'Pozo_{i}')
        afectacion_col = props.get(f'Afectacion_{i}')
        
        if pozo_col is not None:
            # Normalización robusta con y sin guion (ej. P087A / P-087A)
            id_p_limpio = str(pozo_col).strip().upper()
            id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
            id_p_sin_guion = id_p_limpio.replace('-', '')
            
            if (id_p_limpio in pozos_con_incidencia or 
                id_p_con_guion in pozos_con_incidencia or 
                id_p_sin_guion in pozos_con_incidencia):
                
                tiene_incidencia_activa = True
                if pd.notna(afectacion_col):
                    try:
                        val_str = str(afectacion_col).replace('%', '').strip()
                        val_afect = float(val_str)
                        # ⚠️ CAMBIO CLAVE: Sumar los porcentajes en lugar de buscar el máximo
                        suma_afectacion += val_afect
                    except:
                        pass

    if not tiene_incidencia_activa:
        return '#3498DB', 0  # Azul para colonias sin afectación activa

    if tiene_incidencia_activa and suma_afectacion == 0:
        return '#FFA500', 1  

    # Rangos de color según la afectación acumulada total
    if 76 <= suma_afectacion <= 100:
        return '#FF0000', suma_afectacion  # Rojo
    elif 51 <= suma_afectacion <= 75:
        return '#FFFF00', suma_afectacion  # Amarillo
    elif 31 <= suma_afectacion <= 50:
        return '#FFA500', suma_afectacion  # Naranja
    elif 1 <= suma_afectacion <= 30:
        return '#69ADDD', suma_afectacion  # Naranja bajito
    else:
        return '#FF0000', suma_afectacion  # Por si supera el 100%

# 2.7. Funcion para cambiar el formato de horas
def formato_hora(decimal):
    try:
        if decimal == "N/A" or decimal is None: return "00:00"
        horas = int(float(decimal))
        minutos = int((float(decimal) - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except:
        return "00:00"

# 2.8. Funcion para el color de los sectores
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

# 3. SECCION -------------------------------------------------------------------------------- 3. CARGA DE DATOS DE DICCIONARIOS -------------------------------------------------------------------------------------------

# 3.1 Funcion para optener la base de datos Diccionario_de_pozos  
@st.cache_data(ttl=3600) 
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
                "amperajes_l": [row['amperaje_L1'], row['amperaje_L2'], row['amperaje_L3']],
                "totalizado": row['totalizado']
            }
        return nuevo_mapa
    except:
        return {}

# 3.2. Funcion para optener la base de datos Diccionario_de_tanques
@st.cache_data(ttl=3600)
def cargar_tanques_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        query = "SELECT * FROM Diccionario_de_tanques"
        df_tq = pd.read_sql(query, engine)
        
        nuevo_mapa_tq = {}
        for _, row in df_tq.iterrows():
            try:

                coords_str = str(row['coord']).strip().replace('(', '').replace(')', '')
                lat, lon = map(float, coords_str.split(','))
                
                n_max = float(row['Nivel_max']) if row.get('Nivel_max') is not None else 1.0
                if n_max <= 0: n_max = 1.0

                nuevo_mapa_tq[row['TQ']] = {
                    "nombre": row['Nombre_tq'],
                    "coord": (lat, lon),
                    "tag_nivel": row['nivel_tanque'],
                    "nivel_max": n_max,
                    "sitios": row['Sitios']
                }
            except: continue
        return nuevo_mapa_tq
    except: return {}
        
# 3.3. Funcion para optener la base de datos Diccionario_de_rebombeos
@st.cache_data(ttl=3600)
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

# 3.4. Funcion para optener los puntos de control de la base de datos Diccionario_puntos_de_control
@st.cache_data(ttl=5)
def cargar_puntos_de_control_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_puntos_de_control", engine)
        d_res = {}
        for _, r in df.iterrows():
            try:
                raw_c = str(r['coord']).replace('(', '').replace(')', '').replace(' ', '').strip()
                lat_s, lon_s = raw_c.split(',')
                
                # Obtenemos la serie
                id_reg_val = r.get('Serie', r.get('Registrador', 'ID'))
                
                d_res[str(id_reg_val)] = {
                    "nombre": str(r.get('Domicilio', r.get('Nombre_registrador', 'S/N'))),
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'), 
                    "tag_p2": r.get('Presion_2'), 
                    "tag_q": r.get('Caudal'),     
                    "tag_vbat": r.get('bateria'), 
                    "tag_idx": r.get('indice'),
                    # --- CRUCIAL: Agregamos la Serie aquí para que el marcador la vea ---
                    "Serie": str(id_reg_val) 
                }
            except Exception as e:
                continue
        return d_res
    except Exception as e:
        return {}

# 3.5. Funcion para optener los puntos de criticos de la base de datos Diccionario_puntos_criticos
@st.cache_data(ttl=5)
def cargar_puntos_criticos_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_puntos_criticos", engine)
        d_res = {}
        for _, r in df.iterrows():
            try:
                raw_c = str(r['coord']).replace('(', '').replace(')', '').replace(' ', '').strip()
                lat_s, lon_s = raw_c.split(',')
                id_reg = r.get('Serie', r.get('Registrador', 'ID'))
                
                # CORRECCIÓN AQUÍ: Guardar explícitamente 'Domicilio'
                d_res[str(id_reg)] = {
                    "nombre": str(r.get('Colonia', 'S/C')), # Usamos Colonia para el nombre interno
                    "Domicilio": str(r.get('Domicilio', 'Sin Domicilio')), # <--- CLAVE NUEVA
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'),
                    "tag_q": r.get('Caudal'),        
                }
            except Exception as e:
                continue
        return d_res
    except Exception as e:
        return {}
        
# 3.4. Funcion para optener las valvulas reductoras de presion de la base de datos Diccionario_vrp
@st.cache_data(ttl=5)
def cargar_vrp_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        df = pd.read_sql("SELECT * FROM Diccionario_vrp", engine)
        d_res = {}
        for _, r in df.iterrows():
            try:
                raw_c = str(r['coord']).replace('(', '').replace(')', '').replace(' ', '').strip()
                lat_s, lon_s = raw_c.split(',')
                
                # Obtenemos el valor de la serie
                id_val = r.get('Serie', 'ID_VRP')
                
                d_res[str(id_val)] = {
                    "nombre": str(r.get('Domicilio', 'S/N')),
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'),
                    "tag_p2": r.get('Presion_2'),
                    "tag_q": r.get('Caudal'),
                    # --- AGREGAMOS ESTA LÍNEA ---
                    "Serie": str(id_val)
                }
            except: continue
        return d_res
    except: return {}

# 3.5. Funcion para optener los macromedidores desde la base de datos

@st.cache_data(ttl=3600)
def cargar_medidores_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
        # Consulta modificada para obtener la fecha más reciente por medidor
        # Agrupamos por Medidor para obtener el último registro de cada uno
        query = """
            SELECT Medidor, Nombre, Lat, Lon, Flujo, Presion, Consumo, MAX(FECHA) as UltimaFecha 
            FROM MACROMEDIDORES 
            GROUP BY Medidor
        """
        df = pd.read_sql(query, engine)
        
        datos_medidores = {}
        for _, row in df.iterrows():
            datos_medidores[row['Medidor']] = {
                "nombre": row['Nombre'],
                "coord": (float(row['Lat']), float(row['Lon'])),
                "flujo": row['Flujo'],
                "presion": row['Presion'],
                "consumo": row['Consumo'],
                "ultima_fecha": pd.to_datetime(row['UltimaFecha']) # Convertimos a formato fecha
            }
        return datos_medidores
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return {}
        
# 3.6. Funcion para optener las incidencias
@st.cache_data(ttl=60)
def get_data():
    engine = get_mysql_scada_engine()
    
    if engine is None:
        st.error("No se pudo establecer conexión.")
        return pd.DataFrame()
        
    try:
        # AQUÍ ES DONDE AGREGAS TODOS LOS CAMPOS QUE QUIERAS TRAER
        query = """
            SELECT NUM_POZO, COLONIA, FECHA_HORA_INICIO, FECHA_HORA_FIN, 
                   DIAGNOSTICO_FALLA, TIEMPO_ESTIMADO_ATENCION, RESPONSABLE, ESTATUS 
            FROM vw_incidencias_en_pozos 
            ORDER BY FECHA_HORA_INICIO DESC
        """
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        st.error(f"Error: {e}")
        return pd.DataFrame()
        
# 3.7. Funcion para optener las colonias del diccionario de colonias        
@st.cache_data(ttl=60)
def get_diccionario_completo():
    try:
        # Asegúrate de que get_engine_telemetria() esté disponible en tu archivo
        query = "SELECT Pozos, Col_atl, Sector, Distrito, Supervisor, ST_AsText(geom) as geom_wkt FROM Diccionario_colonias"
        return pd.read_sql(query, get_mysql_telemetria_engine())
    except Exception as e:
        st.error(f"Error en get_diccionario_colonias: {e}")
        return pd.DataFrame()
        
# 3.8. Funcion para optener las colonias del diccionario de colonias
@st.cache_data(ttl=60)
def get_geometries(num_pozo):
    numero_limpio = re.sub(r'\D', '', str(num_pozo))
    busqueda = numero_limpio if numero_limpio else str(num_pozo)
    
    # La consulta ya trae los campos, vamos a asegurarnos de que no se pierdan
    query = f"""
    SELECT ST_AsText(geom) as geom_wkt, Col_atl, Sector, Distrito, Supervisor 
    FROM Diccionario_colonias 
    WHERE Pozos LIKE '%%{busqueda}%%'
    """
    
    try:
        df = pd.read_sql(query, get_mysql_telemetria_engine())
        if not df.empty and df['geom_wkt'].iloc[0] is not None:
            df['geometry'] = df['geom_wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs(epsg=32613, inplace=True)
            # Retornamos el gdf con las columnas intactas
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        st.error(f"Error en BD: {e}")
    return None

# 4. SECCION -------------------------------------------------------------------------------- 4. GRAFICAR LOS TANQUES EN EL POPUP --------------------------------------------------------------------
params = st.query_params
tag_a_graficar = params.get("graficar_tanque", None)
nombre_tq = params.get("nombre", "Tanque")

if tag_a_graficar:
    import datetime
    import plotly.express as px
    import pandas as pd
    import plotly.graph_objects as go
    
    st.title(f"📊 Análisis de Nivel: {nombre_tq}")
    
    # 4.1. FILTROS DE FECHA ---
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Selecciona un rango:",
            ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"],
            index=3, # <--- CAMBIO: Ahora selecciona 'Últimos 14 días' por defecto
            key="pop_selector_final_v8"
        )

    hoy = datetime.date.today()
    
    # 4.2. Lógica de selección de fechas
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

    # 4.3. CONSULTA A LA BASE DE DATOS
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
            
            # 4.4. CREACIÓN DEL GRÁFICO DE ÁREA DESVANECIDA
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

            # 1. Definimos las fechas de tus líneas y el diccionario de traducción
            dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
            meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                        7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}
            fechas_lineas = pd.date_range(start=fecha_inicio, end=fecha_fin, freq='D')

            # 2. Lógica de filtrado dinámico para evitar amontonamiento
            # Si seleccionas muchos días, mostramos solo una etiqueta cada X días
            num_dias = len(fechas_lineas)
            if num_dias > 15:
                paso = 2 if num_dias <= 30 else 5  # Muestra cada 2 días o cada 5
            else:
                paso = 1
            
            # Aplicamos el filtro al rango
            ticks_filtrados = fechas_lineas[::paso]

            # 3. Construimos etiquetas solo para los ticks filtrados
            etiquetas_filtradas = [
                f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
                for d in ticks_filtrados
            ]

            # 4. CONFIGURACIÓN DEL EJE X
            fig.update_xaxes(
                tickvals=ticks_filtrados,
                ticktext=etiquetas_filtradas,
                tickangle=0,
                automargin=True,
                showspikes=True,
                spikecolor="gray",
                spikethickness=1,
                spikemode="across",
                spikesnap="cursor",
                spikedash="dash",
                showgrid=True,
                gridcolor='#333'
            )

            fig.update_layout(
                template="plotly_dark",
                hovermode="x unified",
                xaxis_title="Fecha y Hora",
                yaxis_title="Nivel (m)",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=600,
                # --- CONFIGURACIÓN DEL EJE X CON RANGE SLIDER ---
                xaxis=dict(
                    rangeslider=dict(
                        visible=True,
                        thickness=0.08
                    ),
                    type="date",
                    showgrid=True,
                    gridcolor='#333'
                ),
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

            dias_intermedios = pd.date_range(start=fecha_inicio, end=fecha_fin, freq='D')
            
            for dia in dias_intermedios:
                es_lunes = dia.weekday() == 0
                
                # 1. El sombreado gris (la "sombra" detrás de la línea)
                # Usamos un ancho fijo (delta) para que sea una franja pequeña
                delta = pd.Timedelta(hours=1) # Ajusta este valor para hacer la sombra más ancha o angosta
                
                fig.add_vrect(
                    x0=dia - delta,
                    x1=dia + delta,
                    fillcolor="gray",
                    opacity=0.2, # Ajusta esta opacidad para que sea más clara o más oscura
                    layer="below",
                    line_width=0
                )
                
                # 2. La línea punteada encima
                fig.add_vline(
                    x=dia, 
                    line_width=1.5,
                    line_dash="dash",
                    line_color="yellow" if es_lunes else "white",
                    opacity=0.5,
                    layer="above"
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

# 4.6. SECCION -------------------------------------------------------------------------------- 5. GRAFICAR LOS POZOS --------------------------------------------------------------------

from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

params = st.query_params

if "graficar_pozo" in params:
    id_pozo_graf = params["graficar_pozo"]
    nombre_pozo = params.get("nombre", id_pozo_graf)
    
    mapa_pozos_dict = cargar_mapa_pozos_desde_db()
    pozo_info = mapa_pozos_dict.get(id_pozo_graf)

    if not pozo_info:
        st.error(f"❌ No se encontró configuración para el pozo: {id_pozo_graf}")
        st.stop()

    cabecera_placeholder = st.empty()
    
    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Rango de tiempo:", 
            ["Hoy", "Ayer", "Últimos 7 días", "Últimos 14 días", "Este Mes", "Último Mes", "Últimos 3 meses", "Últimos 6 meses", "Personalizado"], 
            index=4, 
            key="fecha_pozo_v8"
        )

    hoy_dt = datetime.now()
# Definimos medianoche como base para todas las comparaciones
    medianoche = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    f_fin = hoy_dt # Por defecto hasta el momento actual

    if opcion_fecha == "Hoy":
        f_ini = medianoche
    elif opcion_fecha == "Ayer":
        f_ini = (medianoche - timedelta(days=1))
        f_fin = medianoche - timedelta(seconds=1)
    elif opcion_fecha == "Últimos 7 días":
        f_ini = (medianoche - timedelta(days=7))
    elif opcion_fecha == "Últimos 14 días":
        f_ini = (medianoche - timedelta(days=14))
    elif opcion_fecha == "Este Mes":
        f_ini = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif opcion_fecha == "Último Mes":
        f_ini = (hoy_dt.replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        f_fin = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    elif opcion_fecha == "Últimos 3 meses":
        f_ini = (medianoche - timedelta(days=90))    
    elif opcion_fecha == "Últimos 6 meses":
        f_ini = (medianoche - timedelta(days=180))
    elif opcion_fecha == "Personalizado":
        with col_f2:
            rango = st.date_input("Selecciona el periodo:", value=(hoy_dt.date() - timedelta(days=7), hoy_dt.date()), max_value=hoy_dt.date())
        if isinstance(rango, (list, tuple)) and len(rango) == 2:
            f_ini = datetime.combine(rango[0], datetime.min.time())
            f_fin = datetime.combine(rango[1], datetime.max.time())
        else:
            st.info("Selecciona el rango.")
            st.stop()

    tag_totalizado = str(pozo_info.get('totalizado', '')).strip()
    tag_caudal_real = pozo_info.get('caudal', '')
    tag_nivel_tanque = pozo_info.get('nivel_tanque', '')
    tag_presion_real = pozo_info.get('presion', '')
    tag_nivel_dinamico = pozo_info.get('nivel_dinamico', '')
    tag_sumergencia = pozo_info.get('sumergencia', '')
    tags_voltaje = [t for t in pozo_info.get('voltajes_l', []) if t and t != 'N/A']
    tags_amperaje = [t for t in pozo_info.get('amperajes_l', []) if t and t != 'N/A']
    
    config_visual = [
        ('caudal', "Caudal (Lps)", 'y', '#00d4ff'), 
        ('nivel_tanque', "Nivel Tanque (m)", 'y5', '#00ffcc'),
        ('presion', "Presión (Kg/cm²)", 'y2', '#00ff00'),
        ('nivel_dinamico', "Nivel Dinámico (m)", 'y3', '#ff00b4'),
        ('sumergencia', "Sumergencia (m)", 'y3', '#a800ff')
    ]
    
    for i, t in enumerate(pozo_info.get('voltajes_l', [])):
        if t and t != 'N/A': config_visual.append((t, f"V L{i+1}", 'y4', '#fffb00'))
    for i, t in enumerate(pozo_info.get('amperajes_l', [])):
        if t and t != 'N/A': config_visual.append((t, f"Amp L{i+1}", 'y4', '#ff8000'))

    tags_grafico = []
    for item in config_visual:
        real_t = pozo_info.get(item[0], item[0])
        if real_t and real_t != 'N/A': tags_grafico.append({'tag': real_t, 'label': item[1], 'axis': item[2], 'color': item[3]})
    
    tags_query = [t['tag'] for t in tags_grafico]
    if tag_totalizado and tag_totalizado != 'N/A': tags_query.append(tag_totalizado)

    if tags_query:
        try:
            engine = get_mysql_scada_engine()
            lista_tags_str = f"','".join(list(set(tags_query)))
            
            q = f"""
                SELECT r.NAME as TagName, h.VALUE, h.FECHA 
                FROM vfitagnumhistory h 
                JOIN VfiTagRef r ON h.GATEID = r.GATEID 
                WHERE r.NAME IN ('{lista_tags_str}') 
                AND h.FECHA BETWEEN '{f_ini}' AND '{f_fin}'
            """
            df = pd.read_sql(q, engine)
            df['FECHA'] = pd.to_datetime(df['FECHA'])
            df = df.sort_values('FECHA', ascending=True)

            # --- CORRECCIÓN LÓGICA AQUÍ ---
            if df.empty:
                # Si está vacío, mostramos el aviso y salimos de esta parte
                st.warning(f"⚠️ No hay registros disponibles para el rango seleccionado.")
                
            else:
                # --- LÓGICA DE INDICADORES (Solo se ejecuta si hay datos) ---
                val_vol, val_cau_prom, val_pre_prom = "0.00", "0.00", "0.00"
                val_v_prom, val_a_prom = "0.00", "0.00"
                val_nd_prom, val_sum_prom, val_nt_prom = "0.00", "0.00", "0.00"
                val_nt_ultimo = "0.00"

                if tag_totalizado in df['TagName'].values:
                    df_tot = df[df['TagName'] == tag_totalizado].sort_values('FECHA')
                    if len(df_tot) >= 2:
                        consumo_neta = float(df_tot['VALUE'].iloc[-1]) - float(df_tot['VALUE'].iloc[0])
                        val_vol = f"{consumo_neta:,.2f}"
                    
                
                if tag_caudal_real in df['TagName'].values:
                    val_cau_prom = f"{df[df['TagName'] == tag_caudal_real]['VALUE'].mean():,.2f}"
                if tag_nivel_tanque in df['TagName'].values:
                    df_nt = df[df['TagName'] == tag_nivel_tanque].sort_values('FECHA')
                    val_nt_ultimo = f"{df_nt['VALUE'].iloc[-1]:,.2f}"
                if tag_presion_real in df['TagName'].values:
                    val_pre_prom = f"{df[df['TagName'] == tag_presion_real]['VALUE'].mean():,.2f}"
                if tag_nivel_dinamico in df['TagName'].values:
                    val_nd_prom = f"{df[df['TagName'] == tag_nivel_dinamico]['VALUE'].mean():,.2f}"
                if tag_sumergencia in df['TagName'].values:
                    val_sum_prom = f"{df[df['TagName'] == tag_sumergencia]['VALUE'].mean():,.2f}"
                if tags_voltaje:
                    val_v_prom = f"{df[df['TagName'].isin(tags_voltaje)]['VALUE'].mean():,.1f}"
                if tags_amperaje:
                    val_a_prom = f"{df[df['TagName'].isin(tags_amperaje)]['VALUE'].mean():,.1f}"

# ----------------------- RENDER CABECERA INDICADORES EN TARGETAS DEL POZO ---------------------------------------------------------------------------------------------
            cabecera_placeholder.markdown(f"""
<div style="display: flex; align-items: center; gap: 20px; margin-bottom: 25px; border-bottom: 1px solid #333; padding-bottom: 15px;">
    <h1 style="margin: 0; font-size: 32px; color: white; white-space: nowrap;">Sitio: <span style="color:#00d4ff;">{nombre_pozo}</span></h1>
    <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <div style="padding: 12px 18px; background: rgba(0, 212, 255, 0.05); border: 2px solid #00d4ff; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Caudal Promedio</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_cau_prom} <small style="font-size: 12px; color: #00d4ff;">Lps</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(0, 212, 255, 0.05); border: 2px solid #00d4ff; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Volumen</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_vol} <small style="font-size: 12px; color: #00d4ff;">m³</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(0, 255, 0, 0.05); border: 2px solid #00ff00; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Presión Promedio</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_pre_prom} <small style="font-size: 12px; color: #00ff00;">Kg/cm²</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(0, 255, 204, 0.05); border: 2px solid #00ffcc; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Nivel Tanque</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_nt_ultimo} <small style="font-size: 12px; color: #00ffcc;">m</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(255, 0, 180, 0.05); border: 2px solid #ff00b4; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Nivel Dinámico</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_nd_prom} <small style="font-size: 12px; color: #ff00b4;">m</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(168, 0, 255, 0.05); border: 2px solid #a800ff; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Sumergencia</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_sum_prom} <small style="font-size: 12px; color: #a800ff;">m</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(255, 251, 0, 0.05); border: 2px solid #fffb00; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Voltaje Prom</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_v_prom} <small style="font-size: 12px; color: #fffb00;">Volt</small></span>
        </div>
        <div style="padding: 12px 18px; background: rgba(255, 128, 0, 0.05); border: 2px solid #ff8000; border-radius: 12px; min-width: 130px; text-align: center;">
            <span style="color: #888; font-size: 13px; font-weight: bold; text-transform: uppercase; display: block; margin-bottom: 6px;">Amperaje Prom</span>
            <span style="color: white; font-size: 24px; font-weight: bold;">{val_a_prom} <small style="font-size: 12px; color: #ff8000;">Amp</small></span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------- PESTAÑA DE VOLÚMENES Y GRAFICO DE BARRAS DE VOLUMEN TOTALIZADO ------------------------------------------------------------------------------
            with st.expander("📅 Análisis de volumen real", expanded=False):
                if tag_totalizado and tag_totalizado != 'N/A':
                    curr_year = datetime.now().year
                    q_hist = f"""
                        SELECT YEAR(h.FECHA) as anio, MONTH(h.FECHA) as mes, h.VALUE, h.FECHA 
                        FROM vfitagnumhistory h 
                        JOIN VfiTagRef r ON h.GATEID = r.GATEID 
                        WHERE r.NAME = '{tag_totalizado}' 
                        AND h.FECHA >= DATE_SUB(NOW(), INTERVAL 24 MONTH)
                        ORDER BY h.FECHA ASC
                    """
                    df_h = pd.read_sql(q_hist, engine)

                    if not df_h.empty:
                        res_meses = df_h.groupby(['anio', 'mes'])['VALUE'].first().reset_index()
                        res_meses = res_meses.sort_values(['anio', 'mes'])
                        
                        # Calculamos la diferencia entre el valor del mes actual y el mes siguiente
                        res_meses['produccion_neta'] = res_meses['VALUE'].shift(-1) - res_meses['VALUE']
                        
                        nombres_meses = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
                        res_meses['Mes_Txt'] = res_meses['mes'].map(nombres_meses)

                        curr_year = datetime.now().year
                        res_meses = res_meses[res_meses['anio'].isin([curr_year, curr_year - 1])]
                        
                        # Eliminamos el último registro (el mes actual) que no tiene producción cerrada
                        res_meses = res_meses.dropna(subset=['produccion_neta'])

                        col_g, col_t = st.columns([2, 1])
                        with col_g:
                            fig_hist = go.Figure()
                            for an in sorted(res_meses['anio'].unique()):
                                df_a = res_meses[res_meses['anio'] == an].sort_values('mes')
                                fig_hist.add_trace(go.Bar(
                                    x=df_a['Mes_Txt'], 
                                    y=df_a['produccion_neta'], 
                                    name=f'Año {an}', 
                                    marker_color='#00d4ff' if an == curr_year else 'rgba(150,150,150,0.4)',
                                    hovertemplate='%{x}<br>Volumen: %{y:,.2f}<extra></extra>'
                                ))
                            fig_hist.update_layout(
                                template="plotly_dark",
                                barmode='group',
                                height=350,
                                paper_bgcolor='rgba(0,0,0,0)',
                                plot_bgcolor='rgba(0,0,0,0)',
                                yaxis=dict(tickformat=',.0f')
                            )
                            st.plotly_chart(fig_hist, use_container_width=True)

                        with col_t:
                            pivot = res_meses.pivot(index='mes', columns='anio', values='produccion_neta').sort_index(ascending=True)
                            pivot.index = [nombres_meses[m] for m in pivot.index]
                            st.dataframe(pivot.style.format("{:,.0f}"), use_container_width=True)
                    else: st.info("Sin datos.")

            # ------------------------ PROCESAMIENTO GRAFICO DE VARIABLES DEL POZO -------------------------------------------------------------------------------------------------------------------
            if not df.empty:
                df['FECHA'] = pd.to_datetime(df['FECHA'])
                
                eje_tiempo_global = sorted(df['FECHA'].unique())
                df_interactivo = pd.DataFrame({'FECHA_INDEX': eje_tiempo_global})
                
                fig_line = go.Figure()
                
                for t in tags_grafico:
                    dft_l = df[df['TagName'] == t['tag']].sort_values('FECHA').copy()

                    if len(dft_l) <= 3:
                        continue
                    
                    if dft_l.empty:
                        fecha_limite = f_ini - timedelta(days=30)
                        q_ultimo = f"""
                            SELECT r.NAME as TagName, h.VALUE, h.FECHA 
                            FROM vfitagnumhistory h 
                            JOIN VfiTagRef r ON h.GATEID = r.GATEID 
                            WHERE r.NAME = '{t['tag']}' 
                            AND h.FECHA BETWEEN '{fecha_limite}' AND '{f_ini}'
                            ORDER BY h.FECHA DESC 
                            LIMIT 1
                        """
                        df_ultimo_reg = pd.read_sql(q_ultimo, engine)
                        
                        if not df_ultimo_reg.empty:
                            df_ultimo_reg['FECHA'] = pd.to_datetime(df_ultimo_reg['FECHA'])
                            dft_l = df_ultimo_reg
                        else:
                            dft_l = pd.DataFrame([{
                                'TagName': t['tag'],
                                'VALUE': 0.0,
                                'FECHA': pd.to_datetime(f_ini)
                            }])

                    # 1. GEOMETRÍA VISUAL REAL
                    fig_line.add_trace(
                        go.Scatter(
                            x=dft_l['FECHA'], 
                            y=dft_l['VALUE'], 
                            name=t['label'], 
                            mode='lines+markers',
                            line=dict(color=t['color'], width=2.2),
                            marker=dict(size=4, symbol='circle'),
                            yaxis=t['axis'],
                            showlegend=True,
                            hoverinfo="skip"
                        )
                    )
                    
                    dias_es = {'Mon': 'Lun', 'Tue': 'Mar', 'Wed': 'Mié', 'Thu': 'Jue', 'Fri': 'Vie', 'Sat': 'Sáb', 'Sun': 'Dom'}
                    meses_es = {'Jan': 'Ene', 'Feb': 'Feb', 'Mar': 'Mar', 'Apr': 'Abr', 'May': 'May', 'Jun': 'Jun', 
                                'Jul': 'Jul', 'Aug': 'Ago', 'Sep': 'Sep', 'Oct': 'Oct', 'Nov': 'Nov', 'Dec': 'Dic'}

                    # 2. PROCESAMIENTO DE FECHA TRADUCIDA
                    # En lugar de solo strftime, transformamos el formato al vuelo
                    def traducir_fecha(d):
                        dia_nom = dias_es.get(d.strftime('%a'), d.strftime('%a'))
                        mes_nom = meses_es.get(d.strftime('%b'), d.strftime('%b'))
                        return f"{dia_nom} {d.day}-{mes_nom} {d.strftime('%H:%M:%S')}"

                    # Aplicamos la traducción a la columna antes del merge
                    dft_l['HORA_TRADUCIDA'] = dft_l['FECHA'].apply(traducir_fecha)
                    
                    df_tag_maestro = pd.merge_asof(
                        df_interactivo, 
                        dft_l, 
                        left_on='FECHA_INDEX', 
                        right_on='FECHA', 
                        direction='backward'
                    )
                    df_tag_maestro['VALUE'] = df_tag_maestro['VALUE'].bfill()
                    # Usamos la columna traducida
                    df_tag_maestro['HORA_TRADUCIDA'] = df_tag_maestro['HORA_TRADUCIDA'].bfill()
                    
                    # 3. TRAZA DE HOVER (Aquí no cambias nada más, el customdata ya lleva el texto en español)
                    fig_line.add_trace(
                        go.Scatter(
                            x=df_interactivo['FECHA_INDEX'],
                            y=df_tag_maestro['VALUE'],
                            name=t['label'],
                            mode='lines',
                            line=dict(color=t['color'], width=0.01), 
                            yaxis=t['axis'],
                            showlegend=False,
                            customdata=df_tag_maestro['HORA_TRADUCIDA'].tolist(), # <--- YA VA TRADUCIDO
                            hovertext=df_tag_maestro['VALUE'].tolist(),
                            hovertemplate=f"<span style='color:{t['color']};'>■</span> <b>{t['label']}</b>: %{{hovertext:,.2f}} <span style='color:#888; font-size:11px;'>(%{{customdata}})</span><extra></extra>",
                            hoverlabel=dict(
                                bordercolor=t['color']
                            )
                        )
                    )

                # 1. GENERACIÓN DE ETIQUETAS Y FECHAS (BLOQUE DE APOYO)
                dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
                meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                            7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}

                fechas_lineas = pd.date_range(start=f_ini, end=f_fin, freq='D')
                num_dias = len(fechas_lineas)
                paso = 1 if num_dias <= 15 else (2 if num_dias <= 30 else 5)
                ticks_filtrados = fechas_lineas[::paso]

                etiquetas_filtradas = [
                    f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
                    for d in ticks_filtrados
                ]

                # 2. DIBUJO DE LÍNEAS CON SOMBRA (VRECT + VLINE)
                delta = pd.Timedelta(hours=0.15) # Ancho del halo detrás de la línea
                for d in fechas_lineas:
                    es_lunes = (d.dayofweek == 0)
                    
                    # Sombra (vrect)
                    fig_line.add_vrect(
                        x0=d - delta,
                        x1=d + delta,
                        fillcolor="gray",
                        opacity=0.2,
                        layer="below",
                        line_width=0
                    )
                    
                    # Línea punteada principal (vline)
                    fig_line.add_vline(
                        x=d, 
                        line_width=1.5, 
                        line_dash="dash", 
                        line_color="#fffb00" if es_lunes else "white",
                        opacity=0.5,
                        layer="above"
                    )

                # 3. CONFIGURACIÓN DEL EJE X
                fig_line.update_layout(
                    template="plotly_dark", 
                    height=580, 
                    paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(0,0,0,0)', 
                    
                    # Mantiene el estado del gráfico al interactuar
                    uirevision='constant', 
                    hovermode="x unified", 
                    legend=dict(orientation="h", y=1.08),
                    
                    xaxis=dict(
                    title=dict(text="<b>Tiempo</b>"),
                    domain=[0.07, 0.91],
                    tickangle=0,
                    showline=False,
                    autorange=True,
                    showspikes=True,
                    spikethickness=1,
                    spikedash="dash",
                    spikemode="across",
                    spikecolor="rgba(255, 255, 255, 0.6)",
                    # Configuración para mostrar día y hora automáticamente
                    tickformatstops=[
                    dict(dtickrange=[None, 86400000], value="%H:%M <br>%A %d-%b-%Y"),
                    dict(dtickrange=[86400000, 604800000], value="%H:%M <br>%A %d-%b-%Y"),
                    dict(dtickrange=[604800000, None], value="%H:%M <br>%d-%b-%Y")
                ]
                ),
                
                    
                    # --- CONFIGURACIÓN DE EJES Y (LÍNEAS DIVISORIAS INTERNAS COMPLETAS) ---
                    yaxis5=dict(
                        title=dict(text="<b>Nivel Tanque (m)</b>", font=dict(color="#00ffcc")), 
                        tickfont=dict(color="#00ffcc"), 
                        side="left",
                        overlaying="y",
                        anchor="free",
                        position=0.00,
                        showline=True,        # Línea activa: Divide Nivel Tanque de Caudal
                        linecolor='white',
                        linewidth=1.5
                    ),
                    yaxis=dict(
                        title=dict(text="<b>Caudal (Lps)</b>", font=dict(color="#00d4ff")), 
                        tickfont=dict(color="#00d4ff"),
                        side="left",
                        anchor="free",
                        position=0.07,
                        showline=True,        # Línea activa: Cierre del área de gráfica izquierda
                        linecolor='white',
                        linewidth=1.5
                    ),
                    yaxis2=dict(
                        title=dict(text="<b>Presión (Kg/cm²)</b>", font=dict(color="#00ff00")), 
                        tickfont=dict(color="#00ff00"), 
                        side="right",
                        overlaying="y",
                        anchor="free",
                        position=0.92,
                        showline=True,        # Línea activa: Cierre del área de gráfica derecha
                        linecolor='white',
                        linewidth=1.5
                    ),
                    yaxis3=dict(
                        title=dict(text="<b>Niveles Pozo (m)</b>", font=dict(color="#ff00b4")), 
                        tickfont=dict(color="#ff00b4"), 
                        side="right",
                        overlaying="y",
                        anchor="free",
                        position=0.955,
                        showline=True,        # Línea activa: Divide Presión de Niveles Pozo
                        linecolor='white',
                        linewidth=1.5
                    ),
                    yaxis4=dict(
                        title=dict(text="<b>Eléctricos (V / A)</b>", font=dict(color="#ff8000")), 
                        tickfont=dict(color="#ff8000"), 
                        side="right",
                        overlaying="y",
                        anchor="free",
                        position=1.00,
                        showline=True,        # Línea activa: Divide Niveles Pozo de Eléctricos
                        linecolor='white',
                        linewidth=1.5,
                        rangemode="tozero"
                    )
                )
                st.plotly_chart(fig_line, use_container_width=True)

                # --- NUEVA SECCIÓN: DESCARGA DE DATOS ---
                # Usamos el dataframe 'df' que ya contiene toda la información de los tags
                if not df.empty:
                    # 1. Identificamos las etiquetas que corresponden a caudal
                    # Buscamos todas las que contengan 'CAU_INS'
                    mask_caudal = df['TagName'].str.contains('CAU_INS', na=False)
                    
                    # 2. Aplicamos filtros SOLO a esas filas
                    # Ponemos en None los valores fuera de rango solo en las filas de caudal
                    df.loc[mask_caudal & (df['VALUE'] < 0), 'VALUE'] = None
                    df.loc[mask_caudal & (df['VALUE'] > 100), 'VALUE'] = None
                    
                    # 3. Pivotamos los datos
                    df_pivot = df.pivot(index='FECHA', columns='TagName', values='VALUE')
                    
                    # 4. Aplicamos el rellenado hacia adelante (ffill) a todo el dataframe
                    # Como ya limpiamos los valores inválidos de caudal, el ffill
                    # tomará el último valor válido para todas las variables.
                    df_pivot = df_pivot.ffill().reset_index()
                    
                    # 5. Convertimos a CSV
                    csv_data = df_pivot.to_csv(index=False).encode('utf-8')
                    
                    st.download_button(
                        label="📥 Descargar datos del grafico",
                        data=csv_data,
                        file_name=f"Datos_{nombre_pozo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        help="Descarga los datos: Caudales (0-100 Lps) y resto de variables sin filtrar"
                    )
                else:
                    st.warning("No hay datos disponibles para procesar.")

        except Exception as e: 
            st.error(f"Error: {e}")
            
    st.stop()

# 4.7. SECCION ---------------------------------------------------------------- 4.7. GRAFICAR LOS MACROMEDIDORES ------------------------------------------------------------------------------------
import streamlit as st
import pandas as pd
import datetime as dt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

# --- Configuración de página ---
if "ver_grafico" in st.query_params:
    st.set_page_config(layout="wide", page_title="Miaa - Macromedidores")
    
    if not st.session_state.get('autenticado'):
        if st.query_params.get("access") == "granted":
            st.session_state.autenticado = True
        else:
            st.stop()

    tag_a_graficar = st.query_params.get("ver_grafico")
    nombre_mm = st.query_params.get("nombre")

    engine = get_mysql_telemetria_engine()
    hoy_dt = dt.datetime.now()
    medianoche = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Consulta con JOIN para traer el Diámetro desde la otra tabla
    query = f"""
        SELECT 
            m.Nombre, 
            m.Domicilio, 
            m.Colonia, 
            b.Diametro 
        FROM MACROMEDIDORES m
        LEFT JOIN Base_macromedidores b ON m.Medidor = b.Medidor
        WHERE m.Medidor = '{tag_a_graficar}' 
        AND m.Medidor != '1000' 
        LIMIT 1
    """
    
    df_info = pd.read_sql(query, engine)
    
    # Asignación segura de variables
    info = df_info.iloc[0] if not df_info.empty else {"Nombre": "N/A", "Domicilio": "N/A", "Colonia": "N/A", "Diametro": "N/A"}

    # --- Cabecera y CSS ---
    st.markdown(f"""
        <style>
            @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
            .spin-icon {{ animation: spin 4s linear infinite; display: inline-block; vertical-align: middle; }}
            .logo-miaa {{ height: 35px; margin-right: 15px; vertical-align: middle; }}
            .cabecera-contenedor {{ display: flex; align-items: center; background-color: #0e1117; padding: 10px 20px; border-radius: 10px; border: 1px solid #30363d; margin-bottom: 10px; flex-wrap: nowrap; }}
            div[data-testid="column"] {{ padding-top: 0px !important; }}
            div[data-testid="stVerticalBlock"] {{ gap: 0px !important; }}
        </style>
        <div class="cabecera-contenedor">
            <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" class="logo-miaa">
            <svg class="spin-icon" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#00FFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 15px;">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path>
            </svg>
            <h3 style="margin: 0; color: #ffffff; margin-right: 20px; font-size: 1.2rem; white-space: nowrap;"> Macro medidor</h3>
            <div style="display: flex; gap: 20px; font-size: 12px; color: #c9d1d9; border-left: 2px solid #00FFFF; padding-left: 15px; align-items: center; text-transform: none !important;">
                <div><b>ID:</b> <span style="color:#ffffff;">{tag_a_graficar}</span></div>
                <div><b>Nombre:</b> <span style="color:#ffffff;">{info['Nombre']}</span></div>
                <div><b>Domicilio:</b> {info['Domicilio']}</div>
                <div><b>Colonia:</b> {info['Colonia']}</div>
                <div style="display: flex; align-items: baseline; gap: 5px;">
                    <b style="color: #c9d1d9;">Diámetro:</b> 
                    <span style="color:#00FFFF; font-size: 16px; font-weight: bold;">{info['Diametro']} Ø</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # --- Selector de fechas ---
    col_sel, col_ind, col_btn = st.columns([2.0, 0.5, 6.0])

    with col_sel:
        st.markdown('<div style="margin-top: 26px;"></div>', unsafe_allow_html=True)
        opcion_fecha = st.selectbox("rango", 
            ["Hoy", "Ayer", "Últimos 7 días", "Últimos 14 días", "Este Mes", "Último Mes", "Últimos 6 meses", "Personalizado"],
            index=4, label_visibility="collapsed", key="selector_fechas_unico")

    # --- Lógica de fechas (DEBE IR ANTES DE LA CONSULTA SQL) ---
    f_fin = hoy_dt
    if opcion_fecha == "Hoy": f_ini = medianoche
    elif opcion_fecha == "Ayer": f_ini, f_fin = medianoche - dt.timedelta(days=1), medianoche - dt.timedelta(seconds=1)
    elif opcion_fecha == "Últimos 7 días": f_ini = medianoche - dt.timedelta(days=7)
    elif opcion_fecha == "Últimos 14 días": f_ini = medianoche - dt.timedelta(days=14)
    elif opcion_fecha == "Este Mes": f_ini = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif opcion_fecha == "Último Mes":
        primer_dia = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        f_fin = primer_dia - dt.timedelta(seconds=1)
        f_ini = (primer_dia.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    elif opcion_fecha == "Últimos 6 meses": f_ini = medianoche - dt.timedelta(days=180)
    else: 
        rango = st.date_input("Periodo:", value=(hoy_dt.date() - dt.timedelta(days=7), hoy_dt.date()))
        f_ini, f_fin = dt.datetime.combine(rango[0], dt.time.min), dt.datetime.combine(rango[1], dt.time.max)

    # --- Consulta de datos ---
    df = pd.read_sql(f"SELECT FECHA, Flujo, Presion, Consumo FROM MACROMEDIDORES WHERE Medidor = '{tag_a_graficar}' AND Medidor != '1000' AND FECHA BETWEEN '{f_ini}' AND '{f_fin}' ORDER BY FECHA ASC", engine)
    df = df.groupby('FECHA').agg({
        'Flujo': 'mean',
        'Presion': 'mean',
        'Consumo': 'sum'
    }).reset_index()
    
    df_diario_exp = pd.DataFrame()
    if not df.empty:
        df_diario_exp = df.copy()
        df_diario_exp['FECHA'] = pd.to_datetime(df_diario_exp['FECHA']).dt.date
        df_diario_exp = df_diario_exp.groupby('FECHA')['Consumo'].sum().reset_index()

    # --- Botones en col_btn ---
    with col_btn:
        st.markdown('<div style="margin-top: 26px;"></div>', unsafe_allow_html=True)
        c_b1, c_b2 = st.columns(2)
        if not df.empty:
            with c_b1:
                st.download_button("📥 Exportar datos de caudal (lps) y presión (kg7cm2)", df.to_csv(index=False).encode('utf-8'), "datos.csv", "text/csv", use_container_width=True)
            with c_b2:
                st.download_button("📊 Exportar datos de consumo (m3)", df_diario_exp.to_csv(index=False).encode('utf-8'), "consumo.csv", "text/csv", use_container_width=True)
        else:
            with c_b1: st.button("📥", disabled=True)
            with c_b2: st.button("📊", disabled=True)

   
    # Creamos el placeholder para indicadores
    placeholder_indicadores = st.empty()

    if not df.empty:
        # 1. Cálculos de indicadores
        avg_caudal = df['Flujo'].mean()
        avg_presion = df['Presion'].mean()
        
        # Cálculo de consumo total para el indicador
        df_diario_calc = df.copy()
        df_diario_calc['FECHA'] = pd.to_datetime(df_diario_calc['FECHA']).dt.date
        total_consumo = df_diario_calc.groupby('FECHA')['Consumo'].sum().sum()
        
        # Formato manual para asegurar punto decimal y coma de miles
        entera = int(total_consumo)
        decimal = int(round((total_consumo - entera) * 100))
        consumo_fmt = f"{entera:,d}.{decimal:02d}".replace(",", "X").replace(".", ",").replace("X", ".")

        # 2. Renderizado de los 3 indicadores JUNTOS
        with placeholder_indicadores.container():
            _, col_m1, col_m2, col_m3, _ = st.columns([1, 2, 2, 2, 1])
            estilo_div = "text-align: center; padding: 5px;"
            estilo_titulo = "font-size: 0.7rem; color: #ffffff; font-weight: bold; margin-bottom: 2px;"
            estilo_valor = "font-size: 1.2rem; font-weight: bold; color: #ffffff;"

            with col_m1:
                st.markdown(f'<div style="{estilo_div}"><div style="{estilo_titulo}">Caudal promedio</div><div style="{estilo_valor}">{avg_caudal:.2f} <span style="font-size: 0.8rem; color: #00FFFF;">Lps</span></div></div>', unsafe_allow_html=True)
            with col_m2:
                st.markdown(f'<div style="{estilo_div}"><div style="{estilo_titulo}">Presión promedio</div><div style="{estilo_valor}">{avg_presion:.2f} <span style="font-size: 0.8rem; color: #00FF00;">kg/cm²</span></div></div>', unsafe_allow_html=True)
            with col_m3:
                st.markdown(f'<div style="{estilo_div}"><div style="{estilo_titulo}">Consumo total</div><div style="{estilo_valor}">{consumo_fmt} <span style="font-size: 0.8rem; color: #00FFFF;">m³</span></div></div>', unsafe_allow_html=True)
                        
        # --- Gráfico de Flujo y Presión ---
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(go.Scatter(
            x=df['FECHA'], y=df['Flujo'],
            name="Caudal (Lps)",
            mode='lines+markers',                # <--- MODO LÍNEAS Y PUNTOS
            marker=dict(size=5),                 # Tamaño de los puntos
            line=dict(color='#00FFFF', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 255, 255, 0.2)',
            hovertemplate="%{y:.2f} Lps<extra></extra>"
        ), secondary_y=False)
        
        # Presión: líneas + puntos
        fig.add_trace(go.Scatter(
            x=df['FECHA'], y=df['Presion'],
            name="Presión (Kg/cm²)",
            mode='lines+markers',                # <--- MODO LÍNEAS Y PUNTOS
            marker=dict(size=5),                 # Tamaño de los puntos
            line=dict(color='#00FF00', width=2),
            hovertemplate="%{y:.2f} Kg/cm²<extra></extra>"
        ), secondary_y=True)

        # 1. GENERACIÓN DE ETIQUETAS Y FECHAS (ESTÁNDAR)
        dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
        meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}

        fechas_lineas = pd.date_range(start=df['FECHA'].min().floor('D'), 
                                      end=df['FECHA'].max().ceil('D'), freq='D')
        
        ticks_filtrados = fechas_lineas
        etiquetas_filtradas = [
            f"00:00<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
            for d in ticks_filtrados
        ]

        # 2. DIBUJO DE LÍNEAS CON SOMBRA
        delta = pd.Timedelta(hours=1)
        for d in fechas_lineas:
            es_lunes = (d.dayofweek == 0)

            # Sombra gris detrás
            fig.add_vrect(
                x0=d - delta,
                x1=d + delta,
                fillcolor="gray",
                opacity=0.2,
                layer="below",
                line_width=0)

            # Línea punteada nítida
            fig.add_vline(
                x=d, line_width=1.5,
                line_dash="dash", 
                line_color="#fffb00" if es_lunes else "white", 
                opacity=0.5, 
                layer="above")

        # 3. CONFIGURACIÓN FINAL
        fig.update_layout(
            height=400, 
            template="plotly_dark",
            hovermode="x unified",
            xaxis=dict(
                rangeslider=dict(visible=True,
                thickness=0.10),
                tickvals=ticks_filtrados,
                ticktext=etiquetas_filtradas,
                tickangle=0, showline=False),
            
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            uirevision='constant'
        )
        
        fig.update_yaxes(title_text="Caudal (Lps)", secondary_y=False)
        fig.update_yaxes(title_text="Presión (Kg/cm²)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)
        
        # 4. Gráfico de Barras (Consumo) --------------------------------------------------------------------------------------------------------------------
        df_diario = df.copy()
        df_diario['FECHA'] = pd.to_datetime(df_diario['FECHA']).dt.date
        df_diario = df_diario.groupby('FECHA')['Consumo'].sum().reset_index()
        rango_completo = pd.date_range(start=df_diario['FECHA'].min(), end=df_diario['FECHA'].max())
        df_diario = df_diario.set_index('FECHA').reindex(rango_completo, fill_value=0).reset_index()
        df_diario.columns = ['FECHA', 'Consumo']
        df_diario['FECHA'] = df_diario['FECHA'].dt.strftime('%d %b %Y')
        
        fig_bar = px.bar(df_diario, x='FECHA', y='Consumo', text='Consumo', color_discrete_sequence=['#00FFFF'])
        fig_bar.update_layout(
            height=300, template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
            xaxis=dict(tickmode='linear', title=None), yaxis=dict(title="Consumo (m3)"),
            margin=dict(t=30, b=20, l=20, r=20), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.1, xanchor="right", x=1)
        )
        fig_bar.update_traces(
            texttemplate='%{text:.1f}',
            textposition='outside',
            name='Consumo (m³)',
            hovertemplate="<b>Día:</b> %{x}<br><b>Consumo:</b> %{y:.2f} m³<extra></extra>"
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    else:
        placeholder_indicadores.empty() # Limpia si no hay datos
        st.warning("No hay datos registrados en este rango.")

        # --- Gráfico de Flujo y Presión ---
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=df['FECHA'], y=df['Flujo'], name="Caudal (Lps)", line=dict(color='#00FFFF', width=2), fill='tozeroy', fillcolor='rgba(0, 255, 255, 0.2)'), secondary_y=False)
        fig.add_trace(go.Scatter(x=df['FECHA'], y=df['Presion'], name="Presión (Kg/cm²)", line=dict(color='#00FF00', width=2)), secondary_y=True)
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=df['FECHA'], y=df['Flujo'], name="Caudal (Lps)", line=dict(color='#00FFFF', width=2), fill='tozeroy', fillcolor='rgba(0, 255, 255, 0.2)'), secondary_y=False)
        fig.add_trace(go.Scatter(x=df['FECHA'], y=df['Presion'], name="Presión (Kg/cm²)", line=dict(color='#00FF00', width=2)), secondary_y=True)
                
        fig.update_yaxes(title_text="Caudal (Lps)", secondary_y=False)
        fig.update_yaxes(title_text="Presión (Kg/cm²)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

        df_diario = df.copy()
        df_diario['FECHA'] = pd.to_datetime(df_diario['FECHA']).dt.date
        df_diario = df_diario.groupby('FECHA')['Consumo'].sum().reset_index()
        
        rango_completo = pd.date_range(start=df_diario['FECHA'].min(), end=df_diario['FECHA'].max())
        df_diario = df_diario.set_index('FECHA').reindex(rango_completo, fill_value=0).reset_index()
        df_diario.columns = ['FECHA', 'Consumo']
        df_diario['FECHA'] = df_diario['FECHA'].dt.strftime('%b %d')

        fig_bar = px.bar(
            df_diario, 
            x='FECHA', 
            y='Consumo', 
            text='Consumo', 
            color_discrete_sequence=['#00FFFF'],
            
        )      
        fig_bar.update_traces(name="Consumo (m³)", showlegend=True)
        fig_bar.update_layout(
            height=300, 
            template="plotly_dark", 
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)', 
            xaxis=dict(tickmode='linear', title=None), # Quitamos título eje X para ahorrar espacio  
            yaxis=dict(title="Consumo (m3)"),
            margin=dict(t=40, b=20, l=20, r=20),
            showlegend=True,                           # Esto activa la leyenda
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.1,                                 # Ajustado para que se vea bien
                xanchor="left",
                x=0
            )
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.stop()
    
# 5. SECCION------------------------------------------------------------------------------5. ESTILO CSS ----------------------------------------------------------------------------------------------------------
st.markdown("""
    <style>
        [data-testid="collapsedControl"], button[kind="headerNoPadding"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0rem !important;
            margin-top: 15px !important; /* Subimos el inicio de la página al máximo */
            max-width: 100% !important;
        }

        .mapa-area iframe { 
            margin-top: 90px !important; /* Ajusta este para subir el mapa al ras */
            border: 1px solid #1f4068 !important;
            height: 85vh !important;
        }

        /* Evitamos que las columnas de sectores se rompan */
            .mapa-area [data-testid="column"] {
            flex: 1 1 0% !important;
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

        /* CONTENEDOR DE INDICADORES (HUD FIJO) */
        .contenedor-indicadores {
           position: fixed;
           top: 65px; 
           left: 320px;
           right: 0;
           display: flex;
           justify-content: center;
           align-items: center;
           gap: 15px; /* <--- Aumenta esto para despegarlos (puedes probar 10px o 15px) */
           z-index: 1001;
           background: transparent; /* Quita el fondo negro del contenedor para que se vea el hueco */
           padding: 0 15px;
         }

        .card-indicador {
           flex: 1;
         /* Cambia el borde a uno más brillante para que se note la separación */
           border: 1px solid #1f4068; 
           background: linear-gradient(180deg, rgba(11, 26, 41, 0.95) 0%, rgba(0, 0, 0, 1) 100%);
           padding: 8px 5px;
           text-align: center;
           border-radius: 10px; /* <--- Añade esto para redondear las esquinas y que no parezca tabla */
           box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.5); /* Sombra para dar volumen */
        }
        .card-indicador:first-child { border-left: 1px solid #1f4068; }

        .card-label { color: #888888; font-size: 0.7rem; font-weight: bold; text-transform: uppercase; margin: 0; }
        .card-value { font-family: 'Courier New', monospace; font-size: 1.5rem; font-weight: bold; margin: 0; }
        
        .val-on { color: #00ff00; text-shadow: 0 0 8px rgba(0, 255, 0, 0.5); }
        .val-off { color: #ff0000; text-shadow: 0 0 8px rgba(255, 0, 0, 0.5); }
        .val-falla { color: #ffaa00; text-shadow: 0 0 8px rgba(255, 170, 0, 0.5); }
        .val-sin { color: #ffffff; }

        /* ESTO SUBE EL MAPA A LA FUERZA */
        .mapa-principal-ajuste {
            margin-top: -200px !important; /* Margen negativo agresivo para eliminar el hueco */
            z-index: 1;
        }
        /* Ajuste específico para el iframe de Folium */
        .mapa-principal-ajuste iframe {
            border: 1px solid #1f4068 !important;
            border-top: none !important;
        }

        /* 6. SIDEBAR - CONTENIDO PEGADO AL LOGO */
        [data-testid="stSidebarContent"] {
            padding-top: 3px !important; 
        }

        [data-testid="stSidebar"] { 
            background-color: #0b1a29 !important; 
            border-right: 2px solid #1f4068; 
        }

        /* Ajuste Sidebar */
       .sidebar-logo { 
           position: fixed; 
           top: 20px; 
           left: 40px; 
           width: 170px;  /* <--- REDUCE ESTE VALOR (ej. 200px) */
           height: 50px;  /* <--- REDUCE ESTE VALOR (ej. 60px) para que sea menos alto */
           z-index: 999999; 
           display: flex; 
           justify-content: center; 
           align-items: center;
           background-color: #0b1a29; 
           border-bottom: 1px solid #1f4068;
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

        .pulsante {
            animation: parpadeo 1.2s infinite;
        }
        @keyframes parpadeo {
            0% { opacity: 1; }
            50% { opacity: 0.1; }
            100% { opacity: 1; }
        }

    </style>
""", unsafe_allow_html=True)
# 6. SECCION----------------------------------------------------------------- 6. PROCESAMIENTO (MODIFICADO) -----------------------------------------------------------------
# 6.1. Carga de datos base
sectores = cargar_sectores_poligonos()
mapa_pozos_dict = cargar_mapa_pozos_desde_db()
mapa_tanques_dict = cargar_tanques_desde_db()
mapa_rebombeos_dict = cargar_rebombeos_desde_db()

# 6.2. Recolección de tags para la consulta masiva
tags_a_consultar = []

for p in mapa_pozos_dict.values():
    # 6.3. Añadimos los campos que te faltaban: nivel_dinamico, sumergencia y columna
    tags_a_consultar.extend([
        p['bomba'], 
        p['caudal'], 
        p['presion'], 
        p['nivel_tanque'],
        p['nivel_dinamico'],
        p['sumergencia'],
        p['columna']
    ])
    # 6.4. Voltajes y amperajes
    tags_a_consultar.extend(p['voltajes_l'] + p['amperajes_l'])

# 6.5. Tags de Tanques
for t in mapa_tanques_dict.values():
    if t['tag_nivel']: tags_a_consultar.append(t['tag_nivel'])

# 6.6. Tags de Rebombeos
for r in mapa_rebombeos_dict.values():
    tags_a_consultar.extend([r['presion'], r['nivel_tanque']])
    tags_a_consultar.extend(r['voltajes_l'] + r['amperajes_l'])

# 6.7. Limpieza de la lista
tags_finales = list(set([str(t).strip() for t in tags_a_consultar if t and str(t) not in ['0', 'Sin telemetria', 'None']]))

# 6.8. Consulta al SCADA pasando la LISTA corregida
data_scada = cargar_datos_scada(tags_finales)

# 6.9. Inicialización de contadores
pozos_on, pozos_off, pozos_sin_telemetria, pozos_falla_com = [], [], [], []
total_q, total_p = 0.0, 0.0

import datetime as dt
ahora = dt.datetime.utcnow() - dt.timedelta(hours=6) 

# 6.10. LÓGICA DE POZOS
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
        if val_bba >= 1:
            info.update({'status_label': 'OPERANDO', 'color_final': '#00FF00', 'blink': False})
            pozos_on.append(id_p)
            total_q += data_scada.get(info['caudal'], (0, ""))[0]
            total_p += data_scada.get(info['presion'], (0, ""))[0]
        else:
            info.update({'status_label': 'APAGADO', 'color_final': '#FF0000', 'blink': True})
            pozos_off.append(id_p)

# 6.11. LÓGICA DE REBOMBEOS (CORREGIDA) 
for id_rb, info in mapa_rebombeos_dict.items():

    telemetria_status = str(info.get('telemetria', '')).strip().lower()
    
    if telemetria_status == "sin telemetria":
        info.update({
            'status_label': 'SIN TELEMETRÍA', 
            'color_final': '#808080',  # Color Gris
            'blink': False
        })
    else:
        # 6.12. Si tiene telemetría, aplicar la lógica de presión actual
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


# 7. SECCION ------------------------------------------------------------------7. DETALLE DE SECTOR -------------------------------------------------------------------------------------------
if sector_seleccionado:
    # 7.1. Estilos CSS: Ajuste agresivo y mejoras para los nuevos gráficos
    st.markdown(
        f"""
        <style>
            [data-testid="column"] {{
            margin-top: -105px !important;
            }}
        
            [data-testid="stSidebar"] {{display: none;}}
            header {{visibility: hidden;}}
            .stAppDeployButton {{display:none;}}
            #MainMenu {{visibility: hidden;}}
            footer {{visibility: hidden;}}
            
            .block-container {{
                padding-top: 0px !important;
                padding-bottom: 0px !important;
                margin-top: -100px !important;
            }}
            
            .contenedor-centrado {{
                text-align: center;
                margin-bottom: 0px;
            }}
            
            .titulo-sector {{
                margin-top: 10px !important;
                font-size: 1.8rem;
                font-weight: 800;
                color: #00d4ff;
                margin: 10px;
                text-transform: uppercase;
            }}

            .col-mapa-offset {{
                margin-top: 0px !important;
            }}

            .stFolium {{
                margin-top: -10px !important;
            }}            

            hr {{
                margin-top: 2px !important;
                margin-bottom: 5px !important;
                border: 0;
                border-top: 1px solid #1f4068;
            }}

            .card-indicador {{
                background: rgba(16, 33, 54, 0.8);
                padding: 10px;
                border-radius: 8px;
                border: 1px solid #1f4068;
                text-align: center;
                margin-bottom: 5px;
            }}

            .label-indicador {{
                color: #ffffff; 
                font-size: 0.8rem; 
                margin: 0;
                text-transform: uppercase;
                letter-spacing: 0.5px;
              }}

             .value-indicador {{
                color: #00ffcc; 
                font-size: 1.1rem; 
                font-weight: bold; 
                margin: 0;
              }}
              
              [data-testid="column"]:nth-child(2) {{
                margin-top: 0px !important;
              }}

            .js-plotly-plot {{
                margin-bottom: 10px !important;
            }}

        </style>
        <div class="contenedor-centrado">
            <h1 class="titulo-sector">ANÁLISIS DE SECTOR: {sector_seleccionado}</h1>
        </div>
        """, unsafe_allow_html=True
    )
    
    sec_id = str(sector_seleccionado).split('.')[0].strip()
    datos_s = next((s for s in sectores if str(s['sector']).strip() == sec_id), None)

    # 7.2. Métricas de cabecera
    if datos_s:
        # --- INICIALIZACIÓN PREVENTIVA DE VARIABLES (EVITA NAMEERROR) ---
        sel_r_id = None
        sel_v_id = None
        f_ini_h = datetime.now().date()
        f_fin_h = datetime.now().date()

        st.markdown('<div class="metrics-row">', unsafe_allow_html=True)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        
        with c1: st.markdown(f'<div class="card-indicador"><p class="label-indicador">Población</p><p class="value-indicador">{datos_s.get("Poblacion", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="card-indicador"><p class="label-indicador">U. Totales</p><p class="value-indicador">{datos_s.get("U_Tot", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="card-indicador"><p class="label-indicador">U. Domésticos</p><p class="value-indicador">{datos_s.get("U_Domesticos", 0):,.0f}</p></div>', unsafe_allow_html=True)
        with c4: st.markdown(f'<div class="card-indicador"><p class="label-indicador">Consumo m³</p><p class="value-indicador">{datos_s.get("Cons_m3", 0):,.1f}</p></div>', unsafe_allow_html=True) 
        with c5: st.markdown(f'<div class="card-indicador"><p class="label-indicador">Dotación</p><p class="value-indicador">{datos_s.get("Dotacion", 0):,.1f}</p></div>', unsafe_allow_html=True)
        with c6: st.markdown(f'<div class="card-indicador"><p class="label-indicador">Balance</p><p class="value-indicador">{datos_s.get("Balance_Estimado", 0):,.1f}%</p></div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.divider()

        # 7.3. Carga de Diccionarios y Selectores
        dict_reg_all = cargar_puntos_de_control_desde_db() 
        dict_reg = {k: v for k, v in dict_reg_all.items() if str(v.get('sector')).strip() == str(sec_id).strip()}
        reg_nombres = {v['nombre']: k for k, v in dict_reg.items()}
        opciones_equipo = list(reg_nombres.keys())
        
        dict_vrp_all = cargar_vrp_desde_db()
        dict_vrp_sec = {k: v for k, v in dict_vrp_all.items() if str(v.get('sector')).strip() == str(sec_id).strip()}
        vrp_nombres = {v['nombre']: k for k, v in dict_vrp_sec.items()}
        opciones_vrp = list(vrp_nombres.keys())

        c_sel_f, c_fecha_ext = st.columns([1, 1])
        with c_sel_f:
            opcion_fecha = st.selectbox(
                "Rango de fechas:",
                ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"],
                index=3,
                key="f_sector_full",
                label_visibility="collapsed" # Colapsamos el label para que queden alineados
        )
        # Inicialización de fechas
        hoy = datetime.now().date()
        f_ini_h, f_fin_h = hoy, hoy

        # Lógica de asignación de periodos
        if opcion_fecha == "Hoy":
            f_ini_h, f_fin_h = hoy, hoy
        elif opcion_fecha == "Esta Semana":
            f_ini_h, f_fin_h = hoy - timedelta(days=hoy.weekday()), hoy
        elif opcion_fecha == "Últimos 14 días":
            f_ini_h, f_fin_h = hoy - timedelta(days=14), hoy
        elif opcion_fecha == "Este Mes":
            f_ini_h, f_fin_h = hoy.replace(day=1), hoy
        elif opcion_fecha == "Personalizado":
            with c_fecha_ext:
                # El calendario aparece a la derecha y nivelado al pixel
                rango_p = st.date_input(
                    "Periodo:",
                    value=(hoy - timedelta(days=7), hoy),
                    max_value=hoy,
                    key="f_sector_custom_global",
                    label_visibility="collapsed"
                )
                if isinstance(rango_p, tuple) and len(rango_p) == 2:
                    f_ini_h, f_fin_h = rango_p
                else:
                    f_ini_h, f_fin_h = hoy, hoy    
        


        # 7.4. Layout Superior: Mapa e Histórico Puntos de Control
        col_izq, col_der = st.columns([1.0, 1.0])
        
        with col_izq:
            st.markdown('<div class="col-mapa-offset">', unsafe_allow_html=True)
            if "ultimo_clic_sv" not in st.session_state:
                st.session_state.ultimo_clic_sv = None
            
            m_sec = folium.Map(location=[21.8820, -102.2800], zoom_start=12, tiles=None, height=350)
            folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Vista Satélite', overlay=False).add_to(m_sec)
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satélite (Esri)', overlay=False).add_to(m_sec)
            folium.TileLayer(tiles="CartoDB dark_matter", name="Vista Nocturna", attr="CartoDB", overlay=False).add_to(m_sec)

            if datos_s and datos_s.get('geo'):
                try:
                    geo_data = json.loads(datos_s['geo'])
                    folium_geo = folium.GeoJson(geo_data, style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 2, 'fillOpacity': 0.15}, name="Límites del Sector").add_to(m_sec)
                    m_sec.fit_bounds(folium_geo.get_bounds())
                except: pass

            # 7.5. RECOLECCIÓN DE TAGS (Incluyendo VRP y PC)
            tags_para_scada = []
            for r in dict_reg.values():
                for k in ['tag_p1', 'tag_p2', 'tag_q', 'tag_vbat']:
                    if r.get(k): tags_para_scada.append(r.get(k))
            
            mapa_pc_all = cargar_puntos_criticos_desde_db()
            dict_pc_sec = {k: v for k, v in mapa_pc_all.items() if str(v.get('sector')).strip() == str(sec_id).strip()}
            for pc in dict_pc_sec.values():
                if pc.get('tag_p1'): tags_para_scada.append(pc.get('tag_p1'))

            for v in dict_vrp_sec.values():
                for k in ['tag_p1', 'tag_p2', 'tag_q']:
                    if v.get(k): tags_para_scada.append(v.get(k))

            scada_res_reg = cargar_datos_scada(list(set(tags_para_scada)))

# 7.6. MARCADORES PUNTOS DE CONTROL
            for r in dict_reg.values():
                def get_rv(tk):
                    v, f = scada_res_reg.get(r.get(tk), (0.0, "N/A"))
                    try: return float(v), f
                    except: return 0.0, f
                
                rp1, fp1 = get_rv('tag_p1'); rcau, fq = get_rv('tag_q'); rbat, fb = get_rv('tag_vbat')
                id_reg = r.get('Serie', 'S/N') 
                html_popup_reg = f"""<div style="background:#000; color:white; padding:12px; border-radius:10px; border:1px solid #00FFFF; width:250px; font-family:sans-serif;"><b style="color:#00FFFF; font-size:14px;">{r['nombre']}</b><hr style="opacity:0.2; margin:8px 0;"><div style="font-size:11px;">💧 Caudal: <b>{rcau:.2f} L/s</b><br><span style="color:#FFFF00;">{fq}</span><br><br>🚀 Presión: <b>{rp1:.2f} kg</b><br><span style="color:#FFFF00;">{fp1}</span><br><br>🔋 Bat: <b>{rbat:.2f} V</b><br><span style="color:#FFFF00;">{fb}</span></div></div>"""



# --- MARCADOR TACHUELA REALISTA AZUL (ESTILO 3D) ---
                from folium.features import DivIcon

                # Ajuste de gradientes para tonos azules tipo SCADA
                icon_html = """
                <div style="position: relative; width: 30px; height: 30px;">
                    <!-- Esfera con volumen azul -->
                    <div style="
                        width: 20px; 
                        height: 20px; 
                        background: radial-gradient(circle at 30% 30%, #66ccff, #007bff, #003366);
                        border-radius: 50%;
                        box-shadow: 2px 4px 6px rgba(0,0,0,0.5);
                        position: absolute;
                        top: 0; left: 5px;
                        z-index: 2;">
                    </div>
                    <!-- Pin metálico -->
                    <div style="
                        width: 2px; 
                        height: 15px; 
                        background: linear-gradient(to right, #e0e0e0, #808080);
                        position: absolute;
                        top: 18px; left: 14px;
                        z-index: 1;">
                    </div>
                </div>
                """

                folium.Marker(
                    location=r['coord'],
                    icon=DivIcon(
                        icon_size=(30, 40),
                        icon_anchor=(15, 33),
                        html=icon_html
                    ),
                    popup=folium.Popup(html_popup_reg, max_width=300)
                ).add_to(m_sec)

                # --- ETIQUETA FLOTANTE (DIVICON) ---
                folium.Marker(
                    location=r['coord'],
                    icon=folium.features.DivIcon(
                        icon_size=(250,36),
                        icon_anchor=(-15, 35), # Desplazado para no tapar la estrella
                        html=f"""
                            <div style="
                                font-size: 10pt; 
                                color: #00FFFF; 
                                font-weight: bold; 
                                text-shadow: 2px 2px 4px #000; 
                                background: rgba(0,0,0,0.6); 
                                padding: 2px 8px; 
                                border-radius: 4px; 
                                width: max-content; 
                                white-space: nowrap; 
                                border: 1px solid rgba(0,255,255,0.4);
                            ">
                                SN: {id_reg}
                            </div>
                        """
                    )
                ).add_to(m_sec)

# 7.7. MARCADORES PUNTOS CRITICOS EN EL MAPA
            for id_pc, pc in dict_pc_sec.items():
                domicilio_texto = pc.get('Domicilio', 'S/D')
                val_p, fec_p = scada_res_reg.get(pc['tag_p1'], (0.0, "N/A"))
                
                html_pc = f"""<div style="background:#000; color:white; padding:10px; border-radius:8px; border:1px solid #FF00FF; width:180px; font-family:sans-serif;">
                                <b style="color:#FF00FF; font-size:13px;">PUNTO CRÍTICO</b><br>
                                <small>{domicilio_texto}</small><br>
                                <hr style="opacity:0.2; margin:5px 0;">
                                Presión: <b style="color:#FF00FF;">{val_p:.2f} kg</b><br>
                                <span style="color:#FFFF00; font-size:9px;">{fec_p}</span>
                            </div>"""
                
                # --- ETIQUETA FLOTANTE (DIVICON) SOLO CON ID/SERIE 
                folium.Marker(
                    location=pc['coord'],
                    icon=folium.DivIcon(
                        icon_size=(250,36),
                        icon_anchor=(-15, 35), # Ajusta la posición a la derecha del marcador
                        html=f"""
                            <div style="
                                font-size: 10pt; 
                                color: #FF00FF; 
                                font-weight: bold; 
                                text-shadow: 2px 2px 4px #000; 
                                background: rgba(0,0,0,0.6); 
                                padding: 2px 8px; 
                                border-radius: 4px; 
                                width: max-content; 
                                white-space: nowrap; 
                                border: 1px solid rgba(255,0,255,0.4);
                            ">
                                NS: {id_pc}
                            </div>
                        """
                    )
                ).add_to(m_sec)
                
# --- MARCADOR TACHUELA REALISTA ROJA (ESTILO 3D) ---
                from folium.features import DivIcon

                # Gradiente rojo para imitar el volumen de image_87abee.png
                icon_html = """
                <div style="position: relative; width: 30px; height: 30px;">
                    <!-- Esfera con volumen rojo -->
                    <div style="
                        width: 20px; 
                        height: 20px; 
                        background: radial-gradient(circle at 30% 30%, #ff4d4d, #ff0000, #800000);
                        border-radius: 50%;
                        box-shadow: 2px 4px 6px rgba(0,0,0,0.5);
                        position: absolute;
                        top: 0; left: 5px;
                        z-index: 2;">
                    </div>
                    <!-- Pin metálico -->
                    <div style="
                        width: 2px; 
                        height: 15px; 
                        background: linear-gradient(to right, #e0e0e0, #808080);
                        position: absolute;
                        top: 18px; left: 14px;
                        z-index: 1;">
                    </div>
                </div>
                """

                folium.Marker(
                    location=pc['coord'],
                    icon=DivIcon(
                        icon_size=(30, 40),
                        icon_anchor=(15, 33),
                        html=icon_html
                    ),
                    popup=folium.Popup(html_pc, max_width=250)
                ).add_to(m_sec)
                
# 7.7.1 MARCADORES DE VALVULAS REDUCTORAS DE PRESION EN EL MAPA
            for id_vrp, vrp in dict_vrp_sec.items():
                val_p1, _ = scada_res_reg.get(vrp['tag_p1'], (0.0, "N/A"))
                val_p2, _ = scada_res_reg.get(vrp['tag_p2'], (0.0, "N/A"))
                serie_vrp = vrp.get('Serie', 'S/N')
                html_vrp = f"""<div style="background:#000; color:white; padding:10px; border-radius:8px; border:1px solid #00FFCC; width:200px; font-family:sans-serif;"><b style="color:#00FFCC; font-size:13px;">VALVULA VRP</b><br><small>{vrp['nombre']}</small><hr style="opacity:0.2; margin:5px 0;">P. Entrada: <b>{val_p1:.2f} kg</b><br>P. Salida: <b style="color:#00FFCC;">{val_p2:.2f} kg</b></div>"""
                
# --- MARCADOR TACHUELA REALISTA VERDE (ESTILO 3D) ---
                from folium.features import DivIcon

                # Gradiente verde para simular volumen y brillo
                icon_html = """
                <div style="position: relative; width: 30px; height: 30px;">
                    <!-- Esfera con volumen verde -->
                    <div style="
                        width: 20px; 
                        height: 20px; 
                        background: radial-gradient(circle at 30% 30%, #a1ffce, #28a745, #004d1a);
                        border-radius: 50%;
                        box-shadow: 2px 4px 6px rgba(0,0,0,0.5);
                        position: absolute;
                        top: 0; left: 5px;
                        z-index: 2;">
                    </div>
                    <!-- Pin metálico -->
                    <div style="
                        width: 2px; 
                        height: 15px; 
                        background: linear-gradient(to right, #e0e0e0, #808080);
                        position: absolute;
                        top: 18px; left: 14px;
                        z-index: 1;">
                    </div>
                </div>
                """

                folium.Marker(
                    location=vrp['coord'],
                    icon=DivIcon(
                        icon_size=(30, 40),
                        icon_anchor=(15, 33),
                        html=icon_html
                    ),
                    popup=folium.Popup(html_vrp, max_width=250)
                ).add_to(m_sec)

                # --- ETIQUETA FLOTANTE PARA VRP ---
                folium.Marker(
                    location=vrp['coord'],
                    icon=folium.features.DivIcon(
                        icon_size=(250,36),
                        icon_anchor=(-15, 35), # Posición a la derecha del icono verde
                        html=f"""
                            <div style="
                                font-size: 10pt; 
                                color: #00FFCC; 
                                font-weight: bold; 
                                text-shadow: 2px 2px 4px #000; 
                                background: rgba(0,0,0,0.6); 
                                padding: 2px 8px; 
                                border-radius: 4px; 
                                width: max-content; 
                                white-space: nowrap; 
                                border: 1px solid rgba(0,255,204,0.4);
                            ">
                                SN: {serie_vrp}
                            </div>
                        """
                    )
                ).add_to(m_sec)

            # 7.8. MARCADOR DE POZOS EN EL MAPA
            ids_p = [p.strip() for p in datos_s.get('Pozos_Sector', '').split(',')] if datos_s.get('Pozos_Sector') else []
            for id_p in ids_p:
                if id_p in mapa_pozos_dict:
                    info = mapa_pozos_dict[id_p]
                    def ds(tag):
                        val, fec = data_scada.get(tag, (0.0, "N/A"))
                        try: return float(val), fec
                        except: return 0.0, fec
                            
                    q, f_q = ds(info['caudal']); p, f_p = ds(info['presion'])
                    v = [ds(info.get(f'v{i}')) for i in range(1, 4)]; a = [ds(info.get(f'a{i}')) for i in range(1, 4)]
                    
                    html_popup_sec = f"""<div style="background: #050505; color: white; padding: 15px; border-radius: 12px; width: 380px; border: 1px solid {info['color_final']}; font-family: sans-serif;"><div style="display: flex; justify-content: space-between; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 10px;"><b style="color: #00d4ff; font-size: 16px;">POZO {id_p}</b><span style="font-size: 10px; background: {info['color_final']}; color: black; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{info['status_label']}</span></div><div style="margin-bottom: 12px;"><div style="font-size: 10px; color: #888; margin-bottom: 4px;">HIDRÁULICA</div><div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;"><span>💧 Caudal: <b>{q:.2f} L/s</b></span><span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_q}</span></div><div style="display: flex; align-items: baseline; font-size: 11px;"><span>🚀 Presión: <b>{p:.2f} kg</b></span><span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_p}</span></div></div><div><div style="font-size: 10px; color: #888; margin-bottom: 4px;">ELÉCTRICO</div><table style="width: 100%; font-size: 10px; border-collapse: collapse;"><tr><td>L1-L2</td><td>{v[0][0]:.1f}V</td><td>{a[0][0]:.1f}A</td></tr></table></div></div>"""

                    # --- ETIQUETA CON NOMBRE DEL POZO (DIVICON) ---
                    folium.Marker(
                        location=info['coord'],
                        icon=folium.DivIcon(
                            html=f"""<div style="font-size: 11px; color: white; font-weight: bold; 
                                     text-shadow: 1px 1px 2px black; width: 100px; 
                                     position: relative; left: 17px; top: -3px;">
                                     {id_p}
                                     </div>"""
                        )
                    ).add_to(m_sec)
                    
                    if info.get('blink'):
                        folium.Marker(
                            location=info['coord'],
                            icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                            popup=folium.Popup(html_popup_sec, max_width=400)
                        ).add_to(m_sec)
                    else:
                        folium.CircleMarker(
                            location=info['coord'],
                            radius=6,
                            color=info['color_final'],
                            fill=True, fill_opacity=1,
                            popup=folium.Popup(html_popup_sec, max_width=400)
                        ).add_to(m_sec)

            if st.session_state.get("ultimo_clic_sv"):
                c_lat, c_lng = st.session_state.ultimo_clic_sv["lat"], st.session_state.ultimo_clic_sv["lng"]
                sv_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={c_lat},{c_lng}"
                html_popup_sv = f"""<div style="background:#000; color:white; padding:10px; border-radius:8px; border:1px solid #00d4ff; width:180px;"><b style="color:#00d4ff; font-size:12px;">COORDENADAS</b><br><code>{c_lat:.5f}, {c_lng:.5f}</code><br><br><a href="{sv_url}" target="_blank" style="display:block; text-align:center; background:#00d4ff; color:black; padding:8px; border-radius:5px; text-decoration:none; font-weight:bold; font-size:10px;">🚹 STREET VIEW</a></div>"""
                folium.Marker(location=[c_lat, c_lng], popup=folium.Popup(html_popup_sv, max_width=200), icon=folium.Icon(color='blue', icon='map-marker')).add_to(m_sec)

            folium.LayerControl(position='topright', collapsed=False).add_to(m_sec)
            Fullscreen(position='topleft').add_to(m_sec)
            salida = st_folium(m_sec, width="100%", height=330, key="mapa_miaa_interactivo_v4", returned_objects=["last_clicked"])
            if salida and salida.get("last_clicked"):
                nuevo_clic = salida["last_clicked"]
                if st.session_state.get("ultimo_clic_sv") != nuevo_clic:
                    st.session_state.ultimo_clic_sv = nuevo_clic
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
# 7.10. ------------------------------------------- Histórico Punto de Control y Pozos del Sector (Lado derecho del mapa) -------------------------
        with col_der:
            st.markdown(f"<h3 style='color:#00d4ff; font-size:18px; text-align: center; margin-bottom:0px;'>Histórico Puntos de control</h3>", unsafe_allow_html=True)
            
            tags_visualizar = []
            mapeo_config = {}

            # 1. Recolección de Puntos de Control (dict_reg)
            for s_id in list(dict_reg.keys()):
                r_info = dict_reg[s_id]
                conf_pc = [
                    ('tag_q', f"S:{s_id} - Q", '#00d4ff', False),
                    ('tag_p1', f"S:{s_id} - P1", '#00ff00', True),
                    ('tag_p2', f"S:{s_id} - P2", '#ffff00', True)
                ]
                for key_t, lb, clr, sec in conf_pc:
                    tag_v = r_info.get(key_t)
                    if tag_v and str(tag_v).strip().lower() not in ['0', 'none', 'n/a', 'null']:
                        tags_visualizar.append(tag_v)
                        mapeo_config[tag_v] = {'label': lb, 'color': clr, 'sec': sec}

            # 2. Recolección de Pozos (mapa_pozos_dict)
            for id_p in ids_p:
                if id_p in mapa_pozos_dict:
                    p_info = mapa_pozos_dict[id_p]
                    conf_pz = [
                        ('caudal', f"Pozo {id_p} - Q", '#00d4ff', False),
                        ('presion', f"Pozo {id_p} - P", '#00ff00', True),
                        ('nivel_tanque', f"Pozo {id_p} - Nivel", '#0000FF', True)
                    ]
                    for key_t, lb, clr, sec in conf_pz:
                        tag_v = p_info.get(key_t)
                        if tag_v and str(tag_v).strip().lower() not in ['0', 'none', 'n/a']:
                            tags_visualizar.append(tag_v)
                            mapeo_config[tag_v] = {'label': lb, 'color': clr, 'sec': sec}

            # 3. Consulta y Renderizado del gráfico derecho
            if tags_visualizar:
                try:
                    engine_h = get_mysql_scada_engine()
                    tags_unicos_query = "', '".join(list(set(tags_visualizar)))
                    q_hist = f"SELECT h.FECHA, h.VALUE, r.NAME as TAG FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_unicos_query}') AND h.FECHA BETWEEN '{f_ini_h} 00:00:00' AND '{f_fin_h} 23:59:59' ORDER BY h.FECHA ASC"
                    df_h = pd.read_sql(q_hist, engine_h)
                    
                    df_h = pd.read_sql(q_hist, engine_h)
                    
                    if not df_h.empty:
                        # --- INICIO DE LA LÓGICA DE FECHAS (Indentación ajustada) ---
                        df_h['FECHA'] = pd.to_datetime(df_h['FECHA'])
                        dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
                        meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                                    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}

                        # Rango para las líneas divisorias
                        fechas_lineas = pd.date_range(start=df_h['FECHA'].min().floor('D'), 
                                                      end=df_h['FECHA'].max().ceil('D'), freq='D')
                        
                        # Cálculo del paso para evitar amontonamiento
                        num_dias = len(fechas_lineas)
                        paso = 1 if num_dias <= 15 else (2 if num_dias <= 30 else 5)
                        ticks_filtrados = fechas_lineas[::paso]

                        # Creación de etiquetas en español
                        etiquetas_filtradas = [
                            f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
                            for d in ticks_filtrados
                        ]
                    
                        fig = go.Figure()
                        
                        # Contadores para variar la intensidad
                        idx_q = 0
                        idx_p = 0

                        for tag_name in tags_visualizar:
                            df_tag = df_h[df_h['TAG'] == tag_name]
                            if not df_tag.empty:
                                cfg = mapeo_config[tag_name]
                                
                                es_caudal = not cfg['sec']
                                
                                label_u = cfg['label'].upper()

                                if es_caudal:
                                    unidad_pc = "Lps"
                                elif "NIVEL" in label_u or "TANQUE" in label_u or "MTS" in label_u:
                                    unidad_pc = "Mts"
                                else:
                                    unidad_pc = "kg/cm²"
                                
                                # --- LÓGICA DE COLORES DINÁMICOS ---
                                if es_caudal:
                                    # Diferentes tonos de AZUL/CIAN (Caudal)
                                    # Variamos la luminosidad basándonos en idx_q
                                    brillo = max(75 - (idx_q * 15), 35) 
                                    color_base = f"hsl(200, 100%, {brillo}%)" 
                                    idx_q += 1
                                else:
                                    # Diferentes tonos de VERDE (Presión)
                                    brillo = max(80 - (idx_p * 20), 30)
                                    color_base = f"hsl(145, 100%, {brillo}%)"
                                    idx_p += 1

                                fig.add_trace(go.Scatter(
                                    x=df_tag['FECHA'], 
                                    y=df_tag['VALUE'], 
                                    name=cfg['label'], 
                                    yaxis="y2" if cfg['sec'] else "y1", 
                                    mode='lines+markers',
                                    line=dict(width=2, color=color_base),
                                    
                                    marker=dict(size=3 if es_caudal else 3, symbol='circle'),
                                    
                                    # Configuración de Área para Caudales
                                    fill='tozeroy' if es_caudal else None,
                                    # La opacidad se mantiene en 0.15 (15%)
                                    fillcolor=color_base.replace("hsl", "hsla").replace(")", ", 0.15)"),
                                    
                                    hovertemplate='<b>%{fullData.name}</b>: %{y:.2f} ' + unidad_pc + '<extra></extra>'
                                                 
                                ))

                        delta = pd.Timedelta(hours=1)
                        for d in fechas_lineas:
                            es_lunes = (d.dayofweek == 0)
                            fig.add_vrect(x0=d - delta, x1=d + delta, fillcolor="gray", opacity=0.2, layer="below", line_width=0)
                            fig.add_vline(x=d, line_width=1.5, line_dash="dash", 
                                          line_color="#fffb00" if es_lunes else "white", opacity=0.5, layer="above")
                        
                        fig.update_layout(
                            paper_bgcolor='rgba(0,0,0,0)', 
                            plot_bgcolor='rgba(0,0,0,0)', 
                            height=350, 
                            margin=dict(l=50, r=50, t=10, b=10), 
                            hovermode="x unified", 
                            legend=dict(
                                orientation="h", 
                                yanchor="bottom", 
                                y=1.05, 
                                x=0.5, 
                                xanchor="center", 
                                font=dict(color="white", size=10)
                            ),
                            xaxis=dict(
                                color="white", 
                                showgrid=False,
                                tickvals=ticks_filtrados,      # <--- Tu lista filtrada
                                ticktext=etiquetas_filtradas,  # <--- Tus etiquetas con fecha/hora
                                tickangle=0,
                                tickformat="%d-%b-%Y %H:%M"
                            ),
                            yaxis=dict(
                                title="Caudales (m³/h)", 
                                color="#00d4ff", 
                                tickformat=".2f"
                            ),
                            yaxis2=dict(
                                title="Presiones (kg)", 
                                side="right", 
                                overlaying="y", 
                                color="#00ff00", 
                                showgrid=False, 
                                tickformat=".2f"
                            )
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.error(f"Error Scada (Derecha): {e}")
                        

# 7.11. ------------------------------------------------------------------------- ZONA : VRP ----------------------------------------------
        col_vrp, col_pc = st.columns([1.0, 1.0])

        with col_vrp:
            # 1. Recolección de TODAS las variables de TODAS las VRP del sector
            tags_vrp_global = []
            mapeo_vrp_global = {}
            
            # Recorremos el diccionario de VRPs del sector
            for v_id, v_info in dict_vrp_sec.items():
                # USAMOS EL ID (v_id) PARA QUE SEA MÁS CORTO EN LA LEYENDA
                identificador = f"VRP {v_id}" 
                
                conf_vrp = [
                    ('tag_q', f"{identificador} - Q", False),
                    ('tag_p1', f"{identificador} - P1", True),
                    ('tag_p2', f"{identificador} - P2", True)
                ]
                
                for key_t, lb, sec in conf_vrp:
                    t_val = v_info.get(key_t)
                    if t_val and str(t_val).strip().lower() not in ['0', 'none', 'n/a']:
                        tags_vrp_global.append(t_val)
                        mapeo_vrp_global[t_val] = {'label': lb, 'sec': sec}

            if tags_vrp_global:
                try:
                    engine_h = get_mysql_scada_engine()
                    tags_in_v = "', '".join(list(set(tags_vrp_global)))
                    q_vrp = f"SELECT h.FECHA, h.VALUE, r.NAME as TAG FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_in_v}') AND h.FECHA BETWEEN '{f_ini_h} 00:00:00' AND '{f_fin_h} 23:59:59' ORDER BY h.FECHA ASC"
                    df_v = pd.read_sql(q_vrp, engine_h)
                    
                    if not df_v.empty:
                        st.markdown(f"<h3 style='color:#00ffcc; font-size:20px; margin-bottom:10px; text-align: center;'>Análisis Integral de VRPs del Sector</h3>", unsafe_allow_html=True)

                        # --- 1. LÓGICA DE FECHAS (Estandarizada) ---
                        df_v['FECHA'] = pd.to_datetime(df_v['FECHA'])
                        dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
                        meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                                    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}
                        
                        fechas_lineas = pd.date_range(start=df_v['FECHA'].min().floor('D'), 
                                                      end=df_v['FECHA'].max().ceil('D'), freq='D')
                        num_dias = len(fechas_lineas)
                        paso = 1 if num_dias <= 15 else (2 if num_dias <= 30 else 5)
                        ticks_filtrados = fechas_lineas[::paso]
                        etiquetas_filtradas = [
                            f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
                            for d in ticks_filtrados
                        ]
                        
                        fig_v = go.Figure()

                        # --- 2. DIBUJO DE SOMBRAS Y LÍNEAS (Separador de días) ---
                        delta = pd.Timedelta(hours=1) # Ajusta este ancho según necesites
                        for d in fechas_lineas:
                            es_lunes = (d.dayofweek == 0)
                            
                            # AÑADIR LA SOMBRA (El fondo gris para resaltar el día)
                            fig_v.add_vrect(
                                x0=d - delta, x1=d + delta, 
                                fillcolor="gray", opacity=0.2, 
                                layer="below", line_width=0
                            )
                            
                            # AÑADIR LA LÍNEA (El separador)
                            fig_v.add_vline(
                                x=d, line_width=0.5, line_dash="dash", 
                                line_color="#fffb00" if es_lunes else "white", 
                                opacity=0.5, layer="above"
                            )
                        
                        idx_vq = 0
                        idx_vp = 0

                        for t_name in tags_vrp_global:
                            df_t = df_v[df_v['TAG'] == t_name]
                            if not df_t.empty:
                                c_vrp = mapeo_vrp_global[t_name]
                                es_caudal_v = not c_vrp['sec']
                                if "P1" in c_vrp['label'] or "P2" in c_vrp['label']:
                                    unidad_final = "kg/cm²"
                                else:
                                    unidad_final = "Lps"
                                
                                # --- COLORES DINÁMICOS ---
                                if es_caudal_v:
                                    # Paleta de Azules: Brillo controlado entre 40% y 75%
                                    brillo = 75 - (idx_vq * 15)
                                    brillo = max(brillo, 35)
                                    color_v = f"hsl(200, 100%, {brillo}%)" 
                                    idx_vq += 1
                                else:
                                    # Paleta de Verdes: Brillo controlado entre 40% y 80%
                                    brillo = 80 - (idx_vp * 15)
                                    brillo = max(brillo, 30)
                                    color_v = f"hsl(150, 100%, {brillo}%)"
                                    idx_vp += 1

                                fig_v.add_trace(go.Scatter(
                                    x=df_t['FECHA'], 
                                    y=df_t['VALUE'], 
                                    name=c_vrp['label'], 
                                    yaxis="y2" if c_vrp['sec'] else "y1", 
                                    mode='lines+markers',
                                    line=dict(width=1.8, color=color_v),
                                    # CORRECCIÓN AQUÍ: Sintaxis de marcador limpia
                                    marker=dict(size=3 if es_caudal_v else 4, symbol='circle'),
                                    fill='tozeroy' if es_caudal_v else None,
                                    fillcolor=color_v.replace("hsl", "hsla").replace(")", ", 0.12)"),
                                    hovertemplate=f'<b>%{{fullData.name}}</b>: %{{y:.2f}} {unidad_final}<extra></extra>'
                                ))

                        for d in fechas_lineas:
                            es_lunes = (d.dayofweek == 0)
                            fig_v.add_vline(x=d, line_width=1.5, line_dash="dash", 
                                          line_color="#fffb00" if es_lunes else "white", opacity=0.3)
                                          
                        fig_v.update_layout(
                            paper_bgcolor='rgba(0,0,0,0)', 
                            plot_bgcolor='rgba(0,0,0,0)', 
                            height=300, 
                            margin=dict(l=50, r=50, t=10, b=10), 
                            hovermode="x unified", 
                            # Mantenemos la leyenda abajo para que no estorbe
                            legend=dict(orientation="h",
                            yanchor="bottom",
                            y=1.05,
                            x=0.5,
                            xanchor="center", font=dict(color="white", size=9)),
                            xaxis=dict(color="white", 
                                showgrid=False,
                                tickvals=ticks_filtrados,
                                ticktext=etiquetas_filtradas,
                                tickangle=0,
                                tickformat="%d-%b-%Y %H:%M" # Encabezado del hover en orden
                            ),
                            
                            yaxis=dict(title="Caudal (Lps)", color="#00d4ff", tickformat=".2f"),
                            yaxis2=dict(title="Presión (kg)", side="right", overlaying="y", color="#00ff00", showgrid=False, tickformat=".2f")
                        )
                        st.plotly_chart(fig_v, use_container_width=True)
                    else:
                        st.warning("No se encontraron datos para las VRPs.")
                except Exception as e:
                    st.error(f"Error Scada VRP: {e}")
                    
# 7.12. ---------------------------------------------------------- GRÁFICO: HISTÓRICO PUNTOS CRÍTICOS -------------------------------------------------------------------------------------
        with col_pc:
            if dict_pc_sec:
                tags_pc_list = [v['tag_p1'] for v in dict_pc_sec.values() if v.get('tag_p1')]
                if tags_pc_list:
                    try:
                        tags_pc_in = "', '".join(tags_pc_list)
                        df_pc_h = pd.read_sql(f"SELECT h.FECHA, h.VALUE, r.NAME as TAG FROM vfitagnumhistory h JOIN VfiTagRef r ON h.GATEID = r.GATEID WHERE r.NAME IN ('{tags_pc_in}') AND h.FECHA BETWEEN '{f_ini_h} 00:00:00' AND '{f_fin_h} 23:59:59' ORDER BY h.FECHA ASC", engine_h)

                        if not df_pc_h.empty:
                            st.markdown(f"<h3 style='color:#ff0000; font-size:18px; margin-bottom:10px; text-align: center;'>Puntos críticos del sector:</h3>", unsafe_allow_html=True)
                            
                            # --- 1. LÓGICA DE FECHAS (Estandarizada) ---
                            df_pc_h['FECHA'] = pd.to_datetime(df_pc_h['FECHA'])
                            dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
                            meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}
                            
                            fechas_lineas = pd.date_range(start=df_pc_h['FECHA'].min().floor('D'), end=df_pc_h['FECHA'].max().ceil('D'), freq='D')
                            num_dias = len(fechas_lineas)
                            paso = 1 if num_dias <= 15 else (2 if num_dias <= 30 else 5)
                            ticks_filtrados = fechas_lineas[::paso]
                            etiquetas_filtradas = [f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}" for d in ticks_filtrados]

                            fig_pc = go.Figure()
                            
                            # --- 2. DIBUJO DE SOMBRAS Y LÍNEAS (Separador de días) ---
                            delta = pd.Timedelta(hours=1)
                            for d in fechas_lineas:
                                es_lunes = (d.dayofweek == 0)
                                fig_pc.add_vrect(x0=d - delta, x1=d + delta, fillcolor="gray", opacity=0.2, layer="below", line_width=0)
                                fig_pc.add_vline(x=d, line_width=1.5, line_dash="dash", line_color="#fffb00" if es_lunes else "white", opacity=0.5, layer="above")

                            tag_to_name = {v['tag_p1']: v.get('Domicilio', v.get('nombre', 'S/D')) for v in dict_pc_sec.values()}

                            # --- 3. TRAZADO DE DATOS ---
                            for tag in tags_pc_list:
                                df_temp = df_pc_h[df_pc_h['TAG'] == tag]
                                if not df_temp.empty:
                                    fig_pc.add_trace(go.Scatter(
                                        x=df_temp['FECHA'], y=df_temp['VALUE'], 
                                        name=tag_to_name.get(tag, tag), mode='lines+markers',
                                        marker=dict(size=4, symbol='circle'), line=dict(width=2),
                                        hovertemplate='<b>%{fullData.name}</b><br>Valor: %{y:.2f} kg<extra></extra>'
                                    ))

                            # --- 4. CONFIGURACIÓN DEL LAYOUT ---
                            fig_pc.update_layout(
                                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=300, 
                                margin=dict(l=50, r=50, t=40, b=10), hovermode="x unified",
                                xaxis=dict(
                                    color="white", 
                                    showgrid=False,
                                    tickvals=ticks_filtrados, 
                                    ticktext=etiquetas_filtradas, 
                                    tickangle=0, 
                                    tickformat="%d-%b-%Y %H:%M" # Encabezado formato Día-Mes-Año
                                ),
                                yaxis=dict(tickformat=".2f", color="white"), # Decimales eje Y
                                legend=dict(orientation="h", yanchor="bottom", y=1.05, x=0.5, xanchor="center", font=dict(color="white", size=10))
                            )
                            st.plotly_chart(fig_pc, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error PC: {e}")

        # Finalizamos el bloque del sector
        st.stop()
    
# 8. SECCION ------------------------------------------------------------------------------- 8. SIDEBAR BARRA LATERAL IZQUIERDA ------------------------------------------------------------------------------------------

st.set_page_config(layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
        /* 1. ELIMINAR EL TIRADOR DE REDIMENSIÓN */
        /* Buscamos el elemento que permite arrastrar la barra y lo desactivamos */
        [data-testid="stSidebarResizer"] {
            display: none !important;
            pointer-events: none !important;
        }
        
        /* 2. FORZAR ANCHO ESTÁTICO E INAMOVIBLE */
        section[data-testid="stSidebar"] {
            width: 250px !important;
            min-width: 250px !important;
            max-width: 250px !important;
            /* Evita que el usuario seleccione texto o interactúe con el borde */
            user-select: none; 
        }

        /* 3. BLOQUEAR EL CURSOR DE REDIMENSIÓN */
        /* A veces el cursor cambia a flechas laterales; esto lo devuelve a la normalidad */
        html, body {
            cursor: default !important;
        }

    
        /* 1. AJUSTE DINÁMICO DEL MAPA AL MARGEN DERECHO */
        [data-testid="stMain"] {
            margin-left: 0px !important;
            /* Restamos el ancho de la barra para que el contenido no desborde */
            width: calc(100% - 0px) !important; 
            padding-right: 2rem !important; /* Espacio de seguridad a la derecha */
        }

        /* 2. ASEGURAR QUE EL CONTENEDOR DE STREAMLIT USE TODO EL ANCHO DISPONIBLE */
        .block-container {
            max-width: 100% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        /* 3. ARREGLAR EL CONTROL DE CAPAS (LayerControl) */
        /* Forzamos que el cuadro de capas de Folium siempre esté visible y no se desborde */
        .leaflet-control-layers {
            margin-right: 20px !important; /* Separa el cuadro del borde derecho de la pantalla */
            border: 2px solid rgba(0,255,255,0.5) !important; /* Opcional: Estilo futurista */
            background: rgba(0, 0, 0, 0.8) !important; /* Fondo oscuro para que combine con tu HUD */
            color: white !important;
        }

        /* Cambiar color de los textos dentro del selector de capas para que se vean en fondo oscuro */
        .leaflet-control-layers-list, .leaflet-control-layers-base, .leaflet-control-layers-overlays {
            color: white !important;
        }
        
        /* 4. RESPONSIVIDAD PARA PANTALLAS PEQUEÑAS */
        @media (max-width: 991px) {
            [data-testid="stMain"] {
                margin-left: 350px !important;
                width: calc(100% - 350px) !important;
            }
        }
        /* Modificar tamaño de fuente general en la sidebar */
        section[data-testid="stSidebar"] {
            font-size: 14px !important; /* Ajusta este valor a tu gusto */
        }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    # 8.1. Contenedor del logo
    st.markdown('<div class="sidebar-logo"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg"></div>', unsafe_allow_html=True)

    # 8.2. Inicializamos variables de estado (Solo si no existen)
    if 'centro_mapa' not in st.session_state:
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5
    
    # 8.3. ESTADO DE LAS CONEXIONES
    with st.expander("🔌 Conexiones BD", expanded=False):
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
    
    # --- BUSCADORES ---
    
    # 8.4. Buscador de Pozos
    lista_pozos_nombres = sorted(list(mapa_pozos_dict.keys()))
    pozo_buscado = st.selectbox(
        "🔍 Localizar Pozo",
        options=[""] + lista_pozos_nombres,
        format_func=lambda x: "Seleccionar" if x == "" else f"📍 {x}"
    )

    # 8.4.1 Buscador de Tanques
    lista_tanques_nombres = sorted(list(mapa_tanques_dict.keys()))
    tanque_buscado = st.selectbox(
        "🛢️ Localizar Tanque",
        options=[""] + lista_tanques_nombres,
        format_func=lambda x: "Seleccionar" if x == "" else f"📦 {x} - {mapa_tanques_dict[x]['nombre']}"
    )

    # 8.4.2 Buscador de Rebombeos
    lista_rebombeos_nombres = sorted(list(mapa_rebombeos_dict.keys()))
    rebombeo_buscado = st.selectbox(
        "🧊 Localizar Rebombeo",
        options=[""] + lista_rebombeos_nombres,
        format_func=lambda x: "Seleccionar" if x == "" else f"🔄 {x}"
    )

    # 8.5. Buscador de Sectores
    lista_sectores = sorted([s['sector'] for s in sectores])
    sector_buscado = st.selectbox(
        "🏘️ Localizar Sector",
        options=[""] + lista_sectores,
        format_func=lambda x: "Seleccionar" if x == "" else f" {x}",
        key="busqueda_sectores"
    )

    # 8.5.1. BUSCADOR DE COLONIAS (BLINDADO)
    if 'gdf_colonias_lista' not in st.session_state:
        st.session_state.gdf_colonias_lista = get_todas_las_colonias()
    
    df_col = st.session_state.gdf_colonias_lista
    
    # Validamos que el DataFrame sea válido y contenga 'Col_atl'
    if df_col is not None and not df_col.empty and 'Col_atl' in df_col.columns:
        lista_colonias = sorted(df_col['Col_atl'].unique().tolist())
    else:
        lista_colonias = []
        if df_col is not None and 'Col_atl' not in df_col.columns:
            st.sidebar.error("Error: La columna 'Col_atl' no existe en los datos.")

    colonia_buscada = st.sidebar.selectbox(
        "🏙️ Localizar Colonia",
        options=[""] + lista_colonias,
        format_func=lambda x: "Seleccionar" if x == "" else f" {x}",
        key="busqueda_colonias"
    )


    # 8.6. ASIGNACIÓN DE POSICIÓN Y PRIORIDAD
    datos_sector_resaltado = None
    
    if pozo_buscado:
        st.session_state.centro_mapa = mapa_pozos_dict[pozo_buscado]['coord']
        st.session_state.zoom_inicial = 18
        
    elif tanque_buscado:
        st.session_state.centro_mapa = mapa_tanques_dict[tanque_buscado]['coord']
        st.session_state.zoom_inicial = 18
        
    elif rebombeo_buscado:
        st.session_state.centro_mapa = mapa_rebombeos_dict[rebombeo_buscado]['coord']
        st.session_state.zoom_inicial = 18
        
    elif sector_buscado:
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

    # NUEVA INTEGRACIÓN PARA COLONIAS
    elif colonia_buscada and colonia_buscada != "":
        df = st.session_state.gdf_colonias_lista
        if df is not None:
            col_sel = df[df['Col_atl'] == colonia_buscada]
            if not col_sel.empty:
                # GUARDAMOS LA COLONIA SELECCIONADA EN EL ESTADO
                st.session_state.colonia_resaltada = col_sel.iloc[0]
                
                centro = st.session_state.colonia_resaltada.geometry.centroid
                st.session_state.centro_mapa = [centro.y, centro.x]
                st.session_state.zoom_inicial = 15.5
                
    else:
        # Si no hay nada seleccionado, mantener vista general
        st.session_state.centro_mapa = [21.8820, -102.2800]
        st.session_state.zoom_inicial = 12.5
        
    # 8.7. BOTON ACTUALIZAR ---
    if st.button("♻️ Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
        
    # 8.8. CONTROL DE CAPAS ---
    with st.expander("🗺️ Control de Capas", expanded=False):
        
        ver_pozos = st.checkbox("💧 Pozos", value=True)
        ver_colonias = st.checkbox("🏙️ Colonias", value=True)
        ver_sectores = st.checkbox("🏘️ Sectores", value=False)
        ver_tanques = st.checkbox("🛢️ Tanques", value=False)
        ver_rebombeos = st.checkbox("🧊 Rebombeos", value=False) # Activado por defecto para facilitar localización
        ver_macromedidores = st.checkbox("🌀 Macromedidores", value=False)
        
    
    # 8.9. LISTADO DE ESTADOS ---
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

    # 8.10. LISTADO DE MACROMEDIDORES ---
    datos_macros = cargar_medidores_desde_db()

    if datos_macros:
        # Filtramos estrictamente los registros antes de hacer cualquier otra cosa
        lista_filtrada = []
        for id_medidor, info in datos_macros.items():
            # Convertimos a string por seguridad para comparar el ID
            id_str = str(id_medidor).strip()
            nombre = str(info.get('nombre', '')).strip()
            
            # Condición estricta: No debe ser '1000' y no debe ser 'Sin instalar'
            if id_str != '1000' and nombre != 'Sin instalar':
                lista_filtrada.append((id_str, nombre))
        
        # Ordenamos la lista filtrada
        lista_filtrada.sort()
        
        with st.expander(f"🟣 Macromedidores ({len(lista_filtrada)})", expanded=False):
            for id_medidor, nombre in lista_filtrada:
                st.write(f"🟣 {id_medidor}")
    else:
        st.warning("No hay macromedidores disponibles.")

          
                
# 9.  SECCION--------------------------------------------------------------------------------- 9. MAPA PRINCIPAL -----------------------------------------------------------------------------------------------------------
st.markdown('<div class="titulo-superior">SISTEMA - AGUASCALIENTES</div>', unsafe_allow_html=True)

# Indicadores usando el sistema de Grid para que ocupen todo el ancho
c_total = total_q if 'total_q' in locals() else 0.0
p_prom = (total_p / max(len(pozos_on), 1)) if 'total_p' in locals() else 0.0

# Render de indicadores
st.markdown(f"""
    <div class="contenedor-indicadores">
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">💧 Caudal total</p><p style="color:#00ffcc; font-size:1.1rem; font-weight:bold; margin:0;">{c_total:.1f} l/s</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">📉 Presión promedio</p><p style="color:#ffff00; font-size:1.1rem; font-weight:bold; margin:0;">{p_prom:.2f} kg</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">🟢 Sitios encendidos</p><p style="color:#00ff00; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_on)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">🔴 Sitios apagados</p><p style="color:#ff0000; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_off)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">⚠️ fallas de comunicación</p><p style="color:#ffaa00; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_falla_com)}</p></div>
        <div class="card-indicador"><p style="color:#ffffff; font-size:0.8rem; margin:0;">⚪ Sin telemetria</p><p style="color:#ffffff; font-size:1.1rem; font-weight:bold; margin:0;">{len(pozos_sin_telemetria)}</p></div>
    </div>
""", unsafe_allow_html=True)

st.markdown('<div class="mapa-area">', unsafe_allow_html=True)
col_mapa, col_capas = st.columns([0.94, 0.06])

with col_mapa:
    m = folium.Map(
        location=st.session_state.centro_mapa, 
        zoom_start=st.session_state.zoom_inicial, 
        
    )

    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        attr='Google',
        name='Vista Satélite',
        overlay=False,
        control=True
    ).add_to(m)

    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satélite (Esri)',
        overlay=False,
        control=True
    ).add_to(m)

            # 2. Capas de Fondo (Selectors)
    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="Vista Nocturna",
        attr="CartoDB",
        overlay=False,
        control=True
    ).add_to(m)

    Fullscreen().add_to(m)


# 9.2. Añadir el resaltado del sector si existe
    if datos_sector_resaltado:
        folium.GeoJson(
            json.loads(datos_sector_resaltado['geo']),
            style_function=lambda x: {'fillColor': '#00d4ff', 'color': '#ffffff', 'weight': 3, 'fillOpacity': 0.4}
        ).add_to(m)

    # 9.3. FUNCIÓN PARA HORARIO 00:00
    def formato_hora(decimal):
        try:
            if decimal == "N/A" or decimal is None: return "00:00"
            horas = int(float(decimal))
            minutos = int((float(decimal) - horas) * 60)
            return f"{horas:02d}:{minutos:02d}"
        except:
            return "00:00"

    # 9.4. FUNCIÓN PARA ICONO PARPADEANTE PEQUEÑO (8px)
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

# 9.5. RENDERIZADO DE SECTORES EN EL MAPA PRINCIPAL ___________________________________________________________________________________________________________________________________

def get_sector_style(feature, visible):
    return {
        'fillColor': '#00d4ff',
        'color': '#00d4ff' if visible else 'transparent',
        'weight': 1.5 if visible else 0,
        'fillOpacity': 0.12 if visible else 0.01,
    }

sectores_data = cargar_sectores_poligonos()

if sectores_data:
    fg_sectores = folium.FeatureGroup(name="Sectores Hidráulicos", z_index=1)
    
    for s in sectores_data:
        try:
            if not s.get('geo'): continue
            
            nombre_sec = s['sector']
            geo_dict = json.loads(s['geo'])
            
            sector_encoded = urllib.parse.quote(nombre_sec)
            url_acceso = f"/?sector={sector_encoded}&access=granted&role={st.session_state.rol}"
            
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

# Declaración global de incidencias para que esté disponible para pozos y colonias siempre
dic_incidencias_activas = obtener_pozos_con_incidencias_hoy() if 'obtener_pozos_con_incidencias_hoy' in globals() else {}            

# 9.6. RENDERIZADO DE POLÍGONOS DE COLONIAS __________________________________________________________________________________________________________________________________
if ver_colonias:
    gdf_colonias = get_todas_las_colonias()
    
    if gdf_colonias is not None and not gdf_colonias.empty:
        
        lista_incidencias_tooltip = []
        lista_afectacion_tooltip = []
        
        for idx, row in gdf_colonias.iterrows():
            suma_afec = 0.0
            descripciones_fallas = []
            
            for i in range(1, 11):
                pozo_col = row.get(f'Pozo_{i}')
                afectacion_col = row.get(f'Afectacion_{i}')
                
                if pd.notna(pozo_col):
                    id_p_limpio = str(pozo_col).strip().upper()
                    id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
                    id_p_sin_guion = id_p_limpio.replace('-', '')
                    
                    if (id_p_limpio in dic_incidencias_activas or 
                        id_p_con_guion in dic_incidencias_activas or 
                        id_p_sin_guion in dic_incidencias_activas):
                        
                        falla = (
                            dic_incidencias_activas.get(id_p_limpio) or 
                            dic_incidencias_activas.get(id_p_con_guion) or 
                            dic_incidencias_activas.get(id_p_sin_guion, 'Activa')
                        )
                        if isinstance(falla, dict):
                            falla_txt = falla.get('diagnostico', falla.get('motivo', 'Activa'))
                        else:
                            falla_txt = str(falla)
                            
                        descripciones_fallas.append(f"{pozo_col}: {falla_txt}")
                        
                        if pd.notna(afectacion_col):
                            try:
                                val_str = str(afectacion_col).replace('%', '').strip()
                                val_f = float(val_str)
                                suma_afec += val_f  # ⚠️ Suma acumulativa para el tooltip
                            except:
                                pass
            
            if descripciones_fallas:
                lista_incidencias_tooltip.append(" | ".join(descripciones_fallas))
                lista_afectacion_tooltip.append(f"{int(suma_afec)}%" if suma_afec > 0 else "N/D")
            else:
                lista_incidencias_tooltip.append("Ninguna")
                lista_afectacion_tooltip.append("0%")

        gdf_colonias['Info_Incidencia'] = lista_incidencias_tooltip
        gdf_colonias['Info_Porcentaje'] = lista_afectacion_tooltip

        fg_colonias = folium.FeatureGroup(name="Colonias")
        
        def estilo_final(feature):
            props = feature.get('properties', {})
            nombre_actual = props.get('Col_atl')
            col_sel = st.session_state.get('colonia_resaltada')
            es_match = (col_sel is not None and nombre_actual == col_sel.get('Col_atl'))
            
            color_dinamico, afectacion_val = calcular_color_colonia(props, dic_incidencias_activas)
            fill_color_final = '#F1C40F' if es_match else color_dinamico
            
            if es_match:
                border_color_final = '#F39C12'
                weight_final = 3
                opacity_final = 0.5
            elif afectacion_val > 0:
                border_color_final = color_dinamico
                weight_final = 2.5
                opacity_final = 0.25
            else:
                border_color_final = '#2980B9'
                weight_final = 1
                opacity_final = 0.08
            
            return {
                'fillColor': fill_color_final,
                'color': border_color_final,
                'weight': weight_final,
                'fillOpacity': opacity_final
            }

        def estilo_hover(feature):
            return {'fillOpacity': 0.8, 'weight': 4, 'color': '#FFFFFF'}

        folium.GeoJson(
            gdf_colonias,
            name="Colonias",
            style_function=estilo_final,
            highlight_function=estilo_hover,
            tooltip=folium.GeoJsonTooltip(
                fields=['Col_atl', 'Pozos', 'Sector', 'Distrito', 'Info_Incidencia', 'Info_Porcentaje'],
                aliases=['Colonia:', 'Pozos:', 'Sector:', 'Distrito:', 'Incidencia:', 'Afectación:'],
                localize=True,
                sticky=True
            )
        ).add_to(fg_colonias)
        
        fg_colonias.add_to(m)

      
    
# 9.7. RENDERIZADO DE POZOS EN EL MAPA PRINCIPAL  ___________________________________________________________________________________________________________________________________

if ver_pozos:  
    fg_pozos = folium.FeatureGroup(name="Pozos", overlay=True, control=True)

    for id_p, info in mapa_pozos_dict.items():
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

        # ==========================================
        # AQUÍ VA LA VALIDACIÓN TOLERANTE CON/SIN GUION
        # ==========================================
        id_p_limpio = str(id_p).strip().upper()
        
        # Generar posibles variantes con o sin guion y con sufijos de letra (ej. P087A / P-087A)
        id_p_con_guion = re.sub(r'^([A-Z]+)(\d+)([A-Z]*)$', r'\1-\2\3', id_p_limpio)
        id_p_sin_guion = id_p_limpio.replace('-', '')
        
        tiene_incidencia_activa = (
            id_p_limpio in dic_incidencias_activas or 
            id_p_con_guion in dic_incidencias_activas or 
            id_p_sin_guion in dic_incidencias_activas
        )

        rol_actual = st.session_state.get('rol', 'usuario')
        nombre_codificado = urllib.parse.quote(id_p)
        
        url_pozo_graf = f"?graficar_pozo={id_p}&nombre={nombre_codificado}&access=granted&role={rol_actual}"

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
                    <div style="font-size: 10px; color: #888; margin-bottom: 4px; border-top: 1px solid #222; paddingTop: 5px;">HORARIOS</div>
                    <div style="display: flex; align-items: baseline; font-size: 11px; margin-bottom: 3px;">
                        <span>▶️ Arranque: <b>{h_arr_fmt}</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_arr}</span>
                    </div>
                    <div style="display: flex; align-items: baseline; font-size: 11px;">
                        <span>⏹️ Paro: <b>{h_par_fmt}</b></span>
                        <span style="color: #FFFF00; font-size: 8px; margin-left: auto;">{f_h_par}</span>
                    </div>

                    <div style="border-top: 1px solid #333; padding-top: 10px;">
                    <a href="{url_pozo_graf}" target="_blank" style="text-decoration: none;">
                        <div style="background: #00d4ff; color: #050a10; text-align: center; padding: 10px; border-radius: 6px; font-weight: bold; font-size: 12px;">
                            📊 VER ANÁLISIS HISTÓRICO
                        </div>
                    </a>
                </div>
            </div>
            """

        # 1. Etiqueta de texto del pozo
        folium.Marker(
            location=info['coord'],
            icon=folium.DivIcon(
                icon_size=(150,36),
                icon_anchor=(-12, 10),
                html=f'<div style="font-size: 9px; font-weight: bold; color: {info["color_final"]}; white-space: nowrap; text-shadow: 1px 1px #000; pointer-events: none;">{id_p}</div>'
            )
        ).add_to(fg_pozos)

        # ==========================================
        # 2. MARCADOR CON LÍNEA EN EL POZO + LISTA EN EL PANEL
        # ==========================================
        if tiene_incidencia_activa:
            info_incidencia = (
                dic_incidencias_activas.get(id_p_limpio) or 
                dic_incidencias_activas.get(id_p_con_guion) or 
                dic_incidencias_activas.get(id_p_sin_guion, {})
            )
            
            if isinstance(info_incidencia, dict):
                diagnostico_falla = info_incidencia.get('diagnostico', info_incidencia.get('motivo', 'FALLA'))
            else:
                diagnostico_falla = str(info_incidencia)
            
            # 1. MANTENEMOS LA LÍNEA Y EL PUNTO EXACTO EN EL POZO (sin el texto al lado)
            html_solo_linea = f"""
            <div style="position: relative; width: 40px; height: 60px; pointer-events: none;">
                <svg style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: visible;">
                    <!-- Línea pequeña que sale del pozo hacia arriba a la derecha -->
                    <line x1="15" y1="45" x2="30" y2="20" stroke="#ff4d4d" stroke-width="2" />
                    <!-- Puntito blanco exacto sobre la coordenada del pozo -->
                    <circle cx="15" cy="45" r="4" fill="#ffffff" stroke="#ff4d4d" stroke-width="2" />
                </svg>
            </div>
            """
            
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(
                    icon_size=(40, 60),
                    icon_anchor=(15, 45),  # Ancla exacta en el punto del pozo
                    html=html_solo_linea
                ),
                popup=folium.Popup(html_popup, max_width=450),
                tooltip=f"⚠️ POZO {id_p} - {diagnostico_falla}"
            ).add_to(fg_pozos)
            
            # 2. ENVIAMOS EL CUADRO DE INCIDENCIA AL PANEL FIJO DE LA DERECHA/ABAJO
            item_html = f"""
            <div style="background: #111; margin-bottom: 6px; padding: 6px 8px; border-radius: 4px; border-left: 3px solid #ff4d4d; display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <span style="font-size: 11px; font-weight: bold; color: #ffffff; margin-right: 8px;">{id_p}</span>
                    <span style="font-size: 10px; font-weight: bold; color: #ffffff; background: #c0392b; padding: 2px 5px; border-radius: 3px;">{diagnostico_falla.upper()}</span>
                </div>
            </div>
            """
            script_add_incidencia = f"""
            document.getElementById('lista_incidencias').innerHTML += `{item_html}`;
            """
            mapa.get_root().html.add_child(folium.Element(f"<script>{script_add_incidencia}</script>"))
            
        elif info.get('blink'):
            folium.Marker(
                location=info['coord'],
                icon=folium.DivIcon(html=get_blink_icon(info['color_final'])),
                popup=folium.Popup(html_popup, max_width=450)
            ).add_to(fg_pozos)
        else:
            folium.CircleMarker(
                location=info['coord'],
                radius=4,
                color=info['color_final'],
                fill=True,
                fill_color=info['color_final'],
                fill_opacity=1,
                popup=folium.Popup(html_popup, max_width=450)
            ).add_to(fg_pozos)

    fg_pozos.add_to(m)
          

# 9.8. RENDERIZADO DE TANQUES EN EL MAPA PRINCIPAL ________________________________________________________________________________________________________________________________
    if ver_tanques:
        for id_tq, info in mapa_tanques_dict.items():
            try:
                val_nivel, fecha_tq = data_scada.get(info['tag_nivel'], (0, "N/A"))
                n_max = info['nivel_max'] if info['nivel_max'] else 1.0
                porcentaje = (val_nivel / n_max) * 100
                
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
            
# 9.9.  RENDERIZADO DE REBOMBEOS EN EL MAPA PRINCIPAL ___________________________________________________________________________________________________________________
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
                MousePosition().add_to(m_sec)

# 9.10. RENDERIZADO DE MACROMEDIDORES EN EL MAPA PRINCIPAL ___________________________________________________________________________________________________________________
    if ver_macromedidores:
        from datetime import datetime, timedelta
        datos_macromedidores = cargar_medidores_desde_db()
        fecha_limite = datetime.now() - timedelta(days=5)

        for id_mm, info in datos_macromedidores.items():
            # --- FILTRO ---
            if str(id_mm) == '1000' or info.get('nombre') == 'Sin instalar':
                continue

            # --- LÓGICA DE ESTADO Y COLOR ---
            es_falla = info['ultima_fecha'] < fecha_limite
            
            color_borde = '#FF0000' if es_falla else '#B19CD9'
            color_relleno = '#8B0000' if es_falla else '#800080'
            color_popup = '#FF0000' if es_falla else '#800080'
            clase_animacion = "pulsante" if es_falla else ""

            try:
                # Recuperamos la lógica completa del botón de gráfico
                url_pestaña = f"?ver_grafico={id_mm}&nombre={info.get('nombre', 'Medidor').replace(' ', '%20')}&access=granted&role={st.session_state.get('rol', 'usuario')}"
                
                html_popup_mm = f"""
                <div style="background: #050505; color: white; padding: 12px; border-radius: 10px; width: 220px; border: 2px solid {color_popup}; font-family: sans-serif;">
                    <b style="color: {color_popup}; font-size: 14px;">MACROMEDIDOR: {id_mm}</b>
                    <hr style="border: 0.5px solid #333; margin: 8px 0;">
                    <div style="font-size: 12px;">
                        📍 Nombre: <b>{info.get('nombre', 'N/A')}</b><br>
                        📡 Última transmisión: <b>{info['ultima_fecha'].strftime('%Y-%m-%d')}</b>
                    </div>
                    <div style="margin-top: 10px; text-align: center;">
                        <a href="{url_pestaña}" target="_blank" style="background-color: {color_popup}; color: white; padding: 8px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 11px; display: inline-block; width: 90%;">📊 ABRIR GRÁFICO</a>
                    </div>
                </div>
                """
                
                # SVG con la clase de parpadeo (pulsante)
                html_svg = f"""
                <svg width="20" height="20" class="{clase_animacion}">
                    <circle cx="10" cy="10" r="6" stroke="{color_borde}" stroke-width="2" fill="{color_relleno}" fill-opacity="0.9" />
                </svg>
                """
                
                # Punto principal
                folium.Marker(
                    location=info['coord'],
                    icon=folium.DivIcon(icon_size=(20, 20), icon_anchor=(10, 10), html=html_svg),
                    popup=folium.Popup(html_popup_mm, max_width=300)
                ).add_to(m)
                
                # Texto combinado: ID y Nombre
                color_texto = "#FF4C4C" if es_falla else "#FFFFFF"
                html_etiqueta = f"""
                <div style="font-size: 11px; font-weight: bold; color: {color_texto}; text-shadow: 1px 1px #000; white-space: nowrap;">
                    {id_mm} - {info.get('nombre', 'N/A')}
                </div>
                """
                
                folium.Marker(
                    location=info['coord'], 
                    icon=folium.DivIcon(icon_anchor=(-15, 10), html=html_etiqueta)
                ).add_to(m)
                
            except Exception as e:
                continue



    # 9.11. CONTROL DE CAPAS Y RENDERIZADO FINAL 
    folium.LayerControl(position='topright', collapsed=False).add_to(m)
    folium_static(m, width=None, height=600)

    # --- % DE AFECTACIONES POR COLONIAS ---
    st.markdown("##### 🗺️ % de Afectación en Colonias")
    
    col_l1, col_l2, col_l3, col_l4, col_l5 = st.columns(5)
    
    with col_l1:
        st.markdown(
            '<div style="background-color: #FF0000; padding: 8px; border-radius: 5px; text-align: center; color: white; font-weight: bold; font-size: 14px;">76% - 100%<br><span style="font-size: 11px;">Rojo (Crítico)</span></div>', 
            unsafe_allow_html=True
        )
    with col_l2:
        st.markdown(
            '<div style="background-color: #FFFF00; padding: 8px; border-radius: 5px; text-align: center; color: black; font-weight: bold; font-size: 14px;">51% - 75%<br><span style="font-size: 11px;">Amarillo (Alto)</span></div>', 
            unsafe_allow_html=True
        )
    with col_l3:
        st.markdown(
            '<div style="background-color: #FFA500; padding: 8px; border-radius: 5px; text-align: center; color: black; font-weight: bold; font-size: 14px;">31% - 50%<br><span style="font-size: 11px;">Naranja (Moderado)</span></div>', 
            unsafe_allow_html=True
        )
    with col_l4:
        st.markdown(
            '<div style="background-color: #69ADDD; padding: 8px; border-radius: 5px; text-align: center; color: black; font-weight: bold; font-size: 14px;">1% - 30%<br><span style="font-size: 11px;">Azul Claro (Leve)</span></div>', 
            unsafe_allow_html=True
        )
    with col_l5:
        st.markdown(
            '<div style="background-color: #3498DB; padding: 8px; border-radius: 5px; text-align: center; color: white; font-weight: bold; font-size: 14px;">0%<br><span style="font-size: 11px;">Normal / Sin Afectación</span></div>', 
            unsafe_allow_html=True
        )

    

    # ---------------------------------------------------------------------------- FINAL DEL MAPA -------------------------------------------------------------------------------------------
