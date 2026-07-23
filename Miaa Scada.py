import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from folium.plugins import Fullscreen
from sqlalchemy import create_engine, event
import psycopg2
import json
import urllib.parse
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import time
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
from plotly.subplots import make_subplots
import plotly.express as px

# 1. CONFIGURACIÓN DE PÁGINA
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

# 2. FUNCIONES DE CONEXIÓN

@st.cache_resource
def get_mysql_scada_engine():
    try:
        c = st.secrets["mysql_scada"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")
        
        @event.listens_for(engine, "connect")
        def set_big_selects(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET SESSION SQL_BIG_SELECTS=1;")
            cursor.close()
        
        with engine.connect() as conn: pass 
        return engine
    except Exception as e:
        st.error(f"Error al conectar a la BD: {e}")
        return None

@st.cache_resource
def get_mysql_telemetria_engine():
    try:
        c = st.secrets["mysql_telemetria"]
        pwd = urllib.parse.quote_plus(c["password"])
        engine = create_engine(
            f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}",
            pool_recycle=3600,
            pool_pre_ping=True
        )
        with engine.connect() as conn: pass 
        return engine
    except Exception as e:
        st.error(f"⚠️ ERROR CRÍTICO DE CONEXIÓN: {e}")
        return None

@st.cache_resource
def get_postgres_conn():
    try: 
        conn = psycopg2.connect(**st.secrets["postgres"])
        return conn
    except Exception as e: 
        st.error(f"Error de conexión Postgres: {e}")
        return None
        
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
        
@st.cache_data(ttl=3600)
def cargar_sectores_poligonos():
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
        df = pd.read_sql(query, conn)
        return df.to_dict('records')
    except Exception as e:
        st.error(f"Error al cargar sectores: {e}")
        return []
    finally:
        if conn:
            conn.close()

@st.cache_data(ttl=3600)
def get_todas_las_colonias():
    query = "SELECT ST_AsText(geom) as geom_wkt, Pozos, Col_atl, Sector, Distrito, Supervisor FROM Diccionario_colonias"
    try:
        df = pd.read_sql(query, get_mysql_telemetria_engine())
        if not df.empty:
            df['geometry'] = df['geom_wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs(epsg=32613, inplace=True)
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        st.error(f"Error cargando polígonos: {e}")
    return None

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

# 3. CARGA DE DATOS DE DICCIONARIOS

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
                    "Serie": str(id_reg_val) 
                }
            except Exception as e:
                continue
        return d_res
    except Exception as e:
        return {}

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
                
                d_res[str(id_reg)] = {
                    "nombre": str(r.get('Colonia', 'S/C')), 
                    "Domicilio": str(r.get('Domicilio', 'Sin Domicilio')), 
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
                id_val = r.get('Serie', 'ID_VRP')
                
                d_res[str(id_val)] = {
                    "nombre": str(r.get('Domicilio', 'S/N')),
                    "coord": [float(lat_s), float(lon_s)],
                    "sector": str(r['Sector']).split('.')[0].strip(),
                    "tag_p1": r.get('Presion_1'),
                    "tag_p2": r.get('Presion_2'),
                    "tag_q": r.get('Caudal'),
                    "Serie": str(id_val)
                }
            except: continue
        return d_res
    except: return {}

@st.cache_data(ttl=3600)
def cargar_medidores_desde_db():
    engine = get_mysql_telemetria_engine()
    if not engine: return {}
    try:
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
                "ultima_fecha": pd.to_datetime(row['UltimaFecha'])
            }
        return datos_medidores
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return {}
        
@st.cache_data(ttl=60)
def get_data():
    engine = get_mysql_scada_engine()
    if engine is None:
        st.error("No se pudo establecer conexión.")
        return pd.DataFrame()
    try:
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
        
@st.cache_data(ttl=60)
def get_diccionario_completo():
    try:
        query = "SELECT Pozos, Col_atl, Sector, Distrito, Supervisor, ST_AsText(geom) as geom_wkt FROM Diccionario_colonias"
        return pd.read_sql(query, get_mysql_telemetria_engine())
    except Exception as e:
        st.error(f"Error en get_diccionario_colonias: {e}")
        return pd.DataFrame()
        
@st.cache_data(ttl=60)
def get_geometries(num_pozo):
    numero_limpio = re.sub(r'\D', '', str(num_pozo))
    busqueda = numero_limpio if numero_limpio else str(num_pozo)
    
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
            return gdf.to_crs(epsg=4326)
    except Exception as e:
        st.error(f"Error en BD: {e}")
    return None

# 4. GRAFICAR LOS TANQUES EN EL POPUP
tag_a_graficar = params.get("graficar_tanque", None)
nombre_tq = params.get("nombre", "Tanque")

if tag_a_graficar:
    import datetime
    
    st.title(f"📊 Análisis de Nivel: {nombre_tq}")
    
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        opcion_fecha = st.selectbox(
            "Selecciona un rango:",
            ["Hoy", "Esta Semana", "Últimos 14 días", "Este Mes", "Personalizado"],
            index=3,
            key="pop_selector_final_v8"
        )

    hoy = datetime.date.today()
    
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
            
            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=df_hist['FECHA'],
                y=df_hist['VALUE'],
                mode='lines+markers',
                line=dict(color='#00d4ff', width=2),
                marker=dict(size=4, color='#00d4ff'),
                fill='tozeroy',
                fillcolor='rgba(0, 212, 255, 0.2)',
                hovertemplate="<b>%{y:.2f} m</b><extra></extra>"
            ))

            dias_es = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
            meses_es = {1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun', 
                        7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'}
            fechas_lineas = pd.date_range(start=fecha_inicio, end=fecha_fin, freq='D')

            num_dias = len(fechas_lineas)
            paso = 2 if num_dias > 15 and num_dias <= 30 else (5 if num_dias > 30 else 1)
            
            ticks_filtrados = fechas_lineas[::paso]

            etiquetas_filtradas = [
                f"{d.strftime('%H:%M')}<br>{dias_es[d.dayofweek]} {d.day}-{meses_es[d.month]}-{d.year}"
                for d in ticks_filtrados
            ]

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
                delta = pd.Timedelta(hours=1)
                
                fig.add_vrect(
                    x0=dia - delta,
                    x1=dia + delta,
                    fillcolor="gray",
                    opacity=0.2,
                    layer="below",
                    line_width=0
                )
                
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

# 5. GRAFICAR LOS POZOS
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
    medianoche = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    f_fin = hoy_dt

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

            if df.empty:
                st.warning(f"⚠️ No hay registros disponibles para el rango seleccionado.")
            else:
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
                        res_meses['produccion_neta'] = res_meses['VALUE'].shift(-1) - res_meses['VALUE']
                        
                        nombres_meses = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
                        res_meses['Mes_Txt'] = res_meses['mes'].map(nombres_meses)

                        curr_year = datetime.now().year
                        res_meses = res_meses[res_meses['anio'].isin([curr_year, curr_year - 1])]
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

                    def traducir_fecha(d):
                        dia_nom = dias_es.get(d.strftime('%a'), d.strftime('%a'))
                        mes_nom = meses_es.get(d.strftime('%b'), d.strftime('%b'))
                        return f"{dia_nom} {d.day}-{mes_nom} {d.strftime('%H:%M:%S')}"

                    dft_l['HORA_TRADUCIDA'] = dft_l['FECHA'].apply(traducir_fecha)
                    
                    df_tag_maestro = pd.merge_asof(
                        df_interactivo, 
                        dft_l, 
                        left_on='FECHA_INDEX', 
                        right_on='FECHA', 
                        direction='backward'
                    )
                    df_tag_maestro['VALUE'] = df_tag_maestro['VALUE'].bfill()
                    df_tag_maestro['HORA_TRADUCIDA'] = df_tag_maestro['HORA_TRADUCIDA'].bfill()
                    
                    fig_line.add_trace(
                        go.Scatter(
                            x=df_interactivo['FECHA_INDEX'],
                            y=df_tag_maestro['VALUE'],
                            name=t['label'],
                            mode='lines',
                            line=dict(color=t['color'], width=0.01), 
                            yaxis=t['axis'],
                            showlegend=False,
                            customdata=df_tag_maestro['HORA_TRADUCIDA'].tolist(),
                            hovertext=df_tag_maestro['VALUE'].tolist(),
                            hovertemplate=f"<span style='color:{t['color']};'>■</span> <b>{t['label']}</b>: %{{hovertext:,.2f}} <span style='color:#888; font-size:11px;'>(%{{customdata}})</span><extra></extra>",
                            hoverlabel=dict(
                                bordercolor=t['color']
                            )
                        )
                    )

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

                delta = pd.Timedelta(hours=0.15)
                for d in fechas_lineas:
                    es_lunes = (d.dayofweek == 0)
                    
                    fig_line.add_vrect(
                        x0=d - delta,
                        x1=d + delta,
                        fillcolor="gray",
                        opacity=0.2,
                        layer="below",
                        line_width=0
                    )
                    
                    fig_line.add_vline(
                        x=d, 
                        line_width=1.5, 
                        line_dash="dash", 
                        line_color="#fffb00" if es_lunes else "white",
                        opacity=0.5,
                        layer="above"
                    )

                fig_line.update_layout(
                    template="plotly_dark", 
                    height=580, 
                    paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(0,0,0,0)', 
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
                        tickformatstops=[
                            dict(dtickrange=[None, 86400000], value="%H:%M <br>%A %d-%b-%Y"),
                            dict(dtickrange=[86400000, 604800000], value="%H:%M <br>%A %d-%b-%Y"),
                            dict(dtickrange=[604800000, None], value="%H:%M <br>%d-%b-%Y")
                        ]
                    ),
                    yaxis5=dict(
                        title=dict(text="<b>Nivel Tanque (m)</b>", font=dict(color="#00ffcc")), 
                        tickfont=dict(color="#00ffcc"), 
                        side="left", overlaying="y", anchor="free", position=0.00,
                        showline=True, linecolor='white', linewidth=1.5
                    ),
                    yaxis=dict(
                        title=dict(text="<b>Caudal (Lps)</b>", font=dict(color="#00d4ff")), 
                        tickfont=dict(color="#00d4ff"),
                        side="left", anchor="free", position=0.07,
                        showline=True, linecolor='white', linewidth=1.5
                    ),
                    yaxis2=dict(
                        title=dict(text="<b>Presión (Kg/cm²)</b>", font=dict(color="#00ff00")), 
                        tickfont=dict(color="#00ff00"), 
                        side="right", overlaying="y", anchor="free", position=0.92,
                        showline=True, linecolor='white', linewidth=1.5
                    ),
                    yaxis3=dict(
                        title=dict(text="<b>Niveles Pozo (m)</b>", font=dict(color="#ff00b4")), 
                        tickfont=dict(color="#ff00b4"), 
                        side="right", overlaying="y", anchor="free", position=0.955,
                        showline=True, linecolor='white', linewidth=1.5
                    ),
                    yaxis4=dict(
                        title=dict(text="<b>Eléctricos (V / A)</b>", font=dict(color="#ff8000")), 
                        tickfont=dict(color="#ff8000"), 
                        side="right", overlaying="y", anchor="free", position=1.00,
                        showline=True, linecolor='white', linewidth=1.5,
                        rangemode="tozero"
                    )
                )
                st.plotly_chart(fig_line, use_container_width=True)

                if not df.empty:
                    mask_caudal = df['TagName'].str.contains('CAU_INS', na=False)
                    df.loc[mask_caudal & (df['VALUE'] < 0), 'VALUE'] = None
                    df.loc[mask_caudal & (df['VALUE'] > 100), 'VALUE'] = None
                    
                    df_pivot = df.pivot(index='FECHA', columns='TagName', values='VALUE')
                    df_pivot = df_pivot.ffill().reset_index()
                    
                    csv_data = df_pivot.to_csv(index=False).encode('utf-8')
                    
                    st.download_button(
                        label="📥 Descargar datos del grafico",
                        data=csv_data,
                        file_name=f"Datos_{nombre_pozo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
        except Exception as e: 
            st.error(f"Error: {e}")
            
    st.stop()

# 6. GRAFICAR LOS MACROMEDIDORES
if "ver_grafico" in st.query_params:
    st.set_page_config(layout="wide", page_title="Miaa - Macromedidores")

    tag_a_graficar = st.query_params.get("ver_grafico")
    nombre_mm = st.query_params.get("nombre")

    engine = get_mysql_telemetria_engine()
    hoy_dt = datetime.now()
    medianoche = hoy_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
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
    info = df_info.iloc[0] if not df_info.empty else {"Nombre": "N/A", "Domicilio": "N/A", "Colonia": "N/A", "Diametro": "N/A"}

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
            <div style="display: flex; gap: 20px; font-size: 12px; color: #c9d1d9; border-left: 2px solid #00FFFF; padding-left: 15px; align-items: center;">
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

    col_sel, col_ind, col_btn = st.columns([2.0, 0.5, 6.0])

    with col_sel:
        st.markdown('<div style="margin-top: 26px;"></div>', unsafe_allow_html=True)
        opcion_fecha = st.selectbox("rango", 
            ["Hoy", "Ayer", "Últimos 7 días", "Últimos 14 días", "Este Mes", "Último Mes", "Últimos 6 meses", "Personalizado"],
            index=4, label_visibility="collapsed", key="selector_fechas_unico")

    f_fin = hoy_dt
    if opcion_fecha == "Hoy": f_ini = medianoche
    elif opcion_fecha == "Ayer": f_ini, f_fin = medianoche - timedelta(days=1), medianoche - timedelta(seconds=1)
    elif opcion_fecha == "Últimos 7 días": f_ini = medianoche - timedelta(days=7)
    elif opcion_fecha == "Últimos 14 días": f_ini = medianoche - timedelta(days=14)
    elif opcion_fecha == "Este Mes": f_ini = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif opcion_fecha == "Último Mes":
        primer_dia = hoy_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        f_fin = primer_dia - timedelta(seconds=1)
        f_ini = (primer_dia.replace(day=1) - timedelta(days=1)).replace(day=1)
    elif opcion_fecha == "Últimos 6 meses": f_ini = medianoche - timedelta(days=180)
    else: 
        rango = st.date_input("Periodo:", value=(hoy_dt.date() - timedelta(days=7), hoy_dt.date()))
        f_ini, f_fin = datetime.combine(rango[0], datetime.min.time()), datetime.combine(rango[1], datetime.max.time())

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

    with col_btn:
        st.markdown('<div style="margin-top: 26px;"></div>', unsafe_allow_html=True)
        c_b1, c_b2 = st.columns(2)
        if not df.empty:
            with c_b1:
                st.download_button("📥 Exportar datos de caudal (lps) y presión (kg/cm²)", df.to_csv(index=False).encode('utf-8'), "datos.csv", "text/csv", use_container_width=True)
            with c_b2:
                st.download_button("📊 Exportar datos de consumo (m³)", df_diario_exp.to_csv(index=False).encode('utf-8'), "consumo.csv", "text/csv", use_container_width=True)
        else:
            with c_b1: st.button("📥", disabled=True)
            with c_b2: st.button("📊", disabled=True)

    placeholder_indicadores = st.empty()

    if not df.empty:
        avg_caudal = df['Flujo'].mean()
        avg_presion = df['Presion'].mean()
        
        df_diario_calc = df.copy()
        df_diario_calc['FECHA'] = pd.to_datetime(df_diario_calc['FECHA']).dt.date
        total_consumo = df_diario_calc.groupby('FECHA')['Consumo'].sum().sum()
        
        entera = int(total_consumo)
        decimal = int(round((total_consumo - entera) * 100))
        consumo_fmt = f"{entera:,d}.{decimal:02d}".replace(",", "X").replace(".", ",").replace("X", ".")

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
                        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(go.Scatter(
            x=df['FECHA'], y=df['Flujo'],
            name="Caudal (Lps)",
            mode='lines+markers',
            marker=dict(size=5),
            line=dict(color='#00FFFF', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 255, 255, 0.2)',
            hovertemplate="%{y:.2f} Lps<extra></extra>"
        ), secondary_y=False)
        
        fig.add_trace(go.Scatter(
            x=df['FECHA'], y=df['Presion'],
            name="Presión (Kg/cm²)",
            mode='lines+markers',
            marker=dict(size=5),
            line=dict(color='#00FF00', width=2),
            hovertemplate="%{y:.2f} Kg/cm²<extra></extra>"
        ), secondary_y=True)

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

        delta = timedelta(hours=1)
        for d in fechas_lineas:
            es_lunes = (d.dayofweek == 0)

            fig.add_vrect(
                x0=d - delta,
                x1=d + delta,
                fillcolor="gray",
                opacity=0.2,
                layer="below",
                line_width=0)

            fig.add_vline(
                x=d, line_width=1.5,
                line_dash="dash", 
                line_color="#fffb00" if es_lunes else "white", 
                opacity=0.5, 
                layer="above")

        fig.update_layout(
            height=400, 
            template="plotly_dark",
            hovermode="x unified",
            xaxis=dict(
                rangeslider=dict(visible=True, thickness=0.10),
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
            xaxis=dict(tickmode='linear', title=None), yaxis=dict(title="Consumo (m³)"),
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
        placeholder_indicadores.empty()
        st.warning("No hay datos registrados en este rango.")

    st.stop()

# ESTILOS CSS GENERALES
st.markdown("""
    <style>
        [data-testid="collapsedControl"], button[kind="headerNoPadding"], [data-testid="stSidebarCollapseButton"] {
            display: none !important;
        }
        header { visibility: hidden !important; height: 0px !important; }
        .stApp { background-color: #000000; color: white; }
        
        .block-container {
            padding-top: 0rem !important;
            margin-top: 15px !important;
            max-width: 100% !important;
        }

        .mapa-area iframe { 
            margin-top: 90px !important;
            border: 1px solid #1f4068 !important;
            height: 85vh !important;
        }

        .mapa-area [data-testid="column"] {
            flex: 1 1 0% !important;
        }

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
            background-color: #000000;
            width: 100%;
            text-align: center;
            padding: 10px 0;
            border-bottom: 1px solid #1f4068;
        }

        .contenedor-indicadores {
           position: fixed;
           top: 65px; 
           left: 320px;
           right: 0;
           display: flex;
           justify-content: center;
           align-items: center;
           gap: 15px;
           z-index: 1001;
           background: transparent;
           padding: 0 15px;
         }

        .card-indicador {
           flex: 1;
           border: 1px solid #1f4068; 
           background: linear-gradient(180deg, rgba(11, 26, 41, 0.95) 0%, rgba(0, 0, 0, 1) 100%);
           padding: 8px 5px;
           text-align: center;
           border-radius: 10px;
           box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.5);
        }
        .card-indicador:first-child { border-left: 1px solid #1f4068; }

        .card-label { color: #888888; font-size: 0.7rem; font-weight: bold; text-transform: uppercase; margin: 0; }
        .card-value { font-family: 'Courier New', monospace; font-size: 1.5rem; font-weight: bold; margin: 0; }
        
        .val-on { color: #00ff00; text-shadow: 0 0 8px rgba(0, 255, 0, 0.5); }
        .val-off { color: #ff0000; text-shadow: 0 0 8px rgba(255, 0, 0, 0.5); }
        .val-falla { color: #ffaa00; text-shadow: 0 0 8px rgba(255, 170, 0, 0.5); }
        .val-sin { color: #ffffff; }

        .mapa-principal-ajuste {
            margin-top: -200px !important;
            z-index: 1;
        }
        .mapa-principal-ajuste iframe {
            border: 1px solid #1f4068 !important;
            border-top: none !important;
        }

        [data-testid="stSidebarContent"] {
            padding-top: 3px !important; 
        }

        [data-testid="stSidebar"] { 
            background-color: #0b1a29 !important; 
            border-right: 2px solid #1f4068; 
        }

       .sidebar-logo { 
           position: fixed; 
           top: 20px; 
           left: 40px; 
           width: 170px;  
           height: 50px;  
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
    </style>
""", unsafe_allow_html=True)
