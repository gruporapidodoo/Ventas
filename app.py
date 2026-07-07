"""Flask API - Dashboard Ventas x Dia x Mes (Odoo 18 Enterprise)."""

import functools
import requests
from datetime import datetime, date
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from flask_cors import CORS
from odoo_client import odoo
from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, SECRET_KEY, ODOO_URL, ODOO_DB

app = Flask(__name__, template_folder="templates", static_folder="static", static_url_path="/static")
app.secret_key = SECRET_KEY
CORS(app)

# Conectar a Odoo al iniciar
try:
    odoo.authenticate()
    print(f"Conectado a Odoo (uid={odoo.uid})")
except Exception as e:
    print(f"Error conectando a Odoo: {e}")

# ── Metas mensuales por company_id ───────────────────────────────────────────
METAS = {
    3: 83000,    # KITCHEN TOTAL SOLUTIONS (KTS) CORP.
    5: 250000,   # GSU HOLDINGS, S.A.
    8: 80000,    # RAPID POOLS, S.A.
}


# ── Auth ─────────────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "No autenticado"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    """Autenticar usuario contra Odoo."""
    try:
        data = request.get_json()
        login = data.get("login", "").strip()
        password = data.get("password", "").strip()

        if not login or not password:
            return jsonify({"error": "Ingresa usuario y contrasena"}), 400

        # Autenticar contra Odoo
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"db": ODOO_DB, "login": login, "password": password},
            "id": 1,
        }
        resp = requests.post(
            f"{ODOO_URL}/web/session/authenticate",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        result = resp.json().get("result", {})
        uid = result.get("uid")

        if not uid:
            return jsonify({"error": "Usuario o contrasena incorrectos"}), 401

        session["uid"] = uid
        session["user_name"] = result.get("name", login)
        session["login"] = login

        # Empresas a las que este usuario de Odoo tiene acceso (res.users.company_ids)
        try:
            urec = odoo.call_kw("res.users", "read", [[uid], ["company_ids"]])
            session["company_ids"] = urec[0].get("company_ids", []) if urec else []
        except Exception:
            session["company_ids"] = []

        return jsonify({"ok": True, "name": session["user_name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    if session.get("uid"):
        return jsonify({"uid": session["uid"], "name": session.get("user_name", "")})
    return jsonify({"error": "No autenticado"}), 401


# ── Helpers ──────────────────────────────────────────────────────────────────

def _allowed_ids():
    """IDs de empresas a las que el usuario logueado tiene acceso (de su usuario Odoo)."""
    return session.get("company_ids") or []


def _company_domain():
    """Dominio de empresa SIEMPRE limitado a las empresas permitidas del usuario."""
    allowed = _allowed_ids()
    cid = request.args.get("company_id")
    if cid and cid != "all":
        c = int(cid)
        # Si pide una empresa a la que NO tiene acceso, se restringe a las permitidas
        if allowed and c not in allowed:
            return [("company_id", "in", allowed)]
        return [("company_id", "=", c)]
    # "all" o sin filtro -> solo las empresas permitidas
    if allowed:
        return [("company_id", "in", allowed)]
    return []


def _today_domain():
    today = date.today().isoformat()
    return [("date_order", ">=", f"{today} 00:00:00"), ("date_order", "<=", f"{today} 23:59:59")]


def _month_domain(year=None, month=None):
    today = date.today()
    y = year or today.year
    m = month or today.month
    if m == 12:
        end = f"{y + 1}-01-01"
    else:
        end = f"{y}-{m + 1:02d}-01"
    return [("date_order", ">=", f"{y}-{m:02d}-01"), ("date_order", "<", end)]


BASE_DOMAIN = [("state", "=", "sale")]


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ── API: Empresas ────────────────────────────────────────────────────────────

@app.route("/api/empresas")
@login_required
def api_empresas():
    try:
        allowed = _allowed_ids()
        domain = [("id", "in", allowed)] if allowed else []
        companies = odoo.search_read(
            "res.company", domain, ["name", "currency_id"], order="name asc",
        )
        return jsonify([{
            "id": c["id"],
            "nombre": c["name"],
            "meta": METAS.get(c["id"], 0),
        } for c in companies])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Metas ───────────────────────────────────────────────────────────────

@app.route("/api/metas", methods=["GET", "POST"])
@login_required
def api_metas():
    if request.method == "POST":
        data = request.get_json()
        cid = int(data.get("company_id", 0))
        meta = float(data.get("meta", 0))
        if cid:
            METAS[cid] = meta
        return jsonify({"ok": True, "metas": METAS})
    return jsonify(METAS)


# ── API: Resumen ventas ──────────────────────────────────────────────────────

@app.route("/api/ventas/resumen")
@login_required
def api_ventas_resumen():
    try:
        cd = _company_domain()

        dia = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _today_domain() + cd,
            fields=["amount_untaxed:sum"],
            groupby=[],
        )
        venta_dia = dia[0].get("amount_untaxed", 0) if dia else 0

        mes = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain() + cd,
            fields=["amount_untaxed:sum"],
            groupby=[],
        )
        venta_mes = mes[0].get("amount_untaxed", 0) if mes else 0

        ordenes_mes = odoo.search_count("sale.order", BASE_DOMAIN + _month_domain() + cd)

        cid = request.args.get("company_id")
        allowed = _allowed_ids()
        if cid and cid != "all" and (not allowed or int(cid) in allowed):
            meta = METAS.get(int(cid), 0)
        elif allowed:
            # Suma solo de las metas de las empresas permitidas
            meta = sum(v for k, v in METAS.items() if k in allowed)
        else:
            meta = sum(METAS.values())

        return jsonify({
            "venta_dia": venta_dia,
            "venta_mes": venta_mes,
            "ordenes_mes": ordenes_mes,
            "meta": meta,
            "porcentaje_meta": round((venta_mes / meta * 100) if meta else 0, 1),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Ventas del DIA por vendedor ─────────────────────────────────────────

@app.route("/api/ventas/dia")
@login_required
def api_ventas_dia():
    try:
        cd = _company_domain()
        data = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _today_domain() + cd,
            fields=["user_id", "amount_untaxed:sum", "__count"],
            groupby=["user_id"],
            orderby="amount_untaxed desc",
        )
        return jsonify([{
            "vendedor": d["user_id"][1] if d.get("user_id") else "Sin asignar",
            "vendedor_id": d["user_id"][0] if d.get("user_id") else 0,
            "monto": d.get("amount_untaxed", 0),
            "ordenes": d.get("__count", 0),
        } for d in data])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Ventas del MES por vendedor ─────────────────────────────────────────

@app.route("/api/ventas/mes")
@login_required
def api_ventas_mes():
    try:
        cd = _company_domain()
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))

        data = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain(year, month) + cd,
            fields=["user_id", "amount_untaxed:sum", "__count"],
            groupby=["user_id"],
            orderby="amount_untaxed desc",
        )
        return jsonify([{
            "vendedor": d["user_id"][1] if d.get("user_id") else "Sin asignar",
            "vendedor_id": d["user_id"][0] if d.get("user_id") else 0,
            "monto": d.get("amount_untaxed", 0),
            "ordenes": d.get("__count", 0),
        } for d in data])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Ventas del mes por dia ──────────────────────────────────────────────

