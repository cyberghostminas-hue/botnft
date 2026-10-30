"""IT Company · bot de Telegram con aiogram 3.x.
Ejecutar:  BOT_TOKEN=... CARD_KEY=<64 hex> ADMIN_IDS=123,456 python bot.py"""
import asyncio, html, logging, os, time
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import BaseMiddleware
import engine as E
from store import Store, Err

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DEV = os.getenv("DEV") == "1"
store: Store
router, admin = Router(), Router()
admin.message.filter(F.from_user.id.in_(ADMIN_IDS))

class W(StatesGroup): bits = State(); card = State()

# ---------- utilidades ----------
def ctx(uid):
    s = store.load_game(uid) or E.fresh(); E.tick(s); return s
def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)
def b(text, data): return Btn(text=text, callback_data=data)
HOME_BTN = [b("🏠 Inicio", "home")]
async def edit(cb: CallbackQuery, text, markup):
    try: await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest: pass          # "message is not modified"

class Throttle(BaseMiddleware):
    """Máx. ~3 acciones/segundo por usuario (antispam y antiautoclick)."""
    def __init__(self): self.last = {}
    async def __call__(self, handler, event, data):
        u = event.from_user.id; t = time.monotonic()
        if t - self.last.get(u, 0) < .3:
            if isinstance(event, CallbackQuery): await event.answer("Más despacio 🙂")
            return
        self.last[u] = t; return await handler(event, data)

# ---------- pantallas ----------
def home_view(uid, s):
    bits = store.balance(uid)
    t = (f"💼 <b>IT Company</b>\n\n💰 Dinero: <b>${E.fmt(s['m'])}</b>\n📈 Ingreso: <b>${E.fmt(E.ips(s))}/s</b>\n"
         f"⭐ Reputación: <b>{s['rep']}</b> (×{E.rep_m(s):.2f})\n🏢 Departamentos: <b>{len(s['fl'])}/16</b>\n"
         f"💎 Bits: <b>{bits}</b> (≈ {int(bits * store.cfg.cup_per_bit)} CUP)\n\n<i>Tu empresa sigue generando dinero aunque cierres el chat (hasta 8 h).</i>")
    return t, kb([[b("🏢 Departamentos", "dl:0"), b("🛒 Mejoras", "gl")], [b("⭐ Prestigio", "pg"), b("💎 Cartera", "wl")],
                  [b("👥 Referidos", "rf"), b("🔄 Actualizar", "home")]])

def dept_list_view(s, page):
    lo = page * E.MAXF; hi = lo + E.MAXF; rows = []
    for i in range(lo, min(hi, len(s["fl"]))):
        f = s["fl"][i]; rows.append([b(f"{E.DEPTS[i][0]} · 👷{f['w']}/{E.MAXW} · Nv{f['l']}", f"d:{i}")])
    n = len(s["fl"]); txt = f"🏢 <b>Edificio {page + 1}</b>\n💰 ${E.fmt(s['m'])}"
    if lo <= n < hi:
        if n >= E.MAXF and not s["b2"]: rows.append([b(f"🔓 Desbloquear edificio 2 (${E.fmt(E.UNLOCK2)})", "u2")])
        else: rows.append([b(f"➕ Abrir {E.DEPTS[n][0]} (${E.fmt(E.build_cost(n))})", "bd")])
    elif page == 1 and not s["b2"]:
        txt += "\n\n🔒 Abre los 8 departamentos del edificio 1 y desbloquea el edificio 2."
        if n >= E.MAXF: rows.append([b(f"🔓 Desbloquear edificio 2 (${E.fmt(E.UNLOCK2)})", "u2")])
    nav = [b("◀️ Edificio 1", "dl:0")] if page == 1 else [b("Edificio 2 ▶️", "dl:1")]
    return txt, kb(rows + [nav + HOME_BTN])

def dept_view(s, i):
    f = s["fl"][i]; name, role, _, _ = E.DEPTS[i]; mult = E.gm(s) * E.rep_m(s)
    t = (f"🏢 <b>{name}</b>\n👷 {role}: <b>{f['w']}/{E.MAXW}</b> · Nivel <b>{f['l']}/{E.MAXL}</b>\n"
         f"📈 Aporta: <b>${E.fmt(E.dept_income(s, i) * mult)}/s</b>\n\n"
         f"Contratar: ${E.fmt(E.hire_cost(s, i)) if f['w'] < E.MAXW else '—'}\nMejorar: ${E.fmt(E.up_cost(s, i)) if f['l'] < E.MAXL else '—'}\n\n💰 Tienes ${E.fmt(s['m'])}")
    return t, kb([[b("👷 Contratar", f"h:{i}"), b("⬆️ Mejorar", f"u:{i}")], [b("◀️ Volver", f"dl:{i // E.MAXF}")] + HOME_BTN])

