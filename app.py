"""Flask API - Dashboard Ventas x Dia x Mes (Odoo 18 Enterprise)."""

import functools
import requests
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, g
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
    """IDs de empresas permitidas del usuario, leídas EN VIVO de Odoo en cada request
    (así los permisos nuevos aparecen sin re-loguear). Se cachea por-request (flask.g)
    para 1 sola lectura por página, con respaldo a la sesión si Odoo falla."""
    if hasattr(g, "_allowed_cids"):
        return g._allowed_cids
    cids = session.get("company_ids") or []
    uid = session.get("uid")
    if uid:
        try:
            urec = odoo.call_kw("res.users", "read", [[uid], ["company_ids"]])
            cids = urec[0].get("company_ids", []) if urec else cids
            session["company_ids"] = cids  # refresca también la caché de sesión
        except Exception:
            pass
    g._allowed_cids = cids
    return cids


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


# Odoo guarda date_order en UTC y Panama va 5 horas atras. Los dias y los meses se
# cortan a medianoche de PANAMA (= 05:00 UTC); si no, lo que se confirma despues de
# las 7 p. m. cae en el dia/mes siguiente (ej. ventas del 30-sep salian en octubre).
PANAMA_OFFSET = timedelta(hours=5)


def _hoy_pa():
    """Fecha de hoy en Panama (el servidor de Render corre en UTC)."""
    return (datetime.utcnow() - PANAMA_OFFSET).date()


def _fecha_pa(valor):
    """date_order (UTC) -> fecha 'YYYY-MM-DD' en hora de Panama."""
    if not valor:
        return ""
    try:
        return (datetime.strptime(str(valor)[:19], "%Y-%m-%d %H:%M:%S") - PANAMA_OFFSET).date().isoformat()
    except ValueError:
        return str(valor)[:10]


def _today_domain():
    today = _hoy_pa()
    return [("date_order", ">=", f"{today.isoformat()} 05:00:00"),
            ("date_order", "<", f"{(today + timedelta(days=1)).isoformat()} 05:00:00")]


def _month_domain(year=None, month=None):
    today = _hoy_pa()
    y = year or today.year
    m = month or today.month
    if m == 12:
        end = f"{y + 1}-01-01"
    else:
        end = f"{y}-{m + 1:02d}-01"
    return [("date_order", ">=", f"{y}-{m:02d}-01 05:00:00"), ("date_order", "<", f"{end} 05:00:00")]


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
        # El mes elegido en el selector. Antes no se leia aqui y las tarjetas
        # mostraban SIEMPRE el mes actual, aunque se eligiera otro: no cuadraban
        # con las demas pestanas, que si lo respetan.
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))

        dia = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _today_domain() + cd,
            fields=["amount_untaxed:sum"],
            groupby=[],
        )
        venta_dia = dia[0].get("amount_untaxed", 0) if dia else 0

        mes = odoo.read_group(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain(year, month) + cd,
            fields=["amount_untaxed:sum"],
            groupby=[],
        )
        venta_mes = mes[0].get("amount_untaxed", 0) if mes else 0

        ordenes_mes = odoo.search_count(
            "sale.order", BASE_DOMAIN + _month_domain(year, month) + cd)

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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))

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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))

        # tz=America/Panama: sin esto Odoo agrupa los dias en UTC y las ventas de la
        # noche se suman al dia siguiente.
        data = odoo.call_kw("sale.order", "read_group", [], {
            "domain": BASE_DOMAIN + _month_domain(year, month) + cd,
            "fields": ["date_order", "amount_untaxed:sum"],
            "groupby": ["date_order:day"],
            "context": {"tz": "America/Panama"},
        })
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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))

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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))

        orders = odoo.search_read(
            "sale.order",
            domain=BASE_DOMAIN + _month_domain(year, month) + cd,
            fields=["name", "partner_id", "date_order", "amount_untaxed", "user_id", "company_id"],
            limit=100, order="date_order desc",
        )
        return jsonify([{
            "numero": o["name"],
            "cliente": o["partner_id"][1] if o.get("partner_id") else "",
            "fecha": _fecha_pa(o.get("date_order")),
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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))
        vendedor_id = request.args.get("vendedor_id")

        domain_vendor = cd[:]
        if vendedor_id and vendedor_id != "all":
            domain_vendor += [("user_id", "=", int(vendedor_id))]

        # --- HOY ---
        domain_hoy = domain_vendor + _today_domain()

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
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))
        vendedor_id = request.args.get("vendedor_id")
        estado = request.args.get("estado", "all")  # all, sale, draft, sent, cancel
        periodo = request.args.get("periodo", "hoy")  # hoy, mes

        if periodo == "hoy":
            domain = _today_domain() + cd
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
                "fecha": _fecha_pa(o.get("date_order")),
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


# ── API: Ventas vs Facturado ─────────────────────────────────────────────────
# Agregado sin tocar nada de lo anterior.
#
# La idea: de lo que YA se vendio (ordenes confirmadas del periodo), cuanto se
# ha facturado y cuanto falta. Para que cuadre con el resto del tablero parte
# del MISMO universo que /api/ventas/resumen:
#     BASE_DOMAIN (state='sale') + _month_domain() + _company_domain()
# y mide con amount_untaxed (sin ITBMS), igual que las demas tarjetas.
#
# Lo facturado se calcula LINEA POR LINEA con qty_invoiced/product_uom_qty
# sobre price_subtotal. Verificado contra agosto 2026: la suma de las lineas da
# $855,261.56, identico al amount_untaxed de las ordenes (diferencia $0.00), asi
# que Vendido = Facturado + Por facturar siempre cierra.
#
# Cuidados tomados para no inflar el "facturado":
#   * la proporcion se capa entre 0 y 1 (hay lineas con qty_invoiced > cantidad)
#   * las lineas de cantidad 0 no aportan
#   * las lineas de nota/seccion (display_type) se ignoran
#   * en servicios RECURRENTES Odoo resetea qty_invoiced en cada ciclo, asi que
#     ese dato puede quedarse corto. Se cuentan aparte y se reportan para que
#     el numero se lea con ese contexto (en agosto: $28,939 de $855,261).

