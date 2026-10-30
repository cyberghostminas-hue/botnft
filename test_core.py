"""Pruebas del motor y de la cartera (no necesitan aiogram ni red)."""
import os, tempfile, time
import engine as E
from store import Store, Cfg, Err

def check(c, t):
    print("OK   " if c else "FALLA", t)
    if not c: raise SystemExit(1)

# ---- motor ----
s = E.fresh(1000.0)
check(E.ips(s) == .2, "ingreso inicial = 0.2/s")
E.tick(s, 1010.0); check(abs(s["m"] - 27.0) < 1e-9, "10 s generan 2 de dinero")
E.tick(s, 1010.0 + 99 * 3600); check(abs((s["m"] - 27.0) - .2 * 8 * 3600) < 1e-6, "offline limitado a 8 h")
s = E.fresh(0); s["m"] = 1e6
ok, _ = E.hire(s, 0); check(ok and s["fl"][0]["w"] == 2, "contratar")
ok, _ = E.upgrade(s, 0); check(ok and s["fl"][0]["l"] == 2, "mejorar")
ok, _ = E.build(s); check(ok and len(s["fl"]) == 2, "abrir departamento")
z = E.fresh(); z["m"] = 5; check(not E.hire(z, 0)[0] and z["fl"][0]["w"] == 1 and z["m"] == 5, "sin dinero no contrata ni cobra")
s = E.fresh(); s["m"] = 1e30
for _ in range(7): check(E.build(s)[0], "construir hasta 8")
check(not E.build(s)[0], "no se abre el 9 sin edificio 2")
check(E.unlock2(s)[0] and E.build(s)[0] and len(s["fl"]) == 9, "edificio 2 desbloquea más")
check(not E.buy_global(E.fresh(), "h1")[0], "mejora del edificio 2 requiere edificio 2")
s["m"] = 1e30; base = E.ips(s); E.buy_global(s, "g1"); check(abs(E.ips(s) / base - 1.25) < 1e-9, "mejora global ×1.25")
s = E.fresh(); s["tot"] = 1e13; check(E.prestige(s) == 0, "sin 2e13 no hay prestigio")
s["tot"] = 8e13; s["m"] = 5; g = E.prestige(s); check(g == 2 and s["rep"] == 2 and s["m"] == 25 and len(s["fl"]) == 1, "prestigio: +2 rep y reinicio")
check(abs(E.rep_m(s) - (1 + .4 * 2 ** .5)) < 1e-9, "multiplicador de reputación")

# ---- cartera, tope, referidos, retiros ----
d = tempfile.mkdtemp(); key = os.urandom(32)
cfg = Cfg(cup_per_bit=1, bits_per_point=100, daily_bits_cap=6000, prestige_cooldown_h=0, min_withdraw_cup=5000, max_withdraw_day_cup=20000, referral_pct=10)
st = Store(d + "/t.db", key, cfg)
st.user(1, "A"); st.user(2, "B", ref=1); st.user(3, "C", ref=3)
check(st.db.execute("SELECT referrer FROM users WHERE id=3").fetchone()["referrer"] is None, "no te puedes referir a ti mismo")
bits, _ = st.award_prestige(2, 70); check(bits == 6000 and st.balance(2) == 6000 and st.balance(1) == 600, "prestigio da Bits y 10% al referidor")
bits, why = st.award_prestige(2, 5); check(bits == 0 and "tope" in why, "tope diario respetado")
for bad in ("1234", "abcd" * 4):
    try: st.request_withdraw(2, 5000, bad); check(False, "tarjeta inválida")
    except Err: check(True, f"tarjeta inválida rechazada ({bad[:4]}…)")
try: st.request_withdraw(2, 4000, "9225123456789012"); check(False, "mínimo")
except Err: check(True, "bajo el mínimo rechazado")
wid = st.request_withdraw(2, 5000, "9225 1234 5678 9012"); check(st.balance(2) == 1000, "retiro descuenta saldo")
try: st.request_withdraw(2, 1000, "9225123456789012"); check(False, "doble")
except Err: check(True, "segundo retiro pendiente bloqueado")
p = st.pending(); check(p[0]["card"] == "9225123456789012" and p[0]["last4"] == "9012", "admin ve tarjeta descifrada")
st.resolve(wid, False, "prueba"); check(st.balance(2) == 6000, "rechazo reembolsa")
try: st.resolve(wid, True); check(False, "doble resolución")
except Err: check(True, "no se resuelve dos veces")
wid = st.request_withdraw(2, 5000, "9225123456789012"); st.resolve(wid, True)
check(st.withdrawals(2)[0]["status"] == "paid", "retiro pagado")
try: st.request_withdraw(2, 1000, "9225123456789012"); check(False, "bajo mínimo tras pagar")
except Err: check(True, "validaciones siguen activas")
st.db.execute("PRAGMA wal_checkpoint(FULL)")
raw = open(d + "/t.db", "rb").read() + (open(d + "/t.db-wal", "rb").read() if os.path.exists(d + "/t.db-wal") else b"")
check(b"9225123456789012" not in raw, "la tarjeta NO está en texto plano en la base")
st.ban(2); 
try: st.user(2); check(False, "ban")
except Err: check(True, "usuario bloqueado no entra")
# enfriamiento
cfg2 = Cfg(bits_per_point=1, daily_bits_cap=999, prestige_cooldown_h=6); st2 = Store(d + "/c.db", key, cfg2); st2.user(9, "Z")
check(st2.award_prestige(9, 3)[0] == 3 and st2.award_prestige(9, 3)[0] == 0, "enfriamiento entre premios")
print("TODO BIEN")