def globals_view(s):
    rows = []; t = f"🛒 <b>Mejoras globales</b>\n💰 ${E.fmt(s['m'])}\n"
    for tbl, tag in ((E.GL, "Todo"), (E.GL2, "Edificio 2")):
        for k, (n, c, m) in tbl.items():
            done = s["up"].get(k); t += f"\n{'✅' if done else '▫️'} {n} — {tag} ×{m} — ${E.fmt(c)}"
            if not done and (tbl is E.GL or s["b2"]): rows.append([b(f"Comprar {n} (${E.fmt(c)})", f"g:{k}")])
    return t, kb(rows + [HOME_BTN])

def prestige_view(uid, s):
    g = E.prestige_gain(s); c = store.cfg
    t = (f"⭐ <b>Prestigio</b>\n\nReinicias la empresa y ganas <b>reputación</b> (más ingresos permanentes) y <b>Bits</b> (dinero real).\n\n"
         f"Puntos ahora: <b>{g}</b>  (necesitas ${E.fmt(E.PRESTIGE_DIV)} generados en total; llevas ${E.fmt(s['tot'])})\n"
         f"Bits por punto: {c.bits_per_point} · Tope diario: {c.daily_bits_cap} Bits · Enfriamiento: {c.prestige_cooldown_h:g} h entre premios.\n\n"
         "<i>La reputación siempre se suma; los Bits solo si no superas el tope/enfriamiento.</i>")
    return t, kb([[b("⭐ Hacer prestigio", "pd")] if g >= 1 else [], HOME_BTN])

def wallet_view(uid):
    c = store.cfg; bits = store.balance(uid); t = (f"💎 <b>Cartera</b>\n\nBits: <b>{bits}</b> ≈ <b>{int(bits * c.cup_per_bit)} CUP</b>\n"
        f"Retiro mínimo: {c.min_withdraw_cup} CUP · Máx. diario: {c.max_withdraw_day_cup} CUP\n")
    w = store.withdrawals(uid)
    if w:
        t += "\n<b>Últimos retiros</b>\n" + "\n".join(f"#{x['id']} · {x['cup']} CUP · ••••{x['last4']} · {x['status']}" for x in w[:5])
    return t, kb([[b("💸 Retirar", "ws")], HOME_BTN])

# ---------- jugador ----------
@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear(); ref = None
    if command.args and command.args.startswith("ref_") and command.args[4:].isdigit(): ref = int(command.args[4:])
    try: store.user(m.from_user.id, m.from_user.first_name or "", ref)
    except Err as e: return await m.answer(str(e))
    s = ctx(m.from_user.id); store.save_game(m.from_user.id, s)
    t, k = home_view(m.from_user.id, s); await m.answer(t, reply_markup=k)

@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext): await state.clear(); await m.answer("Cancelado. Usa /start para volver al menú.")

def guard(fn):  # carga usuario+estado; bloquea baneados
    async def w(cb: CallbackQuery, *a, **k):
        try: store.user(cb.from_user.id, cb.from_user.first_name or "")
        except Err as e: return await cb.answer(str(e), show_alert=True)
        return await fn(cb, *a, **k)
    return w

@router.callback_query(F.data == "home")
@guard
async def cb_home(cb: CallbackQuery):
    s = ctx(cb.from_user.id); store.save_game(cb.from_user.id, s); t, k = home_view(cb.from_user.id, s); await edit(cb, t, k); await cb.answer()

@router.callback_query(F.data.startswith("dl:"))
@guard
async def cb_dl(cb: CallbackQuery):
    s = ctx(cb.from_user.id); store.save_game(cb.from_user.id, s); t, k = dept_list_view(s, int(cb.data[3:])); await edit(cb, t, k); await cb.answer()