@app.route("/api/ventas/diario")
@login_required
def api_ventas_diario():
    try:
        cd = _company_domain()
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))

        data = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain(year, month) + cd,
            fields=["date_order", "amount_untaxed:sum"],
            groupby=["date_order:day"],
        )
        return jsonify({
            "dias": [d.get("date_order:day", "") for d in data],
            "montos": [d.get("amount_untaxed", 0) for d in data],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Ranking por empresa ─────────────────────────────────────────────────

@app.route("/api/ventas/por-empresa")
@login_required
def api_ventas_por_empresa():
    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))

        allowed = _allowed_ids()
        dom = BASE_DOMAIN + _month_domain(year, month)
        if allowed:
            dom += [("company_id", "in", allowed)]

        data = odoo.read_group(
            "sale.order",
            domain=dom,
            fields=["company_id", "amount_untaxed:sum", "__count"],
            groupby=["company_id"],
            orderby="amount_untaxed desc",
        )
        return jsonify([{
            "empresa": d["company_id"][1] if d.get("company_id") else "?",
            "empresa_id": d["company_id"][0] if d.get("company_id") else 0,
            "monto": d.get("amount_untaxed", 0),
            "ordenes": d.get("__count", 0),
            "meta": METAS.get(d["company_id"][0] if d.get("company_id") else 0, 0),
            "porcentaje": round((d.get("amount_untaxed", 0) / METAS.get(d["company_id"][0], 1) * 100) if METAS.get(d.get("company_id", [0])[0] if d.get("company_id") else 0) else 0, 1),
        } for d in data])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Detalle ordenes ─────────────────────────────────────────────────────

