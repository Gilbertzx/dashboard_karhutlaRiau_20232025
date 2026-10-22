"""Dashboard Area Terbakar & Estimasi Karbon - Provinsi Riau 2023-2025.

Fitur: ringkasan beserta perubahan dibanding tahun sebelumnya, peta warna (choropleth) per kabupaten/kota,
perbandingan dua tahun berdampingan, grafik batang luas per kabupaten/kota, dan pemilihan kabupaten/kota dengan
klik pada peta atau grafik sehingga angka ringkasan menampilkan kabupaten/kota tersebut.
Membaca data di folder dashboard_data/ (summary.csv dan kabkota.csv berisi angka per kejadian).

Agar cepat: peta dasar dibuat identik di setiap putaran sehingga tidak digambar ulang di browser; sorotan
kabupaten/kota terpilih dikirim sebagai lapisan tambahan dan perpindahan zoom memakai center/zoom st_folium;
seluruh lingkaran penanda digambar dari satu larik data; klik ditangani lewat callback sehingga satu klik cukup
satu kali menjalankan halaman.
"""
import json
import math
from pathlib import Path

import altair as alt
import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from branca.element import MacroElement
from folium.plugins import DualMap
from folium.template import Template
from shapely.geometry import Point, shape
from shapely.prepared import prep
from streamlit_folium import st_folium

DATA = Path(__file__).parent / "dashboard_data"
st.set_page_config(page_title="Kebakaran Hutan Riau", page_icon="🔥", layout="wide")

# Latar halaman krem lembut; bilah atas Streamlit dibuat transparan. Peta diberi bingkai seperti kartu: garis tipis,
# sudut membulat, bayangan sangat tipis, dan isi sedikit lebih terang dari halaman.
LATAR = "#faf7f2"
LATAR_PETA = "#fffdfa"
st.markdown(f"<style>[data-testid='stApp']{{background:{LATAR};}}"
            "[data-testid='stHeader']{background:transparent;}"
            "iframe[title='streamlit_folium.st_folium']{border:1px solid #e9e2d7;border-radius:14px;"
            f"background:{LATAR_PETA};"
            "box-shadow:0 1px 2px rgba(60,40,20,.04),0 8px 24px rgba(60,40,20,.05);}</style>",
            unsafe_allow_html=True)


def angka(x, d=0):
    """Format angka Indonesia: 1.234,56"""
    return f"{x:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


# Format angka Indonesia untuk sumbu grafik Vega-Lite (1,234 -> 1.234)
SUMBU_ID = "replace(format(datum.value, ',.0f'), /,/g, '.')"


# ---------- Data ----------
@st.cache_data
def load_data():
    read = lambda name: json.loads((DATA / name).read_text(encoding="utf-8"))
    summary = pd.read_csv(DATA / "summary.csv", dtype={"tahun": str})
    kabkota = pd.read_csv(DATA / "kabkota.csv", dtype={"tahun": str})
    years = [t for t in summary["tahun"] if t != "Semua tahun"]
    burns = {t: read(f"burn_{t}.geojson") for t in years}
    return (read("riau_provinsi.geojson"), read("riau_kabupaten.geojson"), burns, summary, kabkota, years,
            read("peta.json"))


for f in ("summary.csv", "kabkota.csv"):
    if not (DATA / f).exists():
        st.error(f"File dashboard_data/{f} belum ada.")
        st.stop()
riau, kabupaten, burns, summary, kabkota, years, pusat = load_data()
ringkas = summary.set_index("tahun")