def _fact_linea(l):
    """Parte facturada de una linea, sin impuestos."""
    qty = l.get("product_uom_qty") or 0
    if qty <= 0:
        return 0.0
    prop = (l.get("qty_invoiced") or 0) / qty
    prop = max(0.0, min(prop, 1.0))          # nunca mas del 100%
    return (l.get("price_subtotal") or 0) * prop


@app.route("/api/ventas/facturacion")
@login_required
def api_ventas_facturacion():
    try:
        cd = _company_domain()
        year = int(request.args.get("year", _hoy_pa().year))
        month = int(request.args.get("month", _hoy_pa().month))
        domain = BASE_DOMAIN + _month_domain(year, month) + cd

        orders, off = [], 0
        while True:
            r = odoo.search_read(
                "sale.order", domain,
                ["name", "partner_id", "user_id", "company_id", "date_order",
                 "amount_untaxed", "invoice_status", "order_line"],
                limit=500, offset=off, order="id",
            )
            orders += r
            if len(r) < 500:
                break
            off += 500

        lids = [l for o in orders for l in (o.get("order_line") or [])]
        lineas = []
        for i in range(0, len(lids), 400):
            lineas += odoo.search_read(
                "sale.order.line", [("id", "in", lids[i:i + 400])],
                ["order_id", "product_uom_qty", "qty_invoiced", "price_subtotal",
                 "recurring_invoice", "display_type"],
            )
        # en Odoo 18 una linea de producto trae display_type='product' (no False)
        lineas = [l for l in lineas if l.get("display_type") in (False, "product")]

        por_orden = {}
        recurrente = 0.0
        for l in lineas:
            oid = l["order_id"][0]
            d = por_orden.setdefault(oid, {"vendido": 0.0, "facturado": 0.0})
            d["vendido"] += l.get("price_subtotal") or 0
            d["facturado"] += _fact_linea(l)
            if l.get("recurring_invoice"):
                recurrente += l.get("price_subtotal") or 0

        ESTADOS = {"invoiced": "Facturada", "to invoice": "Por facturar",
                   "no": "Nada que facturar", "upselling": "Venta adicional"}

        detalle, por_emp, por_vend = [], {}, {}
        tot_v = tot_f = 0.0
        for o in orders:
            d = por_orden.get(o["id"], {"vendido": 0.0, "facturado": 0.0})
            v, fa = round(d["vendido"], 2), round(d["facturado"], 2)
            pend = round(v - fa, 2)
            tot_v += v
            tot_f += fa
            emp = o["company_id"][1] if o.get("company_id") else "Sin empresa"
            vend = o["user_id"][1] if o.get("user_id") else "Sin asignar"
            for grupo, clave in ((por_emp, emp), (por_vend, vend)):
                g = grupo.setdefault(clave, {"nombre": clave, "vendido": 0.0,
                                             "facturado": 0.0, "ordenes": 0})
                g["vendido"] += v
                g["facturado"] += fa
                g["ordenes"] += 1
            detalle.append({
                "numero": o["name"],
                "cliente": o["partner_id"][1] if o.get("partner_id") else "",
                "vendedor": vend,
                "empresa": emp,
                "fecha": _fecha_pa(o.get("date_order")),
                "vendido": v, "facturado": fa, "pendiente": pend,
                "avance": round(fa / v * 100, 1) if v else 0.0,
                "estado": ESTADOS.get(o.get("invoice_status"), o.get("invoice_status") or ""),
            })

        def cerrar(grupo):
            out = []
            for g in grupo.values():
                g["vendido"] = round(g["vendido"], 2)
                g["facturado"] = round(g["facturado"], 2)
                g["pendiente"] = round(g["vendido"] - g["facturado"], 2)
                g["avance"] = round(g["facturado"] / g["vendido"] * 100, 1) if g["vendido"] else 0.0
                out.append(g)
            return sorted(out, key=lambda x: -x["pendiente"])

        tot_v, tot_f = round(tot_v, 2), round(tot_f, 2)
        # lo que mas falta por facturar primero: es la lista para accionar
        detalle.sort(key=lambda x: -x["pendiente"])

        # Las que FALTAN van completas siempre (son las accionables); del resto
        # se manda una muestra para no cargar la pagina de mas.
        faltan = [d for d in detalle if d["pendiente"] > 0.005]
        listas = [d for d in detalle if d["pendiente"] <= 0.005]
        for d in faltan:
            d["falta"] = True
        for d in listas:
            d["falta"] = False
        lista = faltan + listas[:max(0, 300 - len(faltan))]

        return jsonify({
            "vendido": tot_v,
            "facturado": tot_f,
            "pendiente": round(tot_v - tot_f, 2),
            "avance": round(tot_f / tot_v * 100, 1) if tot_v else 0.0,
            "ordenes": len(orders),
            "ordenes_pendientes": len(faltan),
            "recurrente": round(recurrente, 2),
            "por_empresa": cerrar(por_emp),
            "por_vendedor": cerrar(por_vend),
            "detalle": lista,
            "detalle_total": len(detalle),
            "detalle_faltan": len(faltan),
            "detalle_listas_mostradas": len(lista) - len(faltan),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