@app.route("/api/ventas/detalle")
@login_required
def api_ventas_detalle():
    try:
        cd = _company_domain()
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))

        orders = odoo.search_read(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain(year, month) + cd,
            fields=["name", "partner_id", "date_order", "amount_untaxed", "user_id", "company_id"],
            limit=100, order="date_order desc",
        )
        return jsonify([{
            "numero": o["name"],
            "cliente": o["partner_id"][1] if o.get("partner_id") else "",
            "fecha": o["date_order"][:10] if o.get("date_order") else "",
            "monto": o["amount_untaxed"],
            "vendedor": o["user_id"][1] if o.get("user_id") else "",
            "empresa": o["company_id"][1] if o.get("company_id") else "",
        } for o in orders])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Vendedores (lista) ──────────────────────────────────────────────────

@app.route("/api/vendedores")
@login_required
def api_vendedores():
    try:
        cd = _company_domain()
        data = odoo.read_group(
            "sale.order",
            domain=[("state", "in", ["draft", "sent", "sale", "cancel"]), ("date_order", ">=", "2026-01-01")] + cd,
            fields=["user_id"],
            groupby=["user_id"],
        )
        resultado = []
        for d in data:
            if d.get("user_id"):
                resultado.append({"id": d["user_id"][0], "nombre": d["user_id"][1]})
        resultado.sort(key=lambda x: x["nombre"])
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Resumen vendedor (KPIs cotizaciones) ───────────────────────────────