@router.callback_query(F.data.regexp(r"^(d|h|u):\d+$"))
@guard
async def cb_dept(cb: CallbackQuery):
    kind, i = cb.data.split(":"); i = int(i); s = ctx(cb.from_user.id); msg = ""
    if not 0 <= i < len(s["fl"]): return await cb.answer("No existe", show_alert=True)
    if kind == "h": _, msg = E.hire(s, i)
    elif kind == "u": _, msg = E.upgrade(s, i)
    store.save_game(cb.from_user.id, s); t, k = dept_view(s, i); await edit(cb, t, k); await cb.answer(msg)

@router.callback_query(F.data.in_({"bd", "u2"}))
@guard
async def cb_build(cb: CallbackQuery):
    s = ctx(cb.from_user.id); ok, msg = (E.build(s) if cb.data == "bd" else E.unlock2(s))
    store.save_game(cb.from_user.id, s); t, k = dept_list_view(s, 1 if (cb.data == "u2" and ok) or (len(s["fl"]) > E.MAXF) or (cb.data == "bd" and len(s["fl"]) - 1 >= E.MAXF) else 0); await edit(cb, t, k); await cb.answer(msg, show_alert=not ok)

@router.callback_query(F.data == "gl")
@guard
async def cb_gl(cb: CallbackQuery):
    s = ctx(cb.from_user.id); store.save_game(cb.from_user.id, s); t, k = globals_view(s); await edit(cb, t, k); await cb.answer()

@router.callback_query(F.data.regexp(r"^g:(g|h)\d$"))
@guard
async def cb_buyg(cb: CallbackQuery):
    s = ctx(cb.from_user.id); _, msg = E.buy_global(s, cb.data[2:]); store.save_game(cb.from_user.id, s)
    t, k = globals_view(s); await edit(cb, t, k); await cb.answer(msg)

@router.callback_query(F.data == "pg")
@guard
async def cb_pg(cb: CallbackQuery):
    s = ctx(cb.from_user.id); store.save_game(cb.from_user.id, s); t, k = prestige_view(cb.from_user.id, s); await edit(cb, t, k); await cb.answer()

@router.callback_query(F.data == "pd")
@guard
async def cb_pd(cb: CallbackQuery):
    uid = cb.from_user.id; s = ctx(uid); pts = E.prestige(s)
    if not pts: return await cb.answer("Aún no llegas a 1 punto", show_alert=True)
    store.save_game(uid, s)
    try: bits, why = store.award_prestige(uid, pts)
    except Err as e: bits, why = 0, str(e)
    extra = f"💎 +{bits} Bits" if bits else f"💎 0 Bits ({why})"
    await edit(cb, f"⭐ Prestigio hecho: <b>+{pts}</b> de reputación.\n{extra}", kb([HOME_BTN])); await cb.answer()

@router.callback_query(F.data == "wl")
@guard
async def cb_wl(cb: CallbackQuery):
    t, k = wallet_view(cb.from_user.id); await edit(cb, t, k); await cb.answer()

@router.callback_query(F.data == "rf")
@guard
async def cb_rf(cb: CallbackQuery):
    me = await cb.bot.me(); uid = cb.from_user.id
    t = (f"👥 <b>Referidos</b>\n\nTu enlace:\nhttps://t.me/{me.username}?start=ref_{uid}\n\nInvitados: <b>{store.referrals(uid)}</b>\n"
         f"Ganas el <b>{store.cfg.referral_pct}%</b> de los Bits que ganen tus invitados jugando. No hay pago por solo invitar.")
    await edit(cb, t, kb([HOME_BTN])); await cb.answer()

# ---- retiro (FSM) ----
@router.callback_query(F.data == "ws")
@guard
async def cb_ws(cb: CallbackQuery, state: FSMContext):
    c = store.cfg
    await state.set_state(W.bits)
    await cb.message.answer(f"💸 ¿Cuántos <b>Bits</b> quieres retirar? Tienes {store.balance(cb.from_user.id)}.\nMínimo: {c.min_withdraw_cup} CUP.\n/cancel para salir."); await cb.answer()

@router.message(W.bits)
async def w_bits(m: Message, state: FSMContext):
    if not (m.text or "").strip().isdigit(): return await m.answer("Escribe solo un número entero.")
    bits = int(m.text); c = store.cfg
    if bits > store.balance(m.from_user.id): return await m.answer("No tienes tantos Bits.")
    if int(bits * c.cup_per_bit) < c.min_withdraw_cup: return await m.answer(f"Mínimo: {c.min_withdraw_cup} CUP.")
    await state.update_data(bits=bits); await state.set_state(W.card)
    await m.answer("💳 Envía el <b>número de tu tarjeta Bandec</b> (16 dígitos).\n\n⚠️ Envía <b>SOLO</b> el número. <b>Nunca</b> envíes PIN, claves, ni códigos de verificación: no los necesitamos y nadie legítimo te los pide.\nBorraré tu mensaje al recibirlo.")