def batas(geom):
    """Kotak batas [[lat_min, lon_min], [lat_max, lon_max]] dari geometri GeoJSON."""
    xs, ys = [], []

    def jelajah(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for k in c:
                jelajah(k)
    jelajah(geom["coordinates"])
    return [[min(ys), min(xs)], [max(ys), max(xs)]]


GEO_KAB = {f["properties"]["kabupaten"]: f for f in kabupaten["features"]}
BATAS_KAB = {n: batas(f["geometry"]) for n, f in GEO_KAB.items()}
DAFTAR_KAB = sorted(BATAS_KAB)
KAB_SEMUA = "Seluruh Riau"
TINGGI_PETA = 620
TINGGI_GANDA = 560


@st.cache_resource
def bentuk_kab():
    return {n: prep(shape(f["geometry"])) for n, f in GEO_KAB.items()}


def tampilan_kab(nama, lebar=1100, tinggi=TINGGI_PETA):
    """Pusat dan zoom agar seluruh kabupaten/kota terlihat (setara fit_bounds, dihitung di Python)."""
    (la1, lo1), (la2, lo2) = BATAS_KAB[nama]
    merc = lambda la: math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    z_lon = math.log2(lebar * 360 / (256 * (lo2 - lo1)))
    z_lat = math.log2(tinggi * 2 * math.pi / (256 * (merc(la2) - merc(la1))))
    return [(la1 + la2) / 2, (lo1 + lo2) / 2], math.floor((min(z_lon, z_lat) - 0.2) * 4) / 4


# ---------- Pilihan kabupaten/kota (callback: dijalankan sebelum halaman digambar ulang) ----------
st.session_state.setdefault("kab_pilih", KAB_SEMUA)
st.session_state.setdefault("versi", 0)


def klik_peta(kunci):
    """Klik di peta: cari kabupaten/kota yang memuat titik klik (wilayah, lingkaran, maupun areal terbakar)."""
    titik = (st.session_state.get(kunci) or {}).get("last_clicked")
    if not titik:
        return
    pt = Point(titik["lng"], titik["lat"])
    nama = next((n for n, b in bentuk_kab().items() if b.contains(pt)), None)
    if nama:
        st.session_state["kab_pilih"] = nama


def klik_batang(kunci):
    terpilih = ((st.session_state.get(kunci) or {}).get("selection") or {}).get("pilih") or []
    if terpilih and terpilih[0].get("kabupaten") in BATAS_KAB:
        st.session_state["kab_pilih"] = terpilih[0]["kabupaten"]


def ke_seluruh_riau():
    st.session_state["kab_pilih"] = KAB_SEMUA


# ---------- Header & filter ----------
left, mid, right = st.columns([3, 1.4, 1.2])
left.title("Area Terbakar Provinsi Riau")
left.caption("Hasil identifikasi model deep learning pada citra Sentinel-1, 2023–2025")
mode = mid.radio("Tampilan peta", ["Satu tahun", "Bandingkan dua tahun"], horizontal=True)
WARNA_OPSI = {"Luas areal terbakar": "luas_ha", "Emisi CO₂": "emisi_total_tco2", "Tanpa warna": None}
warna_label = mid.selectbox("Warnai kabupaten/kota menurut", list(WARNA_OPSI))
warna = WARNA_OPSI[warna_label]

if mode == "Satu tahun":
    choice = right.selectbox("Tahun", ["Semua tahun"] + years, index=len(years))
    pembanding = years[years.index(choice) - 1] if choice in years[1:] else None
else:
    kiri = right.selectbox("Tahun kiri", years, index=len(years) - 2)
    kanan = right.selectbox("Tahun kanan", years, index=len(years) - 1)
    choice, pembanding = kanan, (kiri if kiri != kanan else None)
right.selectbox("Kabupaten/kota", [KAB_SEMUA] + DAFTAR_KAB, key="kab_pilih")
kab = None if st.session_state["kab_pilih"] == KAB_SEMUA else st.session_state["kab_pilih"]

# Grafik batang dipasang ulang (kunci baru) setiap kali pilihan berubah agar pilihan batang sebelumnya terhapus
if st.session_state.get("kab_tampil", "awal") != kab:
    st.session_state["kab_tampil"] = kab
    st.session_state["versi"] += 1
versi = st.session_state["versi"]


# ---------- Angka wilayah (provinsi atau kabupaten/kota terpilih) ----------
def angka_wilayah(t):
    if kab is None:
        r = ringkas.loc[t]
        return {"luas": r["luas_terbakar_ha"], "emisi": r["emisi_total_tco2"], "gambut": r["areal_gambut_ha"],
                "persen": r["persen_gambut"]}
    d = kabkota[(kabkota["kabupaten"] == kab) &
                (kabkota["tahun"].isin(years if t == "Semua tahun" else [t]))].sum(numeric_only=True)
    return {"luas": d["luas_ha"], "emisi": d["emisi_total_tco2"], "gambut": d["luas_gambut_ha"],
            "persen": d["luas_gambut_ha"] / d["luas_ha"] * 100 if d["luas_ha"] else 0.0}


row = angka_wilayah(choice)
lama = angka_wilayah(pembanding) if pembanding else None


def perubahan(k):
    """Persen perubahan terhadap tahun pembanding, mis. '+37,9% dari 2023'."""
    if lama is None or (lama[k] == 0 and row[k] == 0):
        return None
    if lama[k] == 0:
        return f"+ (tahun {pembanding} bernilai 0)"
    return f"{'+' if row[k] >= lama[k] else '-'}{angka(abs(row[k] - lama[k]) / lama[k] * 100, 1)}% dari {pembanding}"


def perubahan_poin(k):
    if lama is None or (lama[k] == 0 and row[k] == 0):
        return None
    selisih = row[k] - lama[k]
    return f"{'+' if selisih >= 0 else '-'}{angka(abs(selisih), 1)} poin dari {pembanding}"


# ---------- Scorecard ----------
judul_tahun = "2023–2025" if choice == "Semua tahun" else choice
if mode == "Bandingkan dua tahun" and pembanding:
    judul_tahun += f" dibanding {pembanding}"
h1, h2 = st.columns([4, 1])
h1.markdown(f"##### Ringkasan {kab or 'Provinsi Riau'} tahun {judul_tahun}")
if kab:
    h2.button("Tampilkan seluruh Riau", on_click=ke_seluruh_riau, width="stretch")
c1, c2, c3 = st.columns(3)
# delta_color="inverse": kenaikan luas/emisi ditandai merah, penurunan hijau
c1.metric("Luas areal terbakar per kejadian", f"{angka(row['luas'], 2)} ha", perubahan("luas"),
          delta_color="inverse")
# emisi kabupaten/kota bisa jauh di bawah 1 juta ton, jadi satuannya menyesuaikan besar angka
teks_emisi = (f"{angka(row['emisi'] / 1e6, 2)} juta ton CO₂" if row["emisi"] >= 1e6
              else f"{angka(row['emisi'])} ton CO₂")
c2.metric("Estimasi emisi karbon per kejadian", teks_emisi,
          perubahan("emisi"), delta_color="inverse")
c3.metric(f"Areal terbakar di lahan gambut ({angka(row['gambut'], 2)} ha)", f"{angka(row['persen'], 1)} %",
          perubahan_poin("persen"), delta_color="inverse")

# ---------- Peta ----------
# Lingkaran penanda: LUAS lingkaran sebanding dengan luas areal terbakar (jari-jari ~ akar luas),
# dengan batas atas setara 700 ha agar areal yang sangat luas tidak menutupi peta.
CIRCLE_M_PER_SQRT_HA = 1000   # 700 ha -> jari-jari ~26 km (setara gambar ide tampilan)
CIRCLE_MIN_M = 2500           # areal sangat kecil tetap terlihat
CIRCLE_MAX_HA = 700           # areal >= 700 ha memakai lingkaran terbesar yang sama
CIRCLE_HIDE_ZOOM = 8.5        # mulai zoom ini lingkaran disembunyikan (peta awal 7,5; dua kali klik "+")
LEGEND_HA = [10, 50, 200, CIRCLE_MAX_HA]
circle_m = lambda ha: max(CIRCLE_MIN_M, CIRCLE_M_PER_SQRT_HA * min(ha, CIRCLE_MAX_HA) ** 0.5)


class CircleLegend(MacroElement):
    """Legenda 'Luas per areal' sebagai kontrol Leaflet; ukuran lingkaran mengikuti zoom peta."""
    _template = Template("""
    {% macro script(this, kwargs) %}
    (function () {
      var map = {{ this._parent.get_name() }};
      var items = {{ this.items }}, lat0 = {{ this.lat0 }}, hideZoom = {{ this.hide_zoom }};
      var circles = {{ this.circles }};
      var css = document.createElement('style');
      document.head.appendChild(css);
      var legend = L.control({position: 'bottomleft'});
      legend.onAdd = function () {
        this._div = L.DomUtil.create('div');
        this._div.style.cssText = 'background:rgba(255,255,255,0.92);border:1px solid #bdbdbd;' +
          'border-radius:4px;padding:8px 12px;font:12px sans-serif;color:#222';
        return this._div;
      };
      legend.addTo(map);
      function update() {
        var z = map.getZoom(), show = z < hideZoom;
        css.textContent = show ? '' : '.lingkaran-luas{display:none;}';
        legend._div.style.display = (show && map.hasLayer(circles)) ? 'block' : 'none';
        var mpp = 156543.03392 * Math.cos(lat0 * Math.PI / 180) / Math.pow(2, z);
        var rs = items.map(function (it) { return Math.max(it[1] / mpp, 1.5); });
        var rmax = Math.max.apply(null, rs);
        var html = '<div style="font-weight:600;margin-bottom:4px">Luas per areal</div>';
        items.forEach(function (it, i) {
          var r = rs[i];
          html += '<div style="display:flex;align-items:center;margin:3px 0">' +
            '<svg width="' + (2 * rmax + 4) + '" height="' + (2 * r + 4) + '"><circle cx="' + (rmax + 2) +
            '" cy="' + (r + 2) + '" r="' + r + '" fill="#fb6a4a" fill-opacity="0.55" stroke="#b2321f"' +
            ' stroke-width="1"/></svg><span style="margin-left:8px">' + it[0] + '</span></div>';
        });
        legend._div.innerHTML = html;
      }
      map.on('zoomend overlayadd overlayremove', update);
      update();
    })();
    {% endmacro %}
    """)

    def __init__(self, items, lat0, hide_zoom, circles):
        super().__init__()
        self.items, self.lat0, self.hide_zoom = json.dumps(items), lat0, hide_zoom
        self.circles = circles.get_name()


class LapisanLingkaran(MacroElement):
    """Seluruh lingkaran penanda digambar dari satu larik data ringkas, bukan ribuan objek folium terpisah.
    Tampilan, tooltip, dan popup sama seperti sebelumnya."""
    _template = Template("""
    {% macro script(this, kwargs) %}
    (function () {
      var grup = {{ this._parent.get_name() }};
      {{ this.data }}.forEach(function (d) {
        var popup = '<b>Tahun</b> ' + d[3] + '<br><b>Luas</b> ' + d[4] + '<br><b>Kab/Kota</b> ' + d[5] +
                    '<br><b>Lat</b> ' + d[6] + '<br><b>Lon</b> ' + d[7];
        L.circle([d[0], d[1]], {radius: d[2], color: '#b2321f', weight: 1, fill: true, fillColor: '#fb6a4a',
                                fillOpacity: 0.55, className: 'lingkaran-luas'})
          .bindTooltip(d[4] + ' – ' + d[5])
          .bindPopup(popup, {maxWidth: 240})
          .addTo(grup);
      });
    })();
    {% endmacro %}
    """)

    def __init__(self, data):
        super().__init__()
        self.data = data


@st.cache_data
def data_lingkaran(pilihan):
    """[lat, lon, jari-jari, tahun, luas, kab, lat teks, lon teks] untuk setiap areal (urut terluas dulu)."""
    baris = [[float(p["lat"]), float(p["lon"]), round(circle_m(p["luas_ha"])), p["tahun"], p["luas"], p["kab"],
              p["lat"], p["lon"]]
             for y in pilihan for p in (f["properties"] for f in burns[y]["features"])]
    return json.dumps(baris, ensure_ascii=False, separators=(",", ":"))


def nilai_kab(pilihan):
    """Angka per kejadian setiap kabupaten/kota untuk tahun yang dipilih (dijumlahkan bila lebih dari satu)."""
    return kabkota[kabkota["tahun"].isin(pilihan)].groupby("kabupaten")[
        ["luas_ha", "emisi_total_tco2", "jumlah_kejadian"]].sum()


def skala_warna(pilihan, warna, warna_label):
    """Skala warna dibuat sama untuk setiap tahun tunggal agar dua peta dapat dibandingkan langsung."""
    if len(pilihan) > 1:
        vmax = nilai_kab(pilihan)[warna].max()
    else:
        vmax = max(nilai_kab([y])[warna].max() for y in years)
    # Legenda memakai satuan ribu ha / juta ton CO2 dengan angka bulat agar tidak muncul pemisah ribuan "33,517"
    pembagi, satuan = (1e3, "ribu ha") if warna == "luas_ha" else (1e6, "juta ton CO₂")
    langkah = 1 if vmax / pembagi <= 10 else 5 if vmax / pembagi <= 50 else 25
    atas = -(-vmax / pembagi // langkah) * langkah
    cmap = cm.LinearColormap(["#fff5eb", "#fdae6b", "#e6550d", "#7f2704"], vmin=0, vmax=atas,
                             tick_labels=list(range(0, int(atas) + 1, langkah)))
    cmap.caption = f"{warna_label} per kejadian ({satuan})"
    cmap.pembagi, cmap.kolom = pembagi, warna
    return cmap


@st.cache_data
def geo_kab_berwarna(pilihan, warna, warna_label):
    """GeoJSON kabupaten/kota beserta warna isian dan teks tooltip untuk pilihan tahun dan warna tertentu."""
    cmap = skala_warna(pilihan, warna, warna_label) if warna else None
    nilai = nilai_kab(pilihan)
    geo = json.loads(json.dumps(kabupaten))
    for f in geo["features"]:
        p = f["properties"]
        n = nilai.loc[p["kabupaten"]] if p["kabupaten"] in nilai.index else None
        p["isi"] = cmap(float(n[warna]) / cmap.pembagi if n is not None else 0.0) if cmap else "#ffffff"
        p["luas_txt"] = f"{angka(n['luas_ha'], 2) if n is not None else '0'} ha"
        p["emisi_txt"] = f"{angka(n['emisi_total_tco2']) if n is not None else '0'} ton CO₂"
        p["kejadian_txt"] = angka(n["jumlah_kejadian"]) if n is not None else "0"
    return geo


def isi_peta(m, pilihan, warna, warna_label, kab_pilih=None, legenda_warna=True):
    """Lapisan provinsi, choropleth kabupaten/kota, lingkaran penanda, dan poligon areal terbakar."""
    folium.GeoJson(riau, name="Provinsi Riau",
                   style_function=lambda _: {"color": "#a6a6a6", "weight": 1.2, "fillColor": "#f0f0f0",
                                             "fillOpacity": 1.0}, control=False).add_to(m)

    def gaya(f):
        terpilih = f["properties"]["kabupaten"] == kab_pilih
        return {"color": "#111111" if terpilih else ("#8c8c8c" if warna else "#c4c4c4"),
                "weight": 3.5 if terpilih else 0.8, "fillColor": f["properties"]["isi"],
                "fillOpacity": 0.75 if warna else 0.0}
    folium.GeoJson(geo_kab_berwarna(pilihan, warna, warna_label), name="Kabupaten/kota", style_function=gaya,
                   control=False, highlight_function=lambda _: {"weight": 2.5, "color": "#333333"},
                   tooltip=folium.GeoJsonTooltip(
                       fields=["kabupaten", "luas_txt", "emisi_txt", "kejadian_txt"],
                       aliases=["Kab/Kota:", "Luas per kejadian:", "Emisi per kejadian:", "Jumlah kejadian:"])
                   ).add_to(m)
    if warna and legenda_warna:
        skala_warna(pilihan, warna, warna_label).add_to(m)

    circles = folium.FeatureGroup(name="Lingkaran penanda luas").add_to(m)
    circles.add_child(LapisanLingkaran(data_lingkaran(pilihan)))
    for y in pilihan:
        folium.GeoJson(burns[y], name=f"Terbakar {y}", control=False,
                       style_function=lambda _: {"color": "#67000d", "weight": 0.5,
                                                 "fillColor": "#a50f15", "fillOpacity": 0.9},
                       popup=folium.GeoJsonPopup(fields=["tahun", "luas", "kab", "lat", "lon"],
                                                 aliases=["Tahun", "Luas", "Kab/Kota", "Lat", "Lon"],
                                                 max_width=240)).add_to(m)

    label = lambda i, ha: f"≤ {ha} ha" if i == 0 else f"≥ {ha} ha" if ha == CIRCLE_MAX_HA else f"{ha} ha"
    legend_items = [[label(i, ha), circle_m(ha)] for i, ha in enumerate(LEGEND_HA)]
    m.add_child(CircleLegend(legend_items, lat0=pusat["lat"], hide_zoom=CIRCLE_HIDE_ZOOM, circles=circles))
    folium.LayerControl(position="topright", collapsed=False).add_to(m)


GAYA = ("<style>.leaflet-container{background:" + LATAR_PETA + " !important;}"
        ".leaflet-interactive:focus{outline:none !important;}</style>")


def peta_dasar(pilihan, warna, warna_label):
    """Peta satu tahun (atau semua tahun) tanpa sorotan kabupaten/kota, sehingga isinya sama di setiap putaran
    dan st_folium tidak menggambar ulang peta di browser. Objek folium harus dibuat baru setiap putaran karena
    st_folium mengubah strukturnya saat dirender; bagian yang mahal sudah disimpan di cache."""
    m = folium.Map(location=[pusat["lat"], pusat["lon"]], zoom_start=7.5, tiles=None,
                   zoom_snap=0.25, zoom_delta=0.5)
    isi_peta(m, pilihan, warna, warna_label)
    m.get_root().header.add_child(folium.Element(GAYA))
    return m


def sorotan(kab_pilih, ganda=False):
    """Garis tebal kabupaten/kota terpilih sebagai lapisan tambahan (tanpa isian, jadi klik tetap ke peta).
    st_folium hanya menambahkan lapisan ini ke peta kiri, jadi pada peta ganda salinannya dipasang ke peta kanan
    lewat SorotanKanan."""
    fg = folium.FeatureGroup(name="Kabupaten/kota terpilih", control=False)
    if kab_pilih:
        folium.GeoJson(GEO_KAB[kab_pilih], style_function=lambda _: {"color": "#111111", "weight": 3.5,
                                                                     "fill": False}).add_to(fg)
    if ganda:
        fg.add_child(SorotanKanan(GEO_KAB[kab_pilih] if kab_pilih else None))
    return fg


class SorotanKanan(MacroElement):
    """Salinan garis sorotan di peta kanan (map_div2). Sorotan lama dihapus dulu karena st_folium hanya
    membersihkan lapisan tambahan di peta kiri."""
    _template = Template("""
    {% macro script(this, kwargs) %}
    (function () {
      if (typeof map_div2 === 'undefined') { return; }
      if (window.__sorotanKanan) { map_div2.removeLayer(window.__sorotanKanan); window.__sorotanKanan = null; }
      var data = {{ this.data }};
      if (data) {
        window.__sorotanKanan = L.geoJson(data, {style: {color: '#111111', weight: 3.5, fill: false},
                                                 interactive: false}).addTo(map_div2);
      }
    })();
    {% endmacro %}
    """)

    def __init__(self, data):
        super().__init__()
        self.data = json.dumps(data) if data else "null"


class KlikKanan(MacroElement):
    """st_folium hanya mendengarkan klik di peta kiri; klik di peta kanan diteruskan ke peta kiri.
    Koordinatnya sama karena kedua peta tersinkron."""
    _template = Template("""
    {% macro script(this, kwargs) %}
    {{ this.kanan }}.on('click', function (e) {
      {{ this.kiri }}.fire('click', {latlng: e.latlng});
    });
    {% endmacro %}
    """)

    def __init__(self, kiri, kanan):
        super().__init__()
        self.kiri, self.kanan = kiri.get_name(), kanan.get_name()


def peta_ganda(kiri, kanan, warna, warna_label):
    """Dua peta berdampingan yang bergeser dan memperbesar bersamaan, tanpa sorotan agar isinya tetap sama."""
    m = DualMap(location=[pusat["lat"], pusat["lon"]], zoom_start=6.75, tiles=None,
                zoom_snap=0.25, zoom_delta=0.5)
    # Skala warna kedua peta sama, jadi legenda warna cukup satu (di peta kanan); legenda branca selalu
    # menempel pada elemen legenda pertama di halaman sehingga dua legenda akan menumpuk.
    for sub, y, legenda in ((m.m1, kiri, False), (m.m2, kanan, True)):
        isi_peta(sub, (y,), warna, warna_label, legenda_warna=legenda)
    m.m2.add_child(KlikKanan(m.m1, m.m2))   # dipasang di peta kanan saja (DualMap menyalin anak miliknya ke dua peta)
    m.get_root().header.add_child(folium.Element(GAYA))
    return m


if mode == "Satu tahun":
    sel_years = years if choice == "Semua tahun" else [choice]
    pusat_tampil, zoom_tampil = tampilan_kab(kab) if kab else ([pusat["lat"], pusat["lon"]], 7.5)
    st_folium(peta_dasar(tuple(sel_years), warna, warna_label), key="peta", height=TINGGI_PETA,
              use_container_width=True, returned_objects=["last_clicked"], on_change=lambda: klik_peta("peta"),
              center=pusat_tampil, zoom=zoom_tampil, feature_group_to_add=sorotan(kab))
else:
    k1, k2 = st.columns(2)
    k1.markdown(f"<div style='text-align:center;font-weight:600'>{kiri}</div>", unsafe_allow_html=True)
    k2.markdown(f"<div style='text-align:center;font-weight:600'>{kanan}</div>", unsafe_allow_html=True)
    # setiap peta selebar setengah halaman, jadi zoom kabupaten/kota dihitung untuk lebar ±540 piksel
    pusat_tampil, zoom_tampil = (tampilan_kab(kab, lebar=540, tinggi=TINGGI_GANDA) if kab
                                 else ([pusat["lat"], pusat["lon"]], 6.75))
    st_folium(peta_ganda(kiri, kanan, warna, warna_label), key="peta_ganda", height=TINGGI_GANDA,
              use_container_width=True, returned_objects=["last_clicked"],
              on_change=lambda: klik_peta("peta_ganda"), center=pusat_tampil, zoom=zoom_tampil,
              feature_group_to_add=sorotan(kab, ganda=True))
st.caption("Klik kabupaten/kota atau areal terbakar pada peta, atau klik batang pada grafik, untuk menampilkan angka "
           "kabupaten/kota tersebut. Pilih \"Seluruh Riau\" atau tekan tombol \"Tampilkan seluruh Riau\" untuk kembali.")
if warna:
    st.caption("Warna kabupaten/kota menunjukkan angka per kejadian. Skala warna dibuat sama untuk setiap tahun "
               "sehingga warna dapat dibandingkan langsung. Arahkan kursor ke kabupaten/kota untuk melihat angkanya.")

WARNA_TAHUN = alt.Scale(domain=years, range=["#fdae6b", "#e6550d", "#7f2704"])

# ---------- Grafik ----------
if mode == "Bandingkan dua tahun" and kab and pembanding:
    # Perbandingan satu kabupaten/kota untuk dua tahun yang dipilih: empat ukuran dengan skala masing-masing
    st.markdown(f"##### Perbandingan {kab}: {pembanding} dan {choice}")
    UKURAN = {"luas_ha": ("Luas areal terbakar (ha)", 2), "luas_gambut_ha": ("Luas gambut terbakar (ha)", 2),
              "emisi_total_tco2": ("Emisi (ton CO₂)", 0), "jumlah_kejadian": ("Jumlah kejadian", 0)}
    d2 = kabkota[(kabkota["kabupaten"] == kab) & kabkota["tahun"].isin([pembanding, choice])]
    d2 = d2.melt(id_vars="tahun", value_vars=list(UKURAN), var_name="kolom", value_name="nilai")
    d2["ukuran"] = d2["kolom"].map(lambda k: UKURAN[k][0])
    d2["nilai_txt"] = [angka(v, UKURAN[k][1]) for k, v in zip(d2["kolom"], d2["nilai"])]
    dasar = alt.Chart(d2).encode(
        x=alt.X("tahun:N", title=None, sort=[pembanding, choice], axis=alt.Axis(labelAngle=0)),
        y=alt.Y("nilai:Q", title=None, axis=alt.Axis(labelExpr=SUMBU_ID, tickCount=4)),
    )
    batang = dasar.mark_bar(width=46, cornerRadiusEnd=2).encode(
        color=alt.Color("tahun:N", title="Tahun", scale=WARNA_TAHUN, legend=None),
        tooltip=[alt.Tooltip("ukuran:N", title="Ukuran"), alt.Tooltip("tahun:N", title="Tahun"),
                 alt.Tooltip("nilai_txt:N", title="Nilai")])
    label = dasar.mark_text(dy=-7, fontSize=11).encode(text="nilai_txt:N")
    grafik = (batang + label).properties(width=190, height=230).facet(
        column=alt.Column("ukuran:N", title=None, sort=[u[0] for u in UKURAN.values()],
                          header=alt.Header(labelFontWeight="bold", labelFontSize=12))
    ).resolve_scale(y="independent")
    st.altair_chart(grafik.configure(background=LATAR), width="content")
    st.caption("Setiap grafik memakai skalanya sendiri. Tekan \"Tampilkan seluruh Riau\" atau pilih \"Seluruh Riau\" "
               "untuk kembali ke grafik semua kabupaten/kota.")
else:
    tahun_grafik = [pembanding, choice] if (mode == "Bandingkan dua tahun" and pembanding) else (
        years if choice == "Semua tahun" else [choice])
    st.markdown(f"##### Luas areal terbakar per kabupaten/kota ({', '.join(tahun_grafik)})")
    dk = kabkota[kabkota["tahun"].isin(tahun_grafik)].copy()
    dk["luas_txt"] = dk["luas_ha"].map(lambda v: f"{angka(v, 2)} ha")
    dk["emisi_txt"] = dk["emisi_total_tco2"].map(lambda v: f"{angka(v)} ton CO₂")
    urutan = dk.groupby("kabupaten")["luas_ha"].sum().sort_values(ascending=False).index.tolist()
    klik = alt.selection_point(name="pilih", fields=["kabupaten"], on="click")
    bar = alt.Chart(dk).mark_bar(cornerRadiusEnd=2).encode(
        y=alt.Y("kabupaten:N", sort=urutan, title=None),
        x=alt.X("luas_ha:Q", title="Luas per kejadian (ha)", axis=alt.Axis(labelExpr=SUMBU_ID)),
        color=alt.Color("tahun:N", title="Tahun", legend=alt.Legend(values=tahun_grafik), scale=WARNA_TAHUN),
        # kabupaten/kota terpilih tampil penuh, lainnya dipudarkan
        opacity=alt.condition(alt.datum.kabupaten == kab, alt.value(1), alt.value(0.3)) if kab else alt.value(1),
        tooltip=[alt.Tooltip("kabupaten:N", title="Kab/Kota"), alt.Tooltip("tahun:N", title="Tahun"),
                 alt.Tooltip("luas_txt:N", title="Luas"), alt.Tooltip("emisi_txt:N", title="Emisi"),
                 alt.Tooltip("jumlah_kejadian:Q", title="Jumlah kejadian")],
    ).add_params(klik)
    if len(tahun_grafik) > 1:
        bar = bar.encode(yOffset=alt.YOffset("tahun:N"))
    kunci_batang = f"batang_{versi}"
    st.altair_chart(bar.properties(height=380).configure(background=LATAR), width="stretch", key=kunci_batang,
                    on_select=lambda: klik_batang(kunci_batang))
    st.caption("Klik batang untuk menampilkan angka kabupaten/kota tersebut.")

# ---------- Tabel ----------
st.subheader("Ringkasan Provinsi Riau")
KOLOM = {"tahun": "Tahun", "luas_terbakar_ha": "Luas areal terbakar (ha)", "areal_gambut_ha": "Areal gambut (ha)",
         "areal_non_gambut_ha": "Areal non-gambut (ha)", "emisi_vegetasi_tco2": "Emisi vegetasi (ton CO₂)",
         "emisi_gambut_tco2": "Emisi tanah gambut (ton CO₂)", "emisi_total_tco2": "Emisi total (ton CO₂)"}
table = summary[list(KOLOM)].replace({"tahun": {"Semua tahun": "Jumlah"}}).rename(columns=KOLOM)
for c in KOLOM.values():
    if c != "Tahun":
        table[c] = table[c].map(lambda v, d=(2 if "(ha)" in c else 0): angka(v, d))
st.dataframe(table, hide_index=True, width="stretch")
st.caption("Luas dan emisi dihitung pada setiap kejadian dari piksel di dalam batas Provinsi Riau, lalu dijumlahkan "
           "per tahun, sehingga lokasi yang tercakup oleh beberapa kejadian ikut dihitung pada setiap kejadian. "
           "Peta menampilkan sebaran areal terbakar pada peta tahunan, yaitu setiap lokasi digambar satu kali.")
d1, d2 = st.columns(2)
d1.download_button("Unduh ringkasan (CSV)", summary.to_csv(index=False), "ringkasan_kebakaran_riau.csv", "text/csv")
d2.download_button("Unduh per kabupaten/kota (CSV)", kabkota.to_csv(index=False),
                   "kabupaten_kota_kebakaran_riau.csv", "text/csv")

# ---------- Metodologi ----------
with st.expander("Metodologi & keterbatasan"):
    st.markdown("""
- **Model**: U-Net++, model terbaik dari empat arsitektur yang dibandingkan, dengan input backscatter Sentinel-1 setelah kebakaran dan perubahannya terhadap kondisi sebelum kebakaran. Label latih berasal dari data burned area BRIN hasil interpretasi citra Landsat-8 tahun 2019–2021.
- **Luas areal terbakar** dihitung per kejadian di dalam batas Provinsi Riau: areal yang tercakup oleh beberapa kejadian ikut dihitung pada setiap kejadian, sama seperti pada skripsi.
- **Emisi karbon** (ton CO₂) dihitung dengan metode IPCC Tier 1 = Luas terbakar × Fuel load × Combustion factor × Emission factor, terpisah untuk vegetasi dan tanah gambut.
- **Keterbatasan**: pemetaan dimulai dari kejadian yang terdeteksi hotspot dan dibatasi ukuran tile, sehingga kebakaran tanpa hotspot belum terpetakan; sekitar 15% piksel yang ditandai terbakar masih keliru; dan estimasi emisi memakai nilai bawaan IPCC sehingga bersifat perkiraan.
""")