@app.route("/api/vendedor/resumen")
@login_required
def api_vendedor_resumen():
    """KPIs de un vendedor: hoy + acumulado del mes."""
    try:
        cd = _company_domain()
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
        vendedor_id = request.args.get("vendedor_id")

        domain_vendor = cd[:]
        if vendedor_id and vendedor_id != "all":
            domain_vendor += [("user_id", "=", int(vendedor_id))]

        # --- HOY ---
        today = date.today().isoformat()
        domain_hoy = domain_vendor + [("date_order", ">=", f"{today} 00:00:00"), ("date_order", "<=", f"{today} 23:59:59")]

        hoy_counts = {}
        for state in ["draft", "sent", "sale", "cancel"]:
            hoy_counts[state] = odoo.search_count("sale.order", [("state", "=", state)] + domain_hoy)

        hoy_total = sum(hoy_counts.values())
        hoy_cerradas = hoy_counts["sale"]

        hoy_monto = odoo.read_group("sale.order", [("state", "=", "sale")] + domain_hoy, ["amount_untaxed:sum"], groupby=[])
        hoy_monto_cerrado = hoy_monto[0].get("amount_untaxed", 0) if hoy_monto else 0

        # --- MES ---
        domain_mes = domain_vendor + _month_domain(year, month)

        mes_counts = {}
        for state in ["draft", "sent", "sale", "cancel"]:
            mes_counts[state] = odoo.search_count("sale.order", [("state", "=", state)] + domain_mes)

        mes_total = sum(mes_counts.values())
        mes_cerradas = mes_counts["sale"]
        mes_pendientes = mes_counts["draft"] + mes_counts["sent"]
        mes_canceladas = mes_counts["cancel"]
        tasa = round((mes_cerradas / mes_total * 100) if mes_total else 0, 1)

        mes_monto = odoo.read_group("sale.order", [("state", "=", "sale")] + domain_mes, ["amount_untaxed:sum"], groupby=[])
        mes_monto_cerrado = mes_monto[0].get("amount_untaxed", 0) if mes_monto else 0

        mes_pend = odoo.read_group("sale.order", [("state", "in", ["draft", "sent"])] + domain_mes, ["amount_untaxed:sum"], groupby=[])
        mes_monto_pendiente = mes_pend[0].get("amount_untaxed", 0) if mes_pend else 0

        return jsonify({
            "hoy_total": hoy_total,
            "hoy_cerradas": hoy_cerradas,
            "hoy_monto": hoy_monto_cerrado,
            "mes_total": mes_total,
            "mes_cerradas": mes_cerradas,
            "mes_pendientes": mes_pendientes,
            "mes_canceladas": mes_canceladas,
            "tasa_cierre": tasa,
            "mes_monto_cerrado": mes_monto_cerrado,
            "mes_monto_pendiente": mes_monto_pendiente,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Detalle cotizaciones vendedor ───────────────────────────────────────

@app.route("/api/vendedor/cotizaciones")
@login_required
def api_vendedor_cotizaciones():
    """Todas las cotizaciones de un vendedor con productos."""
    try:
        cd = _company_domain()
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
        vendedor_id = request.args.get("vendedor_id")
        estado = request.args.get("estado", "all")  # all, sale, draft, sent, cancel
        periodo = request.args.get("periodo", "hoy")  # hoy, mes

        if periodo == "hoy":
            today = date.today().isoformat()
            domain = [("date_order", ">=", f"{today} 00:00:00"), ("date_order", "<=", f"{today} 23:59:59")] + cd
        else:
            domain = _month_domain(year, month) + cd
        if vendedor_id and vendedor_id != "all":
            domain += [("user_id", "=", int(vendedor_id))]
        if estado and estado != "all":
            domain += [("state", "=", estado)]
        else:
            domain += [("state", "in", ["draft", "sent", "sale", "cancel"])]

        orders = odoo.search_read(
            "sale.order", domain,
            ["name", "partner_id", "date_order", "amount_untaxed", "state", "user_id", "company_id"],
            limit=200, order="date_order desc",
        )

        # Get lines for all orders
        order_ids = [o["id"] for o in orders]
        lines = []
        if order_ids:
            lines = odoo.search_read(
                "sale.order.line",
                [("order_id", "in", order_ids)],
                ["order_id", "product_id", "product_uom_qty", "price_unit", "price_subtotal", "name"],
                limit=1000,
            )

        # Group lines by order
        lines_by_order = {}
        for l in lines:
            oid = l["order_id"][0]
            if oid not in lines_by_order:
                lines_by_order[oid] = []
            lines_by_order[oid].append({
                "producto": l["product_id"][1] if l.get("product_id") else l.get("name", "")[:60],
                "cantidad": l["product_uom_qty"],
                "precio_unit": l["price_unit"],
                "subtotal": l["price_subtotal"],
            })

        estados = {"draft": "Borrador", "sent": "Enviada", "sale": "Confirmada", "cancel": "Cancelada"}

        resultado = []
        for o in orders:
            resultado.append({
                "numero": o["name"],
                "cliente": o["partner_id"][1] if o.get("partner_id") else "",
                "fecha": o["date_order"][:10] if o.get("date_order") else "",
                "monto": o["amount_untaxed"],
                "estado": estados.get(o["state"], o["state"]),
                "estado_key": o["state"],
                "vendedor": o["user_id"][1] if o.get("user_id") else "",
                "empresa": o["company_id"][1] if o.get("company_id") else "",
                "productos": lines_by_order.get(o["id"], []),
            })

        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