@router.message(W.card)
async def w_card(m: Message, state: FSMContext):
    data = await state.get_data(); text = m.text or ""
    try: await m.delete()
    except TelegramBadRequest: pass
    try: wid = store.request_withdraw(m.from_user.id, data["bits"], text)
    except Err as e: return await m.answer(f"❌ {e}\nIntenta de nuevo o /cancel.")
    await state.clear(); await m.answer(f"✅ Retiro #{wid} solicitado. Lo revisamos y te avisamos cuando se pague.")
    for a in ADMIN_IDS:
        try: await m.bot.send_message(a, f"🔔 Nuevo retiro #{wid} de {html.escape(m.from_user.first_name or '')}. Usa /pendientes")
        except Exception: pass

# ---------- administración (solo ADMIN_IDS) ----------
@admin.message(Command("pendientes"))
async def a_pend(m: Message):
    p = store.pending()
    if not p: return await m.answer("Sin retiros pendientes.")
    for w in p:
        await m.answer(f"#{w['id']} · {html.escape(w['name'] or '')} ({w['user_id']})\n<b>{w['cup']} CUP</b> ({w['bits']} Bits) · saldo ahora {w['balance']}\nTarjeta: <code>{w['card']}</code>\n"
                       f"/pagado {w['id']}   ·   /rechazar {w['id']} motivo\n/ledger {w['user_id']}")

async def _resolve(m, wid, paid, note):
    try: uid, cup = store.resolve(wid, paid, note)
    except Err as e: return await m.answer(f"❌ {e}")
    await m.answer("Hecho.")
    try: await m.bot.send_message(uid, f"✅ Tu retiro #{wid} de {cup} CUP fue <b>pagado</b>." if paid else f"❌ Tu retiro #{wid} fue rechazado ({html.escape(note) or 'sin motivo'}). Tus Bits fueron devueltos.")
    except Exception: pass

@admin.message(Command("pagado"))
async def a_paid(m: Message, command: CommandObject):
    if not (command.args or "").strip().isdigit(): return await m.answer("Uso: /pagado ID")
    await _resolve(m, int(command.args), True, "")

@admin.message(Command("rechazar"))
async def a_rej(m: Message, command: CommandObject):
    p = (command.args or "").split(maxsplit=1)
    if not p or not p[0].isdigit(): return await m.answer("Uso: /rechazar ID motivo")
    await _resolve(m, int(p[0]), False, p[1] if len(p) > 1 else "")

@admin.message(Command("ledger"))
async def a_led(m: Message, command: CommandObject):
    if not (command.args or "").strip().isdigit(): return await m.answer("Uso: /ledger USER_ID")
    rows = store.ledger(int(command.args), 25)
    await m.answer("\n".join(f"{time.strftime('%d/%m %H:%M', time.localtime(r['at']))} {r['kind']} {r['bits']:+d} → {r['balance']} {r['ref']}" for r in rows) or "Vacío")

@admin.message(Command("ban", "unban"))
async def a_ban(m: Message, command: CommandObject):
    if not (command.args or "").strip().isdigit(): return await m.answer("Uso: /ban USER_ID")
    store.ban(int(command.args), command.command == "ban"); await m.answer("Hecho.")

@admin.message(Command("grant"))
async def a_grant(m: Message, command: CommandObject):
    if not DEV: return await m.answer("Solo con DEV=1.")
    a = (command.args or "").split()
    if len(a) != 2 or not all(x.lstrip("-").isdigit() for x in a): return await m.answer("Uso: /grant USER_ID BITS")
    store._tx(lambda: store._post(int(a[0]), "dev", int(a[1]), "grant")); await m.answer("Hecho.")

# ---------- arranque ----------
async def main():
    global store
    logging.basicConfig(level=logging.INFO)
    token, key = os.environ["BOT_TOKEN"], os.environ["CARD_KEY"]
    store = Store(os.getenv("DB_FILE", "itco.db"), bytes.fromhex(key))
    bot = Bot(token, default_properties=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); th = Throttle()
    dp.message.middleware(th); dp.callback_query.middleware(th)
    dp.include_routers(admin, router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
