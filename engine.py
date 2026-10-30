"""IT Company · motor de juego (puro, sin Telegram ni base de datos).
Portado de game.js: departamentos, contratar, mejorar, edificio 2, mejoras globales, prestigio."""
import math, time

# (nombre, puesto, costo base, ingreso base/s). Los 8 primeros = edificio 1; los 8 siguientes = edificio 2.
DEPTS = [
    ("Asesoría informática", "asesor", 15, .2), ("Administración web", "webmaster", 100, 1.5),
    ("Ingeniería de software", "programador", 1100, 10), ("Base de datos", "DBA", 12e3, 60),
    ("Estructura de datos", "algoritmista", 13e4, 330), ("Redes y telecom", "técnico de red", 1.4e6, 1800),
    ("Ciberseguridad", "analista", 2e7, 1e4), ("Inteligencia artificial", "ingeniero IA", 3.3e8, 56e3),
    ("Videojuegos", "dev de juegos", 4e9, 2e5), ("Apps móviles", "dev móvil", 1.2e10, 5e5),
    ("Computación en la nube", "ing. de nube", 3.5e10, 1.3e6), ("Diseño UX", "diseñador UX", 9e10, 3e6),
    ("Robótica", "ing. robótico", 2.5e11, 8e6), ("Ciencia de datos", "científico de datos", 6e11, 2e7),
    ("Criptografía", "criptógrafo", 1.6e12, 5e7), ("Realidad virtual", "ing. de RV", 4e12, 1.3e8),
]
MAXF, MAXW, MAXL = 8, 6, 10
# Mejoras globales (edificio 1 + todo): clave -> (nombre, texto, costo, multiplicador)
GL = {"g1": ("Letrero de neón", 2e4, 1.25), "g2": ("Valla publicitaria", 1e6, 1.5),
      "g3": ("Antena satelital", 1e8, 2), "g4": ("Helipuerto corporativo", 1e10, 3)}
# Mejoras del edificio 2 (solo multiplican los departamentos 8-15)
GL2 = {"h1": ("Servidores de juego", 5e10, 1.5), "h2": ("Fibra de 10 Gb", 5e11, 2),
       "h3": ("Centro de datos", 5e12, 3), "h4": ("Laboratorio de IA", 5e13, 4)}
UNLOCK2 = 2e10
PRESTIGE_DIV = 2e13
OFFLINE_CAP_S = 8 * 3600

def fresh(now=None):
    return {"m": 25.0, "tot": 0.0, "rep": 0, "b2": False, "fl": [{"w": 1, "l": 1}], "up": {}, "t": now or time.time(), "daily": 0}

def fmt(n):
    if n < 1e3: return f"{n:.1f}" if n < 10 and n % 1 else str(int(n))
    for u in ["K", "M", "B", "T", "Qa", "Qi"]:
        n /= 1e3
        if n < 1e3 or u == "Qi": return f"{n:.2f}{u}" if n < 10 else f"{n:.1f}{u}" if n < 100 else f"{n:.0f}{u}"

# ---- fórmulas ----
def gm(s):  return math.prod(GL[k][2] for k in GL if s["up"].get(k)) or 1
def gm2(s): return math.prod(GL2[k][2] for k in GL2 if s["up"].get(k)) or 1
def rep_m(s): return 1 + .4 * math.sqrt(s["rep"])
def hire_cost(s, i): return math.ceil(DEPTS[i][2] * 1.18 ** s["fl"][i]["w"])
def up_cost(s, i):   return math.ceil(DEPTS[i][2] * 5 * 2.5 ** s["fl"][i]["l"])
def build_cost(i):   return DEPTS[i][2] * 8
def dept_income(s, i):
    f = s["fl"][i]; return f["w"] * DEPTS[i][3] * 1.6 ** (f["l"] - 1) * (gm2(s) if i >= MAXF else 1)
def ips(s): return sum(dept_income(s, i) for i in range(len(s["fl"]))) * gm(s) * rep_m(s)
def prestige_gain(s): return int(math.sqrt(s["tot"] / PRESTIGE_DIV))

# ---- tiempo ----
def tick(s, now=None):
    """Suma el ingreso acumulado desde la última vez (máx. 8 h). Devuelve lo ganado."""
    now = now or time.time(); dt = max(0.0, min(now - s["t"], OFFLINE_CAP_S)); s["t"] = now
    g = ips(s) * dt; s["m"] += g; s["tot"] += g; return g

# ---- acciones: devuelven (ok, mensaje) ----
def _pay(s, c):
    if s["m"] < c: return False
    s["m"] -= c; return True
def hire(s, i):
    if not 0 <= i < len(s["fl"]): return False, "Departamento no abierto"
    if s["fl"][i]["w"] >= MAXW: return False, "Equipo completo"
    if not _pay(s, hire_cost(s, i)): return False, "Dinero insuficiente"
    s["fl"][i]["w"] += 1; return True, "Contratado"
def upgrade(s, i):
    if not 0 <= i < len(s["fl"]): return False, "Departamento no abierto"
    f = s["fl"][i]
    if f["l"] >= MAXL: return False, "Nivel máximo"
    if not _pay(s, up_cost(s, i)): return False, "Dinero insuficiente"
    f["l"] += 1; return True, "Equipo mejorado"
def build(s):
    i = len(s["fl"])
    if i >= len(DEPTS): return False, "Todo construido"
    if i >= MAXF and not s["b2"]: return False, "Desbloquea el edificio 2"
    if not _pay(s, build_cost(i)): return False, "Dinero insuficiente"
    s["fl"].append({"w": 1, "l": 1}); return True, f"Nuevo departamento: {DEPTS[i][0]}"
def unlock2(s):
    if s["b2"]: return False, "Ya desbloqueado"
    if len(s["fl"]) < MAXF: return False, "Abre primero los 8 departamentos del edificio 1"
    if not _pay(s, UNLOCK2): return False, "Dinero insuficiente"
    s["b2"] = True; return True, "Edificio 2 desbloqueado"
def buy_global(s, key):
    tbl = GL if key in GL else GL2 if key in GL2 else None
    if not tbl: return False, "Mejora inexistente"
    if s["up"].get(key): return False, "Ya comprada"
    if key in GL2 and not s["b2"]: return False, "Necesitas el edificio 2"
    if not _pay(s, tbl[key][1]): return False, "Dinero insuficiente"
    s["up"][key] = 1; return True, f"Comprado: {tbl[key][0]}"
def prestige(s):
    """Reinicia la empresa y suma reputación. Devuelve puntos ganados (0 = no se hizo)."""
    g = prestige_gain(s)
    if g < 1: return 0
    rep = s["rep"] + g; t = s["t"]; s.clear(); s.update(fresh(t)); s["rep"] = rep; return g
