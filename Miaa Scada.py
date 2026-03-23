import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import urllib.parse
import datetime as dt

# 1. CONFIGURACIÓN
st.set_page_config(page_title="MIAA - RELIEVE 3D", layout="wide")

# 2. CARGA DE DATOS (Mantenemos tu lógica eficiente)
@st.cache_resource
def get_engine():
    c = st.secrets["mysql_telemetria"]
    pwd = urllib.parse.quote_plus(c["password"])
    return create_engine(f"mysql+mysqlconnector://{c['user']}:{pwd}@{c['host']}/{c['database']}")

def cargar_pozos():
    engine = get_engine()
    df = pd.read_sql("SELECT Pozos, coord, bomba FROM Diccionario_de_pozos", engine)
    def extraer(c):
        try:
            p = str(c).replace('(','').replace(')','').split(',')
            return float(p[0]), float(p[1])
        except: return None, None
    df['lat'], df['lon'] = zip(*df['coord'].apply(extraer))
    return df.dropna()

df_p = cargar_pozos()

# 3. INTERFAZ 3D (CESIUM / MAPBOX 3D)
st.markdown(f'<h2 style="text-align:center; color:#00d4ff;">SISTEMA MIAA - RELIEVE 3D REAL</h2>', unsafe_allow_html=True)

# Creamos un HTML con Mapbox GL JS que SÍ fuerza el relieve 3D sin errores de Pydeck
# Nota: Mapbox GL JS v2+ requiere un token. Si no tienes uno, este visor usa el relieve base.
mapbox_token = st.secrets.get("mapbox_token", "pk.eyJ1IjoibWlhYS1hZ3MiLCJhIjoiY2x0eXJ0Z3R6MWZqdjJpbW52Z3RneXByMiJ9.example") 

html_mapa = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Relieve 3D MIAA</title>
<meta name="viewport" content="initial-scale=1,maximum-scale=1,user-scalable=no">
<link href="https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.css" rel="stylesheet">
<script src="https://api.mapbox.com/mapbox-gl-js/v2.15.0/mapbox-gl.js"></script>
<style>
body {{ margin: 0; padding: 0; }}
#map {{ position: absolute; top: 0; bottom: 0; width: 100%; background: #000; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
	mapboxgl.accessToken = '{mapbox_token}';
    const map = new mapboxgl.Map({{
        container: 'map',
        style: 'mapbox://styles/mapbox/satellite-streets-v11',
        center: [-102.291, 21.882],
        zoom: 13,
        pitch: 65,
        bearing: -20,
        antialias: true
    }});

    map.on('style.load', () => {{
        // ACTIVAR EL RELIEVE 3D
        map.addSource('mapbox-dem', {{
            'type': 'raster-dem',
            'url': 'mapbox://mapbox.mapbox-terrain-dem-v1',
            'tileSize': 512,
            'maxzoom': 14
        }});
        map.setTerrain({{ 'source': 'mapbox-dem', 'exaggeration': 1.5 }});

        // AÑADIR LOS POZOS COMO PUNTOS 3D
        const pozos = {df_p.to_json(orient='records')};
        
        pozos.forEach(p => {{
            const el = document.createElement('div');
            el.className = 'marker';
            el.style.width = '12px';
            el.style.height = '12px';
            el.style.backgroundColor = '#00FF00';
            el.style.borderRadius = '50%';
            el.style.boxShadow = '0 0 10px #00FF00';

            new mapboxgl.Marker(el)
                .setLngLat([p.lon, p.lat])
                .setPopup(new mapboxgl.Popup({{ offset: 25 }}).setHTML('<h3>' + p.Pozos + '</h3>'))
                .addTo(map);
        }});
    }});
</script>
</body>
</html>
"""

# Renderizar el mapa en Streamlit
st.components.v1.html(html_mapa, height=800)

with st.sidebar:
    st.image("https://raw.githubusercontent.com/Miaa-Aguascalientes/Lecturas-Hes/c45d926ef0e34215c237cd3c7f71f7b97bf9a784/LogoMIAA-BpcVaQaq.svg")
    st.info("Usa Click Derecho para rotar e inclinar el mapa y ver las montañas.")
