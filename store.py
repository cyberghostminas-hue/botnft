"""Base de datos (SQLite), libro contable de Bits, referidos y retiros con tarjeta cifrada."""
import base64, json, os, re, sqlite3, time
from dataclasses import dataclass, field
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class Err(Exception): pass

@dataclass
class Cfg:
    cup_per_bit: float = float(os.getenv("CUP_PER_BIT", 1))          # 1 Bit = X CUP (calíbralo con tus ingresos reales)
    bits_per_point: int = int(os.getenv("BITS_PER_POINT", 1))        # Bits por punto de prestigio
    daily_bits_cap: int = int(os.getenv("DAILY_BITS_CAP", 50))       # tope de Bits ganados por usuario cada 24 h
    prestige_cooldown_h: float = float(os.getenv("PRESTIGE_COOLDOWN_H", 6))
    min_withdraw_cup: int = int(os.getenv("MIN_WITHDRAW_CUP", 5000))
    max_withdraw_day_cup: int = int(os.getenv("MAX_WITHDRAW_DAY_CUP", 20000))
    referral_pct: int = int(os.getenv("REFERRAL_PCT", 10))

class Store:
    def __init__(self, path, card_key: bytes, cfg: Cfg | None = None):
        assert len(card_key) == 32, "CARD_KEY debe ser de 32 bytes (64 hex)"
        self.cfg = cfg or Cfg(); self.aes = AESGCM(card_key)
        self.db = sqlite3.connect(path, isolation_level=None); self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, referrer INTEGER, banned INTEGER DEFAULT 0, risk INTEGER DEFAULT 0, created REAL);
        CREATE TABLE IF NOT EXISTS game(user_id INTEGER PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, bits INTEGER, balance INTEGER, ref TEXT, at REAL);
        CREATE INDEX IF NOT EXISTS ix_l ON ledger(user_id);
        CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bits INTEGER, cup INTEGER, card_enc TEXT, last4 TEXT, status TEXT, note TEXT, created REAL, updated REAL);
        """)
    # ---- transacciones ----
    def _tx(self, fn):
        self.db.execute("BEGIN IMMEDIATE")
        try: r = fn(); self.db.execute("COMMIT"); return r
        except BaseException: self.db.execute("ROLLBACK"); raise
    # ---- usuarios ----
    def user(self, uid, name="", ref=None):
        r = self.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            if ref and (ref == uid or not self.db.execute("SELECT 1 FROM users WHERE id=?", (ref,)).fetchone()): ref = None
            self.db.execute("INSERT INTO users(id,name,referrer,created) VALUES(?,?,?,?)", (uid, name, ref, time.time()))
            r = self.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if r["banned"]: raise Err("Cuenta bloqueada")
        return r
    def referrals(self, uid): return self.db.execute("SELECT COUNT(*) n FROM users WHERE referrer=?", (uid,)).fetchone()["n"]
    def ban(self, uid, v=True): self.db.execute("UPDATE users SET banned=? WHERE id=?", (int(v), uid))
    # ---- estado de juego ----
    def load_game(self, uid):
        r = self.db.execute("SELECT data FROM game WHERE user_id=?", (uid,)).fetchone(); return json.loads(r["data"]) if r else None
    def save_game(self, uid, s): self.db.execute("INSERT OR REPLACE INTO game(user_id,data) VALUES(?,?)", (uid, json.dumps(s)))
    # ---- ledger ----
    def balance(self, uid):
        r = self.db.execute("SELECT balance FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone(); return r["balance"] if r else 0
    def _post(self, uid, kind, bits, ref=""):
        bal = self.balance(uid) + bits
        if bal < 0: raise Err("Saldo insuficiente")
        self.db.execute("INSERT INTO ledger(user_id,kind,bits,balance,ref,at) VALUES(?,?,?,?,?,?)", (uid, kind, bits, bal, ref, time.time())); return bal
    def ledger(self, uid, n=30): return [dict(r) for r in self.db.execute("SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, n))]
    def award_prestige(self, uid, points):
        """Bits por prestigio con tope diario y enfriamiento. Devuelve (bits_acreditados, motivo_si_0)."""
        want = points * self.cfg.bits_per_point
        def run():
            since = time.time() - 86400
            last = self.db.execute("SELECT MAX(at) a FROM ledger WHERE user_id=? AND kind='earn'", (uid,)).fetchone()["a"]
            if last and time.time() - last < self.cfg.prestige_cooldown_h * 3600:
                return 0, f"enfriamiento de {self.cfg.prestige_cooldown_h:g} h entre premios"
            got = self.db.execute("SELECT COALESCE(SUM(bits),0) s FROM ledger WHERE user_id=? AND kind='earn' AND at>?", (uid, since)).fetchone()["s"]
            give = max(0, min(want, self.cfg.daily_bits_cap - got))
            if give == 0: return 0, "tope diario alcanzado"
            self._post(uid, "earn", give, f"prestige:{points}")
            ref = self.db.execute("SELECT referrer FROM users WHERE id=?", (uid,)).fetchone()["referrer"]
            if ref:
                r = give * self.cfg.referral_pct // 100
                if r > 0: self._post(ref, "referral", r, f"from:{uid}")
            return give, ""
        return self._tx(run)
    # ---- tarjeta ----
    def _enc(self, t): iv = os.urandom(12); return base64.b64encode(iv + self.aes.encrypt(iv, t.encode(), None)).decode()
    def _dec(self, s): b = base64.b64decode(s); return self.aes.decrypt(b[:12], b[12:], None).decode()
    # ---- retiros ----
    def request_withdraw(self, uid, bits, card):
        card = re.sub(r"[\s-]", "", card)
        if not re.fullmatch(r"\d{16}", card): raise Err("La tarjeta debe tener exactamente 16 dígitos")
        cup = int(bits * self.cfg.cup_per_bit)
        if bits <= 0: raise Err("Monto inválido")
        if cup < self.cfg.min_withdraw_cup: raise Err(f"Mínimo de retiro: {self.cfg.min_withdraw_cup} CUP")
        def run():
            if self.db.execute("SELECT 1 FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)).fetchone(): raise Err("Ya tienes un retiro pendiente")
            day = self.db.execute("SELECT COALESCE(SUM(cup),0) s FROM withdrawals WHERE user_id=? AND status!='rejected' AND created>?", (uid, time.time() - 86400)).fetchone()["s"]
            if day + cup > self.cfg.max_withdraw_day_cup: raise Err("Superas el límite diario de retiro")
            self._post(uid, "withdraw", -bits, "pending")
            c = self.db.execute("INSERT INTO withdrawals(user_id,bits,cup,card_enc,last4,status,created,updated) VALUES(?,?,?,?,?,'pending',?,?)",
                                (uid, bits, cup, self._enc(card), card[-4:], time.time(), time.time()))
            return c.lastrowid
        return self._tx(run)
    def withdrawals(self, uid): return [dict(r) for r in self.db.execute("SELECT id,bits,cup,last4,status,note,created FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))]
    def pending(self):
        out = []
        for r in self.db.execute("SELECT w.*, u.name FROM withdrawals w JOIN users u ON u.id=w.user_id WHERE status='pending' ORDER BY w.id"):
            d = dict(r); d["card"] = self._dec(d.pop("card_enc")); d["balance"] = self.balance(d["user_id"]); out.append(d)
        return out
    def resolve(self, wid, paid: bool, note=""):
        def run():
            w = self.db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not w or w["status"] != "pending": raise Err("No está pendiente")
            if not paid: self._post(w["user_id"], "refund", w["bits"], f"wd:{wid}")
            self.db.execute("UPDATE withdrawals SET status=?,note=?,updated=? WHERE id=?", ("paid" if paid else "rejected", note, time.time(), wid))
            return w["user_id"], w["cup"]
        return self._tx(run)
